"""Which corner of the job the head is standing on.

The operator parks the head on a corner of the stock and names it;
the job is placed so that corner of its bounding box lands where the
head already is.

Translating the geometry cannot do that. The encoder normalizes a job
to its own bounding box minimum and declares those bounds alongside
it, so a shift moves the declared minimum by exactly as much as the
geometry -- and a controller that anchors the job at its declared
minimum sees no difference at all. The head is moved instead, before
the job is sent, and the job itself is left alone.
"""

import pytest
import pytest_asyncio
from blinker import Signal
from raygeo.ops import Ops

from rayforge.core.doc import Doc
from rayforge.machine.cmd import _cut_scale_ops
from rayforge.machine.driver.ruida.ruida_driver import RuidaDriver
from rayforge.machine.driver.ruida.ruida_encoder import RuidaEncoder
from rayforge.machine.driver.ruida.ruida_util import decode35, encode35
from rayforge.machine.models.laser import Laser
from rayforge.machine.models.machine import Machine, Origin, StartCorner

WIDTH = 50.0
HEIGHT = 30.0
WIDTH_UM = 50000
HEIGHT_UM = 30000

# Where the head stands before the job, in machine micrometres.
HEAD = (500000, 400000)

# Where the pre-move puts it, per corner. The head has to end up on
# the corner the job starts at -- its bounding box minimum -- so a
# head standing on the right edge moves west by the job's width, and
# one standing on the bottom edge moves north by its height. None
# means the head is already there and nothing is sent.
EXPECTED_PREMOVE = {
    StartCorner.TOP_LEFT: None,
    StartCorner.TOP_RIGHT: (HEAD[0] - WIDTH_UM, HEAD[1]),
    StartCorner.BOTTOM_LEFT: (HEAD[0], HEAD[1] - HEIGHT_UM),
    StartCorner.BOTTOM_RIGHT: (HEAD[0] - WIDTH_UM, HEAD[1] - HEIGHT_UM),
}


def _rect_job() -> Ops:
    """A 50 x 30 rectangle, parked away from the origin."""
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.5)
    ops.set_feed_rate(600)
    ops.move_to(10.0, 20.0, 0.0)
    ops.line_to(10.0 + WIDTH, 20.0, 0.0)
    ops.line_to(10.0 + WIDTH, 20.0 + HEIGHT, 0.0)
    ops.line_to(10.0, 20.0 + HEIGHT, 0.0)
    ops.line_to(10.0, 20.0, 0.0)
    ops.layer_end("layer-1")
    ops.job_end()
    return ops


def _cut_extents(commands) -> tuple[tuple[int, int], tuple[int, int]]:
    """The x and y range of the absolute motion in a command list."""
    points = [
        (decode35(c[1:6]), decode35(c[6:11]))
        for c in commands
        if c[:1] in (b"\x88", b"\xa8")
    ]
    assert points
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), max(xs)), (min(ys), max(ys))


def _moves(commands: list[bytes]) -> list[tuple[int, int]]:
    return [
        (decode35(c[3:8]), decode35(c[8:13]))
        for c in commands
        if c[:2] == b"\xd9\x10"
    ]


async def _unknown_position(timeout: float = 2.0):
    return None


class _ClientSpy:
    """Records the moves and the job blob a run puts on the wire."""

    def __init__(self, position=HEAD):
        self.commands: list[bytes] = []
        self.blobs: list[bytes] = []
        self.position = position
        self.is_connected = False
        self.state_changed = Signal()
        self.position_updated = Signal()

    async def disconnect(self):
        pass

    async def set_travel_speed(self, um_per_s: int):
        self.commands.append(b"\xc9\x02" + encode35(um_per_s))

    async def rapid_move_xy(self, x_um: int, y_um: int, light: bool = False):
        self.commands.append(b"\xd9\x10\x00" + encode35(x_um) + encode35(y_um))
        self.position = (x_um, y_um)

    async def stop_process(self):
        self.commands.append(b"\xd8\x01")

    async def read_position(self, timeout: float = 2.0):
        return self.position

    async def send_job(self, blob, on_start=None, on_chunk=None):
        self.blobs.append(blob)


@pytest_asyncio.fixture
async def ruida_driver(lite_context):
    """A RuidaDriver with no transports; tests inject a client spy.

    The profile matches the controllers this driver is written for: a
    top-left origin and no reversed axis, so machine +X runs east and
    machine +Y runs south.
    """
    machine = Machine(lite_context)
    machine.driver_name = "RuidaDriver"
    machine.set_origin(Origin.TOP_LEFT)
    machine.set_axis_extents(800.0, 600.0)
    laser = Laser()
    laser.uid = "laser-1"
    machine.heads.clear()
    machine.add_head(laser)
    lite_context.machine_mgr.add_machine(machine)
    driver = RuidaDriver(lite_context, machine)

    yield driver

    driver._client = None
    await driver.cleanup()
    await machine.shutdown()


@pytest.fixture
def machine(ruida_driver):
    return ruida_driver._machine


async def _run_job(driver, ops) -> _ClientSpy:
    """Run a job through the driver and return what it sent."""
    spy = _ClientSpy()
    driver._client = spy
    doc = Doc()
    encoded = RuidaEncoder().encode(ops, driver._machine, doc)
    await driver.run(encoded, doc, ops)
    return spy


class TestTheJobIsNeverTranslated:
    """The corner is not in the blob, and must not be."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_the_blob_is_the_same_for_every_corner(
        self, ruida_driver, machine, corner
    ):
        machine.set_start_corner(StartCorner.TOP_LEFT)
        baseline = (await _run_job(ruida_driver, _rect_job())).blobs

        machine.set_start_corner(corner)
        spy = await _run_job(ruida_driver, _rect_job())

        assert spy.blobs == baseline

    @pytest.mark.parametrize("corner", list(StartCorner))
    def test_the_geometry_starts_at_the_bounding_box_minimum(
        self, machine, corner
    ):
        """Whatever the corner, the job is normalized the same way."""
        machine.set_start_corner(corner)

        commands = (
            RuidaEncoder()
            .encode(_rect_job(), machine, Doc())
            .driver_data["commands"]
        )

        assert _cut_extents(commands) == ((0, WIDTH_UM), (0, HEIGHT_UM))

    def test_the_declared_bounds_follow_the_geometry(self, machine):
        """E7 03 / E7 07 must describe where the job actually is."""
        machine.set_start_corner(StartCorner.BOTTOM_RIGHT)

        commands = (
            RuidaEncoder()
            .encode(_rect_job(), machine, Doc())
            .driver_data["commands"]
        )

        low = next(c for c in commands if c.startswith(b"\xe7\x03"))
        high = next(c for c in commands if c.startswith(b"\xe7\x07"))
        assert (decode35(low[2:7]), decode35(low[7:12])) == (0, 0)
        assert (decode35(high[2:7]), decode35(high[7:12])) == (
            WIDTH_UM,
            HEIGHT_UM,
        )


class TestJobPreMove:
    """The head is stood on the job's own start corner first."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_the_head_is_moved_to_the_corner(
        self, ruida_driver, machine, corner
    ):
        machine.set_start_corner(corner)

        spy = await _run_job(ruida_driver, _rect_job())

        expected = EXPECTED_PREMOVE[corner]
        assert _moves(spy.commands) == ([] if expected is None else [expected])

    @pytest.mark.asyncio
    async def test_the_default_corner_never_reads_a_position(
        self, ruida_driver, machine
    ):
        """A profile that never touched the setting sends nothing extra."""
        machine.set_start_corner(StartCorner.TOP_LEFT)

        spy = await _run_job(ruida_driver, _rect_job())

        assert spy.commands == []
        assert len(spy.blobs) == 1

    @pytest.mark.asyncio
    async def test_the_pre_move_runs_at_the_panel_jog_speed(
        self, ruida_driver, machine
    ):
        """It is interactive motion the operator watches."""
        machine.set_start_corner(StartCorner.BOTTOM_RIGHT)
        await ruida_driver.set_jog_speed(12000)

        spy = await _run_job(ruida_driver, _rect_job())

        assert spy.commands[0] == b"\xc9\x02" + encode35(200000)

    @pytest.mark.asyncio
    async def test_the_pre_move_lands_before_the_job_is_sent(
        self, ruida_driver, machine
    ):
        """A job that started mid-travel would cut its way there."""
        machine.set_start_corner(StartCorner.BOTTOM_RIGHT)

        spy = await _run_job(ruida_driver, _rect_job())

        assert spy.blobs
        assert spy.position == EXPECTED_PREMOVE[StartCorner.BOTTOM_RIGHT]

    @pytest.mark.asyncio
    async def test_an_unknown_position_refuses_the_job(
        self, ruida_driver, machine
    ):
        """Running it anyway would cut in the wrong place."""
        machine.set_start_corner(StartCorner.BOTTOM_RIGHT)
        spy = _ClientSpy()
        spy.read_position = _unknown_position
        ruida_driver._client = spy
        doc = Doc()
        ops = _rect_job()

        await ruida_driver.run(
            RuidaEncoder().encode(ops, machine, doc), doc, ops
        )

        assert spy.blobs == []


class TestCutScaleIsPlacedLikeAJob:
    """Cut Scale is a job, so it is placed like one."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_cut_scale_pre_moves_like_the_job(
        self, ruida_driver, machine, corner
    ):
        machine.set_start_corner(corner)
        ops = _cut_scale_ops(machine, WIDTH, HEIGHT, 1200, 0.8)

        spy = await _run_job(ruida_driver, ops)

        expected = EXPECTED_PREMOVE[corner]
        assert _moves(spy.commands) == ([] if expected is None else [expected])


class TestGoScaleUsesTheSamePlacement:
    """The traced outline is the outline the job would cut."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_go_scale_starts_where_the_job_starts(
        self, ruida_driver, machine, corner
    ):
        """Same corner, same offset, measured from the same head."""
        machine.set_start_corner(corner)
        spy = _ClientSpy()
        ruida_driver._client = spy

        await ruida_driver.trace_frame(WIDTH, HEIGHT)

        origin = EXPECTED_PREMOVE[corner] or HEAD
        assert _moves(spy.commands) == [
            origin,
            (origin[0] + WIDTH_UM, origin[1]),
            (origin[0] + WIDTH_UM, origin[1] + HEIGHT_UM),
            (origin[0], origin[1] + HEIGHT_UM),
            origin,
        ]

    @pytest.mark.asyncio
    async def test_top_left_still_traces_away_from_the_head(
        self, ruida_driver
    ):
        """The default is unchanged: the head is the box's corner."""
        spy = _ClientSpy()
        ruida_driver._client = spy

        await ruida_driver.trace_frame(WIDTH, HEIGHT)

        assert _moves(spy.commands)[0] == HEAD


class TestStartCornerPersists:
    """The choice belongs to the machine profile."""

    def test_round_trips_through_the_profile(self, lite_context):
        machine = Machine(lite_context)
        machine.set_start_corner(StartCorner.BOTTOM_RIGHT)

        restored = Machine.from_dict(machine.to_dict(), lite_context)

        assert restored.start_corner is StartCorner.BOTTOM_RIGHT

    def test_a_profile_without_one_defaults_to_top_left(self, lite_context):
        """Existing profiles keep the placement they already had."""
        machine = Machine(lite_context)
        machine.set_start_corner(StartCorner.BOTTOM_RIGHT)
        data = machine.to_dict()
        del data["machine"]["start_corner"]

        restored = Machine.from_dict(data, lite_context)

        assert restored.start_corner is StartCorner.TOP_LEFT

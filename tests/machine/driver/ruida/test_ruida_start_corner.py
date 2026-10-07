"""Where the head is when the job starts.

The operator parks the head on a corner of the stock and names it;
the job is placed so that corner of its bounding box lands where the
head already is, and it grows toward the opposite corner.

Translating the geometry cannot do that. The encoder normalizes a job
to its own bounding box minimum and declares those bounds alongside
it, so a shift moves the declared minimum by exactly as much as the
geometry -- and a controller that anchors the job at its declared
minimum sees no difference at all. The head is moved instead, before
the job is sent, and the job itself is left alone.
"""

import asyncio

import pytest
import pytest_asyncio
from blinker import Signal
from raygeo.ops import Ops
from raygeo.ops.axis import Axis

from swiftcut.core.doc import Doc
from swiftcut.machine.cmd import _cut_scale_ops
from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.machine.driver.ruida.ruida_encoder import RuidaEncoder
from swiftcut.machine.driver.ruida.ruida_util import decode35, encode35
from swiftcut.machine.models.laser import Laser
from swiftcut.machine.models.machine import Machine, Origin, StartCorner

WIDTH = 50.0
HEIGHT = 30.0
WIDTH_UM = 50000
HEIGHT_UM = 30000

# Where the head stands before the job, in machine micrometres.
HEAD = (500000, 400000)

# Where the pre-move puts it, per corner. The controller anchors the
# job at its bounding box minimum and grows it toward +X and +Y, so
# the head has to end up on the corner that is the minimum. Which
# visual way +X and +Y run is the jog panel's convention --
# MachinePanel.calculate_jog is what the arrow keys move, and it is
# the calibrated one. On this profile the panel's west is +X and its
# south is +Y, so the minimum is the job's top-right corner: a head on
# a left corner jogs east (-X) by the width, and one on a bottom
# corner jogs north (-Y) by the height. None means the head is already
# there and nothing is sent.
EXPECTED_PREMOVE = {
    StartCorner.TOP_LEFT: (HEAD[0] - WIDTH_UM, HEAD[1]),
    StartCorner.TOP_RIGHT: None,
    StartCorner.BOTTOM_LEFT: (HEAD[0] - WIDTH_UM, HEAD[1] - HEIGHT_UM),
    StartCorner.BOTTOM_RIGHT: (HEAD[0], HEAD[1] - HEIGHT_UM),
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
    @pytest.mark.parametrize(
        "corner, expected",
        [
            (StartCorner.TOP_LEFT, (HEAD[0] - WIDTH_UM, HEAD[1])),
            (StartCorner.TOP_RIGHT, None),
            (
                StartCorner.BOTTOM_LEFT,
                (HEAD[0] - WIDTH_UM, HEAD[1] - HEIGHT_UM),
            ),
            (StartCorner.BOTTOM_RIGHT, (HEAD[0], HEAD[1] - HEIGHT_UM)),
        ],
    )
    async def test_the_corner_jogs_the_way_the_panel_does(
        self, ruida_driver, machine, corner, expected
    ):
        """The arrow keys are the calibrated convention.

        A head on a left corner jogs east, and on this profile the
        panel's east is -X; a head on a bottom corner jogs north, -Y.
        Spelled out in absolute micrometres so the direction cannot
        quietly flip again.
        """
        machine.set_start_corner(corner)

        spy = await _run_job(ruida_driver, _rect_job())

        assert _moves(spy.commands) == ([] if expected is None else [expected])

    @pytest.mark.asyncio
    async def test_the_anchor_corner_never_reads_a_position(
        self, ruida_driver, machine
    ):
        """The corner the job is anchored at needs nothing extra."""
        machine.set_start_corner(StartCorner.TOP_RIGHT)

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


# Go Scale's five moves per corner: from the head round the outline
# the job will occupy and back. The outline is the pre-move target
# (the job's anchor) plus the job size, so Go Scale traces exactly
# what Start then cuts.
EXPECTED_TRACE = {
    StartCorner.TOP_LEFT: [
        HEAD,
        (HEAD[0] - WIDTH_UM, HEAD[1]),
        (HEAD[0] - WIDTH_UM, HEAD[1] + HEIGHT_UM),
        (HEAD[0], HEAD[1] + HEIGHT_UM),
        HEAD,
    ],
    StartCorner.TOP_RIGHT: [
        HEAD,
        (HEAD[0] + WIDTH_UM, HEAD[1]),
        (HEAD[0] + WIDTH_UM, HEAD[1] + HEIGHT_UM),
        (HEAD[0], HEAD[1] + HEIGHT_UM),
        HEAD,
    ],
    StartCorner.BOTTOM_LEFT: [
        HEAD,
        (HEAD[0] - WIDTH_UM, HEAD[1]),
        (HEAD[0] - WIDTH_UM, HEAD[1] - HEIGHT_UM),
        (HEAD[0], HEAD[1] - HEIGHT_UM),
        HEAD,
    ],
    StartCorner.BOTTOM_RIGHT: [
        HEAD,
        (HEAD[0] + WIDTH_UM, HEAD[1]),
        (HEAD[0] + WIDTH_UM, HEAD[1] - HEIGHT_UM),
        (HEAD[0], HEAD[1] - HEIGHT_UM),
        HEAD,
    ],
}


async def _run_go_scale(driver, speed: int = 2400) -> _ClientSpy:
    """Run Go Scale through the driver and return what it sent."""
    spy = _ClientSpy()
    driver._client = spy
    await driver.go_scale(WIDTH, HEIGHT, speed)
    return spy


class TestGoScaleTracesTheJobOutline:
    """Go Scale is rapids around the outline the job would cut."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_one_speed_then_five_moves_round_the_outline(
        self, ruida_driver, machine, corner
    ):
        machine.set_start_corner(corner)

        spy = await _run_go_scale(ruida_driver, speed=2400)

        assert spy.commands[0] == b"\xc9\x02" + encode35(40000)
        assert [c[:2] for c in spy.commands] == [b"\xc9\x02"] + [
            b"\xd9\x10"
        ] * 5
        assert _moves(spy.commands) == EXPECTED_TRACE[corner]

    @pytest.mark.asyncio
    async def test_it_sends_no_job(self, ruida_driver, machine):
        """No D8 00, no blob: the door interlock does not apply."""
        machine.set_start_corner(StartCorner.BOTTOM_LEFT)

        spy = await _run_go_scale(ruida_driver)

        assert spy.blobs == []
        assert b"\xd8\x00" not in spy.commands

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_the_outline_starts_where_start_pre_moves(
        self, ruida_driver, machine, corner
    ):
        """Its minimum corner is the job's anchor, for every corner."""
        machine.set_start_corner(corner)
        job = await _run_job(ruida_driver, _rect_job())

        go = await _run_go_scale(ruida_driver)

        anchor = (_moves(job.commands) or [HEAD])[-1]
        trace = _moves(go.commands)
        assert min(x for x, _ in trace) == anchor[0]
        assert min(y for _, y in trace) == anchor[1]
        assert max(x for x, _ in trace) == anchor[0] + WIDTH_UM
        assert max(y for _, y in trace) == anchor[1] + HEIGHT_UM

    @pytest.mark.asyncio
    async def test_it_leaves_the_head_on_the_start_corner(
        self, ruida_driver, machine
    ):
        """So a Start afterwards pre-moves from the right place."""
        machine.set_start_corner(StartCorner.TOP_LEFT)

        spy = await _run_go_scale(ruida_driver)

        assert spy.position == HEAD

    @pytest.mark.asyncio
    async def test_an_unknown_position_moves_nothing(
        self, ruida_driver, machine
    ):
        spy = _ClientSpy()
        spy.read_position = _unknown_position
        ruida_driver._client = spy

        await ruida_driver.go_scale(WIDTH, HEIGHT, 2400)

        assert spy.commands == []
        assert ruida_driver._jog_busy is False

    @pytest.mark.asyncio
    async def test_it_waits_for_each_corner_before_the_next(
        self, ruida_driver, machine
    ):
        """A move goes out only once the head reads as on the last one."""
        machine.set_start_corner(StartCorner.TOP_LEFT)
        ruida_driver.FRAME_POLL_INTERVAL = 0.01
        spy = _ClientSpy()
        ruida_driver._client = spy
        events: list[tuple[str, tuple[int, int]]] = []
        heading_to: list[tuple[int, int]] = []
        plain_move = spy.rapid_move_xy

        async def move(x_um, y_um, light=False):
            events.append(("move", (x_um, y_um)))
            heading_to[:] = [(x_um, y_um)] * 2

        async def lagging_read(timeout: float = 2.0):
            # The head gets there on the second poll after the move.
            if heading_to:
                target = heading_to.pop()
                if not heading_to:
                    await plain_move(*target)
            events.append(("read", spy.position))
            return spy.position

        spy.rapid_move_xy = move
        spy.read_position = lagging_read

        await ruida_driver.go_scale(WIDTH, HEIGHT, 2400)

        trace = EXPECTED_TRACE[StartCorner.TOP_LEFT]
        moves_at = [i for i, (kind, _) in enumerate(events) if kind == "move"]
        assert [events[i][1] for i in moves_at] == trace
        for n, i in enumerate(moves_at[1:], start=1):
            last_read = next(
                pos for kind, pos in reversed(events[:i]) if kind == "read"
            )
            assert last_read == trace[n - 1]
        assert events[-1] == ("read", trace[-1])

    @pytest.mark.asyncio
    async def test_a_corner_not_reached_in_time_goes_on_to_the_next(
        self, ruida_driver, machine
    ):
        machine.set_start_corner(StartCorner.TOP_LEFT)
        ruida_driver.SCALE_CORNER_TIMEOUT = 0.05
        ruida_driver.FRAME_POLL_INTERVAL = 0.01
        spy = _ClientSpy()
        ruida_driver._client = spy
        plain_move = spy.rapid_move_xy

        async def stuck(x_um, y_um, light=False):
            await plain_move(x_um, y_um, light=light)
            spy.position = HEAD

        spy.rapid_move_xy = stuck

        await ruida_driver.go_scale(WIDTH, HEIGHT, 2400)

        assert len(_moves(spy.commands)) == 5

    @pytest.mark.asyncio
    async def test_a_stop_mid_trace_halts_and_resyncs(
        self, ruida_driver, machine
    ):
        """Stop is D8 01 once and a position read; no move after it."""
        machine.set_start_corner(StartCorner.TOP_LEFT)
        spy = _ClientSpy()
        ruida_driver._client = spy
        plain_move = spy.rapid_move_xy
        plain_read = spy.read_position

        async def move(x_um, y_um, light=False):
            await plain_move(x_um, y_um, light=light)
            if len(_moves(spy.commands)) == 2:
                await ruida_driver.cancel()

        async def read(timeout: float = 2.0):
            spy.commands.append(b"read")
            return await plain_read(timeout)

        spy.rapid_move_xy = move
        spy.read_position = read

        await ruida_driver.go_scale(WIDTH, HEIGHT, 2400)

        after_stop = spy.commands[spy.commands.index(b"\xd8\x01") :]
        assert spy.commands.count(b"\xd8\x01") == 1
        assert after_stop[1] == b"read"
        assert _moves(after_stop) == []
        assert _moves(spy.commands) == EXPECTED_TRACE[StartCorner.TOP_LEFT][:2]
        assert ruida_driver._jog_busy is False

    @pytest.mark.asyncio
    async def test_a_start_during_it_is_refused(self, ruida_driver, machine):
        """
        Start mid-trace must not pre-move from wherever the head is
        nor send a job into the trace; Go Scale goes on undisturbed.
        """
        machine.set_start_corner(StartCorner.TOP_LEFT)
        spy = _ClientSpy()
        ruida_driver._client = spy
        gate = asyncio.Event()
        plain_read = spy.read_position

        async def gated_read(timeout: float = 2.0):
            if _moves(spy.commands):
                await gate.wait()
            return await plain_read(timeout)

        spy.read_position = gated_read
        trace = asyncio.create_task(ruida_driver.go_scale(WIDTH, HEIGHT, 2400))
        while not _moves(spy.commands):
            await asyncio.sleep(0)
        doc = Doc()
        ops = _rect_job()

        try:
            with pytest.raises(RuntimeError, match="busy"):
                await asyncio.wait_for(
                    ruida_driver.run(
                        RuidaEncoder().encode(ops, machine, doc), doc, ops
                    ),
                    1.0,
                )
        finally:
            gate.set()
        await asyncio.wait_for(trace, 5.0)

        assert spy.blobs == []
        assert _moves(spy.commands) == EXPECTED_TRACE[StartCorner.TOP_LEFT]

    @pytest.mark.asyncio
    async def test_a_busy_machine_ignores_it(self, ruida_driver, machine):
        ruida_driver._jog_busy = True

        spy = await _run_go_scale(ruida_driver)

        assert spy.commands == []


class TestOneCornerForEveryAction:
    """Start and Cut Scale place the head the same way."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_job_and_cut_scale_pre_move_alike(
        self, ruida_driver, machine, corner
    ):
        machine.set_start_corner(corner)
        actions = {
            "job": _rect_job(),
            "cut scale": _cut_scale_ops(machine, WIDTH, HEIGHT, 1200, 0.8),
        }

        premoves = {
            name: _moves((await _run_job(ruida_driver, ops)).commands)
            for name, ops in actions.items()
        }

        expected = EXPECTED_PREMOVE[corner]
        assert premoves == {
            name: [] if expected is None else [expected] for name in actions
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_the_job_grows_from_the_head_to_the_opposite_corner(
        self, ruida_driver, machine, corner
    ):
        """Judged by the arrow keys' own mapping, not the helper's."""
        machine.set_start_corner(corner)

        spy = await _run_job(ruida_driver, _rect_job())

        # The controller anchors the job's minimum where the head is
        # when it is sent, and the job runs toward +X and +Y from it.
        anchor = (_moves(spy.commands) or [HEAD])[-1]
        xs = {anchor[0], anchor[0] + WIDTH_UM}
        ys = {anchor[1], anchor[1] + HEIGHT_UM}
        assert HEAD[0] in xs and HEAD[1] in ys
        extents = {Axis.X: WIDTH_UM, Axis.Y: HEIGHT_UM}
        far: list[int] = list(HEAD)
        for direction in corner.toward_opposite:
            for axis, delta in machine.panel.calculate_jog(
                direction, 1.0
            ).items():
                far[0 if axis is Axis.X else 1] += int(delta) * extents[axis]
        assert far[0] in xs and far[0] != HEAD[0]
        assert far[1] in ys and far[1] != HEAD[1]


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

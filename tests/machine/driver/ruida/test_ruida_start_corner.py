"""Which corner of the job the head is standing on.

The operator parks the head on a corner of the stock and names it;
the job is placed so that corner of its bounding box lands where the
head already is. One helper decides the shift, and jobs, Go Scale and
Cut Scale all ask it the same question about the same box -- so the
outline a trace draws is the outline a job cuts.
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
from rayforge.machine.models.machine import (
    Machine,
    StartCorner,
    start_corner_offset,
)

WIDTH = 50.0
HEIGHT = 30.0
WIDTH_UM = 50000
HEIGHT_UM = 30000

# Where a 50 x 30 job's bounding box lands, in job-local micrometres,
# for each corner the head might be standing on.
EXPECTED_RANGES = {
    StartCorner.TOP_LEFT: ((0, WIDTH_UM), (0, HEIGHT_UM)),
    StartCorner.TOP_RIGHT: ((-WIDTH_UM, 0), (0, HEIGHT_UM)),
    StartCorner.BOTTOM_LEFT: ((0, WIDTH_UM), (-HEIGHT_UM, 0)),
    StartCorner.BOTTOM_RIGHT: ((-WIDTH_UM, 0), (-HEIGHT_UM, 0)),
}


@pytest.fixture
def machine(isolated_machine):
    laser = Laser()
    laser.uid = "laser-1"
    isolated_machine.heads.clear()
    isolated_machine.add_head(laser)
    isolated_machine.active_wcs = "MACHINE"
    return isolated_machine


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


class TestStartCornerOffset:
    """The helper itself, which everything else routes through."""

    @pytest.mark.parametrize(
        ("corner", "expected"),
        [
            (StartCorner.TOP_LEFT, (0.0, 0.0)),
            (StartCorner.TOP_RIGHT, (-WIDTH, 0.0)),
            (StartCorner.BOTTOM_LEFT, (0.0, -HEIGHT)),
            (StartCorner.BOTTOM_RIGHT, (-WIDTH, -HEIGHT)),
        ],
    )
    def test_offset_per_corner(self, corner, expected):
        assert start_corner_offset(corner, WIDTH, HEIGHT) == expected

    def test_the_machine_defaults_to_top_left(self, machine):
        assert machine.start_corner is StartCorner.TOP_LEFT


class TestJobPlacement:
    """A job lands where the operator says the head is."""

    @pytest.mark.parametrize("corner", list(StartCorner))
    def test_the_bbox_lands_in_the_expected_range(self, machine, corner):
        machine.set_start_corner(corner)

        commands = (
            RuidaEncoder()
            .encode(_rect_job(), machine, Doc())
            .driver_data["commands"]
        )

        assert _cut_extents(commands) == EXPECTED_RANGES[corner]

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
        assert (decode35(low[2:7]), decode35(low[7:12])) == (
            -WIDTH_UM,
            -HEIGHT_UM,
        )
        assert (decode35(high[2:7]), decode35(high[7:12])) == (0, 0)


class TestCutScaleUsesTheSamePlacement:
    """Cut Scale is a job, so it is placed like one."""

    @pytest.mark.parametrize("corner", list(StartCorner))
    def test_cut_scale_matches_the_job(self, machine, corner):
        machine.set_start_corner(corner)
        ops = _cut_scale_ops(machine, WIDTH, HEIGHT, 1200, 0.8)

        commands = (
            RuidaEncoder().encode(ops, machine, Doc()).driver_data["commands"]
        )

        assert _cut_extents(commands) == EXPECTED_RANGES[corner]


class _ScaleClientSpy:
    """Records the moves a Go Scale run sends."""

    def __init__(self, position=(0, 0)):
        self.commands: list[bytes] = []
        self.position = position
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


def _corners(commands: list[bytes]) -> list[tuple[int, int]]:
    return [
        (decode35(c[3:8]), decode35(c[8:13]))
        for c in commands
        if c[:2] == b"\xd9\x10"
    ]


@pytest_asyncio.fixture
async def ruida_driver(lite_context):
    """A RuidaDriver with no transports; tests inject a client spy."""
    machine = Machine(lite_context)
    machine.driver_name = "RuidaDriver"
    machine.set_axis_extents(400.0, 300.0)
    lite_context.machine_mgr.add_machine(machine)
    driver = RuidaDriver(lite_context, machine)

    yield driver

    driver._client = None
    await driver.cleanup()
    await machine.shutdown()


class TestGoScaleUsesTheSamePlacement:
    """The traced outline is the outline the job would cut."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_go_scale_corners_match_the_jobs(self, ruida_driver, corner):
        """Same corner selection, same rectangle, measured from the head.

        Go Scale traces from wherever the head is, so its corners are
        the job's job-local ranges shifted by the head position -- the
        same offset, applied by the same helper.
        """
        ruida_driver._machine.set_start_corner(corner)
        head = (120000, 90000)
        spy = _ScaleClientSpy(position=head)
        ruida_driver._client = spy

        await ruida_driver.trace_frame(WIDTH, HEIGHT)

        (x_lo, x_hi), (y_lo, y_hi) = EXPECTED_RANGES[corner]
        assert _corners(spy.commands) == [
            (head[0] + x_lo, head[1] + y_lo),
            (head[0] + x_hi, head[1] + y_lo),
            (head[0] + x_hi, head[1] + y_hi),
            (head[0] + x_lo, head[1] + y_hi),
            (head[0] + x_lo, head[1] + y_lo),
        ]

    @pytest.mark.asyncio
    async def test_top_left_still_traces_away_from_the_head(
        self, ruida_driver
    ):
        """The default is unchanged: the head is the box's corner."""
        spy = _ScaleClientSpy(position=(0, 0))
        ruida_driver._client = spy

        await ruida_driver.trace_frame(WIDTH, HEIGHT)

        assert _corners(spy.commands)[0] == (0, 0)


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

"""Where a Start job begins and ends, on the bundled ilab-614 profile.

MachineCmd records machine.last_job_start as the head's position plus
the start-corner move the driver makes before it sends: the point the
controller anchors the job at with D8 12. Crawford mode's "start from
the last job's start position" jogs the head so that the driver's move
lands it there again.

These tests drive MachineCmd.run_send_job through the real RuidaDriver,
so the pre-move, the blob and last_job_start all come from the real
code. Only the controller is a double, and it runs the blob it is sent.

On ilab-614 (top-left origin, no reversed axis) the jog panel's east is
-X and its south +Y (MachinePanel.calculate_jog), so a job's machine
minimum -- where it is anchored -- is its visual top-right corner, its
visual left edge is its high X and its top edge its low Y.
"""

import asyncio
import copy
import logging
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from blinker import Signal
from raygeo.ops import Ops
from raygeo.ops.axis import Axis

from swiftcut.core.doc import Doc
from swiftcut.machine.cmd import MachineCmd
from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.machine.driver.ruida.ruida_encoder import (
    RD_MAGIC,
    RuidaEncoder,
)
from swiftcut.machine.driver.ruida.ruida_util import (
    build_swizzle_lut,
    decode14,
    decode35,
)
from swiftcut.machine.models.default_profile import ILAB_614_PROFILE
from swiftcut.machine.models.machine import (
    JogDirection,
    Machine,
    StartCorner,
)
from swiftcut.pipeline.artifact import JobArtifact

# The owner's job: 785.1 x 600.1 mm of cut geometry, wherever it sits
# in machine space before the encoder normalizes it.
WIDTH = 785.1
HEIGHT = 600.1
X0, Y0 = 10.0, 20.0
# The job's first move, job-local: inside the job, so the first 88 is
# not the anchor itself.
FIRST = (100.0, 50.0)

# Where every job below is anchored, and the head on each corner of
# that job, in machine mm.
ANCHOR = (300.0, 100.0)
HEAD_ON = {
    StartCorner.TOP_LEFT: (1085.1, 100.0),
    StartCorner.TOP_RIGHT: (300.0, 100.0),
    StartCorner.BOTTOM_LEFT: (1085.1, 700.1),
    StartCorner.BOTTOM_RIGHT: (300.0, 700.1),
}

JOG_SPEED = 6000  # mm/min


def _job() -> Ops:
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.5)
    ops.set_feed_rate(600)
    ops.move_to(X0 + FIRST[0], Y0 + FIRST[1], 0.0)
    # Short enough to go out as a relative cut.
    ops.line_to(X0 + FIRST[0] + 5.0, Y0 + FIRST[1], 0.0)
    ops.move_to(X0, Y0, 0.0)
    ops.line_to(X0 + WIDTH, Y0, 0.0)
    ops.line_to(X0 + WIDTH, Y0 + HEIGHT, 0.0)
    ops.line_to(X0, Y0 + HEIGHT, 0.0)
    ops.line_to(X0, Y0, 0.0)
    ops.layer_end("layer-1")
    ops.job_end()
    return ops


# The owner's 16:07 job, by shape: two parts with a circular hole each,
# 170.2 x 199.8 mm of cut geometry far from machine (0, 0).
CUT_MIN = (614.9, 400.3)
CUT_SIZE = (170.2, 199.8)


def _assembled_job() -> Ops:
    """
    A job concatenated from its parts, as the pipeline's job aggregate
    concatenates them.

    raygeo then counts a travel from (0, 0) to the first move in
    ops.rect(include_travel=True), though the encoder emits none: the
    owner's job measured 785.1 x 600.1 that way, and the blob sent
    for it moved within 170.2 x 199.8.
    """
    x0, y0 = CUT_MIN
    w, h = CUT_SIZE
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.65)
    ops.set_feed_rate(1200)
    for top, bottom in ((y0, y0 + h / 2), (y0 + h / 2, y0 + h)):
        part = Ops()
        part.move_to(x0, top, 0.0)
        part.line_to(x0 + w, top, 0.0)
        part.line_to(x0 + w, bottom, 0.0)
        part.line_to(x0, bottom, 0.0)
        part.line_to(x0, top, 0.0)
        cx, cy = x0 + w / 2, (top + bottom) / 2
        part.move_to(cx + 3.2, cy, 0.0)
        part.arc_to(cx - 3.2, cy, -3.2, 0.0, False)
        part.arc_to(cx + 3.2, cy, 3.2, 0.0, False)
        ops.extend(part)
    ops.layer_end("layer-1")
    ops.job_end()
    return ops


def _commands(blob: bytes) -> list[bytes]:
    """Unswizzle a job blob and split it into commands."""
    _swizzle, unswizzle = build_swizzle_lut(RD_MAGIC)
    commands: list[bytes] = []
    current = bytearray()
    for b in blob.translate(unswizzle):
        if b & 0x80 and current:
            commands.append(bytes(current))
            current = bytearray()
        current.append(b)
    commands.append(bytes(current))
    return commands


def _um(point: tuple[float, float]) -> tuple[int, int]:
    return round(point[0] * 1000), round(point[1] * 1000)


def _mm(point: tuple[int, int] | None) -> tuple[float, float]:
    assert point is not None
    return point[0] / 1000, point[1] / 1000


@dataclass
class _JobSeen:
    """One job, as the controller saw it, in micrometres."""

    before_premove: tuple[int, int]
    after_premove: tuple[int, int] | None = None
    anchor: tuple[int, int] | None = None
    first_88: tuple[int, int] | None = None
    end: tuple[int, int] | None = None


class _Controller:
    """
    A Ruida controller, as far as where a job starts and ends.

    Modelled on _ClientSpy in tests/machine/driver/ruida/
    test_ruida_start_corner.py, it stands in for RuidaClient under the
    real RuidaDriver, over USB as on the owner's ilab-614. Unlike the
    spy it runs the blob it is sent:

    - D8 12 anchors the job: job-local (0, 0) is the head's position
      when the job starts.
    - 88 and A8 are absolute moves from that anchor; 89 and A9 are
      relative in X and Y, 8A and AA in X, 8B and AB in Y.
    - At D7, the end of the job, the head goes back to the anchor.

    The return to the anchor is modelled, not captured. It rests on
    the owner's log (ilab-614 over USB, start corner top_left,
    2026-10-21), where every completed job ended, by the controller's
    own doing, on the point the start-corner move had put the head on:

        15:52:54 Start corner top_left: head -> (1273.8, 9.0)
                 ... Job finished; next POS (1273.828, 9.024)
        16:01:00 head -> (1058.6, 9.0); Job finished;
                 POS (1058.573, 9.024)
        16:05:00 (Crawford) head -> (1059.6, 9.0); Job finished;
                 POS (1059.622, 9.024)

    The in-repo simulator models neither D8 12 nor that return. Once
    the blob has run, the status read reports the job-running bit
    clear. Positions are controller micrometres, which on ilab-614,
    with no reversed axis, are machine micrometres.
    """

    def __init__(self, position: tuple[int, int]):
        self.position = position
        self.is_connected = True
        self.state_changed = Signal()
        self.position_updated = Signal()
        self.jobs: list[_JobSeen] = []

    def job_starting(self) -> None:
        """The driver's run begins: its start-corner move is next."""
        self.jobs.append(_JobSeen(before_premove=self.position))

    async def disconnect(self):
        pass

    async def set_travel_speed(self, um_per_s: int):
        pass

    async def rapid_move_xy(self, x_um: int, y_um: int, light: bool = False):
        self.position = (x_um, y_um)

    async def stop_process(self):
        pass

    async def read_position(self, timeout: float = 2.0):
        # RuidaClient publishes every position reply it gets, which is
        # how the machine's device state follows the head.
        for axis, value in zip("xy", self.position, strict=True):
            self.position_updated.send(self, axis=axis, value_um=value)
        return self.position

    async def stream_job(self, blob, should_stop, on_start=None) -> bool:
        job = self.jobs[-1]
        job.after_premove = self.position
        for command in _commands(blob):
            self._execute(job, command)
        return True

    async def _read_memory_wait(self, mem_address: int, timeout=2.0):
        assert mem_address == RuidaDriver.MACHINE_STATUS_ADDRESS
        job = self.jobs[-1]
        if job.end is None:
            job.end = self.position
        return 0

    def _execute(self, job: _JobSeen, command: bytes) -> None:
        op = command[0]
        x, y = self.position
        if command[:2] == b"\xd8\x12":
            job.anchor = self.position
        elif op in (0x88, 0xA8):
            assert job.anchor is not None
            self.position = (
                job.anchor[0] + decode35(command[1:6]),
                job.anchor[1] + decode35(command[6:11]),
            )
            if op == 0x88 and job.first_88 is None:
                job.first_88 = self.position
        elif op in (0x89, 0xA9):
            self.position = (
                x + decode14(command[1:3]),
                y + decode14(command[3:5]),
            )
        elif op in (0x8A, 0xAA):
            self.position = (x + decode14(command[1:3]), y)
        elif op in (0x8B, 0xAB):
            self.position = (x, y + decode14(command[1:3]))
        elif op == 0xD7:
            assert job.anchor is not None
            self.position = job.anchor


@pytest.fixture
def job_ops() -> Ops:
    """The job the rig's Start sends."""
    return _job()


@pytest_asyncio.fixture
async def rig(lite_context, task_mgr, job_ops):
    """
    The bundled ilab-614 profile, on a real RuidaDriver whose client
    is the controller double, and a MachineCmd that starts job_ops.

    The driver is built here and handed to the machine's controller.
    The profile's driver name is cleared first, and auto-connect with
    it: a controller would otherwise build a RuidaDriver of its own,
    set it up on USB and connect it. Every geometry field is the
    profile's own.
    """
    machine = Machine.from_dict(copy.deepcopy(ILAB_614_PROFILE), lite_context)
    machine.driver_name = None
    machine.auto_connect = False
    lite_context.machine_mgr.add_machine(machine)
    assert lite_context.machine_mgr.get_machine_by_id(machine.id) is machine

    driver = RuidaDriver(lite_context, machine)
    driver._connection = "usb"
    controller = machine.controller
    controller._disconnect_driver_signals()
    controller.driver = driver
    controller._connect_driver_signals()

    laser = _Controller(position=(0, 0))
    driver._client = laser
    laser.position_updated.connect(driver._on_position_updated)
    real_run = driver.run

    async def run(*args, **kwargs):
        laser.job_starting()
        await real_run(*args, **kwargs)

    driver.run = run

    ops = job_ops
    doc = Doc()
    artifact = JobArtifact(
        ops=ops,
        distance=ops.distance(),
        generation_id=1,
        encoded_output=RuidaEncoder().encode(ops, machine, doc),
    )
    editor = MagicMock()
    editor.task_manager = task_mgr
    editor.doc = doc
    editor.pipeline.generate_job_artifact_async = AsyncMock(
        return_value=MagicMock()
    )
    store = editor.pipeline.artifact_store
    store.checkout_handle.return_value.__enter__.return_value = artifact

    yield machine, laser, MachineCmd(editor)

    driver._client = None
    await driver.cleanup()
    await machine.shutdown()


async def _settle(task_mgr) -> None:
    await asyncio.sleep(0)
    assert await asyncio.to_thread(task_mgr.wait_until_settled, 10000)
    # Main-thread callbacks, like the profile update, land after.
    await asyncio.sleep(0.05)


async def _put_head(machine: Machine, laser: _Controller, at) -> None:
    """Stand the head somewhere and let the machine read it back."""
    laser.position = _um(at)
    await laser.read_position()
    assert machine.device_state.machine_pos[:2] == pytest.approx(at)


async def _start(task_mgr, cmd: MachineCmd, machine: Machine, **kwargs):
    """Press Start and wait until the job and its aftermath are done."""
    cmd.run_send_job(machine, **kwargs)
    await _settle(task_mgr)


def _notices(cmd: MachineCmd) -> list[str]:
    send = cmd._editor.notification_requested.send
    return [c.kwargs["message"] for c in send.call_args_list]


def test_the_profile_runs_east_minus_x_and_south_plus_y(lite_context):
    """The convention the tables above are written in."""
    machine = Machine.from_dict(copy.deepcopy(ILAB_614_PROFILE), lite_context)

    east = machine.panel.calculate_jog(JogDirection.EAST, 1.0)
    south = machine.panel.calculate_jog(JogDirection.SOUTH, 1.0)

    assert (east, south) == ({Axis.X: -1.0}, {Axis.Y: 1.0})
    assert machine.axis_extents == (1400.0, 900.0)


class TestTheJobEndsWhereItStarted:
    """A2: the job starts on last_job_start and the head returns there."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_the_end_and_the_anchor_are_the_recorded_start(
        self, rig, task_mgr, corner
    ):
        machine, laser, cmd = rig
        machine.set_start_corner(corner)
        await _put_head(machine, laser, HEAD_ON[corner])

        await _start(task_mgr, cmd, machine)

        (job,) = laser.jobs
        start = machine.last_job_start
        assert job.before_premove == _um(HEAD_ON[corner])
        # D8 12 is the blob's first command, so the anchor is where
        # the start-corner move left the head.
        assert job.anchor == job.after_premove
        assert _mm(job.anchor) == pytest.approx(ANCHOR, abs=0.1)
        assert _mm(job.anchor) == pytest.approx(start, abs=0.1)
        assert _mm(job.end) == pytest.approx(start, abs=0.1)
        assert _mm(job.first_88) == pytest.approx(
            (ANCHOR[0] + FIRST[0], ANCHOR[1] + FIRST[1]), abs=0.1
        )
        # It fits once anchored, so nothing warns.
        assert _notices(cmd) == []


class TestCrawfordRepeatsTheLastJob:
    """Start from the last job's start puts the job where it was."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_a_second_job_after_a_jog_away_lands_on_the_first(
        self, rig, task_mgr, corner
    ):
        machine, laser, cmd = rig
        machine.set_start_corner(corner)
        await _put_head(machine, laser, HEAD_ON[corner])
        await _start(task_mgr, cmd, machine)
        start = machine.last_job_start
        assert start is not None

        # The operator jogs away, on the jog panel's own path.
        await machine.jog({Axis.X: 200.0, Axis.Y: 150.0}, JOG_SPEED)
        assert machine.device_state.machine_pos[:2] == pytest.approx(
            (ANCHOR[0] + 200.0, ANCHOR[1] + 150.0), abs=0.1
        )

        await _start(
            task_mgr,
            cmd,
            machine,
            start_at=start,
            premove_speed=JOG_SPEED,
        )

        first, second = laser.jobs
        # The Crawford jog stops where the first job's head stood, and
        # the driver's start-corner move goes on from there.
        assert _mm(second.before_premove) == pytest.approx(
            HEAD_ON[corner], abs=0.1
        )
        assert _mm(second.anchor) == pytest.approx(start, abs=0.1)
        assert _mm(second.first_88) == pytest.approx(
            _mm(first.first_88), abs=0.1
        )
        assert _mm(second.end) == pytest.approx(_mm(first.end), abs=0.1)
        assert machine.last_job_start == pytest.approx(start, abs=0.1)
        assert _notices(cmd) == []


# Heads from which the job, once anchored, leaves the 1400 x 900 bed,
# and where it is anchored.
OVERRUNS = [
    # Low X: a left start grows the job toward -X.
    (StartCorner.TOP_LEFT, (700.0, 100.0), (-85.1, 100.0)),
    # High Y: a top start grows it toward +Y.
    (StartCorner.TOP_LEFT, (1085.1, 400.0), (300.0, 400.0)),
    # High X: a right start grows it toward +X.
    (StartCorner.TOP_RIGHT, (700.0, 100.0), (700.0, 100.0)),
    # Low Y: a bottom start grows it toward -Y.
    (StartCorner.BOTTOM_LEFT, (1085.1, 500.0), (300.0, -100.1)),
    (StartCorner.BOTTOM_RIGHT, (700.0, 700.1), (700.0, 100.0)),
]


class TestBedOverrunFollowsTheAnchor:
    """The overrun warning judges the job where it will be cut."""

    @pytest.mark.asyncio
    async def test_the_owners_job_does_not_warn(self, rig, task_mgr, caplog):
        """
        The owner's log warned "Job extent 785.1 x 600.1 mm from
        (1228.8, 9.0) leaves the 1400 x 900 mm bed" for this job. From
        a top-left start it runs from X 443.7 to 1228.8.
        """
        machine, laser, cmd = rig
        machine.set_start_corner(StartCorner.TOP_LEFT)
        await _put_head(machine, laser, (1228.8, 9.0))

        with caplog.at_level(logging.WARNING, logger="swiftcut.machine.cmd"):
            await _start(task_mgr, cmd, machine)

        assert "leaves the" not in caplog.text
        assert _notices(cmd) == []
        assert machine.last_job_start == pytest.approx((443.7, 9.0))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner, head, anchor", OVERRUNS)
    async def test_a_job_that_leaves_the_bed_warns(
        self, rig, task_mgr, caplog, corner, head, anchor
    ):
        machine, laser, cmd = rig
        machine.set_start_corner(corner)
        await _put_head(machine, laser, head)

        with caplog.at_level(logging.WARNING, logger="swiftcut.machine.cmd"):
            await _start(task_mgr, cmd, machine)

        assert (
            f"from the anchor ({anchor[0]:.1f}, {anchor[1]:.1f}) leaves "
            f"the 1400 x 900 mm bed" in caplog.text
        )
        assert len(_notices(cmd)) == 1
        assert "would run past the bed" in _notices(cmd)[0]


class TestTheOverrunIgnoresTravelFromTheOrigin:
    """
    A pipeline job's ops.rect(include_travel=True) reaches (0, 0): the
    overrun box must not, since the head starts on the job's anchor.
    """

    @pytest.fixture
    def job_ops(self) -> Ops:
        return _assembled_job()

    @pytest.mark.asyncio
    async def test_the_owners_job_does_not_warn(
        self, rig, task_mgr, caplog, job_ops
    ):
        """The owner's 16:07 Start: TOP_LEFT, head (1390.0, 227.6)."""
        machine, laser, cmd = rig
        # The discrepancy itself: raygeo's travel box against the cut.
        assert job_ops.rect(True)[:2] == (0.0, 0.0)
        assert job_ops.rect() == pytest.approx((614.9, 400.3, 785.1, 600.1))
        machine.set_start_corner(StartCorner.TOP_LEFT)
        await _put_head(machine, laser, (1390.0, 227.6))

        with caplog.at_level(logging.WARNING, logger="swiftcut.machine.cmd"):
            await _start(task_mgr, cmd, machine)

        assert "leaves the" not in caplog.text
        assert _notices(cmd) == []
        (job,) = laser.jobs
        assert _mm(job.anchor) == pytest.approx((1219.8, 227.6), abs=0.1)
        assert machine.last_job_start == pytest.approx((1219.8, 227.6))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "corner, head, anchor",
        [
            # Low X: 170.2 mm toward -X from X 100.
            (StartCorner.TOP_LEFT, (100.0, 227.6), (-70.2, 227.6)),
            # High X: 170.2 mm toward +X from X 1300.
            (StartCorner.TOP_RIGHT, (1300.0, 227.6), (1300.0, 227.6)),
            # Low Y: 199.8 mm toward -Y from Y 100.
            (StartCorner.BOTTOM_LEFT, (1390.0, 100.0), (1219.8, -99.8)),
        ],
    )
    async def test_a_real_overrun_still_warns(
        self, rig, task_mgr, caplog, corner, head, anchor
    ):
        machine, laser, cmd = rig
        machine.set_start_corner(corner)
        await _put_head(machine, laser, head)

        with caplog.at_level(logging.WARNING, logger="swiftcut.machine.cmd"):
            await _start(task_mgr, cmd, machine)

        assert (
            f"Job extent 170.2 x 199.8 mm from the anchor "
            f"({anchor[0]:.1f}, {anchor[1]:.1f}) leaves the 1400 x 900 mm "
            f"bed" in caplog.text
        )
        assert len(_notices(cmd)) == 1

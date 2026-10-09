"""The test cut: a 10 mm square at a layer's settings, where the canvas
marks it.

Jobs are anchored at the head, so the square is placed by moving the
head: the marker is an offset from the job's start corner, turned into
native axes by the arrow keys' one mapping, jogged with the jog panel's
primitive, then the square runs as an ordinary one-layer job, then the
head is jogged back. Every driver here is a fake: nothing reaches a
transport.
"""

import asyncio
import logging
import threading
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from blinker import Signal
from raygeo.ops.axis import Axis
from raygeo.ops.types import CommandType

from swiftcut.core.doc import Doc
from swiftcut.machine.cmd import (
    TEST_CUT_GAP_MM,
    TEST_CUT_SIZE_MM,
    MachineCmd,
    _test_cut_ops,
    default_test_cut_offset,
)
from swiftcut.machine.driver.driver import DeviceState
from swiftcut.machine.driver.ruida.ruida_encoder import (
    RuidaEncoder,
    build_rd_bytes,
    commands_to_rd_bytes,
)
from swiftcut.machine.driver.ruida.ruida_util import decode35, encode14
from swiftcut.machine.models.laser import Laser
from swiftcut.machine.models.machine import (
    JogDirection,
    Machine,
    Origin,
    StartCorner,
)
from swiftcut.machine.models.machine_panel import (
    MachinePanel,
    PanelOrientation,
)

# Opcodes that cut.
CUT_OPCODES = (b"\xa8", b"\xa9", b"\xaa", b"\xab")

# 10 mm/s, in the mm/min the model stores and the um/s the controller
# wants.
CUT_MM_MIN = 600
CUT_UM_S = 10000
POWER = 0.60
MIN_POWER = 0.15

# The jog panel's speed, mm/min.
JOG_SPEED = 3000
HEAD = (300.0, 200.0)

LEFT = (StartCorner.TOP_LEFT, StartCorner.BOTTOM_LEFT)


@pytest.fixture
def machine(context_initializer):
    """An ilab-614-like machine: top-left origin, one laser."""
    laser = Laser()
    laser.uid = "laser-1"
    m = Machine(context_initializer)
    m.heads.clear()
    m.add_head(laser)
    m.set_axis_extents(1400, 900)
    m.set_origin(Origin.TOP_LEFT)
    context_initializer.machine_mgr.add_machine(m)
    return m


@pytest.fixture
def doc_and_step(context_initializer, contour_step_class):
    """A document whose active layer has one contour step."""
    doc = Doc()
    workflow = doc.active_layer.workflow
    assert workflow is not None
    workflow.set_steps([])
    step = contour_step_class.create(context_initializer, name="cut")
    step.set_cut_speed(CUT_MM_MIN)
    step.set_power(POWER)
    step.set_min_power(MIN_POWER)
    workflow.add_step(step)
    return doc, step


def _commands(ops, machine, doc) -> list[bytes]:
    return RuidaEncoder().encode(ops, machine, doc).driver_data["commands"]


def _payloads(commands, opcode: bytes) -> list[bytes]:
    return [c[len(opcode) :] for c in commands if c.startswith(opcode)]


def _power14(power: float) -> bytes:
    return encode14(int(power * RuidaEncoder.POWER_SCALE))


class TestTheSquare:
    """The job a test cut sends: the step's own settings, 10 mm."""

    def test_it_is_a_ten_mm_square_from_the_head(self, machine, doc_and_step):
        _doc, step = doc_and_step

        ops = _test_cut_ops(machine, step)

        assert ops.rect() == (0.0, 0.0, TEST_CUT_SIZE_MM, TEST_CUT_SIZE_MM)
        assert TEST_CUT_SIZE_MM == 10.0

    def test_it_cuts_four_segments(self, machine, doc_and_step):
        doc, step = doc_and_step

        commands = _commands(_test_cut_ops(machine, step), machine, doc)

        assert len([c for c in commands if c[:1] in CUT_OPCODES]) == 4

    def test_it_cuts_at_the_steps_power_and_min_power(
        self, machine, doc_and_step
    ):
        """Min Power is read off the step by the uid the layer carries."""
        doc, step = doc_and_step

        commands = _commands(_test_cut_ops(machine, step), machine, doc)

        assert _payloads(commands, b"\xc6\x02") == [_power14(POWER)]
        assert _payloads(commands, b"\xc6\x01") == [_power14(MIN_POWER)]

    def test_it_cuts_at_the_steps_speed(self, machine, doc_and_step):
        doc, step = doc_and_step

        commands = _commands(_test_cut_ops(machine, step), machine, doc)

        speeds = [decode35(p) for p in _payloads(commands, b"\xc9\x02")]
        assert speeds == [CUT_UM_S]

    def test_it_is_one_layer_and_still_a_process(self, machine, doc_and_step):
        """It fires, so the door interlock must still apply to it."""
        doc, step = doc_and_step

        commands = _commands(_test_cut_ops(machine, step), machine, doc)

        assert b"\xca\x22\x00" in commands
        assert b"\xd8\x00" in commands


@pytest.mark.parametrize(
    "corner, expected",
    [
        (StartCorner.TOP_LEFT, (-25.0, 0.0)),
        (StartCorner.BOTTOM_LEFT, (-25.0, 0.0)),
        (StartCorner.TOP_RIGHT, (25.0, 0.0)),
        (StartCorner.BOTTOM_RIGHT, (25.0, 0.0)),
    ],
)
def test_the_default_spot_is_outside_the_start_corners_x_edge(
    corner, expected
):
    """
    The square's near edge is 15 mm out from the job's start-corner X
    edge: its own start corner is that gap plus its size away, level
    with the job's.
    """
    assert TEST_CUT_GAP_MM == 15.0
    assert default_test_cut_offset(corner) == expected


CONVENTIONS = [
    (origin, reverse_x, reverse_y, orientation)
    for origin in Origin
    for reverse_x in (False, True)
    for reverse_y in (False, True)
    for orientation in PanelOrientation
]


@pytest.fixture
def lite_machine(lite_context):
    machine = Machine(lite_context)
    machine.set_axis_extents(800.0, 600.0)
    return machine


def _sum(*vectors: dict[Axis, float]) -> tuple[float, float]:
    x = sum(v.get(Axis.X, 0.0) for v in vectors)
    y = sum(v.get(Axis.Y, 0.0) for v in vectors)
    return x, y


@pytest.mark.parametrize(
    "origin, reverse_x, reverse_y, orientation", CONVENTIONS
)
def test_a_canvas_offset_moves_the_head_as_the_arrows_do(
    lite_machine, origin, reverse_x, reverse_y, orientation
):
    """Right is east and up is north: calculate_jog is the oracle."""
    lite_machine.set_origin(origin)
    lite_machine.set_reverse_x_axis(reverse_x)
    lite_machine.set_reverse_y_axis(reverse_y)
    lite_machine.panel.set_orientation(orientation)
    panel = lite_machine.panel
    jog = panel.calculate_jog

    assert panel.visual_offset_to_native(12.0, 30.0) == pytest.approx(
        _sum(jog(JogDirection.EAST, 12.0), jog(JogDirection.NORTH, 30.0))
    )
    assert panel.visual_offset_to_native(-12.0, -30.0) == pytest.approx(
        _sum(jog(JogDirection.WEST, 12.0), jog(JogDirection.SOUTH, 30.0))
    )


def test_the_offset_comes_from_calculate_jog(lite_machine):
    """One mapping site: flip the arrows and the offset follows."""
    panel = lite_machine.panel
    before = panel.visual_offset_to_native(12.0, -30.0)
    real = MachinePanel.calculate_jog

    def flipped(self, direction, distance):
        return {
            axis: -delta
            for axis, delta in real(self, direction, distance).items()
        }

    with patch.object(MachinePanel, "calculate_jog", flipped):
        after = panel.visual_offset_to_native(12.0, -30.0)

    assert after == (-before[0], -before[1])


def test_on_ilab_614_left_is_plus_x_and_up_is_minus_y(lite_machine):
    """The arrow convention: left = +X, and a top-left origin's Y."""
    lite_machine.set_origin(Origin.TOP_LEFT)

    assert lite_machine.panel.visual_offset_to_native(-25.0, 0.0) == (
        25.0,
        0.0,
    )
    assert lite_machine.panel.visual_offset_to_native(0.0, 10.0) == (
        0.0,
        -10.0,
    )


# The run: jog there, cut, jog back.


class _Driver:
    """A driver whose job ends at once, after an optional side effect."""

    native_overscan = False

    def __init__(self, during_run=None):
        self.runs = []
        self.cancels = 0
        self.job_finished = Signal()
        self._during_run = during_run

    async def run(self, encoded, doc, ops, on_command_done=None):
        self.runs.append((encoded, doc, ops))
        if self._during_run is not None:
            await self._during_run()

    async def cancel(self):
        self.cancels += 1


def _head_at(machine: Machine, x: float | None, y: float | None):
    """Put the head somewhere, as the driver's position reads do."""
    # Built first: a new controller hands the machine its driver's
    # (unknown) position.
    _ = machine.controller
    machine.set_device_state(DeviceState(machine_pos=(x, y, 0.0)))


def _arriving_jog(machine: Machine, order=None, short: float = 0.0):
    """A jog that settles where it was sent, or short of it in X."""

    async def jog(deltas, speed):
        if order is not None:
            order.append("jog")
        x, y = machine.device_state.machine_pos[:2]
        _head_at(
            machine,
            x + deltas.get(Axis.X, 0.0) - short,
            y + deltas.get(Axis.Y, 0.0),
        )

    return AsyncMock(side_effect=jog)


def _cmd(task_mgr, doc) -> MachineCmd:
    editor = MagicMock()
    editor.task_manager = task_mgr
    editor.doc = doc
    return MachineCmd(editor)


def _notices(cmd: MachineCmd) -> list[str]:
    send = cmd._editor.notification_requested.send
    return [c.kwargs["message"] for c in send.call_args_list]


async def wait_for_tasks_to_finish(task_mgr):
    await asyncio.sleep(0)
    if await asyncio.to_thread(task_mgr.wait_until_settled, 2000):
        return
    pytest.fail("Task manager did not become idle in time.")


def _driving(machine, driver, jog):
    """The machine's driver and jog, faked; the Ruida encoder."""
    return (
        patch.object(
            type(machine),
            "driver",
            new_callable=PropertyMock,
            return_value=driver,
        ),
        patch.object(machine, "jog", jog),
        patch(
            "swiftcut.machine.cmd._create_driver_encoder",
            return_value=RuidaEncoder(),
        ),
    )


async def _test_cut(task_mgr, cmd, machine, driver, jog, step, offset):
    """Run a test cut to its end, on fakes."""
    drv, jg, enc = _driving(machine, driver, jog)
    with drv, jg, enc:
        cmd.run_test_cut(machine, step, offset, JOG_SPEED)
        await wait_for_tasks_to_finish(task_mgr)
        # Main-thread callbacks, like the notices, land after.
        await asyncio.sleep(0.05)


class TestTheRun:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("corner", list(StartCorner))
    async def test_the_head_moves_by_the_marker_offset_cuts_and_returns(
        self, task_mgr, machine, doc_and_step, corner
    ):
        """
        The pre-move is the offset in native axes, for every start
        corner; the driver's own corner move follows inside the run,
        and the way back undoes both.
        """
        doc, step = doc_and_step
        machine.set_start_corner(corner)
        offset = default_test_cut_offset(corner)
        native = machine.panel.visual_offset_to_native(*offset)
        # ilab-614: left is +X, so a square left of the job is +25 X.
        assert native == ((25.0, 0.0) if corner in LEFT else (-25.0, 0.0))
        corner_dx, corner_dy = machine.panel.start_corner_offset(
            corner, TEST_CUT_SIZE_MM, TEST_CUT_SIZE_MM
        )
        _head_at(machine, *HEAD)
        order = []

        async def corner_move():
            order.append("run")
            x, y = machine.device_state.machine_pos[:2]
            _head_at(machine, x + corner_dx, y + corner_dy)

        driver = _Driver(during_run=corner_move)
        jog = _arriving_jog(machine, order)
        cmd = _cmd(task_mgr, doc)

        await _test_cut(
            task_mgr, cmd, machine, driver, jog, step, offset
        )

        assert order == ["jog", "run", "jog"]
        there, back = (c.args for c in jog.await_args_list)
        assert there == ({Axis.X: native[0], Axis.Y: native[1]}, JOG_SPEED)
        assert back == (
            {
                Axis.X: -(native[0] + corner_dx),
                Axis.Y: -(native[1] + corner_dy),
            },
            JOG_SPEED,
        )
        assert machine.device_state.machine_pos[:2] == pytest.approx(HEAD)
        assert _notices(cmd) == []
        assert not cmd.is_job_running

    @pytest.mark.asyncio
    async def test_a_picked_spot_moves_the_head_by_its_offset(
        self, task_mgr, machine, doc_and_step
    ):
        """Right 12 and down 30 on ilab-614: -12 X and +30 Y."""
        doc, step = doc_and_step
        machine.set_start_corner(StartCorner.TOP_LEFT)
        _head_at(machine, *HEAD)
        jog = _arriving_jog(machine)

        await _test_cut(
            task_mgr,
            _cmd(task_mgr, doc),
            machine,
            _Driver(),
            jog,
            step,
            (12.0, -30.0),
        )

        assert jog.await_args_list[0].args == (
            {Axis.X: -12.0, Axis.Y: 30.0},
            JOG_SPEED,
        )

    @pytest.mark.asyncio
    async def test_the_job_sent_is_the_square_at_the_steps_settings(
        self, task_mgr, machine, doc_and_step
    ):
        """
        Encoded by the driver's encoder, against a document of its own
        that holds a copy of the step, uid and all.
        """
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        driver = _Driver()

        await _test_cut(
            task_mgr,
            _cmd(task_mgr, doc),
            machine,
            driver,
            _arriving_jog(machine),
            step,
            (-25.0, 0.0),
        )

        ((encoded, sent_doc, ops),) = driver.runs
        assert sent_doc is not doc
        (copy,) = sent_doc.active_layer.workflow.steps
        assert copy is not step
        assert copy.uid == step.uid
        assert ops.rect() == (0.0, 0.0, 10.0, 10.0)
        commands = encoded.driver_data["commands"]
        assert len([c for c in commands if c[:1] in CUT_OPCODES]) == 4
        assert _payloads(commands, b"\xc6\x02") == [_power14(POWER)]
        assert _payloads(commands, b"\xc6\x01") == [_power14(MIN_POWER)]
        speeds = [decode35(p) for p in _payloads(commands, b"\xc9\x02")]
        assert speeds == [CUT_UM_S]

    @pytest.mark.asyncio
    async def test_it_is_not_a_start(self, task_mgr, machine, doc_and_step):
        """Not the last job's start, and not the Start path at all."""
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        cmd = _cmd(task_mgr, doc)
        states = []
        cmd.job_state_changed.connect(
            lambda sender: states.append(cmd.is_job_running), weak=False
        )

        with (
            patch.object(cmd, "_run_send_action") as send_action,
            patch.object(cmd, "_start_job_ended") as start_ended,
        ):
            await _test_cut(
                task_mgr,
                cmd,
                machine,
                _Driver(),
                _arriving_jog(machine),
                step,
                (-25.0, 0.0),
            )

        assert machine.last_job_start is None
        send_action.assert_not_called()
        start_ended.assert_not_called()
        cmd._editor.pipeline.generate_job_artifact_async.assert_not_called()
        # Running from the request until done, as a Start is.
        assert states[0] is True
        assert states[-1] is False

    def test_it_is_its_own_task_not_the_send_job(self, doc_and_step):
        """A job history bound to the "send-job" task never sees it."""
        _doc, step = doc_and_step
        editor = MagicMock()
        cmd = MachineCmd(editor)

        cmd.run_test_cut(MagicMock(), step, (-25.0, 0.0), JOG_SPEED)

        (call,) = editor.task_manager.add_coroutine.call_args_list
        assert call.kwargs["key"] == "test-cut"

    @pytest.mark.asyncio
    async def test_on_done_runs_once_it_is_done(
        self, task_mgr, machine, doc_and_step
    ):
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        cmd = _cmd(task_mgr, doc)
        on_done = MagicMock()
        drv, jg, enc = _driving(machine, _Driver(), _arriving_jog(machine))

        with drv, jg, enc:
            cmd.run_test_cut(
                machine, step, (-25.0, 0.0), JOG_SPEED, on_done=on_done
            )
            assert cmd.is_job_running
            await wait_for_tasks_to_finish(task_mgr)
            await asyncio.sleep(0.05)

        on_done.assert_called_once_with()
        assert not cmd.is_job_running


class TestTheSettingsConfirmedAtCut:
    """
    The laser fires at what the sheet showed: the step is copied at
    Cut, so nothing done to it afterwards reaches the controller.
    """

    @pytest.mark.asyncio
    async def test_an_edit_during_the_move_does_not_reach_the_laser(
        self, task_mgr, machine, doc_and_step
    ):
        """
        Max Power, Min Power and speed changed while the head moves to
        the spot: the ops, the blob encoded before the move and the
        one the driver builds from ops and document when it runs all
        carry the values of Cut.
        """
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        arrive = _arriving_jog(machine).side_effect

        async def edit_while_moving(deltas, speed):
            step.set_power(0.95)
            step.set_min_power(0.90)
            step.set_cut_speed(3000)
            await arrive(deltas, speed)

        driver = _Driver()
        at_run = {}

        async def build_as_the_driver_does():
            # RuidaDriver.run: build_rd_bytes(ops, machine, doc), now.
            ((_encoded, sent_doc, ops),) = driver.runs
            at_run["blob"] = build_rd_bytes(ops, machine, sent_doc)
            at_run["commands"] = _commands(ops, machine, sent_doc)

        driver._during_run = build_as_the_driver_does

        await _test_cut(
            task_mgr,
            _cmd(task_mgr, doc),
            machine,
            driver,
            AsyncMock(side_effect=edit_while_moving),
            step,
            (-25.0, 0.0),
        )

        # The edit landed on the document's step, before the cut.
        assert (step.power, step.min_power, step.cut_speed) == (
            0.95,
            0.90,
            3000,
        )
        ((encoded, _sent_doc, ops),) = driver.runs
        kinds = [ops.command_type(i) for i in range(ops.len())]
        powers = [
            ops.power(i)
            for i, kind in enumerate(kinds)
            if kind == CommandType.SET_POWER
        ]
        rates = [
            ops.rate(i)
            for i, kind in enumerate(kinds)
            if kind == CommandType.SET_FEED_RATE
        ]
        assert powers == [POWER]
        assert rates == [CUT_MM_MIN]
        for commands in (encoded.driver_data["commands"], at_run["commands"]):
            assert _payloads(commands, b"\xc6\x02") == [_power14(POWER)]
            assert _payloads(commands, b"\xc6\x01") == [_power14(MIN_POWER)]
            speeds = [decode35(p) for p in _payloads(commands, b"\xc9\x02")]
            assert speeds == [CUT_UM_S]
        # What goes down the wire is what was encoded before the move.
        assert at_run["blob"] == commands_to_rd_bytes(
            encoded.driver_data["commands"]
        )


class TestRefusals:
    @pytest.mark.asyncio
    async def test_an_unknown_position_moves_and_cuts_nothing(
        self, task_mgr, machine, doc_and_step
    ):
        doc, step = doc_and_step
        _head_at(machine, None, None)
        driver = _Driver()
        jog = _arriving_jog(machine)
        cmd = _cmd(task_mgr, doc)

        await _test_cut(
            task_mgr, cmd, machine, driver, jog, step, (-25.0, 0.0)
        )

        jog.assert_not_awaited()
        assert driver.runs == []
        assert "position is unknown" in _notices(cmd)[0]

    @pytest.mark.asyncio
    async def test_a_head_that_stops_short_cuts_nothing(
        self, task_mgr, machine, doc_and_step, caplog
    ):
        """Ignored while busy, clamped at the bed or timed out."""
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        driver = _Driver()
        jog = _arriving_jog(machine, short=2.0)
        cmd = _cmd(task_mgr, doc)

        with caplog.at_level(logging.WARNING, logger="swiftcut.machine.cmd"):
            await _test_cut(
                task_mgr, cmd, machine, driver, jog, step, (-25.0, 0.0)
            )

        jog.assert_awaited_once()
        assert driver.runs == []
        assert "did not reach its spot" in caplog.text
        assert len(_notices(cmd)) == 1
        assert "did not reach" in _notices(cmd)[0]
        assert not cmd.is_job_running

    def test_a_running_job_refuses_it(self, doc_and_step):
        """A Start that is still running: nothing is scheduled."""
        _doc, step = doc_and_step
        editor = MagicMock()
        cmd = MachineCmd(editor)
        machine = MagicMock()

        cmd.run_send_job(machine)
        cmd.run_test_cut(machine, step, (-25.0, 0.0), JOG_SPEED)

        editor.task_manager.add_coroutine.assert_called_once()
        assert (
            editor.task_manager.add_coroutine.call_args.kwargs["key"]
            == "send-job"
        )

    @pytest.mark.asyncio
    async def test_while_it_runs_a_start_and_a_second_one_are_refused(
        self, task_mgr, machine, doc_and_step, caplog
    ):
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        driver = _Driver()
        jogging = threading.Event()

        async def jog_until_stopped(deltas, speed):
            jogging.set()
            while not driver.cancels:
                await asyncio.sleep(0.01)

        jog = AsyncMock(side_effect=jog_until_stopped)
        cmd = _cmd(task_mgr, doc)
        drv, jg, enc = _driving(machine, driver, jog)
        with drv, jg, enc:
            cmd.run_test_cut(machine, step, (-25.0, 0.0), JOG_SPEED)
            assert await asyncio.to_thread(jogging.wait, 5)
            first = task_mgr.get_task("test-cut")
            assert cmd.is_job_running

            with caplog.at_level(
                logging.WARNING, logger="swiftcut.machine.cmd"
            ):
                cmd.run_test_cut(machine, step, (-25.0, 0.0), JOG_SPEED)
                cmd.run_send_job(machine)
            await asyncio.sleep(0.1)

            assert "Test cut ignored: a job is already running" in (
                caplog.text
            )
            assert "Start ignored: a job is already running" in caplog.text
            assert task_mgr.get_task("test-cut") is first
            assert task_mgr.get_task("send-job") is None
            jog.assert_awaited_once()

            cmd.cancel_job(machine)
            await wait_for_tasks_to_finish(task_mgr)

        assert driver.runs == []


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_during_the_move_cuts_nothing(
        self, task_mgr, machine, doc_and_step
    ):
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        driver = _Driver()
        jogging = threading.Event()

        async def jog_until_stopped(deltas, speed):
            jogging.set()
            while not driver.cancels:
                await asyncio.sleep(0.01)

        jog = AsyncMock(side_effect=jog_until_stopped)
        cmd = _cmd(task_mgr, doc)
        drv, jg, enc = _driving(machine, driver, jog)
        with drv, jg, enc:
            cmd.run_test_cut(machine, step, (-25.0, 0.0), JOG_SPEED)
            assert await asyncio.to_thread(jogging.wait, 5)
            cmd.cancel_job(machine)
            await wait_for_tasks_to_finish(task_mgr)
            await asyncio.sleep(0.05)

        assert driver.runs == []
        assert driver.cancels == 1
        jog.assert_awaited_once()
        assert "was stopped" in _notices(cmd)[0]
        assert not cmd.is_job_running

    @pytest.mark.asyncio
    async def test_stop_during_the_cut_leaves_the_head_there(
        self, task_mgr, machine, doc_and_step
    ):
        """No way back after a Stop: the head stays where it stopped."""
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        cutting = threading.Event()
        driver = _Driver()

        async def cut_until_stopped():
            cutting.set()
            while not driver.cancels:
                await asyncio.sleep(0.01)

        driver._during_run = cut_until_stopped
        jog = _arriving_jog(machine)
        cmd = _cmd(task_mgr, doc)
        drv, jg, enc = _driving(machine, driver, jog)
        with drv, jg, enc:
            cmd.run_test_cut(machine, step, (-25.0, 0.0), JOG_SPEED)
            assert await asyncio.to_thread(cutting.wait, 5)
            cmd.cancel_job(machine)
            await wait_for_tasks_to_finish(task_mgr)
            await asyncio.sleep(0.05)

        assert len(driver.runs) == 1
        jog.assert_awaited_once()
        assert machine.device_state.machine_pos[:2] == (325.0, 200.0)
        assert _notices(cmd) == []

    @pytest.mark.asyncio
    async def test_a_stop_before_this_test_cut_does_not_refuse_it(
        self, task_mgr, machine, doc_and_step
    ):
        """The Stop latch belongs to one run: the next one moves."""
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        driver = _Driver()
        jog = _arriving_jog(machine)
        cmd = _cmd(task_mgr, doc)
        with patch.object(
            type(machine),
            "driver",
            new_callable=PropertyMock,
            return_value=driver,
        ):
            cmd.cancel_job(machine)
            await wait_for_tasks_to_finish(task_mgr)

        await _test_cut(
            task_mgr, cmd, machine, driver, jog, step, (-25.0, 0.0)
        )

        assert len(driver.runs) == 1
        assert jog.await_count == 2


class TestFailures:
    @pytest.mark.asyncio
    async def test_a_refused_job_is_shown_and_the_head_stays(
        self, task_mgr, machine, doc_and_step
    ):
        """The driver raises when busy: no cut, so no way back."""
        doc, step = doc_and_step
        _head_at(machine, *HEAD)

        async def busy():
            raise RuntimeError("the machine is busy")

        driver = _Driver(during_run=busy)
        jog = _arriving_jog(machine)
        cmd = _cmd(task_mgr, doc)

        await _test_cut(
            task_mgr, cmd, machine, driver, jog, step, (-25.0, 0.0)
        )

        jog.assert_awaited_once()
        assert _notices(cmd) == [
            (
                "Test cut failed: the machine is busy. The head was left "
                "at the test spot: a Start from the head's position would "
                "begin there."
            )
        ]
        assert not cmd.is_job_running

    @pytest.mark.asyncio
    async def test_an_encoding_failure_moves_nothing(
        self, task_mgr, machine, doc_and_step
    ):
        """The job is encoded before the move, so the head stays."""
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        driver = _Driver()
        jog = _arriving_jog(machine)
        cmd = _cmd(task_mgr, doc)
        drv, jg, _enc = _driving(machine, driver, jog)
        encoder = MagicMock()
        encoder.encode.side_effect = ValueError("no encoding")

        with (
            drv,
            jg,
            patch(
                "swiftcut.machine.cmd._create_driver_encoder",
                return_value=encoder,
            ),
        ):
            cmd.run_test_cut(machine, step, (-25.0, 0.0), JOG_SPEED)
            await wait_for_tasks_to_finish(task_mgr)
            await asyncio.sleep(0.05)

        jog.assert_not_awaited()
        assert driver.runs == []
        assert _notices(cmd) == ["Test cut not run: no encoding"]
        assert not cmd.is_job_running

    @pytest.mark.asyncio
    async def test_an_error_on_the_way_there_is_shown(
        self, task_mgr, machine, doc_and_step
    ):
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        driver = _Driver()
        jog = AsyncMock(side_effect=OSError("link lost"))
        cmd = _cmd(task_mgr, doc)

        await _test_cut(
            task_mgr, cmd, machine, driver, jog, step, (-25.0, 0.0)
        )

        assert driver.runs == []
        assert _notices(cmd) == [
            (
                "Test cut not run: the move to its spot failed: link "
                "lost. The head may have stopped on the way."
            )
        ]
        assert not cmd.is_job_running

    @pytest.mark.asyncio
    async def test_an_error_on_the_way_back_is_shown(
        self, task_mgr, machine, doc_and_step
    ):
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        arrive = _arriving_jog(machine).side_effect
        jogs = []

        async def jog(deltas, speed):
            jogs.append(deltas)
            if len(jogs) == 2:
                raise OSError("link lost")
            await arrive(deltas, speed)

        driver = _Driver()
        cmd = _cmd(task_mgr, doc)

        await _test_cut(
            task_mgr,
            cmd,
            machine,
            driver,
            AsyncMock(side_effect=jog),
            step,
            (-25.0, 0.0),
        )

        assert len(driver.runs) == 1
        assert len(jogs) == 2
        assert _notices(cmd) == [
            (
                "The test cut ran, but the move back failed: link lost. "
                "A Start from the head's position would begin where it "
                "stopped."
            )
        ]
        assert not cmd.is_job_running

    @pytest.mark.asyncio
    async def test_a_head_that_does_not_get_back_is_shown(
        self, task_mgr, machine, doc_and_step, caplog
    ):
        doc, step = doc_and_step
        _head_at(machine, *HEAD)
        jogs = []

        async def jog(deltas, speed):
            # The way there arrives; the way back stops 3 mm short.
            short = 3.0 if jogs else 0.0
            jogs.append(deltas)
            x, y = machine.device_state.machine_pos[:2]
            _head_at(machine, x + deltas[Axis.X] - short, y + deltas[Axis.Y])

        driver = _Driver()
        cmd = _cmd(task_mgr, doc)

        with caplog.at_level(logging.WARNING, logger="swiftcut.machine.cmd"):
            await _test_cut(
                task_mgr,
                cmd,
                machine,
                driver,
                AsyncMock(side_effect=jog),
                step,
                (-25.0, 0.0),
            )

        assert len(driver.runs) == 1
        assert len(jogs) == 2
        assert "did not return" in caplog.text
        assert _notices(cmd) == [
            "The test cut ran, but the head did not return to where it was."
        ]

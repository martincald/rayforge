"""Failing reproductions for the findings in MOTION_AUDIT.md.

Every test here names its audit id in the docstring. They exercise the
driver against a stub client that records the interactive byte stream,
so no transport, no simulator and no network is involved.
"""

import asyncio

import pytest
import pytest_asyncio
from blinker import Signal

from rayforge.machine.driver.driver import Axis
from rayforge.machine.driver.ruida.ruida_driver import RuidaDriver
from rayforge.machine.driver.ruida.ruida_util import decode35, encode35
from rayforge.machine.models.machine import JogDirection, Machine

STOP = b"\xd8\x01"


class MotionClientSpy:
    """Records the interactive commands the driver emits.

    Position reads are gated so a test can park the driver inside an
    await and drive the interleaving deterministically.
    """

    def __init__(self, position=(0, 0)):
        self.commands: list[bytes] = []
        self.position: tuple[int, int] | None = position
        self.reads = 0
        self.freeze_position = False
        self.read_gate = asyncio.Event()
        self.read_gate.set()
        self.state_changed = Signal()
        self.position_updated = Signal()
        self.is_connected = True

    async def disconnect(self):
        pass

    async def set_travel_speed(self, um_per_s: int):
        self.commands.append(b"\xc9\x02" + encode35(um_per_s))

    async def rapid_move_xy(self, x_um: int, y_um: int, light: bool = False):
        self.commands.append(b"\xd9\x10\x00" + encode35(x_um) + encode35(y_um))
        if not self.freeze_position:
            self.position = (x_um, y_um)

    async def stop_process(self):
        self.commands.append(STOP)

    async def read_position(self, timeout: float = 2.0):
        self.reads += 1
        await self.read_gate.wait()
        return self.position


def moves(commands: list[bytes]) -> list[bytes]:
    """The D9 motion commands out of a recorded stream."""
    return [c for c in commands if c[:1] == b"\xd9"]


def move_target(command: bytes) -> tuple[int, int]:
    return decode35(command[3:8]), decode35(command[8:13])


def moves_after_stop(commands: list[bytes]) -> list[bytes]:
    """Motion recorded at or after the first stop was sent."""
    if STOP not in commands:
        return []
    return moves(commands[commands.index(STOP) :])


@pytest_asyncio.fixture
async def driver(lite_context):
    """A RuidaDriver with no transports; tests inject a client spy."""
    machine = Machine(lite_context)
    machine.driver_name = "RuidaDriver"
    lite_context.machine_mgr.add_machine(machine)
    drv = RuidaDriver(lite_context, machine)
    drv._machine.set_axis_extents(400.0, 300.0)

    yield drv

    drv._client = None
    await drv.cleanup()
    await machine.shutdown()


class TestStopReachesEveryMotion:
    """Any motion the app starts, the app must be able to stop."""

    @pytest.mark.asyncio
    async def test_cancel_aborts_a_running_go_scale(self, driver):
        """MOT-01: STOP must halt a Go Scale, not pause it."""
        spy = MotionClientSpy(position=(0, 0))
        driver._client = spy
        driver.FRAME_CORNER_TIMEOUT = 0.05
        driver.FRAME_POLL_INTERVAL = 0.01
        plain_move = spy.rapid_move_xy

        async def move_then_stop(x_um, y_um, light=False):
            await plain_move(x_um, y_um, light=light)
            if len(moves(spy.commands)) == 2:
                # The head is halted mid-edge and stops reporting
                # progress, exactly as an emergency stop leaves it.
                spy.freeze_position = True
                await driver.cancel()

        spy.rapid_move_xy = move_then_stop

        await driver.trace_frame(100.0, 50.0)

        assert len(moves(spy.commands)) == 2
        assert moves_after_stop(spy.commands) == []

    @pytest.mark.asyncio
    async def test_cancel_before_a_trace_is_not_erased(self, driver):
        """MOT-02: a Stop pressed while the pipeline runs must hold."""
        spy = MotionClientSpy(position=(0, 0))
        driver._client = spy
        driver.FRAME_CORNER_TIMEOUT = 0.05
        driver.FRAME_POLL_INTERVAL = 0.01

        await driver.cancel_frame()
        await driver.trace_frame(100.0, 50.0)

        assert moves(spy.commands) == []

    @pytest.mark.asyncio
    async def test_cancel_does_not_let_a_diagonal_restart(self, driver):
        """MOT-03: releasing half a diagonal after STOP must not move."""
        spy = MotionClientSpy(position=(100000, 100000))
        driver._client = spy
        driver._last_known_pos = (100000, 100000)

        await driver.jog_key_down("x", 1)
        await driver.jog_key_down("y", 1)
        await driver.cancel()
        await driver.jog_key_up("x", 1)

        assert moves_after_stop(spy.commands) == []

    @pytest.mark.asyncio
    async def test_release_all_keys_aborts_a_running_go_scale(self, driver):
        """MOT-04: focus loss during Go Scale must not resume it."""
        spy = MotionClientSpy(position=(0, 0))
        driver._client = spy
        driver.FRAME_CORNER_TIMEOUT = 0.05
        driver.FRAME_POLL_INTERVAL = 0.01
        plain_move = spy.rapid_move_xy

        async def move_then_release(x_um, y_um, light=False):
            await plain_move(x_um, y_um, light=light)
            if len(moves(spy.commands)) == 2:
                spy.freeze_position = True
                await driver.release_all_jog_keys()

        spy.rapid_move_xy = move_then_release

        await driver.trace_frame(100.0, 50.0)

        assert moves_after_stop(spy.commands) == []

    @pytest.mark.asyncio
    async def test_key_up_cannot_be_overtaken_by_its_key_down(self, driver):
        """MOT-06: a run-to-limit must never land after its own stop."""
        spy = MotionClientSpy(position=(100000, 100000))
        driver._client = spy
        driver._last_known_pos = None
        spy.read_gate.clear()

        down = asyncio.create_task(driver.jog_key_down("x", 1))
        await asyncio.sleep(0)
        up = asyncio.create_task(driver.jog_key_up("x", 1))
        await asyncio.sleep(0)
        spy.read_gate.set()
        await asyncio.gather(down, up)

        assert moves_after_stop(spy.commands) == []
        assert driver._jog_busy is False
        assert driver._jog_keys_down == set()

    @pytest.mark.asyncio
    async def test_stop_resyncs_before_clearing_busy(self, driver):
        """MOT-28 companion: a failed resync must not keep the target."""
        spy = MotionClientSpy(position=(100000, 100000))
        driver._client = spy
        driver._last_known_pos = (100000, 100000)

        await driver.jog_key_down("x", 1)
        spy.position = None  # the resync read times out
        await driver.jog_key_up("x", 1)

        # The cache must not still claim the head reached the far limit
        # it was only ever commanded toward.
        assert driver._last_known_pos != (399000, 100000)


class TestBusyFlagNeverLeaks:
    """A leaked busy flag silently swallows every later command."""

    @pytest.mark.asyncio
    async def test_diagonal_release_leaves_the_driver_usable(self, driver):
        """MOT-12: an emptied key set must not pin _jog_busy True."""
        spy = MotionClientSpy(position=(100000, 100000))
        driver._client = spy
        driver._last_known_pos = (100000, 100000)

        first = asyncio.create_task(driver.jog_key_down("x", 1))
        await asyncio.sleep(0)
        spy.read_gate.clear()
        second = asyncio.create_task(driver.jog_key_down("y", 1))
        await asyncio.sleep(0)
        spy.read_gate.set()
        await driver.jog_key_up("x", 1)
        await driver.jog_key_up("y", 1)
        await asyncio.gather(first, second)

        assert driver._jog_keys_down == set()
        assert driver._jog_busy is False

        emitted = len(moves(spy.commands))
        await driver.jog(1200, x=1.0)
        assert len(moves(spy.commands)) > emitted

    @pytest.mark.asyncio
    async def test_a_held_z_key_does_not_block_x_and_y(self, driver):
        """MOT-13: Z is not implemented, so it must not pretend."""
        spy = MotionClientSpy(position=(100000, 100000))
        driver._client = spy
        driver._last_known_pos = (100000, 100000)

        assert driver.can_jog(Axis.Z) is False

        await driver.jog_key_down("z", 1)

        assert spy.commands == []
        assert driver._jog_busy is False
        assert driver._jog_keys_down == set()

    @pytest.mark.asyncio
    async def test_z_step_jog_emits_nothing_and_stays_idle(self, driver):
        """MOT-13: a Z step must be refused, not silently dropped."""
        spy = MotionClientSpy(position=(100000, 100000))
        driver._client = spy
        driver._last_known_pos = (100000, 100000)

        await driver.jog(600, z=5.0)

        assert spy.commands == []
        assert driver._jog_busy is False


class TestOriginIsNeverInvented:
    """An absolute rapid needs a real origin or no command at all."""

    @pytest.mark.asyncio
    async def test_step_jog_refuses_an_unknown_position(self, driver):
        """MOT-08: a failed read must not become the machine corner."""
        spy = MotionClientSpy(position=None)
        driver._client = spy
        driver._last_known_pos = None

        await driver.jog(600, x=10.0)

        assert moves(spy.commands) == []
        assert driver._jog_busy is False

    @pytest.mark.asyncio
    async def test_hold_jog_refuses_an_unknown_position(self, driver):
        """MOT-08: same for the press-and-hold run to the bed limit."""
        spy = MotionClientSpy(position=None)
        driver._client = spy
        driver._last_known_pos = None

        await driver.jog_key_down("x", 1)

        assert moves(spy.commands) == []
        assert driver._jog_busy is False

    @pytest.mark.asyncio
    async def test_go_scale_refuses_an_unknown_position(self, driver):
        """MOT-08: a trace from a fabricated origin is not the job."""
        spy = MotionClientSpy(position=None)
        driver._client = spy
        driver._last_known_pos = None
        driver.FRAME_CORNER_TIMEOUT = 0.05
        driver.FRAME_POLL_INTERVAL = 0.01

        await driver.trace_frame(100.0, 50.0)

        assert moves(spy.commands) == []

    @pytest.mark.asyncio
    async def test_partial_position_update_does_not_invent_the_other(
        self, driver
    ):
        """MOT-31: one axis reply must not assert 0 for the other."""
        driver._last_known_pos = None

        driver._on_position_updated(None, "x", 250000)

        assert driver._last_known_pos is None


class TestReversedAxesJogTheRightWay:
    """calculate_jog already signs the delta; the driver must agree."""

    @pytest.mark.asyncio
    async def test_hold_jog_east_runs_to_the_east_limit(self, driver):
        """MOT-07: a reversed X must not swap the arrows."""
        machine = driver._machine
        machine.set_reverse_x_axis(True)
        driver._client = spy = MotionClientSpy(position=(-100000, 100000))
        driver._last_known_pos = (-100000, 100000)

        delta = machine.panel.calculate_jog(JogDirection.EAST, 10.0)[Axis.X]
        key = 1 if delta > 0 else -1

        await driver.jog_key_down("x", key)

        # East is machine X = -(400 - 1) mm in app space, which is
        # +399 mm on the controller's own 0..extent scale.
        assert move_target(moves(spy.commands)[0])[0] == 399000

    @pytest.mark.asyncio
    async def test_step_jog_east_moves_east(self, driver):
        """MOT-07: a 10 mm east click must not move 10 mm west."""
        machine = driver._machine
        machine.set_reverse_x_axis(True)
        machine.soft_limits_enabled = False
        driver._client = spy = MotionClientSpy(position=(-100000, 100000))
        driver._last_known_pos = (-100000, 100000)

        delta = machine.panel.calculate_jog(JogDirection.EAST, 10.0)[Axis.X]

        await driver.jog(600, x=delta)

        # -100 mm app space, 10 mm further east, is -110 mm app space
        # and +110 mm on the controller.
        assert move_target(moves(spy.commands)[0])[0] == 110000

    @pytest.mark.asyncio
    async def test_reported_position_uses_the_profile_sign(self, driver):
        """MOT-07: the readout must live in the model's own space."""
        driver._machine.set_reverse_x_axis(True)

        driver._on_position_updated(None, "x", 250000)

        assert driver.state.machine_pos[0] == pytest.approx(-250.0)


class TestWaitsAreBounded:
    """A wait that cannot end takes the whole app with it."""

    @pytest.mark.asyncio
    async def test_job_completion_wait_gives_up_on_a_silent_controller(
        self, driver
    ):
        """MOT-10: an unanswered status read must not hang forever."""

        class SilentClient(MotionClientSpy):
            async def _read_memory_wait(self, address, timeout=2.0):
                return None

        driver._client = SilentClient()
        driver.STATUS_POLL_INTERVAL = 0.01

        await asyncio.wait_for(driver._wait_for_job_completion(), timeout=2.0)

    @pytest.mark.asyncio
    async def test_home_waits_on_machine_status_not_on_current_x(self, driver):
        """MOT-11: reading Current X says nothing about homing."""
        addresses: list[int] = []
        busy_reads = [3]

        class HomingClient(MotionClientSpy):
            async def home_xy(self):
                self.commands.append(b"\xd8\x2a")
                assert driver._jog_busy is True

            async def home_z(self):
                self.commands.append(b"\xd8\x2c")

            async def _read_memory_wait(self, address, timeout=2.0):
                addresses.append(address)
                if address != driver.MACHINE_STATUS_ADDRESS:
                    return 0
                if busy_reads[0] > 0:
                    busy_reads[0] -= 1
                    return driver.STATUS_JOB_RUNNING_BIT
                return 0

        driver._client = HomingClient()
        driver.STATUS_POLL_INTERVAL = 0.01

        await driver.home()

        status_reads = addresses.count(driver.MACHINE_STATUS_ADDRESS)
        assert status_reads == 4
        assert driver._jog_busy is False

    @pytest.mark.asyncio
    async def test_home_invalidates_the_cached_position(self, driver):
        """MOT-23: the head is at zero after homing, not where it was."""

        class HomingClient(MotionClientSpy):
            async def home_xy(self):
                self.commands.append(b"\xd8\x2a")

            async def home_z(self):
                self.commands.append(b"\xd8\x2c")

            async def _read_memory_wait(self, address, timeout=2.0):
                return 0

        driver._client = HomingClient()
        driver._last_known_pos = (123000, 45000)
        driver.STATUS_POLL_INTERVAL = 0.01

        await driver.home()

        assert driver._last_known_pos != (123000, 45000)

    @pytest.mark.asyncio
    async def test_settle_timeout_scales_with_the_step(self, driver):
        """MOT-14: the travel-time term must not always be zero."""
        spy = MotionClientSpy(position=(0, 0))
        spy.freeze_position = True  # the head never arrives
        driver._client = spy
        driver._machine.set_axis_extents(2000.0, 2000.0)
        driver._last_known_pos = (0, 0)
        driver.JOG_SETTLE_GRACE = 0.05
        driver.JOG_SETTLE_POLL_INTERVAL = 0.005

        # 300 mm at 60000 mm/min is 0.3 s of travel, so the wait must
        # last far longer than the 0.05 s grace period on its own.
        await driver.jog(60000, x=300.0)

        assert spy.reads > 30

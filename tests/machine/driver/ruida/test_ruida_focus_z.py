"""Focus Z (D8 2E) and the controls this controller does not support.

D8 2E is "Focus Z" in ruida_maps (community provenance, no capture in
this repository), so these tests pin what the app sends, not what the
controller does with it. The driver tests run against a stub client
that records the command stream; the framing tests run the real client
over the UDP and USB transports with the wire mocked.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from blinker import Signal

from swiftcut.machine.cmd import MachineCmd
from swiftcut.machine.driver.ruida.ruida_client import RuidaClient
from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.machine.driver.ruida.ruida_transport import RuidaTransport
from swiftcut.machine.driver.ruida.ruida_usb_transport import (
    RuidaUsbTransport,
)
from swiftcut.machine.driver.ruida.ruida_util import swizzle_byte
from swiftcut.machine.models.machine import Machine

FOCUS_Z = b"\xd8\x2e"
STOP = b"\xd8\x01"


class FocusClientSpy:
    """Records commands; the machine runs until a stop arrives or
    `busy_reads` status reads have passed."""

    def __init__(self, driver, busy_reads=0):
        self.driver = driver
        self.commands: list[bytes] = []
        self.busy_reads = busy_reads
        self.status_reads = 0
        self.busy_during_focus: bool | None = None
        self.on_focus = None
        self.state_changed = Signal()
        self.position_updated = Signal()
        self.is_connected = True

    async def disconnect(self):
        pass

    async def focus_z(self):
        self.commands.append(FOCUS_Z)
        self.busy_during_focus = self.driver._jog_busy
        if self.on_focus is not None:
            await self.on_focus()

    async def stop_process(self):
        self.commands.append(STOP)

    async def read_position(self, timeout: float = 2.0):
        return (0, 0)

    async def _read_memory_wait(self, address, timeout=2.0):
        if address != self.driver.MACHINE_STATUS_ADDRESS:
            return 0
        self.status_reads += 1
        if STOP in self.commands or self.status_reads > self.busy_reads:
            return 0
        return self.driver.STATUS_JOB_RUNNING_BIT


async def _wait_until(predicate, timeout: float = 2.0) -> bool:
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest_asyncio.fixture
async def driver(lite_context):
    """A RuidaDriver with no transports; tests inject a client spy."""
    machine = Machine(lite_context)
    machine.driver_name = "RuidaDriver"
    lite_context.machine_mgr.add_machine(machine)
    drv = RuidaDriver(lite_context, machine)
    drv.STATUS_POLL_INTERVAL = 0.01

    yield drv

    drv._client = None
    await drv.cleanup()
    await machine.shutdown()


class TestFocusZ:
    @pytest.mark.asyncio
    async def test_focus_z_calls_the_client_focus_only(self, driver):
        spy = FocusClientSpy(driver)
        driver._client = spy

        await driver.focus_z()

        assert driver.can_focus_z() is True
        assert spy.commands == [FOCUS_Z]

    @pytest.mark.asyncio
    async def test_focus_z_holds_the_interlock_until_idle(self, driver):
        """Like home: busy from the send until the status bit clears."""
        spy = FocusClientSpy(driver, busy_reads=3)
        driver._client = spy

        await driver.focus_z()

        assert spy.busy_during_focus is True
        assert spy.status_reads == 4
        assert driver._jog_busy is False

    @pytest.mark.asyncio
    async def test_a_jog_during_focus_is_dropped(self, driver):
        spy = FocusClientSpy(driver)
        driver._client = spy
        driver._last_known_pos = (0, 0)
        jog_moves = AsyncMock()
        driver._jog_move_to = jog_moves

        async def jog_while_focusing():
            await driver.jog(6000, x=10.0)

        spy.on_focus = jog_while_focusing

        await driver.focus_z()

        jog_moves.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flag", ["_jog_busy", "_job_running"])
    async def test_focus_z_is_ignored_while_busy(self, driver, flag):
        spy = FocusClientSpy(driver)
        driver._client = spy
        setattr(driver, flag, True)

        await driver.focus_z()

        assert spy.commands == []

    @pytest.mark.asyncio
    async def test_stop_ends_a_running_focus(self, driver):
        """
        Stop, run as its own task like the app's cancel, still sends
        D8 01, and the focus wait that is polling ends with it.
        """
        spy = FocusClientSpy(driver, busy_reads=10**6)
        driver._client = spy
        focus = asyncio.create_task(driver.focus_z())
        assert await _wait_until(lambda: spy.status_reads > 0)

        await driver.cancel()
        await asyncio.wait_for(focus, timeout=2.0)

        assert spy.commands == [FOCUS_Z, STOP]
        assert driver._jog_busy is False


class TestFocusZThroughMachineCmd:
    @pytest.mark.asyncio
    async def test_a_repeat_request_does_not_replace_a_running_focus(
        self, driver, task_mgr
    ):
        """
        A second Focus queued while the first still waits must not
        cancel it: that would clear the interlock with the controller
        still moving and send D8 2E again. The driver drops it instead.
        """
        spy = FocusClientSpy(driver, busy_reads=10**6)
        driver._client = spy
        returned = []
        driver_focus_z = driver.focus_z

        async def focus_z():
            await driver_focus_z()
            returned.append(True)

        driver.focus_z = focus_z
        machine_cmd = MachineCmd(SimpleNamespace(task_manager=task_mgr))
        machine = SimpleNamespace(driver=driver)

        machine_cmd.focus_z(machine)
        assert await _wait_until(lambda: spy.status_reads > 0)
        machine_cmd.focus_z(machine)
        assert await _wait_until(lambda: returned)

        assert spy.commands == [FOCUS_Z]
        assert driver._jog_busy is True

        task_mgr.add_coroutine(lambda ctx: driver.cancel())
        assert await asyncio.to_thread(task_mgr.wait_until_settled, 2000)
        assert spy.commands == [FOCUS_Z, STOP]


class TestUnsupportedControls:
    @pytest.mark.asyncio
    async def test_clear_alarm_is_not_offered_and_sends_nothing(
        self, driver
    ):
        spy = FocusClientSpy(driver)
        driver._client = spy

        await driver.clear_alarm()

        assert driver.can_clear_alarm() is False
        assert spy.commands == []

    def test_pulse_is_not_offered(self, driver):
        assert driver.can_pulse() is False


def _swizzled(command: bytes) -> bytes:
    return bytes(swizzle_byte(b, 0x88) for b in command)


class TestFocusZOnTheWire:
    @pytest.mark.asyncio
    async def test_udp_frames_it_with_a_checksum(self):
        """UDP: swizzled, then a 16-bit sum prefix."""
        udp = MagicMock()
        udp.send = AsyncMock()
        client = RuidaClient(RuidaTransport(udp))

        await client.focus_z()

        payload = _swizzled(FOCUS_Z)
        checksum = (sum(payload) & 0xFFFF).to_bytes(2, "big")
        udp.send.assert_awaited_once_with(checksum + payload)

    @pytest.mark.asyncio
    async def test_usb_sends_it_swizzled_without_a_prefix(self):
        transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
        transport._raw.send = AsyncMock()
        client = RuidaClient(transport)

        await client.focus_z()

        transport._raw.send.assert_awaited_once_with(_swizzled(FOCUS_Z))

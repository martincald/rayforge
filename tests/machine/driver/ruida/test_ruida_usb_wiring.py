"""
Tests for package U3: wiring the profile's connection/usb_backend/
usb_serial settings to RuidaDriver, and the diagnostics it exposes.

The UDP path is not touched by this package -- see
test_ruida_udp_ports.py for the untouched-behaviour regression tests
that must keep passing byte-for-byte. These tests cover only the new
USB branch: setup vars, backend resolution, transport construction
(RuidaUsbTransport is mocked; no real USB/serial device is opened),
precheck, and the diagnostics fields the Device settings page reads.
"""

import asyncio
import queue
import socket
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from blinker import Signal

from swiftcut.machine.driver.driver import DriverPrecheckError
from swiftcut.machine.driver.ruida.ruida_codec import RuidaCodec
from swiftcut.machine.driver.ruida.ruida_driver import (
    RuidaDriver,
    _UsbTrafficCounter,
)
from swiftcut.machine.driver.ruida.ruida_simulator import RuidaSimulator
from swiftcut.machine.driver.ruida.ruida_usb_transport import VcpDeviceInfo
from swiftcut.machine.driver.ruida.ruida_util import encode35
from swiftcut.machine.models.machine import Machine
from swiftcut.machine.transport import TransportStatus
from swiftcut.shared.tasker import task_mgr

_USB = "swiftcut.machine.driver.ruida.ruida_usb_transport"


def test_usb_settings_are_not_in_the_generic_setup_vars():
    """connection and usb_serial are chosen on the Device page; a
    second, generic copy on the General page would go stale."""
    keys = {var.key for var in RuidaDriver.get_setup_vars()}

    assert keys == {"host", "port", "jog_port"}


def test_connection_and_usb_serial_round_trip_through_the_machine_file(
    lite_context,
):
    machine = Machine(lite_context)
    machine.driver_name = "RuidaDriver"
    machine.driver_args = {
        "host": "192.168.1.100",
        "connection": "usb",
        "usb_serial": "A10K3XYZ",
    }

    loaded = Machine.from_dict(machine.to_dict(), lite_context)

    assert loaded.driver_args["connection"] == "usb"
    assert loaded.driver_args["usb_serial"] == "A10K3XYZ"


class TestBackendResolution:
    def test_auto_resolves_to_d2xx_on_windows(self, monkeypatch):
        monkeypatch.setattr(
            "swiftcut.machine.driver.ruida.ruida_driver.sys.platform",
            "win32",
        )
        assert RuidaDriver._resolve_usb_backend("auto") == "d2xx"

    def test_auto_resolves_to_vcp_elsewhere(self, monkeypatch):
        monkeypatch.setattr(
            "swiftcut.machine.driver.ruida.ruida_driver.sys.platform",
            "linux",
        )
        assert RuidaDriver._resolve_usb_backend("auto") == "vcp"

    def test_explicit_backend_is_not_overridden(self):
        assert RuidaDriver._resolve_usb_backend("d2xx") == "d2xx"
        assert RuidaDriver._resolve_usb_backend("vcp") == "vcp"


class TestPrecheck:
    def test_default_connection_still_validates_hostname(self):
        with pytest.raises(DriverPrecheckError):
            RuidaDriver.precheck(host="")

    def test_usb_connection_skips_hostname_validation(self):
        RuidaDriver.precheck(connection="usb")  # must not raise


def _mock_usb_transport(mocker):
    """
    Mocks RuidaUsbTransport where ruida_driver.py imports it, and
    gives the constructed instance real blinker Signals so
    _UsbTrafficCounter's connect() calls behave like the real thing.
    """
    usb_transport_cls = mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_driver.RuidaUsbTransport"
    )
    instance = usb_transport_cls.return_value
    instance.decoded_received = Signal()
    instance.status_changed = Signal()
    instance.send_command = AsyncMock()
    instance.send = AsyncMock()
    instance.device = None
    return usb_transport_cls, instance


_CARD_ID_READ = b"\xda\x00\x05\x7e"
_STATUS_READ = b"\xda\x00\x04\x00"
# The owner's controller's answer to the card-ID read (2026-10-06).
_CARD_ID_REPLY = b"\xda\x01\x05\x7e" + encode35(0x72107210)


class _SimulatedFtdiPort:
    """
    A pyserial-shaped FTDI port with the Ruida simulator behind it.
    Each write is answered the way run_udp_simulator answers a
    datagram -- an ACK, then any reply -- swizzled, with no checksum.
    """

    def __init__(self, *args, **kwargs):
        self._codec = RuidaCodec(0x88)
        self._simulator = RuidaSimulator()
        self._replies: queue.Queue[bytes] = queue.Queue()
        self.in_waiting = 0
        self.rts = True
        self.dtr = True
        self.written: list[bytes] = []

    def read(self, size=1):
        try:
            return self._replies.get(timeout=0.05)
        except queue.Empty:
            return b""

    def write(self, data):
        self.written.append(bytes(data))
        plain = self._codec.unswizzle(bytes(data))
        response = self._simulator.process_commands(plain)
        if response in (b"", b"\xcc"):
            response = b""
        self._replies.put(self._codec.swizzle(b"\xcc" + response))
        return len(data)

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def close(self):
        pass


@pytest.mark.asyncio
async def test_a_usb_profile_connects_to_the_controller(lite_context, mocker):
    """
    End to end below the UI: a USB profile with no host and no pin
    enumerates the FTDI port, opens it, and the connection loop's
    card-ID handshake brings the driver to connected, with
    Diagnostics naming the port and device.
    """
    mocker.patch(f"{_USB}.serial.Serial", side_effect=_SimulatedFtdiPort)
    mocker.patch(
        f"{_USB}.list_ports.comports",
        return_value=[
            SimpleNamespace(
                device="/dev/cu.usbserial-A10K3XYZ",
                vid=0x0403,
                pid=0x6001,
                description="FT245R USB FIFO",
                serial_number="A10K3XYZ",
            )
        ],
    )
    machine = Machine(lite_context)
    driver = RuidaDriver(lite_context, machine)
    driver._setup_implementation(connection="usb", usb_backend="vcp")
    try:
        await driver._connect_implementation()
        for _ in range(100):
            if driver.is_connected:
                break
            await asyncio.sleep(0.05)
        assert driver.is_connected

        diagnostics = driver.get_diagnostics()
        assert diagnostics.usb_port == "/dev/cu.usbserial-A10K3XYZ"
        assert diagnostics.usb_device == "FT245R USB FIFO (A10K3XYZ)"
        assert diagnostics.usb_handshake_ok is True
        assert diagnostics.last_enq_sent_at is None
        assert diagnostics.last_ack_received_at is not None
        assert diagnostics.usb_bytes_sent > 0
        assert diagnostics.usb_bytes_received > 0
    finally:
        await driver.cleanup()


@pytest.mark.asyncio
async def test_usb_mode_checks_over_usb_and_opens_no_udp_socket(
    lite_context, mocker, monkeypatch
):
    """
    A USB profile still carries its UDP host and ports. None of them
    may be used: the connection check, a card-ID read, goes out on
    the USB port, the keepalive is a status read, no ENQ is ever
    sent, no UdpTransport is built and no datagram socket is created.
    """
    monkeypatch.setattr(RuidaDriver, "USB_KEEPALIVE_INTERVAL", 0.05)
    ports: list[_SimulatedFtdiPort] = []

    def open_port(*args, **kwargs):
        ports.append(_SimulatedFtdiPort())
        return ports[-1]

    mocker.patch(f"{_USB}.serial.Serial", side_effect=open_port)
    mocker.patch(
        f"{_USB}.list_ports.comports",
        return_value=[
            SimpleNamespace(
                device="/dev/cu.usbserial-A10K3XYZ",
                vid=0x0403,
                pid=0x6001,
                description="FT245R USB FIFO",
                serial_number="A10K3XYZ",
            )
        ],
    )
    udp_transport_cls = mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_driver.UdpTransport"
    )
    datagram_sockets = []
    real_socket = socket.socket

    class _RecordingSocket(real_socket):
        def __init__(self, family=-1, type=-1, *args, **kwargs):
            super().__init__(family, type, *args, **kwargs)
            if self.type == socket.SOCK_DGRAM:
                datagram_sockets.append(self)

    monkeypatch.setattr(socket, "socket", _RecordingSocket)
    machine = Machine(lite_context)
    driver = RuidaDriver(lite_context, machine)
    driver._setup_implementation(
        connection="usb",
        usb_backend="vcp",
        host="192.168.1.100",
        port=50200,
        jog_port=50207,
    )
    try:
        await driver._connect_implementation()
        for _ in range(100):
            if driver.is_connected:
                break
            await asyncio.sleep(0.05)
        assert driver.is_connected

        codec = RuidaCodec(0x88)
        assert await _wait_until(
            lambda: codec.swizzle(_STATUS_READ) in ports[0].written
        )
        assert len(ports) == 1
        assert ports[0].written[0] == codec.swizzle(_CARD_ID_READ)
        assert codec.swizzle(b"\xce") not in ports[0].written
    finally:
        await driver.cleanup()

    udp_transport_cls.assert_not_called()
    assert datagram_sockets == []


class _ControllerPort(_SimulatedFtdiPort):
    """
    Answers a card-ID read with its DA 01 reply alone, as in the
    2026-10-06 probe log. The n-th status read is answered when
    status_answers[n] is true and dropped otherwise (all are answered
    when it is None). Everything else is answered by the simulator.
    """

    def __init__(self, status_answers: list[bool] | None = None):
        super().__init__()
        self._status_answers = status_answers
        self.status_reads = 0
        self.status_reads_at_close: int | None = None

    def write(self, data):
        plain = self._codec.unswizzle(bytes(data))
        if plain == _CARD_ID_READ:
            self.written.append(bytes(data))
            self._replies.put(self._codec.swizzle(_CARD_ID_REPLY))
            return len(data)
        if plain == _STATUS_READ:
            n = self.status_reads
            self.status_reads += 1
            answers = self._status_answers
            if answers is not None and not (n < len(answers) and answers[n]):
                self.written.append(bytes(data))
                return len(data)
        return super().write(data)

    def close(self):
        if self.status_reads_at_close is None:
            self.status_reads_at_close = self.status_reads


class _SilentPort(_SimulatedFtdiPort):
    """Opens, takes every write, and never answers."""

    def write(self, data):
        self.written.append(bytes(data))
        return len(data)


async def _connect_usb_driver(lite_context, mocker, port) -> RuidaDriver:
    mocker.patch(f"{_USB}.serial.Serial", return_value=port)
    mocker.patch(f"{_USB}.list_ports.comports", return_value=[_FTDI_PORT])
    driver = RuidaDriver(lite_context, Machine(lite_context))
    driver._setup_implementation(connection="usb", usb_backend="vcp")
    await driver._connect_implementation()
    return driver


@pytest.mark.asyncio
async def test_the_handshake_card_id_shows_in_diagnostics(
    lite_context, mocker
):
    driver = await _connect_usb_driver(lite_context, mocker, _ControllerPort())
    try:
        assert await _wait_until(lambda: driver.is_connected)

        diagnostics = driver.get_diagnostics()
        assert diagnostics.usb_handshake_ok is True
        assert diagnostics.card_id == 0x72107210
        assert diagnostics.model_name == "RDC644x (card 0x7210)"
    finally:
        await driver.cleanup()


@pytest.mark.asyncio
async def test_a_silent_controller_fails_the_handshake(
    lite_context, mocker, monkeypatch
):
    """No answer to the card-ID read: not connected, the error says
    so, and the read is all that was sent -- no ENQ."""
    monkeypatch.setattr(RuidaDriver, "USB_HANDSHAKE_TIMEOUT", 0.2)
    monkeypatch.setattr(RuidaDriver, "RECONNECT_INTERVAL", 30.0)
    port = _SilentPort()
    statuses: list[tuple] = []
    driver = await _connect_usb_driver(lite_context, mocker, port)
    driver.connection_status_changed.connect(
        lambda sender, status, message="": statuses.append((status, message)),
        weak=False,
    )
    try:
        assert await _wait_until(
            lambda: driver.get_diagnostics().usb_handshake_ok is False
        )
        assert not driver.is_connected
        assert (
            TransportStatus.ERROR,
            "No response from controller",
        ) in statuses
        assert port.written == [RuidaCodec(0x88).swizzle(_CARD_ID_READ)]
    finally:
        await driver.cleanup()


@pytest.mark.asyncio
async def test_three_missed_status_reads_in_a_row_drop_the_connection(
    lite_context, mocker, monkeypatch, caplog
):
    """
    The USB keepalive is a status read. Two misses and then an answer
    start the count over; the third miss in a row drops the
    connection, on the sixth read.
    """
    monkeypatch.setattr(RuidaDriver, "USB_KEEPALIVE_INTERVAL", 0.05)
    monkeypatch.setattr(RuidaDriver, "CONNECTION_TIMEOUT", 0.3)
    monkeypatch.setattr(RuidaDriver, "RECONNECT_INTERVAL", 30.0)
    port = _ControllerPort(
        status_answers=[False, False, True, False, False, False]
    )
    driver = await _connect_usb_driver(lite_context, mocker, port)
    try:
        assert await _wait_until(
            lambda: port.status_reads_at_close is not None, timeout=10.0
        )
        assert port.status_reads_at_close == 6
        assert not driver.is_connected
    finally:
        await driver.cleanup()

    assert (
        "Controller missed 3 status reads in a row, reconnecting"
        in caplog.messages
    )


@pytest.mark.asyncio
async def test_the_usb_keepalive_pauses_while_polling_is_suspended(
    lite_context, mocker, monkeypatch
):
    """A job, homing or move owns the wire and polls status itself;
    the keepalive leaves it alone until polling resumes."""
    monkeypatch.setattr(RuidaDriver, "USB_KEEPALIVE_INTERVAL", 0.05)
    port = _ControllerPort()
    driver = await _connect_usb_driver(lite_context, mocker, port)
    try:
        assert await _wait_until(lambda: port.status_reads > 0)
        with driver._polling_suspended():
            await asyncio.sleep(0.1)  # a read already in flight lands
            before = port.status_reads
            await asyncio.sleep(0.5)
            assert port.status_reads == before
        assert await _wait_until(lambda: port.status_reads > before)
    finally:
        await driver.cleanup()


class TestSetupUsb:
    def test_default_connection_is_still_udp(self, lite_context, mocker):
        """No connection= key at all must behave exactly as before."""
        udp_transport_cls = mocker.patch(
            "swiftcut.machine.driver.ruida.ruida_driver.UdpTransport"
        )
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)

        driver._setup_implementation(
            host="192.168.1.100", port=50200, jog_port=50207
        )

        assert driver._connection == "udp"
        assert udp_transport_cls.called

    def test_d2xx_backend_constructs_ruida_usb_transport(
        self, lite_context, mocker
    ):
        usb_transport_cls, _instance = _mock_usb_transport(mocker)
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)

        driver._setup_implementation(
            connection="usb", usb_backend="d2xx", usb_serial="ABC123"
        )

        usb_transport_cls.assert_called_once_with(
            backend="d2xx", usb_serial="ABC123"
        )
        assert driver._connection == "usb"
        assert driver._usb_backend_resolved == "d2xx"
        assert driver._client is not None
        assert driver._udp_transport is None
        assert driver.host is None

    def test_vcp_backend_pins_usb_serial(self, lite_context, mocker):
        usb_transport_cls, _instance = _mock_usb_transport(mocker)
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)

        driver._setup_implementation(
            connection="usb", usb_backend="vcp", usb_serial="A10K3XYZ"
        )

        usb_transport_cls.assert_called_once_with(
            backend="vcp", usb_serial="A10K3XYZ"
        )
        assert driver._usb_backend_resolved == "vcp"

    def test_vcp_backend_without_a_pin_finds_the_device_itself(
        self, lite_context, mocker
    ):
        """No pin is not a setup error: the transport enumerates FTDI
        ports on connect."""
        usb_transport_cls, _instance = _mock_usb_transport(mocker)
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)

        driver._setup_implementation(connection="usb", usb_backend="vcp")

        usb_transport_cls.assert_called_once_with(
            backend="vcp", usb_serial=None
        )

    @pytest.mark.asyncio
    async def test_usb_connection_starts_without_a_host(
        self, lite_context, mocker
    ):
        """A USB profile has no host; connecting must still start the
        connection loop instead of reporting "No host configured"."""
        _mock_usb_transport(mocker)
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)
        driver._setup_implementation(connection="usb")
        loop = mocker.patch.object(driver, "_connection_loop", new=AsyncMock())

        await driver._connect_implementation()
        await driver._connection_task

        loop.assert_awaited_once()

    def test_auto_backend_is_resolved_before_construction(
        self, lite_context, mocker, monkeypatch
    ):
        monkeypatch.setattr(
            "swiftcut.machine.driver.ruida.ruida_driver.sys.platform",
            "win32",
        )
        usb_transport_cls, _instance = _mock_usb_transport(mocker)
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)

        driver._setup_implementation(connection="usb", usb_backend="auto")

        usb_transport_cls.assert_called_once_with(
            backend="d2xx", usb_serial=None
        )
        assert driver._usb_backend_resolved == "d2xx"


class TestUsbDiagnostics:
    def test_before_setup_reports_udp_connection_and_no_usb_state(
        self, lite_context
    ):
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)

        diagnostics = driver.get_diagnostics()

        assert diagnostics.connection == "udp"
        assert diagnostics.usb_backend is None
        assert diagnostics.usb_device is None
        assert diagnostics.usb_bytes_sent == 0
        assert diagnostics.usb_bytes_received == 0

    def test_after_usb_setup_reports_backend_and_pinned_device(
        self, lite_context, mocker
    ):
        _mock_usb_transport(mocker)
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)

        driver._setup_implementation(
            connection="usb", usb_backend="d2xx", usb_serial="ABC123"
        )
        diagnostics = driver.get_diagnostics()

        assert diagnostics.connection == "usb"
        assert diagnostics.usb_backend == "d2xx"
        assert diagnostics.usb_device == "ABC123"
        # No UDP endpoint is in play over USB.
        assert diagnostics.host is None
        assert diagnostics.response_port_bound is None

    def test_unpinned_usb_device_reports_an_auto_note(
        self, lite_context, mocker
    ):
        _mock_usb_transport(mocker)
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)

        driver._setup_implementation(connection="usb", usb_backend="d2xx")
        diagnostics = driver.get_diagnostics()

        assert diagnostics.usb_device == "auto (first device found)"

    def test_opened_device_reports_its_port_and_identity(
        self, lite_context, mocker
    ):
        _usb_transport_cls, instance = _mock_usb_transport(mocker)
        instance.device = VcpDeviceInfo(
            "/dev/cu.usbserial-A10K3XYZ", "FT245R USB FIFO", "A10K3XYZ"
        )
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)

        driver._setup_implementation(connection="usb", usb_backend="vcp")
        diagnostics = driver.get_diagnostics()

        assert diagnostics.usb_port == "/dev/cu.usbserial-A10K3XYZ"
        assert diagnostics.usb_device == "FT245R USB FIFO (A10K3XYZ)"

    @pytest.mark.asyncio
    async def test_reports_bytes_sent_and_received(self, lite_context, mocker):
        _usb_transport_cls, instance = _mock_usb_transport(mocker)
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)
        driver._setup_implementation(connection="usb", usb_backend="d2xx")

        await driver._usb_traffic.send_command(b"\x01\x02")
        instance.decoded_received.send(instance, data=b"\xaa\xbb\xcc")

        diagnostics = driver.get_diagnostics()
        assert diagnostics.usb_bytes_sent == 2
        assert diagnostics.usb_bytes_received == 3


class TestUsbTrafficCounter:
    """Direct tests of the byte-counting wrapper, isolated from setup."""

    class _FakeTransport:
        def __init__(self):
            self.decoded_received = Signal()
            self.status_changed = Signal()
            self._connected = False
            self.sent: list[bytes] = []

        @property
        def is_connected(self) -> bool:
            return self._connected

        async def connect(self) -> None:
            self._connected = True

        async def disconnect(self) -> None:
            self._connected = False

        async def send_command(self, command: bytes) -> None:
            self.sent.append(command)

        async def send(self, data: bytes) -> None:
            self.sent.append(data)

    @pytest.mark.asyncio
    async def test_forwards_calls_and_tallies_bytes(self):
        fake = self._FakeTransport()
        counter = _UsbTrafficCounter(fake)

        await counter.connect()
        assert counter.is_connected is True

        await counter.send_command(b"\x01\x02\x03")
        await counter.send(b"\x04\x05")
        fake.decoded_received.send(fake, data=b"\xaa\xbb\xcc\xdd")

        assert counter.bytes_sent == 5
        assert counter.bytes_received == 4
        assert fake.sent == [b"\x01\x02\x03", b"\x04\x05"]

        await counter.disconnect()
        assert counter.is_connected is False


@pytest.mark.asyncio
async def test_changing_connection_rebuilds_on_the_other_transport(
    lite_context,
):
    """
    No restart: rewriting the profile's connection is all it takes.
    The rebuild that set_driver_args schedules replaces the UDP
    driver with one on USB, and back again.
    """
    machine = Machine(lite_context)
    lite_context.machine_mgr.add_machine(machine)
    # Created before the driver is named, so it schedules no rebuild
    # of its own on the task manager's loop beside this test's.
    controller = machine.controller
    machine.driver_name = "RuidaDriver"
    machine.driver_args = {
        "host": "192.168.1.100",
        "port": 50200,
        "jog_port": 50207,
    }
    # Never let a test dial out to a real machine.
    machine.auto_connect = False

    await controller.rebuild_driver()
    assert controller.driver._connection == "udp"

    machine.driver_args = {**machine.driver_args, "connection": "usb"}
    await controller.rebuild_driver()
    usb_driver = controller.driver
    assert usb_driver._connection == "usb"
    assert usb_driver._usb_transport is not None
    assert usb_driver._udp_transport is None

    machine.driver_args = {**machine.driver_args, "connection": "udp"}
    await controller.rebuild_driver()
    assert controller.driver is not usb_driver
    assert controller.driver._connection == "udp"
    assert controller.driver.host == "192.168.1.100"

    await machine.shutdown()


_FTDI_PORT = SimpleNamespace(
    device="/dev/cu.usbserial-A10K3XYZ",
    vid=0x0403,
    pid=0x6001,
    description="FT245R USB FIFO",
    serial_number="A10K3XYZ",
)


async def _wait_until(predicate, timeout: float = 2.0) -> bool:
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


def _on_task_loop(coro):
    """
    Runs coro on the task manager's loop, as the app runs every
    rebuild: the connection loop a rebuild starts, and the sync tasks
    a connection schedules, then share one event loop.
    """
    return asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(coro, task_mgr.loop)
    )


def _usb_controller(lite_context):
    """
    A controller for a USB profile that connects on rebuild. It is
    built before the driver is named, so it schedules no rebuild of
    its own on the task manager's loop.
    """
    machine = Machine(lite_context)
    lite_context.machine_mgr.add_machine(machine)
    controller = machine.controller
    machine.driver_name = "RuidaDriver"
    machine.driver_args = {"connection": "usb", "usb_backend": "vcp"}
    # USB against a simulated port only: nothing here can dial out.
    machine.auto_connect = True
    return machine, controller


@pytest.mark.asyncio
async def test_a_repeated_rebuild_for_the_same_settings_keeps_the_port(
    lite_context, mocker
):
    """
    One settings change asks for two rebuilds, set_driver_args' own
    and the controller's change listener, and the second can come
    after the first driver has opened the port. It must leave that
    driver alone: the port is opened exactly once.
    """
    serial_cls = mocker.patch(
        f"{_USB}.serial.Serial", side_effect=_SimulatedFtdiPort
    )
    mocker.patch(f"{_USB}.list_ports.comports", return_value=[_FTDI_PORT])
    machine, controller = _usb_controller(lite_context)
    try:
        await _on_task_loop(controller.rebuild_driver())
        first = controller.driver
        assert await _wait_until(lambda: first.is_connected)

        await _on_task_loop(controller.rebuild_driver())

        assert controller.driver is first
        assert first.is_connected
        assert serial_cls.call_count == 1
    finally:
        await _on_task_loop(machine.shutdown())


@pytest.mark.asyncio
async def test_a_rebuild_closes_the_old_port_before_the_new_driver_opens(
    lite_context, mocker, monkeypatch
):
    """
    New settings while the first driver is still opening the port:
    the rebuild cancels that driver's loop, waits for its open to
    finish and closes it, and only then does the new driver open the
    port. The port is never held twice.
    """
    events: list[str] = []

    class _Port(_SimulatedFtdiPort):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            events.append("open")

        def close(self):
            events.append("close")

    in_first_open = threading.Event()
    release = threading.Event()

    def settle(seconds):
        if not in_first_open.is_set():
            in_first_open.set()
            release.wait(2.0)

    monkeypatch.setattr(f"{_USB}.time.sleep", settle)
    mocker.patch(f"{_USB}.serial.Serial", side_effect=_Port)
    mocker.patch(f"{_USB}.list_ports.comports", return_value=[_FTDI_PORT])
    machine, controller = _usb_controller(lite_context)
    try:
        await _on_task_loop(controller.rebuild_driver())
        first_loop = controller.driver._connection_task
        assert await _wait_until(in_first_open.is_set)

        machine.driver_args = {**machine.driver_args, "usb_serial": "A10K3XYZ"}
        asyncio.get_running_loop().call_later(0.1, release.set)
        await _on_task_loop(controller.rebuild_driver())

        assert first_loop.cancelled()
        assert await _wait_until(lambda: controller.driver.is_connected)
        assert events == ["open", "close", "open"]
    finally:
        release.set()
        await _on_task_loop(machine.shutdown())


@pytest.mark.asyncio
async def test_a_second_connect_keeps_the_one_running_loop(
    lite_context, mocker
):
    _usb_transport_cls, instance = _mock_usb_transport(mocker)
    instance.disconnect = AsyncMock()
    driver = RuidaDriver(lite_context, Machine(lite_context))
    driver._setup_implementation(connection="usb")
    mocker.patch.object(
        driver, "_connection_loop", new=lambda: asyncio.sleep(10)
    )
    try:
        await driver._connect_implementation()
        first_loop = driver._connection_task
        await driver._connect_implementation()

        assert driver._connection_task is first_loop
        assert not first_loop.done()
    finally:
        await driver.cleanup()


@pytest.mark.asyncio
async def test_overlapping_rebuilds_never_hold_the_port_twice(
    lite_context, mocker, monkeypatch
):
    """
    A rebuild that starts while another is still closing the old
    driver's port waits its turn, instead of connecting a third
    driver beside a port that is still open.
    """
    held = 0
    most_held = 0

    class _Port(_SimulatedFtdiPort):
        def __init__(self, *args, **kwargs):
            nonlocal held, most_held
            super().__init__(*args, **kwargs)
            held += 1
            most_held = max(most_held, held)

        def close(self):
            nonlocal held
            held -= 1

    in_first_open = threading.Event()
    release = threading.Event()

    def settle(seconds):
        if not in_first_open.is_set():
            in_first_open.set()
            release.wait(2.0)

    monkeypatch.setattr(f"{_USB}.time.sleep", settle)
    mocker.patch(f"{_USB}.serial.Serial", side_effect=_Port)
    mocker.patch(f"{_USB}.list_ports.comports", return_value=[_FTDI_PORT])
    machine, controller = _usb_controller(lite_context)
    try:
        await _on_task_loop(controller.rebuild_driver())
        assert await _wait_until(in_first_open.is_set)

        machine.driver_args = {**machine.driver_args, "usb_serial": "A10K3XYZ"}
        second = _on_task_loop(controller.rebuild_driver())
        await asyncio.sleep(0.05)
        machine.driver_args = {**machine.driver_args, "usb_serial": ""}
        third = _on_task_loop(controller.rebuild_driver())
        await asyncio.sleep(0.05)
        release.set()
        await asyncio.gather(second, third)

        assert await _wait_until(lambda: controller.driver.is_connected)
        assert most_held == 1
        assert held == 1
    finally:
        release.set()
        await _on_task_loop(machine.shutdown())


class _StreamPort(_SilentPort):
    """
    A silent port that also logs the job stream's writes. Commands
    arrive through write(), job chunks through write_some(), and both
    land in .written in wire order, unswizzled in .plain.
    """

    def __init__(self):
        super().__init__()
        self.plain: list[bytes] = []
        self.chunk_writes = 0
        self.on_chunk = None

    def write(self, data):
        self.plain.append(self._codec.unswizzle(bytes(data)))
        return super().write(data)

    def write_some(self, data: bytes) -> int:
        self.written.append(bytes(data))
        self.plain.append(self._codec.unswizzle(bytes(data)))
        self.chunk_writes += 1
        if self.on_chunk:
            self.on_chunk(self.chunk_writes)
        return len(data)


@pytest.mark.asyncio
async def test_a_stop_mid_stream_ends_it_within_a_chunk_with_one_stop(
    lite_context, mocker
):
    """
    Over USB a job streams unacknowledged. A Stop pressed while chunk
    3 of 17 is going out lets chunk 3 finish, writes nothing more of
    the job, and sends exactly one D8 01 -- after the last chunk, so
    never inside one.
    """
    from swiftcut.machine.driver.ruida import ruida_client

    mocker.patch.object(ruida_client, "JOB_STREAM_REPLY_WINDOW", 0.2)
    port = _StreamPort()
    mocker.patch(f"{_USB}.serial.Serial", return_value=port)
    mocker.patch(f"{_USB}.list_ports.comports", return_value=[_FTDI_PORT])
    mocker.patch(
        f"{_USB}._VcpBackend._raw_write_some",
        lambda self, data: port.write_some(data),
    )
    command = b"\xd9\x10" + b"\x00" * 11
    plain_job = command * 1270  # 17 chunks
    codec = RuidaCodec(0x88)
    mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_driver.build_rd_bytes",
        return_value=codec.swizzle(plain_job),
    )

    driver = RuidaDriver(lite_context, Machine(lite_context))
    driver._setup_implementation(connection="usb", usb_backend="vcp")
    await driver._client.connect()
    driver._move_to_start_corner = AsyncMock(return_value=True)
    # Nothing answers the stop's position resync on this silent port.
    driver._client.read_position = AsyncMock(return_value=None)
    finished = []
    driver.job_finished.connect(
        lambda sender: finished.append(True), weak=False
    )
    loop = asyncio.get_running_loop()
    stops = []

    def press_stop(n):
        if n == 3:
            stops.append(
                asyncio.run_coroutine_threadsafe(driver.cancel(), loop)
            )

    port.on_chunk = press_stop
    try:
        await asyncio.wait_for(
            driver.run(
                SimpleNamespace(op_map=None), None, SimpleNamespace()
            ),
            timeout=5.0,
        )
        await asyncio.wait_for(asyncio.wrap_future(stops[0]), 5.0)
    finally:
        await driver._client.disconnect()

    job_writes = [p for p in port.plain if p.startswith(command)]
    stop_writes = [p for p in port.plain if p == b"\xd8\x01"]
    assert len(job_writes) == 3
    assert b"".join(job_writes) == plain_job[: len(b"".join(job_writes))]
    assert len(stop_writes) == 1
    assert port.plain[-1] == b"\xd8\x01"
    assert b"\xd8\x02" not in port.plain
    assert finished == [True]
    assert not driver._job_running


@pytest.mark.asyncio
async def test_a_usb_job_never_waits_for_a_chunk_ack(lite_context, mocker):
    """All 17 chunks go out once each on a port that never answers."""
    from swiftcut.machine.driver.ruida import ruida_client

    mocker.patch.object(ruida_client, "JOB_STREAM_REPLY_WINDOW", 0.2)
    port = _StreamPort()
    mocker.patch(f"{_USB}.serial.Serial", return_value=port)
    mocker.patch(f"{_USB}.list_ports.comports", return_value=[_FTDI_PORT])
    mocker.patch(
        f"{_USB}._VcpBackend._raw_write_some",
        lambda self, data: port.write_some(data),
    )
    command = b"\xd9\x10" + b"\x00" * 11
    plain_job = command * 1270
    mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_driver.build_rd_bytes",
        return_value=RuidaCodec(0x88).swizzle(plain_job),
    )

    driver = RuidaDriver(lite_context, Machine(lite_context))
    driver._setup_implementation(connection="usb", usb_backend="vcp")
    await driver._client.connect()
    driver._move_to_start_corner = AsyncMock(return_value=True)
    driver._wait_for_job_completion = AsyncMock()
    send_job = mocker.spy(driver._client, "send_job")
    try:
        await asyncio.wait_for(
            driver.run(
                SimpleNamespace(op_map=None), None, SimpleNamespace()
            ),
            timeout=5.0,
        )
    finally:
        await driver._client.disconnect()

    assert port.chunk_writes == 17
    assert b"".join(port.plain) == plain_job
    send_job.assert_not_called()
    driver._wait_for_job_completion.assert_awaited_once()

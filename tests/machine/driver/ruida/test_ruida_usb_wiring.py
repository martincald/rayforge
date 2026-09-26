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
from swiftcut.machine.models.machine import Machine

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

    def read(self, size=1):
        try:
            return self._replies.get(timeout=0.05)
        except queue.Empty:
            return b""

    def write(self, data):
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
    ENQ/ACK brings the driver to connected, with Diagnostics naming
    the port and device.
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
        assert diagnostics.last_enq_sent_at is not None
        assert diagnostics.last_ack_received_at is not None
        assert diagnostics.usb_bytes_sent > 0
        assert diagnostics.usb_bytes_received > 0
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
    machine.driver_name = "RuidaDriver"
    machine.driver_args = {
        "host": "192.168.1.100",
        "port": 50200,
        "jog_port": 50207,
    }
    # Never let a test dial out to a real machine.
    machine.auto_connect = False
    controller = machine.controller

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

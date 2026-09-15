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

from unittest.mock import AsyncMock

import pytest
from blinker import Signal

from swiftcut.machine.driver.driver import (
    DriverPrecheckError,
    DriverSetupError,
)
from swiftcut.machine.driver.ruida.ruida_driver import (
    RuidaDriver,
    _UsbTrafficCounter,
)
from swiftcut.machine.models.machine import Machine


def test_get_setup_vars_adds_connection_usb_backend_and_usb_serial():
    setup_vars = RuidaDriver.get_setup_vars()
    connection_var = setup_vars.get("connection")
    backend_var = setup_vars.get("usb_backend")
    serial_var = setup_vars.get("usb_serial")

    assert connection_var is not None
    assert connection_var.choices == ["udp", "usb"]
    assert connection_var.default == "udp"

    assert backend_var is not None
    assert backend_var.choices == ["auto", "d2xx", "vcp"]
    assert backend_var.default == "auto"

    assert serial_var is not None
    assert serial_var.default == ""


def test_new_settings_round_trip_through_the_profile():
    """set_values()/get_values() is exactly what the profile save/load
    path uses (see general_preferences_page.py)."""
    setup_vars = RuidaDriver.get_setup_vars()
    setup_vars.set_values(
        {"connection": "usb", "usb_backend": "vcp", "usb_serial": "COM7"}
    )
    values = setup_vars.get_values()

    assert values["connection"] == "usb"
    assert values["usb_backend"] == "vcp"
    assert values["usb_serial"] == "COM7"


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
    return usb_transport_cls, instance


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

    def test_vcp_backend_passes_usb_serial_as_the_port(
        self, lite_context, mocker
    ):
        usb_transport_cls, _instance = _mock_usb_transport(mocker)
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)

        driver._setup_implementation(
            connection="usb", usb_backend="vcp", usb_serial="COM5"
        )

        usb_transport_cls.assert_called_once_with(
            backend="vcp", port="COM5"
        )
        assert driver._usb_backend_resolved == "vcp"

    def test_vcp_backend_without_usb_serial_raises_setup_error(
        self, lite_context, mocker
    ):
        _mock_usb_transport(mocker)
        machine = Machine(lite_context)
        driver = RuidaDriver(lite_context, machine)

        with pytest.raises(DriverSetupError):
            driver._setup_implementation(connection="usb", usb_backend="vcp")

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

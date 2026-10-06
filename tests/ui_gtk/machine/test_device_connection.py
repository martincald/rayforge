"""UI tests for the Device page's Connection group (Ethernet or USB,
and which FTDI device over USB), and for the General page leaving
those args alone when it saves its own."""

from types import SimpleNamespace

import pytest

from swiftcut.machine.driver.ruida.ruida_usb_transport import VcpDeviceInfo
from swiftcut.machine.models.controller import MachineController
from swiftcut.machine.models.default_profile import ILAB_614_PROFILE
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.machine import device_settings_page as dsp_module

_A = VcpDeviceInfo("/dev/cu.usbserial-A10K3XYZ", "FT245R USB FIFO", "A10K3XYZ")
_B = VcpDeviceInfo("/dev/cu.usbserial-BBB", "FT232R USB UART", "BBB")
_UDP_ARGS = {"host": "192.168.1.100", "port": 50200, "jog_port": 50207}


class _FakeDriver:
    supports_settings = False


@pytest.fixture(autouse=True)
def no_rebuild(monkeypatch):
    """set_driver_args schedules a driver rebuild; it is stubbed so no
    test opens a real socket or serial port."""

    async def _noop_rebuild(self, ctx=None):
        return

    monkeypatch.setattr(MachineController, "rebuild_driver", _noop_rebuild)


@pytest.fixture
def usb_devices(monkeypatch):
    """What enumeration returns; tests mutate .devices."""
    found = SimpleNamespace(devices=[_A, _B], backends=[])

    def fake_list_usb_devices(backend):
        found.backends.append(backend)
        return list(found.devices)

    monkeypatch.setattr(dsp_module, "list_usb_devices", fake_list_usb_devices)
    return found


def _page(ui_context_initializer, monkeypatch, driver_name, driver_args):
    from swiftcut.ui_gtk.machine.device_settings_page import (
        DeviceSettingsPage,
    )

    machine = Machine(ui_context_initializer)
    ui_context_initializer.machine_mgr.add_machine(machine)
    machine.driver_name = driver_name
    machine.driver_args = dict(driver_args)
    machine.auto_connect = False
    monkeypatch.setattr(
        type(machine), "driver", property(lambda self: _FakeDriver())
    )
    return DeviceSettingsPage(machine=machine), machine


def _labels(row) -> list[str]:
    model = row.get_model()
    return [model.get_string(i) for i in range(model.get_n_items())]


@pytest.mark.ui
def test_connection_group_is_only_for_ruida(
    ui_context_initializer, monkeypatch, usb_devices
):
    page, _machine = _page(
        ui_context_initializer, monkeypatch, "GrblSerialDriver", {}
    )

    assert not page.connection_group.get_visible()


@pytest.mark.ui
def test_a_udp_profile_shows_ethernet_without_the_usb_picker(
    ui_context_initializer, monkeypatch, usb_devices
):
    page, _machine = _page(
        ui_context_initializer, monkeypatch, "RuidaDriver", _UDP_ARGS
    )

    assert page.connection_group.get_visible()
    assert page.connection_row.get_selected() == 0
    assert not page.usb_device_row.get_visible()
    assert usb_devices.backends == []


@pytest.mark.ui
def test_a_usb_profile_lists_ftdi_devices_and_selects_the_pin(
    ui_context_initializer, monkeypatch, usb_devices
):
    page, _machine = _page(
        ui_context_initializer,
        monkeypatch,
        "RuidaDriver",
        {"connection": "usb", "usb_serial": "BBB"},
    )

    assert page.connection_row.get_selected() == 1
    assert page.usb_device_row.get_visible()
    assert _labels(page.usb_device_row) == [
        "Automatic",
        "FT245R USB FIFO (A10K3XYZ)",
        "FT232R USB UART (BBB)",
    ]
    assert page.usb_device_row.get_selected() == 2


@pytest.mark.ui
def test_the_seeded_profile_shows_usb_and_ethernet_stays_selectable(
    ui_context_initializer, monkeypatch, usb_devices
):
    seeded_args = ILAB_614_PROFILE["machine"]["driver_args"]
    page, machine = _page(
        ui_context_initializer, monkeypatch, "RuidaDriver", seeded_args
    )

    assert page.connection_row.get_selected() == 1
    assert page.usb_device_row.get_visible()
    assert _labels(page.connection_row) == ["Ethernet", "USB"]

    page.connection_row.set_selected(0)

    assert machine.driver_args["connection"] == "udp"
    assert machine.driver_args["host"] == "192.168.1.100"
    assert not page.usb_device_row.get_visible()

    # A profile without the key is still Ethernet, as the driver
    # falls back to UDP.
    keyless_args = {k: v for k, v in seeded_args.items() if k != "connection"}
    page, _machine = _page(
        ui_context_initializer, monkeypatch, "RuidaDriver", keyless_args
    )
    assert page.connection_row.get_selected() == 0


@pytest.mark.ui
def test_choosing_usb_switches_the_profile_and_keeps_the_host(
    ui_context_initializer, monkeypatch, usb_devices
):
    page, machine = _page(
        ui_context_initializer, monkeypatch, "RuidaDriver", _UDP_ARGS
    )

    page.connection_row.set_selected(1)

    assert machine.driver_args == {**_UDP_ARGS, "connection": "usb"}
    assert page.usb_device_row.get_visible()
    assert _labels(page.usb_device_row)[1:] == [
        "FT245R USB FIFO (A10K3XYZ)",
        "FT232R USB UART (BBB)",
    ]

    page.connection_row.set_selected(0)

    assert machine.driver_args["connection"] == "udp"
    assert not page.usb_device_row.get_visible()


@pytest.mark.ui
def test_picking_a_usb_device_pins_its_serial(
    ui_context_initializer, monkeypatch, usb_devices
):
    page, machine = _page(
        ui_context_initializer,
        monkeypatch,
        "RuidaDriver",
        {"connection": "usb"},
    )
    assert page.usb_device_row.get_selected() == 0

    page.usb_device_row.set_selected(1)
    assert machine.driver_args["usb_serial"] == "A10K3XYZ"

    page.usb_device_row.set_selected(0)
    assert machine.driver_args["usb_serial"] == ""


@pytest.mark.ui
def test_refresh_lists_a_device_plugged_in_later(
    ui_context_initializer, monkeypatch, usb_devices
):
    usb_devices.devices = []
    page, machine = _page(
        ui_context_initializer,
        monkeypatch,
        "RuidaDriver",
        {"connection": "usb"},
    )
    assert _labels(page.usb_device_row) == ["Automatic"]

    usb_devices.devices = [_A]
    page._on_refresh_usb_devices_clicked(None)

    assert _labels(page.usb_device_row) == [
        "Automatic",
        "FT245R USB FIFO (A10K3XYZ)",
    ]
    assert page.usb_device_row.get_selected() == 0
    assert "usb_serial" not in machine.driver_args


@pytest.mark.ui
def test_an_unplugged_pinned_device_stays_selected(
    ui_context_initializer, monkeypatch, usb_devices
):
    usb_devices.devices = []
    page, machine = _page(
        ui_context_initializer,
        monkeypatch,
        "RuidaDriver",
        {"connection": "usb", "usb_serial": "ZZZ"},
    )

    assert _labels(page.usb_device_row) == ["Automatic", "ZZZ (not found)"]
    assert page.usb_device_row.get_selected() == 1
    assert machine.driver_args["usb_serial"] == "ZZZ"


@pytest.mark.ui
def test_general_page_edits_keep_the_usb_connection(ui_context_initializer):
    """The General page's VarSet has no connection or usb_serial, so
    saving it must merge into the profile's args, not replace them."""
    from swiftcut.ui_gtk.machine.general_preferences_page import (
        GeneralPreferencesPage,
    )

    machine = Machine(ui_context_initializer)
    ui_context_initializer.machine_mgr.add_machine(machine)
    machine.driver_name = "RuidaDriver"
    machine.driver_args = {
        **_UDP_ARGS,
        "connection": "usb",
        "usb_serial": "A10K3XYZ",
    }
    machine.auto_connect = False
    page = GeneralPreferencesPage(machine)

    page.driver_group.set_values({"host": "192.168.1.101"})
    page.on_driver_param_changed(page.driver_group)

    assert machine.driver_args["host"] == "192.168.1.101"
    assert machine.driver_args["connection"] == "usb"
    assert machine.driver_args["usb_serial"] == "A10K3XYZ"

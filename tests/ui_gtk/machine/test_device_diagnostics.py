"""UI tests for Package A3's operator diagnostics on the Device page.

Covers the Diagnostics group (resolved driver, endpoints, response
port bind state, ENQ/ACK timestamps, log file) and the Windows
Firewall note shown while the connection is in the ERROR state.
"""

import pytest
import yaml

from swiftcut.machine.driver.ruida.ruida_driver import RuidaDiagnostics
from swiftcut.machine.models.controller import MachineController
from swiftcut.machine.models.machine import Machine
from swiftcut.machine.transport import TransportStatus
from swiftcut.ui_gtk.machine import device_settings_page as dsp_module


class _FakeRuidaDriver:
    supports_settings = False

    def __init__(self, diagnostics):
        self._diagnostics = diagnostics

    def get_diagnostics(self):
        return self._diagnostics


class _FakeGenericDriver:
    """A driver with no get_diagnostics, like NoDeviceDriver or GRBL."""

    supports_settings = False


def _page(ui_context_initializer, monkeypatch, driver):
    from swiftcut.ui_gtk.machine.device_settings_page import (
        DeviceSettingsPage,
    )

    machine = Machine(ui_context_initializer)
    ui_context_initializer.machine_mgr.add_machine(machine)
    monkeypatch.setattr(type(machine), "driver", property(lambda self: driver))

    page = DeviceSettingsPage(machine=machine)
    return page, machine


@pytest.mark.ui
def test_diagnostics_group_shows_ruida_endpoints(
    ui_context_initializer, monkeypatch
):
    diagnostics = RuidaDiagnostics(
        driver_class="RuidaDriver",
        host="192.168.1.100",
        port=50200,
        jog_port=50207,
        response_port=40200,
        response_port_bound=True,
        response_port_error=None,
        last_enq_sent_at=None,
        last_ack_received_at=None,
    )
    page, _machine = _page(
        ui_context_initializer, monkeypatch, _FakeRuidaDriver(diagnostics)
    )

    assert page.diag_host_row.get_subtitle() == "192.168.1.100"
    assert page.diag_port_row.get_subtitle() == "50200"
    assert page.diag_jog_port_row.get_subtitle() == "50207"
    assert page.diag_response_port_row.get_subtitle() == "40200"
    assert page.diag_response_bound_row.get_subtitle() == "Yes"
    assert page.diag_enq_row.get_subtitle() == "Never"
    assert page.diag_ack_row.get_subtitle() == "Never"
    for row in page._driver_specific_diag_rows:
        assert row.get_visible()


@pytest.mark.ui
def test_diagnostics_group_shows_the_log_file_path(
    ui_context_initializer, monkeypatch
):
    """A2/A3: the operator must be able to find the session log
    without hunting through the config directory."""
    from pathlib import Path

    log_path = Path("C:/fake/session-2026-09-15.log")
    monkeypatch.setattr(dsp_module, "get_current_log_file", lambda: log_path)
    diagnostics = RuidaDiagnostics(
        driver_class="RuidaDriver",
        host="192.168.1.100",
        port=50200,
        jog_port=50207,
        response_port=40200,
        response_port_bound=True,
        response_port_error=None,
        last_enq_sent_at=None,
        last_ack_received_at=None,
    )
    page, _machine = _page(
        ui_context_initializer, monkeypatch, _FakeRuidaDriver(diagnostics)
    )

    assert page.diag_log_row.get_subtitle() == str(log_path)


@pytest.mark.ui
def test_diagnostics_group_surfaces_a_bind_failure(
    ui_context_initializer, monkeypatch
):
    diagnostics = RuidaDiagnostics(
        driver_class="RuidaDriver",
        host="192.168.1.100",
        port=50200,
        jog_port=50207,
        response_port=40200,
        response_port_bound=False,
        response_port_error="port in use (another SwiftCut instance?)",
        last_enq_sent_at=None,
        last_ack_received_at=None,
    )
    page, _machine = _page(
        ui_context_initializer, monkeypatch, _FakeRuidaDriver(diagnostics)
    )

    assert page.diag_response_bound_row.get_subtitle() == (
        "No: port in use (another SwiftCut instance?)"
    )


@pytest.mark.ui
def test_diagnostics_group_hides_ruida_rows_for_other_drivers(
    ui_context_initializer, monkeypatch
):
    page, _machine = _page(
        ui_context_initializer, monkeypatch, _FakeGenericDriver()
    )

    assert page.diag_driver_row.get_subtitle() == "_FakeGenericDriver"
    for row in page._driver_specific_diag_rows:
        assert not row.get_visible()


@pytest.mark.ui
def test_firewall_note_matches_the_required_text(
    ui_context_initializer, monkeypatch
):
    monkeypatch.setattr(dsp_module.sys, "platform", "win32")
    diagnostics = RuidaDiagnostics(
        driver_class="RuidaDriver",
        host=None,
        port=None,
        jog_port=None,
        response_port=40200,
        response_port_bound=None,
        response_port_error=None,
        last_enq_sent_at=None,
        last_ack_received_at=None,
    )
    page, machine = _page(
        ui_context_initializer, monkeypatch, _FakeRuidaDriver(diagnostics)
    )

    assert not page.firewall_row.get_visible()

    machine.connection_status = TransportStatus.ERROR
    page._update_ui_state()

    assert page.firewall_row.get_visible()
    assert page.firewall_row.get_title() == (
        "Windows Firewall may be blocking SwiftCut.exe - allow it for "
        "private networks"
    )


@pytest.mark.ui
def test_firewall_note_is_windows_only(ui_context_initializer, monkeypatch):
    monkeypatch.setattr(dsp_module.sys, "platform", "linux")
    diagnostics = RuidaDiagnostics(
        driver_class="RuidaDriver",
        host=None,
        port=None,
        jog_port=None,
        response_port=40200,
        response_port_bound=None,
        response_port_error=None,
        last_enq_sent_at=None,
        last_ack_received_at=None,
    )
    page, machine = _page(
        ui_context_initializer, monkeypatch, _FakeRuidaDriver(diagnostics)
    )

    machine.connection_status = TransportStatus.ERROR
    page._update_ui_state()

    assert not page.firewall_row.get_visible()


def _ruida_diagnostics(port=50200, jog_port=50207):
    return RuidaDiagnostics(
        driver_class="RuidaDriver",
        host="192.168.1.100",
        port=port,
        jog_port=jog_port,
        response_port=40200,
        response_port_bound=True,
        response_port_error=None,
        last_enq_sent_at=None,
        last_ack_received_at=None,
    )


@pytest.mark.ui
def test_ruida_port_warning_shows_for_wrong_ports(
    ui_context_initializer, monkeypatch
):
    page, machine = _page(
        ui_context_initializer,
        monkeypatch,
        _FakeRuidaDriver(_ruida_diagnostics(port=50201)),
    )
    machine.driver_name = "RuidaDriver"
    machine.driver_args = {
        "host": "192.168.1.100",
        "port": 50201,
        "jog_port": 50207,
    }
    page._update_ui_state()

    assert page.diag_port_warning_row.get_visible()
    assert "50201" in page.diag_port_warning_row.get_subtitle()


@pytest.mark.ui
def test_ruida_port_warning_hidden_for_correct_ports(
    ui_context_initializer, monkeypatch
):
    page, machine = _page(
        ui_context_initializer,
        monkeypatch,
        _FakeRuidaDriver(_ruida_diagnostics()),
    )
    machine.driver_name = "RuidaDriver"
    machine.driver_args = {
        "host": "192.168.1.100",
        "port": 50200,
        "jog_port": 50207,
    }
    page._update_ui_state()

    assert not page.diag_port_warning_row.get_visible()


@pytest.mark.ui
def test_ruida_port_warning_hidden_for_a_non_ruida_driver(
    ui_context_initializer, monkeypatch
):
    """The notice must not fire for a non-Ruida driver."""
    page, machine = _page(
        ui_context_initializer, monkeypatch, _FakeGenericDriver()
    )
    machine.driver_name = "GRBLDriver"
    machine.driver_args = {"port": 50201}
    page._update_ui_state()

    assert not page.diag_port_warning_row.get_visible()


@pytest.mark.ui
def test_reset_ports_button_writes_defaults_and_clears_notice(
    ui_context_initializer, monkeypatch
):
    """
    Pressing the button writes the canonical ports to disk and clears
    the notice. The rebuild_driver coroutine that set_driver_args
    schedules is stubbed out: it would otherwise construct a real
    RuidaDriver and bind a real UDP socket on a background thread,
    which this test has no need to exercise.
    """

    async def _noop_rebuild(self, ctx=None):
        return

    monkeypatch.setattr(MachineController, "rebuild_driver", _noop_rebuild)

    page, machine = _page(
        ui_context_initializer,
        monkeypatch,
        _FakeRuidaDriver(_ruida_diagnostics(port=50201)),
    )
    machine.driver_name = "RuidaDriver"
    machine.driver_args = {
        "host": "127.0.0.1",
        "port": 50201,
        "jog_port": 50207,
    }
    machine.auto_connect = False
    page._update_ui_state()
    assert page.diag_port_warning_row.get_visible()

    page._on_reset_ruida_ports_clicked(None)

    assert machine.driver_args == {
        "host": "127.0.0.1",
        "port": 50200,
        "jog_port": 50207,
        "response_port": 40200,
    }
    assert not page.diag_port_warning_row.get_visible()

    saved_file = ui_context_initializer.machine_mgr.filename_from_id(
        machine.id
    )
    saved = yaml.safe_load(saved_file.read_text())
    assert saved["machine"]["driver_args"]["port"] == 50200
    assert saved["machine"]["driver_args"]["jog_port"] == 50207
    assert saved["machine"]["driver_args"]["response_port"] == 40200

"""UI tests for the jog panel's job controls and position readout."""

from unittest.mock import MagicMock, patch

import gi
import pytest

gi.require_version("Gtk", "4.0")

from rayforge.machine.driver.driver import DeviceState  # noqa: E402
from rayforge.machine.models.machine import Machine  # noqa: E402
from rayforge.machine.transport import TransportStatus  # noqa: E402


def _widget(ui_context_initializer, machine_cmd):
    from rayforge.ui_gtk.machine.jog_widget import JogWidget

    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    ui_context_initializer.machine_mgr.add_machine(machine)

    widget = JogWidget()
    widget.set_machine(machine, machine_cmd)
    return widget, machine


@pytest.mark.ui
def test_job_controls_are_start_pause_stop(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, MagicMock())

    assert widget.start_btn.get_tooltip_text() == "Start job"
    assert widget.pause_btn.get_tooltip_text() == "Pause job"
    assert widget.stop_btn.get_tooltip_text() == "Stop job"
    assert not hasattr(widget, "send_btn")
    assert not hasattr(widget, "cancel_btn")


@pytest.mark.ui
def test_start_runs_the_job(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    widget.start_btn.emit("clicked")

    machine_cmd.run_send_job.assert_called_once_with(machine)


@pytest.mark.ui
def test_pause_holds_the_job(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    widget.pause_btn.emit("clicked")

    machine_cmd.set_hold.assert_called_once_with(machine, True)


@pytest.mark.ui
def test_stop_cancels_the_job(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    widget.stop_btn.emit("clicked")

    machine_cmd.cancel_job.assert_called_once_with(machine)


@pytest.mark.ui
def test_position_readout_starts_unknown(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, MagicMock())

    assert widget.position_label.get_label() == "X —  Y —"


@pytest.mark.ui
def test_position_readout_follows_the_polled_position(
    ui_context_initializer,
):
    widget, machine = _widget(ui_context_initializer, MagicMock())
    state = DeviceState(machine_pos=(123.44, 567.81, 0.0))

    machine.set_device_state(state)
    widget._on_machine_state_changed(machine, state)

    assert widget.position_label.get_label() == "X 123.4  Y 567.8"


@pytest.mark.ui
def test_job_controls_need_a_connection(ui_context_initializer):
    widget, machine = _widget(ui_context_initializer, MagicMock())

    widget._update_button_sensitivity()
    assert widget.start_btn.get_sensitive() is False

    machine.connection_status = TransportStatus.CONNECTED
    with patch.object(type(machine), "is_connected", return_value=True):
        widget._update_button_sensitivity()

        assert widget.start_btn.get_sensitive() is True
        assert widget.pause_btn.get_sensitive() is True
        assert widget.stop_btn.get_sensitive() is True

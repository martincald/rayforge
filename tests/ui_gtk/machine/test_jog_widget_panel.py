"""UI tests for the jog panel's job controls and position readout."""

from unittest.mock import MagicMock, patch

import gi
import pytest
from blinker import Signal

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402

from swiftcut.machine.driver.driver import DeviceState  # noqa: E402
from swiftcut.machine.models.machine import Machine  # noqa: E402
from swiftcut.machine.transport import TransportStatus  # noqa: E402


def _widget(ui_context_initializer, machine_cmd):
    from swiftcut.ui_gtk.machine.jog_widget import JogWidget

    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    ui_context_initializer.machine_mgr.add_machine(machine)

    widget = JogWidget()
    widget.set_machine(machine, machine_cmd)
    return widget, machine


@pytest.mark.ui
def test_job_controls_are_start_pause_stop(ui_context_initializer):
    widget, _machine = _widget(
        ui_context_initializer, MagicMock(is_job_running=False)
    )

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
    widget, _machine = _widget(
        ui_context_initializer, MagicMock(is_job_running=False)
    )

    assert widget.position_label.get_label() == "X —  Y —"


@pytest.mark.ui
def test_position_readout_follows_the_polled_position(
    ui_context_initializer,
):
    widget, machine = _widget(
        ui_context_initializer, MagicMock(is_job_running=False)
    )
    state = DeviceState(machine_pos=(123.44, 567.81, 0.0))

    machine.set_device_state(state)
    widget._on_machine_state_changed(machine, state)

    assert widget.position_label.get_label() == "X 123.4  Y 567.8"


@pytest.mark.ui
def test_position_readout_says_running_during_a_job(ui_context_initializer):
    """
    Nothing reads the head while a job runs (MOTION_AUDIT.md,
    2026-10-29), so the readout says "running" rather than holding the
    position from before the job, and shows the head again after it.
    """
    machine_cmd = MagicMock(is_job_running=False, job_state_changed=Signal())
    widget, machine = _widget(ui_context_initializer, machine_cmd)
    before = DeviceState(machine_pos=(10.0, 20.0, 0.0))
    machine.set_device_state(before)
    widget._on_machine_state_changed(machine, before)

    machine_cmd.is_job_running = True
    machine_cmd.job_state_changed.send(machine_cmd)
    assert widget.position_label.get_label() == "running"
    widget._on_machine_state_changed(machine, before)
    assert widget.position_label.get_label() == "running"

    after = DeviceState(machine_pos=(123.44, 567.81, 0.0))
    machine.set_device_state(after)
    machine_cmd.is_job_running = False
    machine_cmd.job_state_changed.send(machine_cmd)
    assert widget.position_label.get_label() == "X 123.4  Y 567.8"


@pytest.mark.ui
def test_job_controls_need_a_connection(ui_context_initializer):
    widget, machine = _widget(
        ui_context_initializer, MagicMock(is_job_running=False)
    )

    widget._update_button_sensitivity()
    assert widget.start_btn.get_sensitive() is False

    machine.connection_status = TransportStatus.CONNECTED
    with patch.object(type(machine), "is_connected", return_value=True):
        widget._update_button_sensitivity()

        assert widget.start_btn.get_sensitive() is True
        assert widget.pause_btn.get_sensitive() is True
        assert widget.stop_btn.get_sensitive() is True


@pytest.mark.ui
def test_position_readout_names_the_origin_corner(ui_context_initializer):
    """
    The readout is in machine coordinates, so it has to say which
    corner those run from -- and follow the profile when it changes.
    """
    from swiftcut.machine.models.machine import Machine, Origin
    from swiftcut.ui_gtk.machine.jog_widget import JogWidget

    machine = Machine(ui_context_initializer)
    machine.set_origin(Origin.TOP_LEFT)
    ui_context_initializer.machine_mgr.add_machine(machine)

    widget = JogWidget()
    widget.set_machine(machine, MagicMock())
    assert "top-left" in (widget.position_label.get_tooltip_text() or "")

    machine.set_origin(Origin.BOTTOM_RIGHT)
    assert "bottom-right" in (widget.position_label.get_tooltip_text() or "")


@pytest.mark.ui
def test_natural_height_is_never_below_the_minimum(ui_context_initializer):
    """The button borders put the grid above the bare-cell cap.

    GTK warns on every layout pass when natural < minimum and then
    corrects it, so the widget's own answer is what is checked, not
    the corrected one measure() hands back.
    """
    from swiftcut.ui_gtk import theme
    from swiftcut.ui_gtk.machine.jog_widget import JogWidget

    theme.install()
    widget = JogWidget()
    window = Gtk.Window(child=widget)
    window.present()

    minimum, natural, _, _ = widget.do_measure(Gtk.Orientation.VERTICAL, -1)

    assert natural >= minimum
    window.destroy()

"""UI tests for the jog widget's Go Scale and Cut Scale buttons.

The two scale actions replace the old Frame button. Go Scale traverses
the job outline with the laser off; Cut Scale burns the same rectangle
after asking for speed and power.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, PropertyMock, patch

import gi
import pytest

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402

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


def _scale_cmd(has_ops=True):
    machine_cmd = MagicMock()
    machine_cmd.has_job_ops = has_ops
    machine_cmd.first_layer_power.return_value = 0.8
    return machine_cmd


@contextmanager
def _connected(machine):
    """
    Present a connected machine.

    is_connected is patched as well: building the machine's controller
    on first use resets the connection status, which would otherwise
    flip mid-way through a sensitivity pass.
    """
    machine.connection_status = TransportStatus.CONNECTED
    driver = MagicMock()
    with (
        patch.object(
            type(machine), "driver", new_callable=PropertyMock
        ) as driver_prop,
        patch.object(type(machine), "is_connected", return_value=True),
    ):
        driver_prop.return_value = driver
        yield driver


@pytest.mark.ui
def test_frame_button_is_gone(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, _scale_cmd())

    assert not hasattr(widget, "frame_btn")


@pytest.mark.ui
def test_both_scale_buttons_sit_in_the_jog_pad(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, _scale_cmd())

    box = widget.go_scale_btn.get_parent()
    assert isinstance(box, Gtk.Box)
    assert widget.cut_scale_btn.get_parent() is box
    assert box.get_parent() is widget._jog_grid


@pytest.mark.ui
def test_scale_row_spans_the_pad_width(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, _scale_cmd())

    box = widget.go_scale_btn.get_parent()
    assert isinstance(box, Gtk.Box)
    column, row, width, _height = widget._jog_grid.query_child(box)

    assert (column, row, width) == (0, 3, 3)


@pytest.mark.ui
def test_scale_button_captions(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, _scale_cmd())

    assert _captions(widget.go_scale_btn) == ["Go Scale"]
    assert _captions(widget.cut_scale_btn) == ["Cut Scale"]


@pytest.mark.ui
def test_no_speed_field_below_the_scale_row(ui_context_initializer):
    """The old frame-speed spin button is gone."""
    widget, _machine = _widget(ui_context_initializer, _scale_cmd())

    assert not hasattr(widget, "speed_spin")


@pytest.mark.ui
def test_scale_disabled_when_disconnected(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, _scale_cmd())

    widget._update_button_sensitivity()

    assert widget.go_scale_btn.get_sensitive() is False
    assert widget.cut_scale_btn.get_sensitive() is False


@pytest.mark.ui
def test_scale_disabled_without_ops(ui_context_initializer):
    machine_cmd = _scale_cmd(has_ops=False)
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _connected(machine):
        widget._update_button_sensitivity()

        assert widget.go_scale_btn.get_sensitive() is False
        assert widget.cut_scale_btn.get_sensitive() is False


@pytest.mark.ui
def test_scale_enabled_when_connected_with_ops(ui_context_initializer):
    widget, machine = _widget(ui_context_initializer, _scale_cmd())

    with _connected(machine):
        widget._update_button_sensitivity()

        assert widget.go_scale_btn.get_sensitive() is True
        assert widget.cut_scale_btn.get_sensitive() is True


@pytest.mark.ui
def test_click_starts_the_go_scale(ui_context_initializer):
    machine_cmd = _scale_cmd()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _connected(machine):
        widget._update_button_sensitivity()
        widget.go_scale_btn.emit("clicked")

    machine_cmd.run_go_scale.assert_called_once()
    assert machine_cmd.run_go_scale.call_args.args[0] is machine


@pytest.mark.ui
def test_button_becomes_stop_while_running(ui_context_initializer):
    machine_cmd = _scale_cmd()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _connected(machine):
        widget._update_button_sensitivity()
        widget.go_scale_btn.emit("clicked")

        assert _captions(widget.go_scale_btn) == ["Stop"]
        assert widget.go_scale_btn.get_sensitive() is True
        assert widget.cut_scale_btn.get_sensitive() is False


@pytest.mark.ui
def test_second_click_stops_instead_of_restarting(ui_context_initializer):
    machine_cmd = _scale_cmd()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _connected(machine):
        widget._update_button_sensitivity()
        widget.go_scale_btn.emit("clicked")
        widget.go_scale_btn.emit("clicked")

    machine_cmd.cancel_job.assert_called_once_with(machine)
    assert machine_cmd.run_go_scale.call_count == 1


@pytest.mark.ui
def test_button_returns_to_go_scale_when_the_run_ends(
    ui_context_initializer,
):
    machine_cmd = _scale_cmd()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _connected(machine):
        widget._update_button_sensitivity()
        widget.go_scale_btn.emit("clicked")
        widget._on_scale_done()

        assert _captions(widget.go_scale_btn) == ["Go Scale"]
        assert widget.go_scale_btn.get_sensitive() is True


@pytest.mark.ui
def test_settled_document_refreshes_the_buttons(ui_context_initializer):
    """Ops appearing or vanishing must reach the scale buttons."""
    machine_cmd = _scale_cmd(has_ops=False)
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _connected(machine):
        widget._update_button_sensitivity()
        assert widget.go_scale_btn.get_sensitive() is False

        machine_cmd.has_job_ops = True
        widget._on_document_settled(None)

        assert widget.go_scale_btn.get_sensitive() is True


@pytest.mark.ui
def test_cut_scale_dialog_defaults_to_the_first_layer_power(
    ui_context_initializer,
):
    from rayforge.ui_gtk.machine.cut_scale_dialog import (
        DEFAULT_SPEED_MM_MIN,
        CutScaleDialog,
    )

    confirmed = []
    dialog = CutScaleDialog(80.0, lambda s, p: confirmed.append((s, p)))

    assert dialog.power_row.get_value() == 80.0
    assert dialog.speed_row.get_value_in_base_units() == DEFAULT_SPEED_MM_MIN
    assert DEFAULT_SPEED_MM_MIN == 1200  # 20 mm/s

    dialog._on_response(dialog, "cut")

    assert confirmed == [(1200, 0.8)]


@pytest.mark.ui
def test_cut_scale_dialog_cancel_runs_nothing(ui_context_initializer):
    from rayforge.ui_gtk.machine.cut_scale_dialog import CutScaleDialog

    confirmed = []
    dialog = CutScaleDialog(80.0, lambda s, p: confirmed.append((s, p)))

    dialog._on_response(dialog, "cancel")

    assert confirmed == []


def _captions(button) -> list[str]:
    box = button.get_child()
    assert isinstance(box, Gtk.Box)
    return [c.get_label() for c in box if isinstance(c, Gtk.Label)]

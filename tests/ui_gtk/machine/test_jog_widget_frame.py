"""UI tests for the jog widget's Frame button.

Frame replaces the three single-axis home buttons. Homing stays
reachable from the secondary action column.
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


def _frame_cmd(has_ops=True):
    machine_cmd = MagicMock()
    machine_cmd.has_job_ops = has_ops
    return machine_cmd


@contextmanager
def _frame_driver(machine, can_trace=True):
    """
    Present a connected driver that can trace an outline.

    is_connected is patched as well: building the machine's controller
    on first use resets the connection status, which would otherwise
    flip mid-way through a sensitivity pass.
    """
    machine.connection_status = TransportStatus.CONNECTED
    driver = MagicMock()
    driver.can_trace_frame.return_value = can_trace
    with (
        patch.object(
            type(machine), "driver", new_callable=PropertyMock
        ) as driver_prop,
        patch.object(type(machine), "is_connected", return_value=True),
    ):
        driver_prop.return_value = driver
        yield driver


@pytest.mark.ui
def test_single_axis_home_buttons_are_gone(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, _frame_cmd())

    assert not hasattr(widget, "home_x_btn")
    assert not hasattr(widget, "home_y_btn")
    assert not hasattr(widget, "home_z_btn")


@pytest.mark.ui
def test_frame_button_sits_in_the_jog_pad(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, _frame_cmd())

    assert widget.frame_btn.get_parent() is widget._jog_grid


@pytest.mark.ui
def test_frame_button_spans_the_pad_width(ui_context_initializer):
    """One large button in place of the three home buttons."""
    widget, _machine = _widget(ui_context_initializer, _frame_cmd())

    column, row, width, _height = widget._jog_grid.query_child(
        widget.frame_btn
    )

    assert (column, row, width) == (0, 3, 3)


@pytest.mark.ui
def test_frame_button_tooltip_and_label(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, _frame_cmd())

    assert (
        widget.frame_btn.get_tooltip_text()
        == "Trace job outline with the pointer"
    )
    box = widget.frame_btn.get_child()
    assert isinstance(box, Gtk.Box)
    captions = [c.get_label() for c in box if isinstance(c, Gtk.Label)]
    assert captions == ["Frame"]


@pytest.mark.ui
def test_home_machine_stays_reachable(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, _frame_cmd())

    assert widget.home_all_btn.get_parent() is widget._action_grid
    assert widget.home_all_btn.get_tooltip_text() == "Home machine"


@pytest.mark.ui
def test_frame_disabled_when_disconnected(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, _frame_cmd())

    widget._update_button_sensitivity()

    assert widget.frame_btn.get_sensitive() is False


@pytest.mark.ui
def test_frame_disabled_without_ops(ui_context_initializer):
    machine_cmd = _frame_cmd(has_ops=False)
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _frame_driver(machine):
        widget._update_button_sensitivity()

        assert widget.frame_btn.get_sensitive() is False


@pytest.mark.ui
def test_frame_disabled_when_driver_cannot_trace(ui_context_initializer):
    widget, machine = _widget(ui_context_initializer, _frame_cmd())

    with _frame_driver(machine, can_trace=False):
        widget._update_button_sensitivity()

        assert widget.frame_btn.get_sensitive() is False


@pytest.mark.ui
def test_frame_enabled_when_connected_with_ops(ui_context_initializer):
    widget, machine = _widget(ui_context_initializer, _frame_cmd())

    with _frame_driver(machine):
        widget._update_button_sensitivity()

        assert widget.frame_btn.get_sensitive() is True


@pytest.mark.ui
def test_click_starts_the_trace(ui_context_initializer):
    machine_cmd = _frame_cmd()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _frame_driver(machine):
        widget._update_button_sensitivity()
        widget.frame_btn.emit("clicked")

    machine_cmd.trace_frame.assert_called_once()
    assert machine_cmd.trace_frame.call_args.args[0] is machine


@pytest.mark.ui
def test_button_becomes_stop_while_tracing(ui_context_initializer):
    machine_cmd = _frame_cmd()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _frame_driver(machine):
        widget._update_button_sensitivity()
        widget.frame_btn.emit("clicked")

        assert widget._frame_caption.get_label() == "Stop"
        assert widget.frame_btn.get_tooltip_text() == (
            "Stop tracing the outline"
        )
        assert widget.frame_btn.get_sensitive() is True


@pytest.mark.ui
def test_second_click_cancels_instead_of_restarting(ui_context_initializer):
    machine_cmd = _frame_cmd()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _frame_driver(machine):
        widget._update_button_sensitivity()
        widget.frame_btn.emit("clicked")
        widget.frame_btn.emit("clicked")

    machine_cmd.cancel_frame.assert_called_once_with(machine)
    assert machine_cmd.trace_frame.call_count == 1


@pytest.mark.ui
def test_button_returns_to_frame_when_the_trace_ends(
    ui_context_initializer,
):
    machine_cmd = _frame_cmd()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _frame_driver(machine):
        widget._update_button_sensitivity()
        widget.frame_btn.emit("clicked")
        widget._on_frame_done()

        assert widget._frame_caption.get_label() == "Frame"
        assert widget.frame_btn.get_sensitive() is True


@pytest.mark.ui
def test_settled_document_refreshes_the_button(ui_context_initializer):
    """Ops appearing or vanishing must reach the Frame button."""
    machine_cmd = _frame_cmd(has_ops=False)
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _frame_driver(machine):
        widget._update_button_sensitivity()
        assert widget.frame_btn.get_sensitive() is False

        machine_cmd.has_job_ops = True
        widget._on_document_settled(None)

        assert widget.frame_btn.get_sensitive() is True

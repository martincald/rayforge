"""Failing reproductions for the widget findings in MOTION_AUDIT.md.

Every test names its audit id in the docstring. Handlers are invoked
directly, so no real pointer, grab or window is needed.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, PropertyMock, patch

import gi
import pytest

gi.require_version("Gtk", "4.0")

from rayforge.machine.models.machine import (  # noqa: E402
    JogDirection,
    Machine,
)
from rayforge.machine.transport import TransportStatus  # noqa: E402


def _widget(ui_context_initializer, machine_cmd):
    from rayforge.ui_gtk.machine.jog_widget import JogWidget

    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    ui_context_initializer.machine_mgr.add_machine(machine)

    widget = JogWidget()
    widget.set_machine(machine, machine_cmd)
    return widget, machine


def _scale_cmd():
    machine_cmd = MagicMock()
    machine_cmd.has_job_ops = True
    machine_cmd.first_layer_power.return_value = 0.8
    return machine_cmd


@contextmanager
def _hold_jog_driver(machine):
    """Present a connected driver that supports press-and-hold jog."""
    machine.connection_status = TransportStatus.CONNECTED
    driver = MagicMock()
    driver.can_hold_jog.return_value = True
    with (
        patch.object(
            type(machine), "driver", new_callable=PropertyMock
        ) as driver_prop,
        patch.object(type(machine), "is_connected", return_value=True),
    ):
        driver_prop.return_value = driver
        yield driver


def _hold(widget, *directions):
    """Press an arrow and let the hold delay elapse."""
    widget._on_jog_pressed(None, 1, 0.0, 0.0, directions)
    widget._cancel_pending_hold()
    widget._start_hold(directions)


def _start_cut_scale(widget):
    """Run the Cut Scale click through to its confirm callback."""
    with patch(
        "rayforge.ui_gtk.machine.jog_widget.CutScaleDialog"
    ) as dialog_cls:
        widget._on_cut_scale_clicked(widget.cut_scale_btn)
        confirm = dialog_cls.call_args.args[1]
    confirm(1200, 0.8)


@pytest.mark.ui
def test_stop_during_a_cut_scale_cancels_the_job(ui_context_initializer):
    """MOT-09: Cut Scale is a job, so its Stop must stop a job."""
    machine_cmd = _scale_cmd()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _start_cut_scale(widget)
        assert widget._scaling is True
        widget._on_go_scale_clicked(widget.go_scale_btn)

    machine_cmd.cancel_job.assert_called_once_with(machine)
    machine_cmd.cancel_frame.assert_not_called()


@pytest.mark.ui
def test_stop_during_a_go_scale_cancels_the_trace(ui_context_initializer):
    """MOT-09: Go Scale is rapids, so its Stop must stop the trace."""
    machine_cmd = _scale_cmd()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        widget._on_go_scale_clicked(widget.go_scale_btn)
        widget._on_go_scale_clicked(widget.go_scale_btn)

    machine_cmd.cancel_frame.assert_called_once_with(machine)
    machine_cmd.cancel_job.assert_not_called()


@pytest.mark.ui
def test_dragging_off_a_held_button_releases_it(ui_context_initializer):
    """MOT-15: the drag-off abort must work inside the pointer grab."""
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, JogDirection.EAST)

        gesture = MagicMock()
        gesture.get_point.return_value = (True, -40.0, -40.0)
        button = MagicMock()
        button.contains.return_value = False
        widget._on_jog_gesture_update(
            gesture, None, button, (JogDirection.EAST,)
        )

    machine_cmd.jog_key_up.assert_called_once_with(machine, "x", 1)
    assert widget._keys_down == set()


@pytest.mark.ui
def test_moving_inside_a_held_button_keeps_it_held(ui_context_initializer):
    """MOT-15: a wobble within the button must not stop the jog."""
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, JogDirection.EAST)

        gesture = MagicMock()
        gesture.get_point.return_value = (True, 12.0, 12.0)
        button = MagicMock()
        button.contains.return_value = True
        widget._on_jog_gesture_update(
            gesture, None, button, (JogDirection.EAST,)
        )

    machine_cmd.jog_key_up.assert_not_called()
    assert widget._keys_down == {("x", 1)}


@pytest.mark.ui
def test_every_jog_button_tracks_drag_off(ui_context_initializer):
    """MOT-15: the abort is wired on every arrow, not just one."""
    from rayforge.ui_gtk.machine.jog_widget import JogWidget

    machine_cmd = MagicMock()
    widget, _machine = _widget(ui_context_initializer, machine_cmd)

    assert callable(getattr(JogWidget, "_on_jog_gesture_update", None))
    for button in widget._button_directions:
        gestures = [
            c
            for c in button.observe_controllers()
            if isinstance(c, gi.repository.Gtk.GestureClick)
        ]
        assert gestures, "every jog button needs its own click gesture"

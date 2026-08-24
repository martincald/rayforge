"""UI tests for press-and-hold jogging in the jog widget.

Pressing an arrow holds a keypad key down; releasing it lets go. Every
path that can lose a release must send the key-up anyway, because a
stuck head is unacceptable.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, PropertyMock, patch

import gi
import pytest

gi.require_version("Gtk", "4.0")

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


@contextmanager
def _hold_jog_driver(machine):
    """Present a connected driver that supports press-and-hold jog."""
    machine.connection_status = TransportStatus.CONNECTED
    driver = MagicMock()
    driver.can_hold_jog.return_value = True
    with patch.object(
        type(machine), "driver", new_callable=PropertyMock
    ) as driver_prop:
        driver_prop.return_value = driver
        yield driver


@pytest.mark.ui
def test_arrows_no_longer_jog_on_click(ui_context_initializer):
    """Click and gesture together would double every jog."""
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        widget.east_btn.emit("clicked")

    machine_cmd.jog.assert_not_called()
    machine_cmd.jog_key_down.assert_not_called()


@pytest.mark.ui
def test_press_emits_exactly_one_key_down(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, _east())

    machine_cmd.jog_key_down.assert_called_once_with(machine, "x", 1)


@pytest.mark.ui
def test_repeated_press_does_not_repeat_the_key_down(
    ui_context_initializer,
):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, _east())
        _hold(widget, _east())

    assert machine_cmd.jog_key_down.call_count == 1


@pytest.mark.ui
def test_release_emits_the_key_up(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, _east())
        widget._on_jog_released(None, 1, 0.0, 0.0, (_east(),))

    machine_cmd.jog_key_up.assert_called_once_with(machine, "x", 1)
    assert widget._keys_down == set()


@pytest.mark.ui
def test_diagonal_press_holds_both_axes(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, _east(), _north())

    held = {c.args[1:] for c in machine_cmd.jog_key_down.call_args_list}
    assert held == {("x", 1), ("y", 1)}


@pytest.mark.ui
def test_focus_loss_releases_a_held_key(ui_context_initializer):
    """Simulated window focus loss must let go of the keypad."""
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, _east())
        root = MagicMock()
        root.is_active.return_value = False
        widget._on_root_active_changed(root, None)

    machine_cmd.jog_key_up.assert_called_once_with(machine, "x", 1)
    machine_cmd.release_all_jog_keys.assert_called_once_with(machine)
    assert widget._keys_down == set()


@pytest.mark.ui
def test_focus_gain_does_not_release(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, _east())
        root = MagicMock()
        root.is_active.return_value = True
        widget._on_root_active_changed(root, None)

    machine_cmd.jog_key_up.assert_not_called()


@pytest.mark.ui
def test_pointer_leave_releases_a_held_key(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, _east())
        widget._on_jog_leave(None, (_east(),))

    machine_cmd.jog_key_up.assert_called_once_with(machine, "x", 1)


@pytest.mark.ui
def test_gesture_cancel_releases_a_held_key(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, _east())
        widget._on_jog_cancelled(None, None, (_east(),))

    machine_cmd.jog_key_up.assert_called_once_with(machine, "x", 1)


@pytest.mark.ui
def test_unmap_releases_a_held_key(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, _east())
        widget._on_unmapped(widget)

    machine_cmd.jog_key_up.assert_called_once_with(machine, "x", 1)


@pytest.mark.ui
def test_leave_without_a_held_key_sends_nothing(ui_context_initializer):
    """Drivers without hold support must not see stray key-ups."""
    machine_cmd = MagicMock()
    widget, _machine = _widget(ui_context_initializer, machine_cmd)

    widget._on_jog_leave(None, (_east(),))

    machine_cmd.jog_key_up.assert_not_called()


@pytest.mark.ui
def test_release_falls_back_to_step_jog_without_hold_support(
    ui_context_initializer,
):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)
    machine.connection_status = TransportStatus.CONNECTED

    driver = MagicMock()
    driver.can_hold_jog.return_value = False
    with patch.object(
        type(machine), "driver", new_callable=PropertyMock
    ) as driver_prop:
        driver_prop.return_value = driver
        widget._on_jog_pressed(None, 1, 0.0, 0.0, (_east(),))
        widget._on_jog_released(None, 1, 0.0, 0.0, (_east(),))

    machine_cmd.jog_key_down.assert_not_called()
    machine_cmd.jog.assert_called_once()


@pytest.mark.ui
def test_disconnect_drops_the_held_key_set(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        _hold(widget, _east())

    machine.connection_status = TransportStatus.DISCONNECTED
    widget._on_connection_status_changed(machine)

    assert widget._keys_down == set()


@pytest.mark.ui
def test_speed_change_is_debounced_then_pushed(ui_context_initializer):
    """One push when the control settles, not per keypress."""
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        widget.set_jog_speed(50)
        widget.set_jog_speed(80)
        machine_cmd.set_jog_speed.assert_not_called()

        widget._commit_jog_speed()

    # 80 mm/s set, pushed in the mm/min base unit.
    machine_cmd.set_jog_speed.assert_called_once_with(machine, 4800)


@pytest.mark.ui
def test_speed_debounce_timeout_is_300ms(ui_context_initializer):
    from rayforge.ui_gtk.machine import jog_widget

    assert jog_widget._JOG_SPEED_DEBOUNCE_MS == 300


@pytest.mark.ui
def test_short_click_steps_once_instead_of_holding(ui_context_initializer):
    """A press too short to become a hold moves one step size."""
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        widget._on_jog_pressed(None, 1, 0.0, 0.0, (_east(),))
        widget._on_jog_released(None, 1, 0.0, 0.0, (_east(),))

    machine_cmd.jog_key_down.assert_not_called()
    machine_cmd.jog_key_up.assert_not_called()
    machine_cmd.jog.assert_called_once()


@pytest.mark.ui
def test_focus_loss_cancels_a_pending_hold(ui_context_initializer):
    """Losing focus mid-press must not start jogging afterwards."""
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    with _hold_jog_driver(machine):
        widget._on_jog_pressed(None, 1, 0.0, 0.0, (_east(),))
        root = MagicMock()
        root.is_active.return_value = False
        widget._on_root_active_changed(root, None)

    assert widget._hold_timeout_id is None
    machine_cmd.jog_key_down.assert_not_called()


@pytest.mark.ui
def test_hold_start_delay_is_150ms(ui_context_initializer):
    from rayforge.ui_gtk.machine import jog_widget

    assert jog_widget._HOLD_START_DELAY_MS == 150


def _hold(widget, *directions):
    """Press an arrow and let the hold delay elapse."""
    widget._on_jog_pressed(None, 1, 0.0, 0.0, directions)
    widget._cancel_pending_hold()
    widget._start_hold(directions)


def _east():
    from rayforge.machine.models.machine import JogDirection

    return JogDirection.EAST


def _north():
    from rayforge.machine.models.machine import JogDirection

    return JogDirection.NORTH

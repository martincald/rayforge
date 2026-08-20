"""UI tests for the jog widget's Origin button.

The centre of the jog pad is the Origin action ("anchor the job here").
Homing is still reachable, demoted to the secondary action column.
"""

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


@pytest.mark.ui
def test_origin_button_replaces_home_all_in_the_pad(ui_context_initializer):
    """The jog pad centre is Origin; Home All no longer sits there."""
    widget, _machine = _widget(ui_context_initializer, MagicMock())

    assert widget.origin_btn.get_parent() is widget._jog_grid
    assert widget.home_all_btn.get_parent() is widget._action_grid


@pytest.mark.ui
def test_origin_button_has_a_tooltip(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, MagicMock())

    assert (
        widget.origin_btn.get_tooltip_text()
        == "Set job origin to current position"
    )


@pytest.mark.ui
def test_origin_button_carries_a_visible_label(ui_context_initializer):
    """Icon plus caption, so the one distinguished pad action reads."""
    widget, _machine = _widget(ui_context_initializer, MagicMock())

    box = widget.origin_btn.get_child()
    assert isinstance(box, Gtk.Box)
    captions = [c.get_label() for c in box if isinstance(c, Gtk.Label)]

    assert captions == ["Origin"]


@pytest.mark.ui
def test_home_machine_stays_reachable(ui_context_initializer):
    """Homing is demoted, not removed."""
    widget, _machine = _widget(ui_context_initializer, MagicMock())

    assert widget.home_all_btn.get_tooltip_text() == "Home machine"


@pytest.mark.ui
def test_origin_click_calls_set_origin(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    widget.origin_btn.emit("clicked")

    machine_cmd.set_origin.assert_called_once_with(machine)


@pytest.mark.ui
def test_home_click_still_calls_home(ui_context_initializer):
    machine_cmd = MagicMock()
    widget, machine = _widget(ui_context_initializer, machine_cmd)

    widget.home_all_btn.emit("clicked")

    machine_cmd.home.assert_called_once_with(machine)


@pytest.mark.ui
def test_origin_button_disabled_when_driver_cannot_set_origin(
    ui_context_initializer,
):
    """Drivers without origin support leave the button insensitive."""
    widget, machine = _widget(ui_context_initializer, MagicMock())
    machine.connection_status = TransportStatus.CONNECTED
    widget._update_button_sensitivity()

    driver = machine.driver
    assert driver is None or driver.can_set_origin() is False
    assert widget.origin_btn.get_sensitive() is False


@pytest.mark.ui
def test_origin_button_enabled_when_driver_supports_it(
    ui_context_initializer,
):
    widget, machine = _widget(ui_context_initializer, MagicMock())
    machine.connection_status = TransportStatus.CONNECTED

    driver = MagicMock()
    driver.can_set_origin.return_value = True
    with patch.object(
        type(machine), "driver", new_callable=PropertyMock
    ) as driver_prop:
        driver_prop.return_value = driver
        widget._update_button_sensitivity()

        assert widget.origin_btn.get_sensitive() is True

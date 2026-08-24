"""UI tests for the jog widget's Home button and Set origin action.

The centre of the jog pad homes the machine. Setting the job origin is
still reachable, demoted to a compact button beside the pad.
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
def test_home_button_occupies_the_pad_centre(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, MagicMock())

    column, row, width, height = widget._jog_grid.query_child(
        widget.home_all_btn
    )

    assert (column, row, width, height) == (1, 1, 1, 1)


@pytest.mark.ui
def test_home_button_carries_a_visible_label(ui_context_initializer):
    widget, _machine = _widget(ui_context_initializer, MagicMock())

    box = widget.home_all_btn.get_child()
    assert isinstance(box, Gtk.Box)
    captions = [c.get_label() for c in box if isinstance(c, Gtk.Label)]

    assert captions == ["Home"]


@pytest.mark.ui
def test_set_origin_is_a_compact_action_beside_the_pad(
    ui_context_initializer,
):
    widget, _machine = _widget(ui_context_initializer, MagicMock())

    assert widget.origin_btn.get_label() == "Set origin"
    assert (
        widget.origin_btn.get_tooltip_text()
        == "Set job origin to current position"
    )
    assert widget.origin_btn.has_css_class("flat")


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

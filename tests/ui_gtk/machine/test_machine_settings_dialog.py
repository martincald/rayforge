"""UI tests for the Machine Settings dialog as the ilab-614 profile
sees it: no driver-maturity warning, and none of the pages or rows a
Ruida CO2 machine cannot use (docs/removal-inventory-2.md)."""

import copy

import pytest
from gi.repository import Adw, Gtk

from swiftcut.machine.driver import DriverMaturity, RuidaDriver
from swiftcut.machine.models.controller import MachineController
from swiftcut.machine.models.default_profile import ILAB_614_PROFILE
from swiftcut.machine.models.machine import Machine


@pytest.fixture(autouse=True)
def no_rebuild(monkeypatch):
    """Editing the profile schedules a driver rebuild; it is stubbed so
    no test opens a real socket or serial port."""

    async def _noop_rebuild(self, ctx=None):
        return

    monkeypatch.setattr(MachineController, "rebuild_driver", _noop_rebuild)


def _ilab_614(context) -> Machine:
    machine = Machine.from_dict(
        copy.deepcopy(ILAB_614_PROFILE), context=context
    )
    machine.auto_connect = False
    context.machine_mgr.add_machine(machine)
    return machine


def _dialog(context, **kwargs):
    from swiftcut.ui_gtk.machine.settings_dialog import MachineSettingsDialog

    return MachineSettingsDialog(machine=_ilab_614(context), **kwargs)


def _texts(widget) -> list[str]:
    """Every label, title and subtitle under widget."""
    found = []
    if isinstance(widget, Gtk.Label):
        found.append(widget.get_text())
    if isinstance(widget, Adw.PreferencesRow):
        found.append(widget.get_title())
    if isinstance(widget, Adw.ActionRow):
        found.append(widget.get_subtitle() or "")
    if isinstance(widget, Adw.PreferencesGroup):
        found.append(widget.get_title() or "")
        found.append(widget.get_description() or "")
    child = widget.get_first_child()
    while child is not None:
        found.extend(_texts(child))
        child = child.get_next_sibling()
    return found


def test_ruida_driver_is_stable():
    assert RuidaDriver.maturity is DriverMaturity.STABLE


@pytest.mark.ui
def test_no_driver_warning(ui_context_initializer):
    dialog = _dialog(ui_context_initializer)

    texts = " ".join(_texts(dialog)).lower()
    assert "experimental" not in texts
    assert "buggy" not in texts
    assert "at your own risk" not in texts
    dialog.destroy()


def _page(dialog, name):
    return dialog.content_stack.get_child_by_name(name)


@pytest.mark.ui
def test_only_the_pages_a_ruida_machine_uses(ui_context_initializer):
    dialog = _dialog(ui_context_initializer)

    stack_pages = dialog.content_stack.get_pages()
    names = [
        stack_pages.get_item(i).get_name()
        for i in range(stack_pages.get_n_items())
    ]
    assert names == [
        "general",
        "hardware",
        "advanced",
        "device",
        "heads",
        "nogo-zones",
        "maintenance",
    ]
    assert list(dialog._row_to_page_name.values()) == names
    dialog.destroy()


@pytest.mark.ui
def test_heads_page_edits_the_one_laser_head(ui_context_initializer):
    dialog = _dialog(ui_context_initializer)
    page = _page(dialog, "heads")
    head = dialog.machine.get_default_laser_head()

    texts = _texts(page)
    for gone in (
        "Add New Head",
        "Spindle",
        "3D Model",
        "Tool Number",
        "Laser Type",
        "Max Power",
        "Focal Distance",
        "PWM Frequency",
        "Pulse Width",
    ):
        assert not any(gone in t for t in texts), gone
    for kept in (
        "Name",
        "Focus Power",
        "Spot Size X",
        "Spot Size Y",
        "Cut Color",
        "Raster Color",
        "Frame Power",
    ):
        assert kept in texts, kept

    widget = page.laser_widget
    assert widget.focus_power_row.get_value() == pytest.approx(
        head.focus_power_percent * 100
    )
    # A user edit (mm), which set_value() would not report.
    widget.spot_size_x_row.get_spin_button().set_value(0.3)
    assert head.spot_size_mm[0] == pytest.approx(0.3)
    dialog.destroy()


@pytest.mark.ui
def test_general_page_has_no_unit_system_and_travel_speed_is_live(
    ui_context_initializer,
):
    dialog = _dialog(ui_context_initializer)
    page = _page(dialog, "general")

    texts = _texts(page)
    assert "Unit System" not in texts
    assert "Machine Unit System" not in texts
    assert page.travel_speed_row.get_sensitive()
    assert page.travel_speed_row.get_subtitle() == (
        "Maximum rapid movement speed"
    )
    dialog.destroy()


@pytest.mark.ui
def test_advanced_page_keeps_arcs_and_home_on_start_only(
    ui_context_initializer,
):
    dialog = _dialog(ui_context_initializer)
    page = _page(dialog, "advanced")

    texts = _texts(page)
    assert "Support Arcs" in texts
    assert "Home On Start" in texts
    for gone in (
        "Support Bézier Curves",
        "Allow Single Axis Homing",
        "Clear Alarm On Connect",
    ):
        assert gone not in texts
    assert dialog.machine.supports_curves is False
    dialog.destroy()


@pytest.mark.ui
def test_hardware_page_has_no_reverse_z(ui_context_initializer):
    dialog = _dialog(ui_context_initializer)
    texts = _texts(_page(dialog, "hardware"))

    assert "Reverse X-Axis Direction" in texts
    assert "Reverse Z-Axis Direction" not in texts
    dialog.destroy()


@pytest.mark.ui
def test_device_page_has_no_firmware_settings_editor(ui_context_initializer):
    dialog = _dialog(ui_context_initializer)
    page = _page(dialog, "device")

    texts = _texts(page)
    assert "Connection" in texts
    assert "Diagnostics" in texts
    for gone in (
        "Device Settings",
        "The current driver does not support reading device settings.",
        "Click the refresh button to load settings from the device.",
    ):
        assert gone not in texts
    dialog.destroy()


@pytest.mark.ui
def test_maintenance_page_id_opens_the_maintenance_page(
    ui_context_initializer,
):
    # The page id the main window's maintenance alert passes.
    dialog = _dialog(ui_context_initializer, initial_page="maintenance")

    row = dialog.sidebar_list.get_selected_row()
    assert dialog._row_to_page_name[row] == "maintenance"
    assert dialog.content_stack.get_visible_child_name() == "maintenance"
    assert dialog.content_page.get_title() == "Maintenance"
    dialog.destroy()


def test_profile_round_trip_keeps_the_fields_behind_removed_rows(
    lite_context,
):
    """The rows are gone; the profile keys they edited still load and
    save, so the job path and YAML see no difference."""
    data = copy.deepcopy(ILAB_614_PROFILE)
    machine = Machine.from_dict(data, context=lite_context)
    saved = machine.to_dict()["machine"]

    for key in (
        "hookmacros",
        "macros",
        "rotary_modules",
        "supports_curves",
        "single_axis_homing_enabled",
        "clear_alarm_on_connect",
        "reverse_z_axis",
    ):
        assert key in saved, key
    head = saved["heads"][0]
    for key in (
        "tool_number",
        "laser_type",
        "max_power",
        "focal_distance",
        "pwm_frequency",
        "max_pwm_frequency",
        "pulse_width",
        "min_pulse_width",
        "max_pulse_width",
    ):
        assert key in head, key

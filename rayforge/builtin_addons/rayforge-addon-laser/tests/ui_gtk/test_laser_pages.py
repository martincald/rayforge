# flake8: noqa: E402
"""UI tests for the laser step settings pages."""

from typing import Any

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk
from laser_essentials.widgets.contour_page import (
    ContourStepSettingsPage,
    ThresholdRow,
)
from laser_essentials.widgets.material_test_grid_page import (
    MaterialTestGridSettingsPage,
)
from laser_essentials.widgets.raster_page import RasterSettingsPage
from laser_essentials.widgets.rows import (
    AirAssistRow,
    OffsetRow,
    PowerRow,
)

from rayforge.core.step_registry import step_registry
from rayforge.ui_gtk.doceditor.step_settings.dialog import StepSettingsDialog
from rayforge.ui_gtk.doceditor.step_settings.pages import StepSettingsPage
from rayforge.ui_gtk.doceditor.step_settings.rows import (
    CutSpeedRow,
    HeadRow,
    TravelSpeedRow,
)


def _find(widget, cls):
    for row in widget._rows:
        if isinstance(row, cls):
            return row
    raise AssertionError(f"row {cls.__name__} not found in page")


def _contour_step(ui_context) -> Any:
    step_cls = step_registry.get("ContourStep")
    assert step_cls is not None
    return step_cls.create(ui_context)


@pytest.mark.ui
def test_contour_page_composes_step_and_laser_rows(
    editor, laser_machine, ui_context
):
    step = _contour_step(ui_context)
    page = ContourStepSettingsPage(editor, step)
    laser_page = page.laser_page()

    assert isinstance(page, StepSettingsPage)
    assert isinstance(page, Adw.PreferencesPage)
    assert isinstance(laser_page, StepSettingsPage)

    for cls in (OffsetRow, ThresholdRow):
        _find(page, cls)
    for cls in (
        PowerRow,
        CutSpeedRow,
        TravelSpeedRow,
        AirAssistRow,
        HeadRow,
    ):
        _find(laser_page, cls)


@pytest.mark.ui
def test_path_offset_insensitive_on_centerline(
    editor, laser_machine, ui_context
):
    step = _contour_step(ui_context)
    page = ContourStepSettingsPage(editor, step)
    offset = _find(page, OffsetRow)

    assert step.cut_side == "CENTERLINE"
    assert offset.widget.get_sensitive() is False

    step.cut_side = "OUTSIDE"
    step.updated.send(step)
    assert offset.widget.get_sensitive() is True


@pytest.mark.ui
def test_threshold_visible_only_when_rescanning(
    editor, laser_machine, ui_context
):
    step = _contour_step(ui_context)
    page = ContourStepSettingsPage(editor, step)
    threshold = _find(page, ThresholdRow)

    step.override_threshold = False
    step.updated.send(step)
    assert threshold.widget.get_visible() is False

    step.override_threshold = True
    step.updated.send(step)
    assert threshold.widget.get_visible() is True


@pytest.mark.ui
def test_head_change_does_not_touch_offset(editor, laser_machine, ui_context):
    step = _contour_step(ui_context)
    page = ContourStepSettingsPage(editor, step)
    laser_page = page.laser_page()
    offset_before = step.offset_mm

    target = laser_machine.heads[1]
    laser_page.head_row.head_changed.send(
        laser_page.head_row, head_uid=target.uid
    )
    assert step.selected_head_uid == target.uid
    assert step.offset_mm == offset_before


@pytest.mark.ui
def test_offset_row_uses_user_units(editor, laser_machine, ui_context):
    ui_context.config.unit_preferences["length"] = "in"
    step = _contour_step(ui_context)
    page = ContourStepSettingsPage(editor, step)
    offset = _find(page, OffsetRow)

    step.offset_mm = 25.4
    step.updated.send(step)

    assert offset.widget is not None
    assert offset.widget.get_value_in_base_units() == pytest.approx(25.4)
    assert offset.widget.get_value() == pytest.approx(1.0, abs=1e-2)


@pytest.mark.ui
def test_material_test_page_builds(editor, laser_machine, ui_context):
    step_cls = step_registry.get("MaterialTestStep")
    assert step_cls is not None
    page = MaterialTestGridSettingsPage(editor, step_cls.create(ui_context))
    assert isinstance(page, StepSettingsPage)


@pytest.mark.ui
def test_raster_page_builds(editor, laser_machine, ui_context):
    step_cls = step_registry.get("EngraveStep")
    assert step_cls is not None
    page = RasterSettingsPage(editor, step_cls.create(ui_context))
    assert isinstance(page, StepSettingsPage)


@pytest.mark.ui
def test_dialog_uses_contour_page(editor, laser_machine, ui_context):
    dialog = StepSettingsDialog(editor, _contour_step(ui_context))
    assert type(dialog.general_view).__name__ == "ContourStepSettingsPage"
    assert [title for title, _, _ in dialog._extra_pages] == ["Laser"]
    assert len(dialog._extra_buttons) == 1
    dialog.close()


@pytest.mark.ui
def test_dialog_initial_laser_page(editor, laser_machine, ui_context):
    dialog = StepSettingsDialog(editor, _contour_step(ui_context))
    dialog.set_initial_page("laser")
    assert dialog._extra_buttons[0].get_active() is True
    assert dialog.btn_step_settings.get_active() is False
    dialog.close()


@pytest.mark.ui
def test_speed_rows_display_mm_per_second(editor, laser_machine, ui_context):
    """Cut/travel speed are stored in mm/min and shown in mm/s."""
    step = _contour_step(ui_context)
    laser_page = ContourStepSettingsPage(editor, step).laser_page()
    cut = _find(laser_page, CutSpeedRow)
    travel = _find(laser_page, TravelSpeedRow)

    step.cut_speed = 600
    step.travel_speed = 3000
    step.updated.send(step)

    assert cut.widget.get_value_in_base_units() == pytest.approx(600)
    assert cut.widget.get_value() == pytest.approx(10.0)
    assert travel.widget.get_value_in_base_units() == pytest.approx(3000)
    assert travel.widget.get_value() == pytest.approx(50.0)


@pytest.mark.ui
def test_speed_row_input_is_stored_in_base_units(
    editor, laser_machine, ui_context
):
    """Typing mm/s writes mm/min back to the step."""
    step = _contour_step(ui_context)
    laser_page = ContourStepSettingsPage(editor, step).laser_page()
    cut = _find(laser_page, CutSpeedRow)

    cut.widget.get_spin_button().set_value(25.0)

    assert cut.widget.get_value_in_base_units() == pytest.approx(1500)


@pytest.mark.ui
def test_power_row_has_a_spin_button_on_the_slider_adjustment(
    editor, laser_machine, ui_context
):
    """The numeric entry and the slider share one adjustment."""
    step = _contour_step(ui_context)
    laser_page = ContourStepSettingsPage(editor, step).laser_page()
    power = _find(laser_page, PowerRow)

    assert isinstance(power._spin, Gtk.SpinButton)
    assert power._spin.get_adjustment() is power._scale.get_adjustment()


@pytest.mark.ui
def test_power_row_spans_zero_to_one_hundred_percent(
    editor, laser_machine, ui_context
):
    step = _contour_step(ui_context)
    laser_page = ContourStepSettingsPage(editor, step).laser_page()
    power = _find(laser_page, PowerRow)
    adj = power._spin.get_adjustment()

    assert adj.get_lower() == pytest.approx(0.0)
    assert adj.get_upper() == pytest.approx(100.0)
    assert adj.get_step_increment() == pytest.approx(1.0)
    assert power._spin.get_digits() == 1


@pytest.mark.ui
def test_power_row_shows_the_attribute_as_a_percentage(
    editor, laser_machine, ui_context
):
    """A 0.0-1.0 attribute renders on a 0-100 scale."""
    step = _contour_step(ui_context)
    laser_page = ContourStepSettingsPage(editor, step).laser_page()
    power = _find(laser_page, PowerRow)

    step.power = 0.42
    step.updated.send(step)

    assert power._spin.get_value() == pytest.approx(42.0)


@pytest.mark.ui
def test_typing_power_moves_the_slider(editor, laser_machine, ui_context):
    """Typing and sliding stay in sync via the shared adjustment."""
    step = _contour_step(ui_context)
    laser_page = ContourStepSettingsPage(editor, step).laser_page()
    power = _find(laser_page, PowerRow)

    power._spin.set_value(75.0)

    assert power._scale.get_value() == pytest.approx(75.0)

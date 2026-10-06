# flake8: noqa: E402
"""Integration tests for AddEditRecipeDialog step-type targeting."""

from gettext import gettext as _

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, Gtk

from swiftcut.core.color import COLOR_PALETTE
from swiftcut.core.recipe import Recipe
from swiftcut.core.recipe_manager import RecipeManager
from swiftcut.machine.models.laser import Laser
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.doceditor.recipes.edit_recipe_dialog import (
    AddEditRecipeDialog,
)
from swiftcut.ui_gtk.doceditor.recipes.recipe_list import RecipeListWidget

pytestmark = pytest.mark.ui


@pytest.fixture
def laser_machine(ui_context_initializer):
    """A machine with one laser head, set as the active machine."""
    context = ui_context_initializer
    machine = Machine(context)
    machine.set_axis_extents(200, 150)
    machine.max_cut_speed = 5000
    machine.max_travel_speed = 10000

    laser = Laser()
    laser.name = "Laser 1"
    laser.spot_size_mm = (0.1, 0.2)
    machine.heads.clear()
    machine.add_head(laser)

    context.machine_mgr.machines.clear()
    context.machine_mgr.add_machine(machine)
    context.config.set_machine(machine)
    return machine


@pytest.fixture
def recipe_mgr(ui_context_initializer, tmp_path, monkeypatch):
    """A RecipeManager on a private directory, used by the context."""
    mgr = RecipeManager(tmp_path / "recipes")
    monkeypatch.setattr(ui_context_initializer, "_recipe_mgr", mgr)
    return mgr


def _settings_keys(dialog):
    """Collect widget keys across all settings pages."""
    keys = []
    for page in dialog._settings_pages.values():
        keys.extend(page.keys)
    return keys


def test_default_selection_is_generic(laser_machine):
    """Opening the editor with no recipe defaults to a generic (any step)
    selection and base Step settings."""
    dialog = AddEditRecipeDialog(parent=None, recipe=None)
    page = dialog.applicability_page

    assert page.get_step_types() == []

    keys = _settings_keys(dialog)
    assert "cut_speed" in keys
    assert "travel_speed" in keys
    assert "power" not in keys
    assert "cut_side" not in keys

    data = dialog.get_recipe_data()
    assert data["target_step_types"] == []

    dialog.close()


def test_single_step_type_shows_step_specific_settings(laser_machine):
    """Selecting one step type shows that step's full settings groups."""
    recipe = Recipe(
        name="Contour Recipe",
        target_step_types=["ContourStep"],
        settings={"power": 0.8, "cut_side": "OUTSIDE"},
    )
    dialog = AddEditRecipeDialog(parent=None, recipe=recipe)

    # Two settings pages: "Laser" and "Step Settings".
    titles = [p.group_title for p in dialog._settings_pages.values()]
    assert any("Laser" in t for t in titles)
    assert any("Step Settings" in t for t in titles)

    all_keys = set(_settings_keys(dialog))
    assert "cut_side" in all_keys
    assert "cut_order" in all_keys
    assert "power" in all_keys

    data = dialog.get_recipe_data()
    assert data["target_step_types"] == ["ContourStep"]
    assert data["settings"]["power"] == 0.8
    assert data["settings"]["cut_side"] == "OUTSIDE"

    dialog.close()


def test_multi_step_types_show_common_settings(laser_machine):
    """Multiple step types show only the settings common to all of them.

    ContourStep and EngraveStep only share the inherited Laser group;
    their step-specific settings (cut_side / scan_angle) are excluded.
    """
    recipe = Recipe(
        name="Multi",
        target_step_types=["ContourStep", "EngraveStep"],
    )
    dialog = AddEditRecipeDialog(parent=None, recipe=recipe)

    keys = _settings_keys(dialog)
    assert "cut_speed" in keys
    assert "travel_speed" in keys
    assert "power" in keys
    assert "cut_side" not in keys  # ContourStep-specific
    assert "scan_angle" not in keys  # EngraveStep-specific

    data = dialog.get_recipe_data()
    assert data["target_step_types"] == ["ContourStep", "EngraveStep"]

    dialog.close()


def test_selecting_single_step_type_rebuilds_settings(laser_machine):
    """Changing the selection to a single step type rebuilds the settings."""
    dialog = AddEditRecipeDialog(parent=None, recipe=None)
    page = dialog.applicability_page

    # Simulate the StepTypeSelectionDialog callback.
    page._on_step_types_selected(["ContourStep"])

    assert page.get_step_types() == ["ContourStep"]
    all_keys = set(_settings_keys(dialog))
    assert "cut_side" in all_keys
    assert "power" in all_keys

    dialog.close()


def test_selecting_multi_step_types_shows_common(laser_machine):
    """Changing to multiple step types shows the common settings only."""
    dialog = AddEditRecipeDialog(parent=None, recipe=None)
    page = dialog.applicability_page

    page._on_step_types_selected(["ContourStep", "EngraveStep"])

    keys = _settings_keys(dialog)
    assert "power" in keys  # shared laser setting
    assert "cut_side" not in keys
    assert "scan_angle" not in keys

    dialog.close()


# --- POST-PROCESSING TAB ---


def test_post_processing_tab_hidden_for_generic_selection(laser_machine):
    """The base Step has no transformers, so no tab appears."""
    dialog = AddEditRecipeDialog(parent=None, recipe=None)
    assert dialog._post_processing_page is None
    assert "post-processing" not in dialog._tab_buttons
    assert "transformer_dicts" in dialog.get_recipe_data()
    assert dialog.get_recipe_data()["transformer_dicts"] == []
    dialog.close()


def test_post_processing_tab_appears_for_contour(laser_machine):
    """ContourStep has transformers, so the tab appears with them."""
    recipe = Recipe(name="Contour", target_step_types=["ContourStep"])
    dialog = AddEditRecipeDialog(parent=None, recipe=recipe)

    assert dialog._post_processing_page is not None
    assert "post-processing" in dialog._tab_buttons
    names = [
        d.get("name")
        for d in dialog._post_processing_page.get_transformer_dicts()
    ]
    assert "Optimize" in names
    assert "CropTransformer" in names

    # All dicts default to "Leave Unchanged" (recipe_apply=False).
    assert all(
        not d.get("recipe_apply")
        for d in dialog._post_processing_page.get_transformer_dicts()
    )

    dialog.close()


def test_post_processing_tab_restores_recipe_values(laser_machine):
    """Stored recipe values are overlaid onto the common transformers."""
    recipe = Recipe(
        name="Contour",
        target_step_types=["ContourStep"],
        transformer_dicts=[
            {
                "name": "Optimize",
                "recipe_apply": True,
                "enabled": False,
            }
        ],
    )
    dialog = AddEditRecipeDialog(parent=None, recipe=recipe)
    assert dialog._post_processing_page is not None

    dicts = {
        d.get("name"): d
        for d in dialog._post_processing_page.get_transformer_dicts()
    }
    assert dicts["Optimize"]["recipe_apply"] is True
    assert dicts["Optimize"]["enabled"] is False
    # Other transformers default to Leave Unchanged.
    assert dicts["CropTransformer"]["recipe_apply"] is False

    data = dialog.get_recipe_data()
    data_dicts = {d.get("name"): d for d in data["transformer_dicts"]}
    assert data_dicts["Optimize"]["recipe_apply"] is True
    assert data_dicts["Optimize"]["enabled"] is False

    dialog.close()


def test_tri_state_selection_updates_dict(laser_machine):
    """Selecting a tri-state option writes recipe_apply/enabled."""
    recipe = Recipe(name="Contour", target_step_types=["ContourStep"])
    dialog = AddEditRecipeDialog(parent=None, recipe=recipe)
    assert dialog._post_processing_page is not None
    page = dialog._post_processing_page

    group = _group_for_transformer(page, "Optimize")
    dicts = {d.get("name"): d for d in page.get_transformer_dicts()}
    optimize_dict = dicts["Optimize"]
    assert optimize_dict["recipe_apply"] is False

    # Select "Enabled" in the group's tri-state popover.
    _click_tri_state(page, group, _("Enabled"))
    assert optimize_dict["recipe_apply"] is True
    assert optimize_dict["enabled"] is True

    # Select "Disabled".
    _click_tri_state(page, group, _("Disabled"))
    assert optimize_dict["recipe_apply"] is True
    assert optimize_dict["enabled"] is False

    # Select "Leave Unchanged".
    _click_tri_state(page, group, _("Leave Unchanged"))
    assert optimize_dict["recipe_apply"] is False

    dialog.close()


def test_post_processing_tab_rebuilds_with_selection(laser_machine):
    """Changing the step-type selection rebuilds the post-processing tab."""
    dialog = AddEditRecipeDialog(parent=None, recipe=None)
    assert dialog._post_processing_page is None

    dialog.applicability_page._on_step_types_selected(["ContourStep"])
    assert dialog._post_processing_page is not None

    dialog.applicability_page._on_step_types_selected(["EngraveStep"])
    assert dialog._post_processing_page is not None

    dialog.applicability_page._on_step_types_selected([])
    assert dialog._post_processing_page is None

    dialog.close()


def test_new_recipe_gets_an_unused_palette_color(laser_machine, recipe_mgr):
    """A new recipe defaults to the first palette color not yet used."""
    recipe_mgr.add_recipe(Recipe(name="Taken", color=COLOR_PALETTE[0]))
    dialog = AddEditRecipeDialog(parent=None, recipe=None)

    assert dialog.get_recipe_data()["color"] == COLOR_PALETTE[1]

    dialog.close()


def test_recipe_color_is_prefilled_and_picked(laser_machine, recipe_mgr):
    """The editor shows the recipe color and returns the picked one."""
    recipe = Recipe(name="Red", color="#ff0000")
    dialog = AddEditRecipeDialog(parent=None, recipe=recipe)
    assert dialog.get_recipe_data()["color"] == "#ff0000"

    rgba = Gdk.RGBA()
    rgba.parse("#123456")
    dialog.general_page.color_button.set_rgba(rgba)

    assert dialog.get_recipe_data()["color"] == "#123456"

    dialog.close()


def test_edited_recipe_keeps_its_color(
    laser_machine, recipe_mgr, monkeypatch
):
    """Saving an edit stores the color shown in the editor."""
    dialogs = []
    monkeypatch.setattr(
        AddEditRecipeDialog, "present", lambda d: dialogs.append(d)
    )
    kept = Recipe(name="Kept", color="#ff0000")
    picked = Recipe(name="Picked", color="#ff0000")
    recipe_mgr.add_recipe(kept)
    recipe_mgr.add_recipe(picked)
    widget = RecipeListWidget()

    widget._on_edit_recipe(kept)
    dialogs[-1]._send_response("save")
    widget._on_edit_recipe(picked)
    rgba = Gdk.RGBA()
    rgba.parse("#123456")
    dialogs[-1].general_page.color_button.set_rgba(rgba)
    dialogs[-1]._send_response("save")

    reloaded = RecipeManager(recipe_mgr.base_dir)
    assert reloaded.recipes[kept.uid].color == "#ff0000"
    assert reloaded.recipes[picked.uid].color == "#123456"


def test_added_recipe_stores_its_color(
    laser_machine, recipe_mgr, monkeypatch
):
    """Adding a recipe from the list stores the editor's color."""
    dialogs = []
    monkeypatch.setattr(
        AddEditRecipeDialog, "present", lambda d: dialogs.append(d)
    )
    widget = RecipeListWidget()

    widget._on_add_clicked(Gtk.Button())
    dialogs[-1].general_page.name_row.set_text("New")
    dialogs[-1]._send_response("add")

    (added,) = RecipeManager(recipe_mgr.base_dir).get_all_recipes()
    assert added.color == COLOR_PALETTE[0]


def _group_for_transformer(page, name):
    """The settings group backing the named transformer, if any."""
    for group, t_dict in page._group_dicts.items():
        if t_dict.get("name") == name:
            return group
    raise AssertionError(f"No group for transformer '{name}'")


def _click_tri_state(page, group, label):
    """Select a tri-state popover entry by label, mirroring a click."""
    button = group.tri_state_button
    assert button is not None
    list_box = button.get_popover().get_child()
    row = list_box.get_first_child()
    while row is not None:
        child = row.get_child()
        if isinstance(child, Gtk.Button) and child.get_label() == label:
            child.emit("clicked")
            return
        row = row.get_next_sibling()
    raise AssertionError(f"No tri-state entry '{label}'")

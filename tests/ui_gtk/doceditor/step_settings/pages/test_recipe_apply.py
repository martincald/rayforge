# flake8: noqa: E402
"""Tests for applying a recipe and syncing the settings page widgets."""

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from swiftcut.core.recipe import Recipe
from swiftcut.core.recipe_manager import RecipeManager
from swiftcut.ui_gtk.doceditor.step_settings.pages import StepSettingsPage
from swiftcut.ui_gtk.doceditor.step_settings.rows import SliderRow, SpinRow


@pytest.mark.ui
def test_applying_recipe_updates_page_widgets(editor, step):
    page = StepSettingsPage(editor, step)
    count_row = SpinRow(
        editor, step, "count", "Count", None, 1, 10, 1, 0, is_int=True
    )
    power_row = SliderRow(
        editor, step, "power", "Power", None, 0.0, 1.0, 0.01, 2
    )
    page.add_section("Params", count_row, power_row)

    recipe = Recipe(
        name="Test Recipe",
        settings={"count": 9, "power": 0.8},
    )

    updated = []
    step.updated.connect(lambda *_: updated.append(1), weak=False)
    page.recipe_control._apply_recipe(recipe)

    assert step.applied_recipe_uid == recipe.uid
    assert step.count == 9
    assert step.power == pytest.approx(0.8)
    assert updated, "applying a recipe must emit step.updated"
    assert count_row.widget.get_value() == 9
    assert power_row._adj.get_value() == pytest.approx(0.8)


@pytest.mark.ui
def test_applying_recipe_uses_setters(editor, step):
    page = StepSettingsPage(editor, step)
    recipe = Recipe(
        name="Setter Recipe",
        settings={"count": 5},
    )

    page.recipe_control._apply_recipe(recipe)

    assert step.count == 5


@pytest.mark.ui
def test_applying_recipe_colors_the_layer_undoably(editor, step):
    layer = editor.doc.layers[0]
    layer.workflow.add_step(step)
    old_color = layer.color
    page = StepSettingsPage(editor, step)
    recipe = Recipe(name="Red", color="#ff0000", settings={"count": 5})

    page.recipe_control._apply_recipe(recipe)

    assert layer.color == "#ff0000"
    assert step.count == 5
    editor.doc.history_manager.undo()
    assert layer.color == old_color
    assert step.count == 3


@pytest.mark.ui
def test_applying_recipe_without_color_leaves_layer(editor, step):
    layer = editor.doc.layers[0]
    layer.workflow.add_step(step)
    old_color = layer.color
    page = StepSettingsPage(editor, step)

    page.recipe_control._apply_recipe(Recipe(settings={"count": 5}))

    assert step.count == 5
    assert layer.color == old_color


@pytest.mark.ui
@pytest.mark.parametrize("builtin", [False, True])
def test_update_is_offered_only_for_user_recipes(
    editor, step, ui_context, tmp_path, monkeypatch, builtin
):
    """A step that diverged from a built-in cannot update it."""
    recipe_mgr = RecipeManager(tmp_path / "recipes")
    monkeypatch.setattr(ui_context, "_recipe_mgr", recipe_mgr)
    recipe = Recipe(name="Nine", builtin=builtin, settings={"count": 9})
    recipe_mgr.add_recipe(recipe)
    step.applied_recipe_uid = recipe.uid

    page = StepSettingsPage(editor, step)

    assert step.count != 9
    assert page.recipe_control.update_button.get_visible() is not builtin


@pytest.mark.ui
def test_applying_recipe_uses_the_active_machines_values(
    editor, step, ui_context, tmp_path, monkeypatch
):
    """Choose applies the active machine's values over the shared ones,
    and the step then matches the recipe: nothing to update."""
    recipe_mgr = RecipeManager(tmp_path / "recipes")
    monkeypatch.setattr(ui_context, "_recipe_mgr", recipe_mgr)
    recipe = Recipe(
        name="Per machine",
        settings={"count": 5, "power": 0.4},
        machine_settings={
            ui_context.machine.name: {"power": 0.9},
            "elsewhere": {"power": 0.1},
        },
    )
    recipe_mgr.add_recipe(recipe)
    page = StepSettingsPage(editor, step)

    page.recipe_control._apply_recipe(recipe)

    assert step.count == 5
    assert step.power == pytest.approx(0.9)
    assert not page.recipe_control.update_button.get_visible()


@pytest.mark.ui
def test_resync_overrides_pending_edit(editor, step):
    row = SpinRow(
        editor, step, "count", "Count", None, 1, 10, 1, 0, is_int=True
    )
    row.widget.get_adjustment().set_value(9)
    assert row._debounce_timer != 0

    step.count = 4
    row.resync()

    assert row.widget.get_value() == 4
    assert row._debounce_timer == 0

"""Tests for the recipe list row subtitle."""

import pytest
from gi.repository import Gtk

from swiftcut.core.recipe import Recipe
from swiftcut.ui_gtk.doceditor.recipes.recipe_list import RecipeRow

pytestmark = pytest.mark.ui


def _row_for(recipe: Recipe, on_duplicate=lambda recipe: None) -> RecipeRow:
    return RecipeRow(
        recipe,
        on_delete=lambda recipe: None,
        on_edit=lambda recipe: None,
        on_duplicate=on_duplicate,
    )


def _buttons(widget: Gtk.Widget) -> list[Gtk.Button]:
    """Every button inside a widget, in tree order."""
    found = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Button):
            found.append(child)
        else:
            found.extend(_buttons(child))
        child = child.get_next_sibling()
    return found


def test_step_types_shown(ui_context_initializer):
    """A step-scoped recipe shows its step type, not 'Any'."""
    recipe = Recipe(
        name="Contour Only",
        target_step_types=["ContourStep"],
    )
    subtitle = _row_for(recipe)._get_subtitle()
    assert "Contour" in subtitle
    assert "Any" not in subtitle


def test_multiple_step_types_joined(ui_context_initializer):
    """Multiple step types are joined in the subtitle."""
    recipe = Recipe(
        name="Multi",
        target_step_types=["ContourStep", "FrameStep"],
    )
    subtitle = _row_for(recipe)._get_subtitle()
    assert "Contour" in subtitle
    assert "Frame" in subtitle


def test_generic_recipe_shows_any(ui_context_initializer):
    """A generic recipe (no step types) shows 'Any'."""
    recipe = Recipe(name="Generic", target_step_types=[])
    subtitle = _row_for(recipe)._get_subtitle()
    assert subtitle == "Any"


def test_user_recipe_row_can_be_edited_and_deleted(ui_context_initializer):
    """A user recipe row has Edit and Delete, and no Duplicate."""
    row = _row_for(Recipe(name="Mine"))
    assert [b.get_tooltip_text() for b in _buttons(row)] == [
        "Edit this recipe",
        "Delete this recipe",
    ]


def test_builtin_row_only_offers_duplicate(ui_context_initializer):
    """A built-in row cannot be edited or deleted, only duplicated."""
    recipe = Recipe(name="Shipped", builtin=True)
    duplicated = []
    row = _row_for(recipe, on_duplicate=duplicated.append)

    (button,) = _buttons(row)
    assert button.get_tooltip_text() == "Duplicate this recipe to customize it"
    button.emit("clicked")
    assert duplicated == [recipe]
    assert row._get_subtitle().startswith("Built-in")

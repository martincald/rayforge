"""Adding a step from a workflow panel applies the best recipe."""

from types import SimpleNamespace

import pytest

from swiftcut.core.recipe import Recipe
from swiftcut.core.recipe_manager import RecipeManager
from swiftcut.core.step import Step


@pytest.fixture
def editor(ui_context_initializer, ui_task_mgr):
    from swiftcut.doceditor.editor import DocEditor

    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    yield editor
    editor.cleanup()


def _add_from_view(editor, layer, popup):
    from swiftcut.ui_gtk.doceditor.workflow_view import WorkflowView

    WorkflowView(editor, layer.workflow).on_add_dialog_response(popup)


def _add_from_row(editor, layer, popup):
    from swiftcut.ui_gtk.doceditor.workflow_row import WorkflowRow

    WorkflowRow(editor, layer)._on_add_step_dialog_response(popup)


@pytest.mark.ui
@pytest.mark.parametrize("add_step", [_add_from_view, _add_from_row])
def test_added_step_colors_its_layer_in_one_undo(
    editor, tmp_path, monkeypatch, add_step
):
    """The layer takes the recipe color; one undo reverts both."""
    from swiftcut.ui_gtk.doceditor.step_settings.dialog import (
        StepSettingsDialog,
    )

    recipe_mgr = RecipeManager(tmp_path / "recipes")
    recipe_mgr.add_recipe(Recipe(name="Teal", color="#123456"))
    monkeypatch.setattr(editor.context, "_recipe_mgr", recipe_mgr)
    monkeypatch.setattr(
        StepSettingsDialog, "present_for_step", lambda *args: None
    )
    layer = editor.doc.layers[0]
    old_color = layer.color
    old_steps = list(layer.workflow.steps)
    step = Step(typelabel="Test")
    popup = SimpleNamespace(selected_item=lambda context: step)

    add_step(editor, layer, popup)

    assert layer.color == "#123456"
    assert step in layer.workflow.steps
    editor.history_manager.undo()
    assert layer.color == old_color
    assert layer.workflow.steps == old_steps

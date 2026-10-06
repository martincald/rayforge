import pytest

from swiftcut.core.recipe import Recipe
from swiftcut.core.recipe_manager import RecipeManager
from swiftcut.core.step import Step
from swiftcut.doceditor.step_cmd import StepCmd


@pytest.fixture
def step_cmd(doc_editor):
    """Provides a StepCmd instance."""
    return StepCmd(doc_editor)


@pytest.fixture
def recipe_mgr(doc_editor, tmp_path, monkeypatch):
    """A RecipeManager on a private directory, used by the context."""
    mgr = RecipeManager(tmp_path / "recipes")
    monkeypatch.setattr(doc_editor.context, "_recipe_mgr", mgr)
    return mgr


def test_apply_best_recipe_colors_the_given_layer(
    step_cmd, doc_editor, recipe_mgr
):
    """A recipe color reaches the layer passed in, undoably."""
    recipe = Recipe(name="Red", color="#ff0000", settings={"power": 0.4})
    recipe_mgr.add_recipe(recipe)
    layer = doc_editor.doc.layers[0]
    old_color = layer.color
    step = Step(typelabel="Test")

    step_cmd.apply_best_recipe_to_step(step, layer=layer)

    assert step.applied_recipe_uid == recipe.uid
    assert layer.color == "#ff0000"
    doc_editor.history_manager.undo()
    assert layer.color == old_color


def test_apply_best_recipe_without_layer_leaves_colors(
    step_cmd, doc_editor, recipe_mgr
):
    """Without a layer, applying a colored recipe changes no layer."""
    recipe = Recipe(name="Red", color="#ff0000")
    recipe_mgr.add_recipe(recipe)
    colors = [layer.color for layer in doc_editor.doc.layers]
    step = Step(typelabel="Test")

    step_cmd.apply_best_recipe_to_step(step)

    assert step.applied_recipe_uid == recipe.uid
    assert [layer.color for layer in doc_editor.doc.layers] == colors
    assert not doc_editor.history_manager.can_undo()


def test_apply_best_recipe_without_color_leaves_layer(
    step_cmd, doc_editor, recipe_mgr
):
    """A legacy recipe without a color leaves the layer color alone."""
    recipe = Recipe(name="Plain")
    recipe_mgr.add_recipe(recipe)
    layer = doc_editor.doc.layers[0]
    old_color = layer.color
    step = Step(typelabel="Test")

    step_cmd.apply_best_recipe_to_step(step, layer=layer)

    assert step.applied_recipe_uid == recipe.uid
    assert layer.color == old_color
    assert not doc_editor.history_manager.can_undo()


def test_set_step_param(step_cmd):
    """Test setting a step parameter."""
    target_dict = {}
    key = "test_key"
    new_value = "test_value"
    name = "Test Command"

    step_cmd.set_step_param(target_dict, key, new_value, name)

    assert target_dict[key] == new_value


def test_set_step_param_no_change(step_cmd):
    """Test that setting the same value does nothing."""
    target_dict = {"test_key": "test_value"}
    key = "test_key"
    new_value = "test_value"
    name = "Test Command"

    step_cmd.set_step_param(target_dict, key, new_value, name)

    assert target_dict[key] == new_value


def test_set_step_param_float_tolerance(step_cmd):
    """Test that setting a float value within tolerance does nothing."""
    target_dict = {"test_key": 1.0}
    key = "test_key"
    new_value = 1.0000001  # Within 1e-6 tolerance
    name = "Test Command"

    step_cmd.set_step_param(target_dict, key, new_value, name)

    assert target_dict[key] == 1.0

"""Tests for the bundled default recipes and the context's sync."""

import yaml

from swiftcut import config
from swiftcut.core.color import normalize_color
from swiftcut.core.recipe import Recipe
from swiftcut.core.recipe_manager import (
    DEFAULTS_VERSION_FILE,
    RecipeManager,
)
from swiftcut.core.step_registry import step_registry

# Read at import, before the autouse no_builtin_recipe_sync fixture
# clears it for each test.
SHIPPED_DEFAULTS = config.BUILTIN_RECIPES_FILE


def _shipped() -> dict:
    with open(SHIPPED_DEFAULTS, "r") as f:
        return yaml.safe_load(f)


def _bundled_material_uids() -> set[str]:
    """uids of the materials the bundled materials addon ships."""
    materials_dir = (
        config.BUILTIN_ADDONS_DIR / "rayforge-addon-materials" / "materials"
    )
    uids = set()
    for path in materials_dir.glob("*.yaml"):
        with open(path, "r") as f:
            uids.add(yaml.safe_load(f).get("uid"))
    return uids


def test_shipped_defaults_are_valid(context_initializer):
    """defaults.yaml has a version and well-formed, unique recipes."""
    data = _shipped()
    assert isinstance(data["version"], int) and data["version"] >= 1
    entries = data["recipes"]
    assert entries
    uids = [entry["uid"] for entry in entries]
    assert len(set(uids)) == len(uids)

    for entry in entries:
        recipe = Recipe.from_dict(entry)
        assert recipe.extra == {}, recipe.name
        assert entry["color"] == normalize_color(entry["color"])
        assert recipe.target_step_types, recipe.name
        for step_type in recipe.target_step_types:
            step_class = step_registry.get(step_type)
            assert step_class is not None, step_type
            assert set(recipe.settings) <= set(step_class.recipe_keys())
        for key in ("power", "min_power", "tab_power"):
            if key in recipe.settings:
                assert 0.0 <= recipe.settings[key] <= 1.0, recipe.name
        assert recipe.material_uid in _bundled_material_uids(), recipe.name


def test_version_bump_keeps_no_copy_of_unedited_shipped_recipes(tmp_path):
    """Bumping the version of an unchanged bundle makes no copies."""
    data = _shipped()
    RecipeManager(tmp_path / "recipes", SHIPPED_DEFAULTS)
    bumped = tmp_path / "defaults.yaml"
    bumped.write_text(yaml.safe_dump({**data, "version": data["version"] + 1}))

    recipe_mgr = RecipeManager(tmp_path / "recipes", bumped)

    recipes = recipe_mgr.get_all_recipes()
    assert {r.uid for r in recipes} == {e["uid"] for e in data["recipes"]}
    assert all(r.builtin and r.modified_from is None for r in recipes)


def test_context_syncs_shipped_defaults(
    context_initializer, tmp_path, monkeypatch
):
    """The app's recipe manager seeds the shipped built-ins."""
    monkeypatch.setattr(config, "USER_RECIPES_DIR", tmp_path / "recipes")
    monkeypatch.setattr(config, "BUILTIN_RECIPES_FILE", SHIPPED_DEFAULTS)
    monkeypatch.setattr(context_initializer, "_recipe_mgr", None)

    recipe_mgr = context_initializer.recipe_mgr

    data = _shipped()
    assert {r.uid for r in recipe_mgr.get_all_recipes() if r.builtin} == {
        entry["uid"] for entry in data["recipes"]
    }
    version_file = tmp_path / "recipes" / DEFAULTS_VERSION_FILE
    assert version_file.read_text() == f"{data['version']}\n"


def test_tests_do_not_sync_defaults(
    context_initializer, tmp_path, monkeypatch
):
    """Under the test suite the context seeds no built-ins."""
    monkeypatch.setattr(config, "USER_RECIPES_DIR", tmp_path / "recipes")
    monkeypatch.setattr(context_initializer, "_recipe_mgr", None)

    recipe_mgr = context_initializer.recipe_mgr

    assert recipe_mgr.get_all_recipes() == []
    assert not (tmp_path / "recipes" / DEFAULTS_VERSION_FILE).exists()

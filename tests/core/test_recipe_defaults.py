"""Tests for the bundled default recipes and the context's sync."""

import pytest
import yaml

from swiftcut import config
from swiftcut.core.color import normalize_color
from swiftcut.core.recipe import Recipe
from swiftcut.core.recipe_manager import (
    DEFAULTS_VERSION_FILE,
    RecipeManager,
    bundle_recipe_dicts,
)
from swiftcut.core.step_registry import step_registry
from swiftcut.machine.models.default_profile import BUNDLED_NAMES

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


def _translated() -> dict[str, dict]:
    """The shipped lab list as Recipe dicts, by uid."""
    return {d["uid"]: d for d in bundle_recipe_dicts(_shipped())}


def test_shipped_defaults_are_valid(context_initializer):
    """defaults.yaml is a well-formed lab list that translates cleanly."""
    data = _shipped()
    assert isinstance(data["version"], int) and data["version"] >= 3
    entries = data["recipes"]
    assert entries
    ids = [entry["id"] for entry in entries]
    assert len(set(ids)) == len(ids)
    translated = _translated()
    assert set(translated) == set(ids)

    steps = step_registry.all_steps().values()
    for entry in entries:
        assert set(entry["machines"]) == set(BUNDLED_NAMES), entry["id"]
        step = data["operations"][entry["operation"]]["step"]
        matches = [c for c in steps if c.ASSEMBLER_NAME == step]
        assert len(matches) == 1, step

        recipe = Recipe.from_dict(translated[entry["id"]])
        assert recipe.extra == {}, recipe.name
        assert matches[0].__name__ == recipe.target_step_types[0], recipe.name
        assert normalize_color(entry["color"]) is not None, recipe.name
        for step_type in recipe.target_step_types:
            step_class = step_registry.get(step_type)
            assert step_class is not None, step_type
            assert {"power", "min_power", "cut_speed"} <= set(
                step_class.recipe_keys()
            )
        for name in BUNDLED_NAMES:
            values = recipe.machine_settings[name]
            assert set(values) == {"power", "min_power", "cut_speed"}
            assert 0.0 <= values["power"] <= 1.0, (recipe.name, name)
            # The owner's rule: the minimum power equals the power.
            assert values["min_power"] == values["power"], (recipe.name, name)
        assert recipe.material_uid in _bundled_material_uids(), recipe.name
        assert recipe.min_thickness_mm == recipe.max_thickness_mm


def test_operations_map_to_step_types():
    """Cut and scan are contours, engrave is a raster fill."""
    translated = _translated()
    for uid in (
        "mdf-6-cut",
        "mdf-3-cut",
        "mdf-scan",
        "acrylic-scan",
        "foamboard-3-scan",
    ):
        assert translated[uid]["target_step_types"] == ["ContourStep"], uid
    for uid in ("mdf-engrave", "acrylic-3-engrave"):
        assert translated[uid]["target_step_types"] == ["EngraveStep"], uid


def test_lab_numbers_in_model_units():
    """mm/s and percent become the model's mm/min and 0..1."""
    translated = _translated()
    mdf_cut = translated["mdf-6-cut"]["machine_settings"]
    assert mdf_cut["ilab-614"]["cut_speed"] == 1200
    assert mdf_cut["ilab-614"]["power"] == pytest.approx(0.65)
    assert mdf_cut["ilab-614"]["min_power"] == pytest.approx(0.65)
    assert mdf_cut["ilab-626"]["cut_speed"] == 750
    assert mdf_cut["ilab-626"]["power"] == pytest.approx(0.75)
    assert mdf_cut["ilab-626"]["min_power"] == pytest.approx(0.75)
    for uid in ("mdf-scan", "mdf-engrave", "acrylic-scan"):
        assert translated[uid]["min_thickness_mm"] is None, uid
        assert translated[uid]["max_thickness_mm"] is None, uid


# Placeholder recipes of the old shape, standing in for an installed set.
_V1_RECIPES = [
    {
        "uid": "fcc9c750-5441-497c-ab74-c9d6702645b8",
        "name": "Plywood 3 mm Cut",
        "description": "Placeholder, not tested.",
        "color": "#ff6600",
        "target_step_types": ["ContourStep"],
        "material_uid": "plywood",
        "min_thickness_mm": 3.0,
        "max_thickness_mm": 3.0,
        "settings": {"power": 0.65, "cut_speed": 1200},
    },
    {
        "uid": "dd26a12f-28d4-4591-a00a-281ad7d650e5",
        "name": "Plywood 3 mm Engrave",
        "description": "Placeholder, not tested.",
        "color": "#00ccff",
        "target_step_types": ["EngraveStep"],
        "material_uid": "plywood",
        "min_thickness_mm": 3.0,
        "max_thickness_mm": 3.0,
        "settings": {"power": 0.2, "cut_speed": 18000},
    },
    {
        "uid": "fa1c565c-b875-471c-bdb6-1800d14b5f2a",
        "name": "Acrylic 3 mm Cut",
        "description": "Placeholder, not tested.",
        "color": "#cc3366",
        "target_step_types": ["ContourStep"],
        "material_uid": "acrylic",
        "min_thickness_mm": 3.0,
        "max_thickness_mm": 3.0,
        "settings": {"power": 0.7, "cut_speed": 600},
    },
]


def test_install_synced_at_placeholder_v2_takes_the_lab_list(tmp_path):
    """An install that already synced placeholders at version 2 is replaced."""
    v2 = tmp_path / "v2.yaml"
    v2.write_text(yaml.safe_dump({"version": 2, "recipes": _V1_RECIPES}))
    RecipeManager(tmp_path / "recipes", v2)
    shipped = _shipped()
    # A version 1 file would never replace the version 2 install.
    assert shipped["version"] > 2

    recipe_mgr = RecipeManager(tmp_path / "recipes", SHIPPED_DEFAULTS)

    recipes = recipe_mgr.get_all_recipes()
    assert {r.uid for r in recipes} == {e["id"] for e in shipped["recipes"]}
    assert all(r.builtin and r.modified_from is None for r in recipes)
    mdf_cut = recipe_mgr.recipes["mdf-6-cut"]
    assert set(mdf_cut.machine_settings) == set(BUNDLED_NAMES)
    assert mdf_cut.settings == {}


def test_version_bump_keeps_no_copy_of_unedited_shipped_recipes(tmp_path):
    """Bumping the version of an unchanged bundle makes no copies."""
    data = _shipped()
    RecipeManager(tmp_path / "recipes", SHIPPED_DEFAULTS)
    bumped = tmp_path / "defaults.yaml"
    bumped.write_text(yaml.safe_dump({**data, "version": data["version"] + 1}))

    recipe_mgr = RecipeManager(tmp_path / "recipes", bumped)

    recipes = recipe_mgr.get_all_recipes()
    assert {r.uid for r in recipes} == {e["id"] for e in data["recipes"]}
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
        entry["id"] for entry in data["recipes"]
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

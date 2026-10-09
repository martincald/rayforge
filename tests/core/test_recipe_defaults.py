"""Tests for the bundled default recipes and the context's sync."""

from types import SimpleNamespace

import yaml

from swiftcut import config
from swiftcut.core.color import normalize_color
from swiftcut.core.recipe import Recipe
from swiftcut.core.recipe_manager import (
    DEFAULTS_VERSION_FILE,
    RecipeManager,
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


def test_shipped_defaults_are_valid(context_initializer):
    """defaults.yaml has a version and well-formed, unique recipes."""
    data = _shipped()
    assert isinstance(data["version"], int) and data["version"] >= 2
    entries = data["recipes"]
    assert entries
    uids = [entry["uid"] for entry in entries]
    assert len(set(uids)) == len(uids)

    for entry in entries:
        recipe = Recipe.from_dict(entry)
        assert recipe.extra == {}, recipe.name
        assert entry["color"] == normalize_color(entry["color"])
        assert recipe.target_step_types, recipe.name
        # Each lab machine has its own numbers, and only those.
        assert set(recipe.machine_settings) == set(BUNDLED_NAMES)
        for name in BUNDLED_NAMES:
            assert set(recipe.machine_settings[name]) == {
                "power",
                "min_power",
                "cut_speed",
            }, recipe.name
        layers = [recipe.settings, *recipe.machine_settings.values()]
        for step_type in recipe.target_step_types:
            step_class = step_registry.get(step_type)
            assert step_class is not None, step_type
            for settings in layers:
                assert set(settings) <= set(step_class.recipe_keys())
        for settings in layers:
            for key in ("power", "min_power", "tab_power"):
                if key in settings:
                    assert 0.0 <= settings[key] <= 1.0, recipe.name
        for name in BUNDLED_NAMES:
            values = recipe.settings_for(SimpleNamespace(name=name))
            assert values["min_power"] <= values["power"], (recipe.name, name)
        assert recipe.material_uid in _bundled_material_uids(), recipe.name
        assert recipe.min_thickness_mm == recipe.max_thickness_mm


def test_shipped_numbers_differ_per_machine(context_initializer):
    """The two lab machines do not share speed and power."""
    for entry in _shipped()["recipes"]:
        per_machine = Recipe.from_dict(entry).machine_settings
        assert per_machine["ilab-614"] != per_machine["ilab-626"]


def test_engrave_recipes_fill_the_engrave_settings(context_initializer):
    """An engrave recipe sets every shared engrave setting."""
    engrave_keys = {
        "engrave_mode",
        "scan_angle",
        "depth_mode",
        "invert",
        "min_power_level",
        "max_power_level",
    }
    engraves = [
        Recipe.from_dict(entry)
        for entry in _shipped()["recipes"]
        if entry["target_step_types"] == ["EngraveStep"]
    ]
    assert engraves
    for recipe in engraves:
        assert set(recipe.settings) == engrave_keys, recipe.name


# The bundle as shipped at version 1, before per-machine values.
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


def test_install_synced_at_v1_takes_the_per_machine_set(tmp_path):
    """An existing install re-syncs: no copies, per-machine values."""
    v1 = tmp_path / "v1.yaml"
    v1.write_text(yaml.safe_dump({"version": 1, "recipes": _V1_RECIPES}))
    RecipeManager(tmp_path / "recipes", v1)

    recipe_mgr = RecipeManager(tmp_path / "recipes", SHIPPED_DEFAULTS)

    recipes = recipe_mgr.get_all_recipes()
    assert {r.uid for r in recipes} == {
        e["uid"] for e in _shipped()["recipes"]
    }
    assert all(r.builtin and r.modified_from is None for r in recipes)
    plywood_cut = recipe_mgr.recipes[_V1_RECIPES[0]["uid"]]
    assert plywood_cut.settings == {}
    assert set(plywood_cut.machine_settings) == set(BUNDLED_NAMES)


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

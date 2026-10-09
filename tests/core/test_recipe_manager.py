"""Tests for the RecipeManager class."""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from swiftcut.core.doc import Doc
from swiftcut.core.recipe import Recipe
from swiftcut.core.recipe_manager import (
    DEFAULTS_VERSION_FILE,
    RecipeManager,
    content_hash,
)
from swiftcut.core.stock import StockItem
from swiftcut.core.stock_asset import StockAsset
from swiftcut.machine.models.machine import Machine


class TestRecipeManager:
    """Test cases for the RecipeManager class."""

    @pytest.fixture
    def recipes_dir(self):
        """Creates a temporary directory for recipe files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def machine_a(self) -> Mock:
        mock = Mock(spec=Machine)
        mock.id = "machine-a"
        mock.name = "Machine A"
        head1 = Mock()
        head1.uid = "laser-1"
        mock.heads = [head1]
        return mock

    @pytest.fixture
    def machine_b(self) -> Mock:
        mock = Mock(spec=Machine)
        mock.id = "machine-b"
        mock.name = "Machine B"
        return mock

    @pytest.fixture
    def stock_item_factory(self):
        """Factory creating real, structured StockItem instances."""

        def _create(
            material_uid: str | None, thickness: float | None
        ) -> StockItem:
            doc = Doc()
            asset = StockAsset()
            asset.material_uid = material_uid
            asset.thickness = thickness
            doc.add_asset(asset)
            item = StockItem(stock_asset_uid=asset.uid)
            doc.add_child(item)
            return item

        return _create

    def test_manager_creation_and_load_empty(self, recipes_dir: Path):
        """Test creating a RecipeManager for an empty directory."""
        manager = RecipeManager(recipes_dir)
        assert not manager.recipes
        assert manager.get_all_recipes() == []

    def test_load_recipes(self, recipes_dir: Path):
        """Test loading recipes from files."""
        recipe1_data = {
            "uid": "recipe1",
            "name": "Recipe 1",
            "target_step_types": ["ContourStep"],
            "settings": {"power": 0.8},
        }
        recipe2_data = {"uid": "recipe2", "name": "Recipe 2"}
        with open(recipes_dir / "recipe1.yaml", "w") as f:
            yaml.dump(recipe1_data, f)
        with open(recipes_dir / "recipe2.yaml", "w") as f:
            yaml.dump(recipe2_data, f)

        manager = RecipeManager(recipes_dir)
        assert len(manager.recipes) == 2
        assert "recipe1" in manager.recipes
        recipe2 = manager.get_recipe_by_id("recipe2")
        assert recipe2 is not None
        assert recipe2.name == "Recipe 2"

    def test_load_invalid_recipe_file(self, recipes_dir: Path):
        """Test that the manager skips invalid recipe files."""
        with open(recipes_dir / "invalid.yaml", "w") as f:
            f.write("this is not yaml")

        manager = RecipeManager(recipes_dir)
        assert len(manager.recipes) == 0

    def test_save_recipe(self, recipes_dir: Path):
        """Test saving a new recipe to a file."""
        manager = RecipeManager(recipes_dir)
        recipe = Recipe(uid="new-recipe", name="New Recipe")

        manager.save_recipe(recipe)

        recipe_file = recipes_dir / "new-recipe.yaml"
        assert recipe_file.exists()

        with open(recipe_file, "r") as f:
            data = yaml.safe_load(f)
        assert data["name"] == "New Recipe"

    def test_save_load_transformer_dicts_round_trip(self, recipes_dir: Path):
        """transformer_dicts survive a save + reload through the manager."""
        manager = RecipeManager(recipes_dir)
        recipe = Recipe(
            uid="with-transformers",
            name="Transformer Recipe",
            transformer_dicts=[
                {
                    "name": "CropTransformer",
                    "enabled": True,
                    "recipe_apply": True,
                    "offset": 1.25,
                },
                {
                    "name": "Optimize",
                    "enabled": False,
                    "recipe_apply": False,
                },
            ],
        )

        manager.add_recipe(recipe)

        reloaded = RecipeManager(recipes_dir)
        restored = reloaded.get_recipe_by_id("with-transformers")
        assert restored is not None
        assert restored.transformer_dicts == recipe.transformer_dicts

    def test_save_load_color_round_trip(self, recipes_dir: Path):
        """The color survives a save + reload through the manager."""
        manager = RecipeManager(recipes_dir)
        manager.add_recipe(Recipe(uid="colored", color="#ff6600"))
        manager.add_recipe(Recipe(uid="plain"))

        with open(recipes_dir / "colored.yaml", "r") as f:
            assert yaml.safe_load(f)["color"] == "#ff6600"

        reloaded = RecipeManager(recipes_dir)
        colored = reloaded.get_recipe_by_id("colored")
        plain = reloaded.get_recipe_by_id("plain")
        assert colored is not None and plain is not None
        assert colored.color == "#ff6600"
        assert "color" not in colored.extra
        assert plain.color is None

    def test_add_recipe(self, recipes_dir: Path):
        """Test adding a recipe, which should also save it."""
        manager = RecipeManager(recipes_dir)
        recipe = Recipe(uid="added-recipe", name="Added Recipe")

        manager.add_recipe(recipe)

        assert "added-recipe" in manager.recipes
        assert (recipes_dir / "added-recipe.yaml").exists()

    def test_delete_recipe(self, recipes_dir: Path):
        """Test deleting a recipe and its corresponding file."""
        recipe_data = {"uid": "to-delete", "name": "To Delete"}
        recipe_file = recipes_dir / "to-delete.yaml"
        with open(recipe_file, "w") as f:
            yaml.dump(recipe_data, f)

        manager = RecipeManager(recipes_dir)
        assert "to-delete" in manager.recipes
        assert recipe_file.exists()

        manager.delete_recipe("to-delete")

        assert "to-delete" not in manager.recipes
        assert not recipe_file.exists()

    # --- find_recipes LOGIC TESTS ---

    @pytest.fixture
    def manager_with_recipes(
        self, recipes_dir: Path, machine_a: Mock
    ) -> RecipeManager:
        """Provides a manager pre-populated with a variety of recipes.

        All ContourStep-targeted recipes except the last, which targets
        EngraveStep.
        """
        manager = RecipeManager(recipes_dir)

        # 1. Most specific: Machine, Laser, Material, Thickness
        manager.add_recipe(
            Recipe(
                uid="machine-a-laser-1-walnut-3mm",
                name="Cut 3mm Walnut on Machine A with Laser 1",
                target_machine_id=machine_a.id,
                material_uid="walnut",
                min_thickness_mm=2.9,
                max_thickness_mm=3.1,
                target_step_types=["ContourStep"],
                settings={"power": 0.8, "selected_head_uid": "laser-1"},
            )
        )

        # 2. Machine, Material, Thickness
        manager.add_recipe(
            Recipe(
                uid="machine-a-walnut-3mm",
                name="Cut 3mm Walnut on Machine A",
                target_machine_id=machine_a.id,
                material_uid="walnut",
                min_thickness_mm=2.9,
                max_thickness_mm=3.1,
                target_step_types=["ContourStep"],
                settings={"power": 0.8},
            )
        )

        # 3. Material, Thickness
        manager.add_recipe(
            Recipe(
                uid="walnut-3mm-cut",
                name="Cut 3mm Walnut",
                material_uid="walnut",
                min_thickness_mm=2.9,
                max_thickness_mm=3.1,
                target_step_types=["ContourStep"],
                settings={"power": 0.9},
            )
        )

        # 4. Material, Any thickness
        manager.add_recipe(
            Recipe(
                uid="walnut-any-thickness",
                name="Cut Any Walnut",
                material_uid="walnut",
                target_step_types=["ContourStep"],
                settings={"power": 0.85},
            )
        )

        # 5. Generic ContourStep
        manager.add_recipe(
            Recipe(
                uid="generic-cut",
                name="Generic Cut",
                target_step_types=["ContourStep"],
                settings={"power": 1.0},
            )
        )

        # 6. EngraveStep-only (different step type)
        manager.add_recipe(
            Recipe(
                uid="generic-engrave",
                name="Generic Engrave",
                target_step_types=["EngraveStep"],
                settings={"power": 0.2},
            )
        )
        return manager

    def test_find_recipes_perfect_match(
        self,
        manager_with_recipes: RecipeManager,
        machine_a: Mock,
        stock_item_factory,
    ):
        """Test finding recipes with a perfect stock and machine match,
        checking sort order."""
        stock = stock_item_factory("walnut", 3.0)
        results = manager_with_recipes.find_recipes(
            [stock], machine=machine_a, step_type="ContourStep"
        )

        assert len(results) == 5
        # Specificity order: (machine, laser, material, thickness)
        assert results[0].uid == "machine-a-laser-1-walnut-3mm"  # (0,0,0,0)
        assert results[1].uid == "machine-a-walnut-3mm"  # (0,1,0,0)
        assert results[2].uid == "walnut-3mm-cut"  # (1,1,0,0)
        assert results[3].uid == "walnut-any-thickness"  # (1,1,0,1)
        assert results[4].uid == "generic-cut"  # (1,1,1,1)

    def test_find_recipes_different_machine(
        self,
        manager_with_recipes: RecipeManager,
        machine_b: Mock,
        stock_item_factory,
    ):
        """Test that machine-specific recipes are filtered out."""
        stock = stock_item_factory("walnut", 3.0)
        results = manager_with_recipes.find_recipes(
            [stock], machine=machine_b, step_type="ContourStep"
        )

        assert len(results) == 3
        assert "machine-a-walnut-3mm" not in [r.uid for r in results]
        assert "machine-a-laser-1-walnut-3mm" not in [r.uid for r in results]
        assert results[0].uid == "walnut-3mm-cut"
        assert results[1].uid == "walnut-any-thickness"
        assert results[2].uid == "generic-cut"

    def test_find_recipes_no_machine_provided(
        self, manager_with_recipes: RecipeManager, stock_item_factory
    ):
        """Test that machine-specific recipes are filtered out when no
        machine is provided."""
        stock = stock_item_factory("walnut", 3.0)
        results = manager_with_recipes.find_recipes(
            [stock], machine=None, step_type="ContourStep"
        )

        assert len(results) == 3
        assert "machine-a-walnut-3mm" not in [r.uid for r in results]
        assert results[0].uid == "walnut-3mm-cut"

    def test_find_recipes_material_only_match(
        self,
        manager_with_recipes: RecipeManager,
        machine_a: Mock,
        stock_item_factory,
    ):
        """Test finding recipes when only material matches."""
        stock = stock_item_factory("walnut", 10.0)  # Thickness mismatch
        results = manager_with_recipes.find_recipes(
            [stock], machine=machine_a, step_type="ContourStep"
        )

        assert len(results) == 2
        assert results[0].uid == "walnut-any-thickness"
        assert results[1].uid == "generic-cut"

    def test_find_recipes_thickness_only_match(
        self,
        manager_with_recipes: RecipeManager,
        machine_a: Mock,
        stock_item_factory,
    ):
        """Test finding recipes when only thickness matches."""
        stock = stock_item_factory("mdf", 3.0)  # Material mismatch
        results = manager_with_recipes.find_recipes(
            [stock], machine=machine_a, step_type="ContourStep"
        )

        assert len(results) == 1
        assert results[0].uid == "generic-cut"

    def test_find_recipes_no_match(
        self,
        manager_with_recipes: RecipeManager,
        machine_a: Mock,
        stock_item_factory,
    ):
        """Test finding recipes when nothing matches, only generic returns."""
        stock = stock_item_factory("mdf", 10.0)
        results = manager_with_recipes.find_recipes(
            [stock], machine=machine_a, step_type="ContourStep"
        )

        assert len(results) == 1
        assert results[0].uid == "generic-cut"

    def test_find_recipes_no_stock_provided(
        self, manager_with_recipes: RecipeManager, machine_a: Mock
    ):
        """Only generic recipes return when no stock is provided."""
        results = manager_with_recipes.find_recipes(
            [], machine=machine_a, step_type="ContourStep"
        )

        assert len(results) == 1
        assert results[0].uid == "generic-cut"

    def test_find_recipes_filters_by_step_type(
        self,
        manager_with_recipes: RecipeManager,
        machine_a: Mock,
        stock_item_factory,
    ):
        """Only recipes targeting the queried step type match."""
        stock = stock_item_factory("walnut", 3.0)
        results = manager_with_recipes.find_recipes(
            [stock], machine=machine_a, step_type="EngraveStep"
        )

        assert len(results) == 1
        assert results[0].uid == "generic-engrave"

    def test_find_recipes_multi_step_type_recipe(
        self,
        manager_with_recipes: RecipeManager,
        machine_a: Mock,
        stock_item_factory,
    ):
        """A recipe targeting multiple step types matches each of them."""
        stock = stock_item_factory("walnut", 3.0)
        manager_with_recipes.add_recipe(
            Recipe(
                uid="multi",
                name="Multi Step Type",
                target_step_types=["ContourStep", "EngraveStep"],
                settings={"power": 0.5},
            )
        )

        contour = manager_with_recipes.find_recipes(
            [stock], machine=machine_a, step_type="ContourStep"
        )
        engrave = manager_with_recipes.find_recipes(
            [stock], machine=machine_a, step_type="EngraveStep"
        )
        assert "multi" in [r.uid for r in contour]
        assert "multi" in [r.uid for r in engrave]

    def test_find_recipes_single_more_specific_than_multi(
        self,
        manager_with_recipes: RecipeManager,
        machine_a: Mock,
        stock_item_factory,
    ):
        """A single-target recipe outranks a multi-target one for sorting."""
        stock = stock_item_factory("walnut", 3.0)
        manager_with_recipes.add_recipe(
            Recipe(
                uid="multi",
                name="Multi Step Type",
                target_step_types=["ContourStep", "EngraveStep"],
                settings={"power": 0.5},
            )
        )

        results = manager_with_recipes.find_recipes(
            [stock], machine=machine_a, step_type="ContourStep"
        )
        uids = [r.uid for r in results]
        # generic-cut (single ContourStep) outranks multi (two step types),
        # both having otherwise-generic machine/material/thickness.
        assert uids.index("generic-cut") < uids.index("multi")


CUT = {
    "uid": "builtin-cut",
    "name": "Cut",
    "color": "#ff0000",
    "target_step_types": ["ContourStep"],
    "settings": {"power": 0.5, "cut_speed": 600},
}
ENGRAVE = {
    "uid": "builtin-engrave",
    "name": "Engrave",
    "color": "#0000ff",
    "target_step_types": ["EngraveStep"],
    "settings": {"power": 0.2, "cut_speed": 18000},
}


def _write_bundle(path: Path, version: int, recipes: list[dict]) -> Path:
    with open(path, "w") as f:
        yaml.safe_dump({"version": version, "recipes": recipes}, f)
    return path


def _edit_file(recipes_dir: Path, uid: str, **changes):
    """Edits a recipe file on disk, outside the manager."""
    path = recipes_dir / f"{uid}.yaml"
    data = yaml.safe_load(path.read_text())
    data.update(changes)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _snapshot(recipes_dir: Path) -> dict[str, tuple[int, bytes]]:
    """mtime and content of every file in the recipe directory."""
    return {
        p.name: (p.stat().st_mtime_ns, p.read_bytes())
        for p in recipes_dir.iterdir()
    }


class TestBuiltinSync:
    """Syncing the bundled default recipes into a user store."""

    @pytest.fixture
    def recipes_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "recipes"

    def test_fresh_store_gets_bundle(self, tmp_path, recipes_dir):
        """An empty store gets every bundled recipe as a built-in."""
        bundle = _write_bundle(tmp_path / "defaults.yaml", 1, [CUT, ENGRAVE])

        manager = RecipeManager(recipes_dir, bundle)

        assert set(manager.recipes) == {"builtin-cut", "builtin-engrave"}
        cut = manager.recipes["builtin-cut"]
        assert cut.builtin
        on_disk = (recipes_dir / "builtin-cut.yaml").read_text()
        assert cut.builtin_hash == content_hash(yaml.safe_load(on_disk))
        assert cut.color == "#ff0000"
        assert cut.settings == {"power": 0.5, "cut_speed": 600}
        assert (recipes_dir / DEFAULTS_VERSION_FILE).read_text() == "1\n"

    def test_newer_bundle_replaces_builtins(self, tmp_path, recipes_dir):
        """v2 over v1: built-ins follow the bundle, user recipes stay."""
        RecipeManager(
            recipes_dir,
            _write_bundle(tmp_path / "v1.yaml", 1, [CUT, ENGRAVE]),
        ).add_recipe(Recipe(uid="mine", name="Mine", settings={"power": 1}))
        user_file = (recipes_dir / "mine.yaml").read_bytes()
        new_cut = {**CUT, "name": "Cut v2", "settings": {"power": 0.6}}
        frame = {"uid": "builtin-frame", "name": "Frame"}

        manager = RecipeManager(
            recipes_dir,
            _write_bundle(tmp_path / "v2.yaml", 2, [new_cut, frame]),
        )

        assert set(manager.recipes) == {
            "builtin-cut",
            "builtin-frame",
            "mine",
        }
        cut = manager.recipes["builtin-cut"]
        assert cut.builtin
        assert cut.name == "Cut v2"
        assert cut.settings == {"power": 0.6}
        assert manager.recipes["builtin-frame"].builtin
        assert not manager.recipes["mine"].builtin
        assert (recipes_dir / "mine.yaml").read_bytes() == user_file
        assert (recipes_dir / DEFAULTS_VERSION_FILE).read_text() == "2\n"

    def test_edited_builtin_is_kept_as_modified_copy(
        self, tmp_path, recipes_dir
    ):
        """An edited built-in survives as a user copy beside the fresh one."""
        RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v1.yaml", 1, [CUT])
        )
        _edit_file(recipes_dir, "builtin-cut", settings={"power": 0.9})

        manager = RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v2.yaml", 2, [CUT])
        )

        fresh = manager.recipes["builtin-cut"]
        assert fresh.builtin
        assert fresh.settings == CUT["settings"]
        (kept,) = [
            r for r in manager.recipes.values() if r.uid != "builtin-cut"
        ]
        assert not kept.builtin
        assert kept.builtin_hash is None
        assert kept.modified_from == "builtin-cut"
        assert kept.name == "Cut (modified)"
        assert kept.settings == {"power": 0.9}
        assert kept.color == "#ff0000"
        assert (recipes_dir / f"{kept.uid}.yaml").exists()

    def test_removed_builtin_disappears_unless_edited(
        self, tmp_path, recipes_dir
    ):
        """A built-in dropped from the bundle goes; an edited one is kept."""
        RecipeManager(
            recipes_dir,
            _write_bundle(tmp_path / "v1.yaml", 1, [CUT, ENGRAVE]),
        )
        _edit_file(recipes_dir, "builtin-engrave", description="mine now")

        manager = RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v2.yaml", 2, [])
        )

        (kept,) = manager.get_all_recipes()
        assert kept.name == "Engrave (modified)"
        assert kept.modified_from == "builtin-engrave"
        assert kept.description == "mine now"
        assert not kept.builtin
        assert not (recipes_dir / "builtin-cut.yaml").exists()
        assert not (recipes_dir / "builtin-engrave.yaml").exists()

    def test_unlocked_builtin_is_kept_as_modified_copy(
        self, tmp_path, recipes_dir
    ):
        """A user recipe with a bundled uid is copied, not overwritten."""
        RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v1.yaml", 1, [CUT])
        )
        _edit_file(recipes_dir, "builtin-cut", builtin=False, name="Mine")

        manager = RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v2.yaml", 2, [CUT])
        )

        assert manager.recipes["builtin-cut"].builtin
        assert manager.recipes["builtin-cut"].name == "Cut"
        (kept,) = [
            r for r in manager.recipes.values() if r.uid != "builtin-cut"
        ]
        assert kept.name == "Mine (modified)"
        assert kept.modified_from == "builtin-cut"
        assert not kept.builtin

    def test_schema_change_does_not_mark_builtins_modified(
        self, tmp_path, recipes_dir, monkeypatch
    ):
        """An untouched built-in stays unedited when Recipe gains a field."""
        RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v1.yaml", 1, [CUT])
        )
        to_dict = Recipe.to_dict
        monkeypatch.setattr(
            Recipe, "to_dict", lambda self: {**to_dict(self), "new": 0}
        )

        manager = RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v2.yaml", 2, [CUT])
        )

        assert set(manager.recipes) == {"builtin-cut"}

    def test_same_version_changes_nothing(self, tmp_path, recipes_dir):
        """A bundle at the recorded version leaves every file alone."""
        RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v1.yaml", 1, [CUT])
        )
        _edit_file(recipes_dir, "builtin-cut", settings={"power": 0.9})
        before = _snapshot(recipes_dir)

        changed = {**CUT, "name": "Changed"}
        manager = RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v1b.yaml", 1, [changed])
        )

        assert _snapshot(recipes_dir) == before
        assert manager.recipes["builtin-cut"].name == "Cut"

    def test_older_bundle_changes_nothing(self, tmp_path, recipes_dir):
        """A bundle older than the recorded version changes nothing."""
        RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v2.yaml", 2, [CUT])
        )
        before = _snapshot(recipes_dir)

        RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v1.yaml", 1, [ENGRAVE])
        )

        assert _snapshot(recipes_dir) == before

    def test_sync_is_idempotent(self, tmp_path, recipes_dir):
        """Unedited built-ins are not copied, and a rerun is a no-op."""
        RecipeManager(
            recipes_dir,
            _write_bundle(tmp_path / "v1.yaml", 1, [CUT, ENGRAVE]),
        )
        v2 = _write_bundle(tmp_path / "v2.yaml", 2, [CUT, ENGRAVE])
        RecipeManager(recipes_dir, v2)
        before = _snapshot(recipes_dir)

        manager = RecipeManager(recipes_dir, v2)

        assert _snapshot(recipes_dir) == before
        assert set(manager.recipes) == {"builtin-cut", "builtin-engrave"}

    def test_no_defaults_file_syncs_nothing(self, tmp_path, recipes_dir):
        """Without a defaults file nothing is seeded or recorded."""
        manager = RecipeManager(recipes_dir)

        assert manager.recipes == {}
        assert list(recipes_dir.iterdir()) == []

    def test_unreadable_version_file_counts_as_unsynced(
        self, tmp_path, recipes_dir
    ):
        """A damaged version file is treated like a missing one."""
        RecipeManager(recipes_dir).add_recipe(Recipe(uid="mine"))
        (recipes_dir / DEFAULTS_VERSION_FILE).write_text("garbage")

        manager = RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v1.yaml", 1, [CUT])
        )

        assert set(manager.recipes) == {"mine", "builtin-cut"}
        assert (recipes_dir / DEFAULTS_VERSION_FILE).read_text() == "1\n"

    def test_broken_bundle_is_logged(self, tmp_path, recipes_dir):
        """A defaults file without a version does not stop loading."""
        RecipeManager(recipes_dir).add_recipe(Recipe(uid="mine"))
        bundle = tmp_path / "defaults.yaml"
        bundle.write_text("recipes: []\n")

        manager = RecipeManager(recipes_dir, bundle)

        assert set(manager.recipes) == {"mine"}

    def test_duplicate_of_modified_copy_points_nowhere(
        self, tmp_path, recipes_dir
    ):
        """A duplicate is not marked as made from a built-in."""
        manager = RecipeManager(recipes_dir)
        kept = Recipe(name="Cut (modified)", modified_from="builtin-cut")
        manager.add_recipe(kept)

        assert manager.duplicate_recipe(kept).modified_from is None

    def test_duplicate_makes_editable_copy(self, tmp_path, recipes_dir):
        """A duplicate of a built-in is a separate user recipe."""
        manager = RecipeManager(
            recipes_dir, _write_bundle(tmp_path / "v1.yaml", 1, [CUT])
        )
        builtin = manager.recipes["builtin-cut"]

        dup = manager.duplicate_recipe(builtin)
        dup.settings["power"] = 0.1

        assert dup.uid != builtin.uid
        assert dup.name == "Cut (copy)"
        assert not dup.builtin
        assert dup.builtin_hash is None
        assert dup.color == builtin.color
        assert builtin.settings["power"] == 0.5
        reloaded = RecipeManager(recipes_dir)
        assert not reloaded.recipes[dup.uid].builtin
        assert reloaded.recipes["builtin-cut"].builtin


class TestMaterialRecipes:
    """The materials recipes are made for, and their recipe per step."""

    @staticmethod
    def _recipe(uid, material, thickness, step_type, **kwargs) -> Recipe:
        return Recipe(
            uid=uid,
            name=uid,
            material_uid=material,
            min_thickness_mm=thickness,
            max_thickness_mm=thickness,
            target_step_types=[step_type],
            **kwargs,
        )

    @pytest.fixture
    def manager(self, tmp_path) -> RecipeManager:
        manager = RecipeManager(tmp_path / "recipes")
        for recipe in (
            self._recipe("mdf-cut", "mdf", 3.0, "ContourStep"),
            self._recipe("mdf-engrave", "mdf", 3.0, "EngraveStep"),
            self._recipe("mdf-6-cut", "mdf", 6.0, "ContourStep"),
            self._recipe("acrylic-cut", "acrylic", 3.0, "ContourStep"),
            Recipe(
                uid="range",
                material_uid="plywood",
                min_thickness_mm=3.0,
                max_thickness_mm=6.0,
            ),
            Recipe(uid="generic", name="Generic"),
        ):
            manager.add_recipe(recipe)
        return manager

    def test_choices_are_distinct_exact_pairs_sorted(self, manager):
        assert manager.material_choices() == [
            ("acrylic", 3.0),
            ("mdf", 3.0),
            ("mdf", 6.0),
        ]

    def test_finds_the_recipe_per_step_type(self, manager):
        assert (
            manager.find_material_recipe("mdf", 3.0, None, "ContourStep").uid
            == "mdf-cut"
        )
        assert (
            manager.find_material_recipe("mdf", 3.0, None, "EngraveStep").uid
            == "mdf-engrave"
        )
        assert (
            manager.find_material_recipe("mdf", 6.0, None, "ContourStep").uid
            == "mdf-6-cut"
        )

    def test_no_recipe_for_the_material_and_step(self, manager):
        assert (
            manager.find_material_recipe("mdf", 6.0, None, "EngraveStep")
            is None
        )
        assert (
            manager.find_material_recipe("cork", 3.0, None, "ContourStep")
            is None
        )

    def test_a_recipe_for_the_machine_wins(self, manager, machine_b):
        manager.add_recipe(
            self._recipe(
                "mdf-cut-b",
                "mdf",
                3.0,
                "ContourStep",
                target_machine_id="machine-b",
            )
        )

        assert (
            manager.find_material_recipe(
                "mdf", 3.0, machine_b, "ContourStep"
            ).uid
            == "mdf-cut-b"
        )
        assert (
            manager.find_material_recipe("mdf", 3.0, None, "ContourStep").uid
            == "mdf-cut"
        )

    def test_a_user_recipe_beats_a_builtin_one_as_specific(self, manager):
        # The built-in sorts first by name; the user's recipe wins.
        shipped = self._recipe(
            "mdf-cut-shipped", "mdf", 3.0, "ContourStep", builtin=True
        )
        shipped.name = "A shipped MDF cut"
        manager.add_recipe(shipped)
        manager.recipes["mdf-cut"].name = "My MDF cut"

        assert (
            manager.find_material_recipe("mdf", 3.0, None, "ContourStep").uid
            == "mdf-cut"
        )

    def test_choices_leave_out_recipes_for_another_machine(
        self, manager, machine_b
    ):
        manager.add_recipe(
            self._recipe(
                "cork-cut-b",
                "cork",
                3.0,
                "ContourStep",
                target_machine_id="machine-b",
            )
        )
        other = Mock(spec=Machine)
        other.id = "machine-c"
        other.name = "Machine C"

        assert ("cork", 3.0) in manager.material_choices(machine_b)
        assert ("cork", 3.0) not in manager.material_choices(other)
        assert ("cork", 3.0) not in manager.material_choices(None)
        assert manager.material_choices(other) == [
            ("acrylic", 3.0),
            ("mdf", 3.0),
            ("mdf", 6.0),
        ]

    @pytest.fixture
    def machine_b(self) -> Mock:
        mock = Mock(spec=Machine)
        mock.id = "machine-b"
        mock.name = "Machine B"
        return mock


def test_edited_machine_settings_are_kept_as_modified_copy(tmp_path):
    """Per-machine values edited on disk count as an edit at a bump."""
    cut = {**CUT, "machine_settings": {"ilab-614": {"power": 0.6}}}
    recipes_dir = tmp_path / "recipes"
    RecipeManager(recipes_dir, _write_bundle(tmp_path / "v1.yaml", 1, [cut]))
    _edit_file(
        recipes_dir, "builtin-cut", machine_settings={"ilab-614": {"power": 1}}
    )

    manager = RecipeManager(
        recipes_dir, _write_bundle(tmp_path / "v2.yaml", 2, [cut])
    )

    (kept,) = [r for r in manager.recipes.values() if not r.builtin]
    assert kept.name == "Cut (modified)"
    assert kept.machine_settings == {"ilab-614": {"power": 1}}
    assert manager.recipes["builtin-cut"].machine_settings == {
        "ilab-614": {"power": 0.6}
    }

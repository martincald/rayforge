import copy
import hashlib
import logging
import uuid
from gettext import gettext as _
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml

from .recipe import Recipe

if TYPE_CHECKING:
    from ..machine.models.machine import Machine
    from .stock import StockItem

logger = logging.getLogger(__name__)

# Holds the version of the bundled defaults a recipe directory was last
# synced with. load() only reads "*.yaml", so it never sees this file.
DEFAULTS_VERSION_FILE = ".defaults-version"

# Built-in bookkeeping, left out of a recipe's content hash.
_BUILTIN_KEYS = ("builtin", "builtin_hash", "modified_from")

# The step class each "step" of the lab's authoring format stands for,
# by the step's ASSEMBLER_NAME. Hardcoded because the step registry can
# be empty when the bundle is synced; tests check it against the steps.
_BUNDLE_STEP_TYPES = {"contour": "ContourStep", "raster": "EngraveStep"}


def content_hash(data: dict) -> str:
    """A hash of a recipe's data, without its built-in bookkeeping."""
    data = {k: v for k, v in data.items() if k not in _BUILTIN_KEYS}
    text = yaml.safe_dump(data, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bundle_recipe_dicts(bundle: dict) -> list[dict]:
    """
    The recipes of a bundled defaults file, as Recipe dicts.

    A bundle with an ``operations`` key is in the lab's authoring
    format: speeds in mm/s, powers in percent, one value pair per
    machine. This is the ONE place those become the model's mm/min and
    0..1. The minimum power is written equal to the power on purpose:
    a step's min_power only follows its power until set explicitly.
    Any other bundle holds Recipe dicts already and is returned as is.
    """
    if "operations" not in bundle:
        return bundle.get("recipes") or []
    result = []
    for entry in bundle.get("recipes") or []:
        step = bundle["operations"][entry["operation"]]["step"]
        thickness = entry["thickness_mm"]
        if thickness is not None:
            thickness = float(thickness)
        machine_settings = {
            name: {
                "power": values["power_pct"] / 100,
                "min_power": values["power_pct"] / 100,
                "cut_speed": round(values["speed_mm_s"] * 60),
            }
            for name, values in entry["machines"].items()
        }
        result.append(
            {
                "uid": entry["id"],
                "name": entry["name"],
                "description": entry.get("notes") or "",
                "color": entry["color"],
                "target_step_types": [_BUNDLE_STEP_TYPES[step]],
                "material_uid": entry["material"].lower(),
                "min_thickness_mm": thickness,
                "max_thickness_mm": thickness,
                "settings": {},
                "machine_settings": machine_settings,
            }
        )
    return result


class RecipeManager:
    """
    Manages loading, saving, and querying Recipe objects from a directory.

    When a defaults file is given, the built-in recipes in the directory
    are synced with it before loading (see :meth:`sync_builtins`).
    """

    def __init__(self, base_dir: Path, defaults_file: Path | None = None):
        self.base_dir = base_dir
        self.recipes: dict[str, Recipe] = {}
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if defaults_file is not None:
            try:
                self.sync_builtins(defaults_file)
            except Exception as e:  # noqa: BLE001 - keep loading recipes
                logger.error(f"Failed to sync built-in recipes: {e}")
        self.load()

    def sync_builtins(self, defaults_file: Path):
        """
        Replaces the built-in recipes with the bundled set, if its
        version is newer than the one this directory was synced with.

        A built-in whose content no longer matches its hash was edited
        outside the app; it is kept as a user copy marked modified.
        Recipes the user created are not touched.
        """
        with open(defaults_file, "r", encoding="utf-8") as f:
            bundle = yaml.safe_load(f)
        version = int(bundle["version"])
        version_file = self.base_dir / DEFAULTS_VERSION_FILE
        try:
            synced = int(version_file.read_text())
        except (OSError, ValueError):  # missing or damaged: never synced
            synced = 0
        if version <= synced:
            return

        # Translate first: a malformed bundle must raise before the
        # store or the version file is touched.
        new_recipes = [
            Recipe.from_dict(data) for data in bundle_recipe_dicts(bundle)
        ]
        self.load()
        old_builtins = [r for r in self.recipes.values() if r.builtin]
        for recipe in old_builtins:
            # Hash the file, not the loaded recipe, so that a change to
            # the Recipe schema does not look like an edit.
            with open(self.filename_from_id(recipe.uid), "r") as f:
                on_disk = yaml.safe_load(f)
            if content_hash(on_disk) != recipe.builtin_hash:
                self._keep_modified_copy(recipe)
        for recipe in old_builtins:
            self.delete_recipe(recipe.uid)
        for recipe in new_recipes:
            if recipe.uid in self.recipes:
                # A user recipe with a bundled uid, e.g. a built-in
                # unlocked by hand: keep it rather than overwrite it.
                self._keep_modified_copy(self.recipes[recipe.uid])
            recipe.builtin = True
            recipe.builtin_hash = content_hash(recipe.to_dict())
            self.add_recipe(recipe)
        version_file.write_text(f"{version}\n")
        logger.info(f"Synced built-in recipes to version {version}.")

    def _keep_modified_copy(self, recipe: Recipe):
        """Adds a user copy of an edited built-in, marked modified."""
        kept = self._user_copy(recipe, _("{name} (modified)"))
        kept.modified_from = recipe.uid
        self.add_recipe(kept)

    @staticmethod
    def _user_copy(recipe: Recipe, name_format: str) -> Recipe:
        """A copy of a recipe with a new uid that is not a built-in."""
        result = copy.deepcopy(recipe)
        result.uid = str(uuid.uuid4())
        result.name = name_format.format(name=recipe.name)
        result.builtin = False
        result.builtin_hash = None
        result.modified_from = None
        return result

    def duplicate_recipe(self, recipe: Recipe) -> Recipe:
        """Adds an editable copy of a recipe and returns it."""
        result = self._user_copy(recipe, _("{name} (copy)"))
        self.add_recipe(result)
        return result

    def filename_from_id(self, recipe_id: str) -> Path:
        """Generates a consistent filename for a given recipe UID."""
        return self.base_dir / f"{recipe_id}.yaml"

    def load(self):
        """Loads all recipes from the base directory."""
        self.recipes.clear()
        for file in self.base_dir.glob("*.yaml"):
            try:
                with open(file, "r") as f:
                    data = yaml.safe_load(f)
                if not data:
                    logger.warning(
                        f"Skipping empty or invalid recipe {file.name}"
                    )
                    continue

                recipe = Recipe.from_dict(data)
                # Ensure UID from file content is used, but fallback
                # to filename
                recipe.uid = data.get("uid", file.stem)
                self.recipes[recipe.uid] = recipe

            except Exception as e:  # noqa: BLE001 - arbitrary user YAML file
                logger.error(f"Error loading recipe file {file.name}: {e}")
        logger.info(f"Loaded {len(self.recipes)} recipes.")

    def save_recipe(self, recipe: Recipe):
        """Saves a single recipe to a YAML file."""
        logger.debug(f"Saving recipe {recipe.name} ({recipe.uid})")
        recipe_file = self.filename_from_id(recipe.uid)
        try:
            with open(recipe_file, "w") as f:
                data = recipe.to_dict()
                yaml.safe_dump(data, f, sort_keys=False)
        except (OSError, yaml.YAMLError) as e:
            logger.error(f"Failed to save recipe {recipe.uid}: {e}")

    def add_recipe(self, recipe: Recipe):
        """Adds a recipe to the manager and saves it."""
        if recipe.uid in self.recipes:
            logger.warning(
                f"Recipe with UID {recipe.uid} already exists. Overwriting."
            )
        self.recipes[recipe.uid] = recipe
        self.save_recipe(recipe)

    def delete_recipe(self, recipe_uid: str):
        """Deletes a recipe from memory and removes its file."""
        if recipe_uid in self.recipes:
            del self.recipes[recipe_uid]
            recipe_file = self.filename_from_id(recipe_uid)
            if recipe_file.exists():
                try:
                    recipe_file.unlink()
                    logger.info(f"Deleted recipe file: {recipe_file}")
                except OSError as e:
                    logger.error(
                        f"Failed to delete recipe file {recipe_file}: {e}"
                    )

    def get_recipe_by_id(self, recipe_id: str) -> Recipe | None:
        """Retrieves a recipe by its unique identifier."""
        return self.recipes.get(recipe_id)

    def get_all_recipes(self) -> list[Recipe]:
        """Returns a list of all loaded recipes."""
        return list(self.recipes.values())

    def find_recipes(
        self,
        stock_items: list["StockItem"],
        machine: Optional["Machine"] = None,
        step_type: str | None = None,
    ) -> list[Recipe]:
        """
        Finds matching recipes, sorted from most specific to least specific.

        Args:
            stock_items: A list of StockItems. If empty, only generic recipes
                         (without material/thickness constraints) are returned.
            machine: An optional machine context to match against. Can be None.
            step_type: An optional step class name (as registered in
                       ``step_registry``) to match
                       :attr:`Recipe.target_step_types` against.

        Returns:
            A list of Recipe objects, sorted by relevance.
        """
        # 1. Filter the recipes using the `matches` method
        candidates = [
            r
            for r in self.get_all_recipes()
            if r.matches(stock_items, machine, step_type=step_type)
        ]

        # 2. Sort candidates based on their specificity score and name
        candidates.sort(
            key=lambda r: (r.get_specificity_score(), r.name.lower())
        )

        return candidates

    def material_choices(
        self, machine: Optional["Machine"] = None
    ) -> list[tuple[str, float]]:
        """
        The materials recipes are made for, as distinct
        (material uid, thickness in mm) pairs, sorted. Only recipes for
        one exact thickness count; a thickness range is not a choice.
        A recipe made for another machine than the given one does not
        count.
        """
        pairs = {
            (r.material_uid, r.min_thickness_mm)
            for r in self.recipes.values()
            if r.material_uid
            and r.min_thickness_mm is not None
            and r.min_thickness_mm == r.max_thickness_mm
            and (
                not r.target_machine_id
                or (machine is not None and machine.id == r.target_machine_id)
            )
        }
        return sorted(pairs)

    def find_material_recipe(
        self,
        material_uid: str,
        thickness_mm: float,
        machine: Optional["Machine"] = None,
        step_type: str | None = None,
    ) -> Recipe | None:
        """
        The most specific recipe made for a material and thickness, for
        a machine and step type, or None. On equal specificity a user's
        recipe wins over a built-in one.
        """
        candidates = [
            r
            for r in self.get_all_recipes()
            if r.matches_material(
                material_uid, thickness_mm, machine, step_type=step_type
            )
        ]
        candidates.sort(
            key=lambda r: (
                r.get_specificity_score(),
                r.builtin,
                r.name.lower(),
            )
        )
        return candidates[0] if candidates else None

    def is_material_in_use(self, material_uid: str) -> bool:
        """
        Checks if any recipe in the library references the given material UID.
        """
        for recipe in self.recipes.values():
            if recipe.material_uid == material_uid:
                return True
        return False

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


def content_hash(data: dict) -> str:
    """A hash of a recipe's data, without its built-in bookkeeping."""
    data = {k: v for k, v in data.items() if k not in _BUILTIN_KEYS}
    text = yaml.safe_dump(data, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
        with open(defaults_file, "r") as f:
            bundle = yaml.safe_load(f)
        version = int(bundle["version"])
        version_file = self.base_dir / DEFAULTS_VERSION_FILE
        try:
            synced = int(version_file.read_text())
        except (OSError, ValueError):  # missing or damaged: never synced
            synced = 0
        if version <= synced:
            return

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
        for data in bundle.get("recipes") or []:
            recipe = Recipe.from_dict(data)
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

    def is_material_in_use(self, material_uid: str) -> bool:
        """
        Checks if any recipe in the library references the given material UID.
        """
        for recipe in self.recipes.values():
            if recipe.material_uid == material_uid:
                return True
        return False

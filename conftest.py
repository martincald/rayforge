import sys
from pathlib import Path

import pytest

_root_dir = Path(__file__).parent
_builtin_addons = _root_dir / "swiftcut" / "builtin_addons"
_private_addons = _root_dir / "swiftcut" / "private_addons"

for _addon_dir in [_builtin_addons, _private_addons]:
    if not _addon_dir.exists():
        continue
    for _addon_path in _addon_dir.iterdir():
        if _addon_path.is_dir():
            _resolved = _addon_path.resolve()
            if str(_resolved) not in sys.path:
                sys.path.insert(0, str(_resolved))


@pytest.fixture(autouse=True)
def no_builtin_recipe_sync(monkeypatch):
    """
    Keeps the context's RecipeManager from syncing the bundled recipes.

    USER_RECIPES_DIR is the shared test config directory and no fixture
    redirects it, so synced built-ins would be picked by every test that
    adds a step. Tests of the sync pass a defaults file themselves.

    It lives here so that it also covers the addon test paths. config is
    imported in the fixture, not at the top of this file, so that it is
    not imported before tests/conftest.py sets RAYFORGE_CONFIG_DIR.
    """
    from swiftcut import config

    monkeypatch.setattr(config, "BUILTIN_RECIPES_FILE", None)

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_config_dir, user_log_dir

logger = logging.getLogger(__name__)

# Marker file written into the "swiftcut" config dir once a legacy
# "rayforge" config dir has been imported from (automatically or via
# the "Import settings from Rayforge" action), so that either path
# only ever happens once. Its presence - not merely the existence of
# the swiftcut dir - is what makes both `_migrate_legacy_config_dir`
# and `should_offer_legacy_import` idempotent: a pre-migration build
# could have already created the swiftcut dir without ever migrating
# anything into it, so "swiftcut dir exists" alone is not a reliable
# signal that a migration was ever attempted.
MIGRATION_MARKER_FILENAME = ".migrated-from-rayforge"


def _migration_marker_path(new_dir: Path) -> Path:
    return new_dir / MIGRATION_MARKER_FILENAME


def _write_migration_marker(
    new_dir: Path, old_dir: Path, imported: list[str]
) -> None:
    """Records that a legacy-config import happened, from where, when,
    and what was actually copied, both to suppress future imports and
    as an audit trail if the wrong machine profile shows up."""
    lines = [
        f"source: {old_dir}",
        f"migrated_at: {datetime.now(timezone.utc).isoformat()}",
        "imported:",
    ]
    lines += [f"  - {name}" for name in imported] or ["  (nothing new)"]
    _migration_marker_path(new_dir).write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _migrate_legacy_config_dir(old_dir: Path, new_dir: Path) -> None:
    """
    Copy a pre-rebrand "rayforge" config directory into the new
    "swiftcut" location on first run.

    The old directory is only ever read from - it is never moved,
    deleted, or modified, since it may hold the user's live machine
    profile. This is a no-op (and logs nothing) if a migration marker
    is already present in `new_dir`, if there is no legacy directory to
    migrate from, or if `new_dir` already exists: an existing `new_dir`
    without a marker means it was populated some other way (e.g. a
    pre-migration build already created it), and a wholesale copy over
    it could silently overwrite content already there. That case is
    instead left to the explicit, user-triggered "Import settings from
    Rayforge" action (see `should_offer_legacy_import` /
    `import_legacy_config`). This makes it safe to call on every
    startup.
    """
    if _migration_marker_path(new_dir).exists() or not old_dir.is_dir():
        return
    if new_dir.exists():
        return
    shutil.copytree(old_dir, new_dir)
    _write_migration_marker(new_dir, old_dir, imported=["(full copy)"])
    logger.info(f"Migrated config from {old_dir} to {new_dir}")


def _copy_missing(src: Path, dst: Path) -> list[str]:
    """
    Recursively copies entries from `src` into `dst`, skipping any
    entry that already exists at the destination so nothing under
    `dst` - most importantly the machine profile the user is currently
    using - is ever overwritten. `src` is only ever read. Returns the
    `src`-relative paths of everything that was actually copied.
    """
    copied: list[str] = []
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        target = dst / entry.name
        if target.exists():
            if entry.is_dir() and target.is_dir():
                copied += [
                    f"{entry.name}/{p}" for p in _copy_missing(entry, target)
                ]
            continue
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)
        copied.append(entry.name)
    return copied


def should_offer_legacy_import(old_dir: Path, new_dir: Path) -> bool:
    """
    Whether the one-time "Import settings from Rayforge" action should
    be offered: a legacy "rayforge" config dir exists, the "swiftcut"
    dir is already populated (so the automatic startup migration in
    `_migrate_legacy_config_dir` skipped it as unsafe), and no import
    has already happened.
    """
    return (
        old_dir.is_dir()
        and new_dir.exists()
        and not _migration_marker_path(new_dir).exists()
    )


def import_legacy_config(old_dir: Path, new_dir: Path) -> list[str]:
    """
    One-time, copy-only import of a legacy "rayforge" config dir's
    contents into an already-populated "swiftcut" config dir.

    Meant to be triggered explicitly by the user (the "Import settings
    from Rayforge" action in Device Settings) for the case where
    `should_offer_legacy_import` returns True and an automatic copy
    would be unsafe. Never overwrites anything already present under
    `new_dir` - any entry that would collide by name, most importantly
    the machine profile the user is currently using, is left alone so
    nothing is clobbered without the user's say-so. `old_dir` is only
    ever read from, never modified or deleted. Writes the migration
    marker afterwards so this only ever runs once; call
    `should_offer_legacy_import` first to check.

    Returns the `old_dir`-relative paths of everything actually
    copied (an empty list if everything already existed in `new_dir`).
    """
    copied = _copy_missing(old_dir, new_dir)
    _write_migration_marker(new_dir, old_dir, imported=copied)
    logger.info(f"Imported legacy config from {old_dir}: {copied}")
    return copied


def _get_config_dir() -> Path:
    """Get the config directory, respecting RAYFORGE_CONFIG_DIR env var."""
    env_config = os.environ.get("RAYFORGE_CONFIG_DIR")
    if env_config:
        return Path(env_config)
    new_dir = Path(user_config_dir("swiftcut"))
    _migrate_legacy_config_dir(Path(user_config_dir("rayforge")), new_dir)
    return new_dir


CONFIG_DIR = _get_config_dir()
logger.info(f"Config dir is {CONFIG_DIR}")

# The pre-rebrand config dir, kept around (read-only) so the "Import
# settings from Rayforge" action in Device Settings can offer to copy
# from it even when the automatic startup migration above skipped it.
LEGACY_CONFIG_DIR = Path(user_config_dir("rayforge"))

MACHINE_DIR = CONFIG_DIR / "machines"
logger.debug(f"MACHINE_DIR is {MACHINE_DIR}")
MACHINE_DIR.mkdir(parents=True, exist_ok=True)

DIALECT_DIR = CONFIG_DIR / "dialects"
logger.debug(f"DIALECT_DIR is {DIALECT_DIR}")
DIALECT_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = CONFIG_DIR / "config.yaml"
ADDONS_DIR = CONFIG_DIR / "addons"
LICENSES_DIR = CONFIG_DIR / "licenses"
ADDON_DATA_DIR = CONFIG_DIR / "addon_data"
AI_CONFIG_FILE = CONFIG_DIR / "ai.yaml"


def get_addon_data_dir(addon_name: str) -> Path:
    """
    Get the data directory for an addon.

    Args:
        addon_name: The canonical name of the addon.

    Returns:
        Path to the addon's data directory.
    """
    path = ADDON_DATA_DIR / addon_name
    path.mkdir(parents=True, exist_ok=True)
    return path


BUILTIN_ADDONS_DIR = Path(__file__).parent / "builtin_addons"
PRIVATE_ADDONS_DIR = Path(__file__).parent / "private_addons"

USER_DEVICES_DIR = CONFIG_DIR / "devices"
BUILTIN_DEVICES_DIR = Path(__file__).parent / "resources" / "devices"

# State files (like logs)
LOG_DIR = Path(user_log_dir("swiftcut"))
logger.info(f"Log dir is {LOG_DIR}")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Material directories
USER_MATERIALS_DIR = CONFIG_DIR / "materials"
USER_RECIPES_DIR = CONFIG_DIR / "recipes"
USER_COLOR_PRESETS_DIR = CONFIG_DIR / "color_presets"

ADDON_REGISTRY_URL = (
    "https://raw.githubusercontent.com/barebaric/rayforge-registry/"
    "main/registry.yaml"
)

PATREON_CLIENT_ID = (
    "nx7wTdFBp5Cc3NtMU4xYK7mkzlaqLg5hXgLlY6WAtAMq62je5WDE_x8ewrrCvJ34"
)


def getflag(name, default=False):
    default = "true" if default else "false"
    return os.environ.get(name, default).lower() in ("true", "1")

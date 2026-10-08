"""Tests for the first-run config-dir migration from "rayforge" to
"swiftcut" (see rayforge/config.py, `_migrate_legacy_config_dir`).

These tests call the functions directly with tmp_path-backed
directories - they never touch the real OS config dir, and they never
import swiftcut.config (which has import-time side effects driven by
the RAYFORGE_CONFIG_DIR env var that tests/conftest.py already sets).
"""

from pathlib import Path

from swiftcut.config import (
    MIGRATION_MARKER_FILENAME,
    _migrate_legacy_config_dir,
)
from swiftcut.core.config import Config


def test_migrates_when_old_dir_exists_and_new_dir_does_not(tmp_path):
    old_dir = tmp_path / "rayforge"
    new_dir = tmp_path / "swiftcut"
    old_dir.mkdir()
    (old_dir / "config.yaml").write_text("machine: foo\n", encoding="utf-8")
    machines_dir = old_dir / "machines"
    machines_dir.mkdir()
    (machines_dir / "laser.yaml").write_text("id: laser\n", encoding="utf-8")

    _migrate_legacy_config_dir(old_dir, new_dir)

    assert new_dir.is_dir()
    assert (new_dir / "config.yaml").read_text(
        encoding="utf-8"
    ) == "machine: foo\n"
    assert (new_dir / "machines" / "laser.yaml").read_text(
        encoding="utf-8"
    ) == "id: laser\n"

    # The source directory must be left completely untouched.
    assert old_dir.is_dir()
    assert (old_dir / "config.yaml").read_text(
        encoding="utf-8"
    ) == "machine: foo\n"
    assert (old_dir / "machines" / "laser.yaml").read_text(
        encoding="utf-8"
    ) == "id: laser\n"


def test_does_not_migrate_when_new_dir_already_exists(tmp_path):
    old_dir = tmp_path / "rayforge"
    new_dir = tmp_path / "swiftcut"
    old_dir.mkdir()
    (old_dir / "config.yaml").write_text("machine: foo\n", encoding="utf-8")
    new_dir.mkdir()
    (new_dir / "config.yaml").write_text("machine: bar\n", encoding="utf-8")

    _migrate_legacy_config_dir(old_dir, new_dir)

    # The pre-existing new dir is not overwritten by the old one.
    assert (new_dir / "config.yaml").read_text(
        encoding="utf-8"
    ) == "machine: bar\n"


def test_does_not_migrate_when_old_dir_does_not_exist(tmp_path):
    old_dir = tmp_path / "rayforge"
    new_dir = tmp_path / "swiftcut"

    _migrate_legacy_config_dir(old_dir, new_dir)

    assert not new_dir.exists()
    assert not old_dir.exists()


def test_migration_is_idempotent(tmp_path, caplog):
    old_dir = tmp_path / "rayforge"
    new_dir = tmp_path / "swiftcut"
    old_dir.mkdir()
    (old_dir / "config.yaml").write_text("machine: foo\n", encoding="utf-8")

    with caplog.at_level("INFO"):
        _migrate_legacy_config_dir(old_dir, new_dir)
        first_migration_logs = [
            r for r in caplog.records if "Migrated config" in r.message
        ]
        assert len(first_migration_logs) == 1

        # A second call must not re-copy or log again: the new dir
        # already exists, so it is a silent no-op.
        _migrate_legacy_config_dir(old_dir, new_dir)
        all_migration_logs = [
            r for r in caplog.records if "Migrated config" in r.message
        ]
        assert len(all_migration_logs) == 1


def test_pre_populated_new_dir_is_not_auto_migrated(tmp_path):
    """
    Root-cause regression: a pre-migration build (or a stray mkdir)
    can create the swiftcut dir before any migration ever ran. The
    old, existence-only guard treated that the same as an already-
    completed migration. It must instead be left alone: no auto-copy,
    and no marker claiming a migration happened.
    """
    old_dir = tmp_path / "rayforge"
    new_dir = tmp_path / "swiftcut"
    old_dir.mkdir()
    (old_dir / "config.yaml").write_text("machine: foo\n", encoding="utf-8")
    new_dir.mkdir()
    (new_dir / "config.yaml").write_text("machine: bar\n", encoding="utf-8")

    _migrate_legacy_config_dir(old_dir, new_dir)

    assert (new_dir / "config.yaml").read_text(
        encoding="utf-8"
    ) == "machine: bar\n"
    assert not (new_dir / MIGRATION_MARKER_FILENAME).exists()


def test_full_auto_migration_writes_a_marker(tmp_path):
    """A completed automatic migration leaves a marker, so it never
    runs again."""
    old_dir = tmp_path / "rayforge"
    new_dir = tmp_path / "swiftcut"
    old_dir.mkdir()
    (old_dir / "config.yaml").write_text("machine: foo\n", encoding="utf-8")

    _migrate_legacy_config_dir(old_dir, new_dir)

    assert (new_dir / MIGRATION_MARKER_FILENAME).exists()


def test_haptics_are_on_by_default_and_survive_the_config_file():
    assert Config().canvas_view.haptics_enabled is True
    blank = Config.from_dict({}, lambda _id: None)
    assert blank.canvas_view.haptics_enabled is True

    config = Config()
    config.canvas_view.haptics_enabled = False
    restored = Config.from_dict(config.to_dict(), lambda _id: None)

    assert restored.canvas_view.haptics_enabled is False


def test_crawford_mode_is_off_by_default_and_survives_the_config_file():
    assert Config().crawford_mode is False
    blank = Config.from_dict({}, lambda _id: None)
    assert blank.crawford_mode is False

    config = Config()
    config.set_crawford_mode(True)
    restored = Config.from_dict(config.to_dict(), lambda _id: None)

    assert restored.crawford_mode is True


def test_getting_started_is_unseen_until_closed_and_survives_the_file(
    tmp_path,
):
    from blinker import Signal

    from swiftcut.core.config import ConfigManager

    class Machines:
        machine_removed = Signal()

        @staticmethod
        def get_machine_by_id(machine_id):
            return None

    path = tmp_path / "config.yaml"
    # A config file from before the guide has no key: not seen yet.
    path.write_text("theme: system\n")
    manager = ConfigManager(path, Machines())
    assert Config().getting_started_seen is False
    assert manager.config.getting_started_seen is False

    manager.config.set_getting_started_seen(True)

    assert "getting_started_seen: true" in path.read_text()
    assert ConfigManager(path, Machines()).config.getting_started_seen


def test_snapping_is_on_by_default_and_survives_the_config_file():
    assert Config().canvas_view.snapping_enabled is True
    blank = Config.from_dict({}, lambda _id: None)
    assert blank.canvas_view.snapping_enabled is True

    config = Config()
    config.canvas_view.snapping_enabled = False
    restored = Config.from_dict(config.to_dict(), lambda _id: None)

    assert restored.canvas_view.snapping_enabled is False


def test_the_view_state_has_no_3d_toggles():
    """With the 3D view gone, only the 2D canvas toggles persist; an
    older config naming a removed toggle still loads."""
    assert set(Config().canvas_view.to_dict()) == {
        "show_workpieces",
        "show_travel_lines",
        "show_nogo_zones",
        "show_grid",
        "show_tabs",
        "pan_inertia_enabled",
        "haptics_enabled",
        "snapping_enabled",
    }
    old = Config.from_dict(
        {"canvas_view": {"show_camera": True, "show_grid": False}},
        lambda _id: None,
    )
    assert old.canvas_view.show_grid is False

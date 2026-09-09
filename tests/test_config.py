"""Tests for the first-run config-dir migration from "rayforge" to
"swiftcut" (see rayforge/config.py, `_migrate_legacy_config_dir`).

These tests call the migration function directly with tmp_path-backed
directories - they never touch the real OS config dir, and they never
import swiftcut.config (which has import-time side effects driven by
the RAYFORGE_CONFIG_DIR env var that tests/conftest.py already sets).
"""

from pathlib import Path

from swiftcut.config import _migrate_legacy_config_dir


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

    assert (new_dir / "config.yaml").read_text(
        encoding="utf-8"
    ) == "machine: foo\n"

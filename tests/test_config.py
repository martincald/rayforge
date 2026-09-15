"""Tests for the first-run config-dir migration from "rayforge" to
"swiftcut" (see rayforge/config.py, `_migrate_legacy_config_dir`), and
for the one-time "Import settings from Rayforge" action that covers
the case where the swiftcut dir was already populated (e.g. by a
pre-migration build) before it was ever migrated
(`should_offer_legacy_import` / `import_legacy_config`).

These tests call the functions directly with tmp_path-backed
directories - they never touch the real OS config dir, and they never
import swiftcut.config (which has import-time side effects driven by
the RAYFORGE_CONFIG_DIR env var that tests/conftest.py already sets).
"""

from pathlib import Path

from swiftcut.config import (
    MIGRATION_MARKER_FILENAME,
    _migrate_legacy_config_dir,
    import_legacy_config,
    should_offer_legacy_import,
)


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
    completed migration and silently gave up on the user's legacy
    profile forever. It must instead be left alone (no auto-copy, no
    marker) so the explicit import action can offer to fix it up.
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
    # should_offer_legacy_import is exactly what should catch this case.
    assert should_offer_legacy_import(old_dir, new_dir) is True


def test_full_auto_migration_writes_a_marker(tmp_path):
    """A completed automatic migration must never be offered again,
    even though `new_dir` now exists."""
    old_dir = tmp_path / "rayforge"
    new_dir = tmp_path / "swiftcut"
    old_dir.mkdir()
    (old_dir / "config.yaml").write_text("machine: foo\n", encoding="utf-8")

    _migrate_legacy_config_dir(old_dir, new_dir)

    assert (new_dir / MIGRATION_MARKER_FILENAME).exists()
    assert should_offer_legacy_import(old_dir, new_dir) is False


def test_should_offer_legacy_import_false_without_legacy_dir(tmp_path):
    old_dir = tmp_path / "rayforge"
    new_dir = tmp_path / "swiftcut"
    new_dir.mkdir()

    assert should_offer_legacy_import(old_dir, new_dir) is False


def test_should_offer_legacy_import_false_without_new_dir(tmp_path):
    old_dir = tmp_path / "rayforge"
    new_dir = tmp_path / "swiftcut"
    old_dir.mkdir()

    assert should_offer_legacy_import(old_dir, new_dir) is False


def test_import_legacy_config_copies_missing_without_overwriting(tmp_path):
    """
    The core safety property: importing into an already-populated
    swiftcut dir must add the legacy machine profile without touching
    the machine profile the user is currently using, and must never
    modify the legacy dir it reads from.
    """
    old_dir = tmp_path / "rayforge"
    new_dir = tmp_path / "swiftcut"
    old_dir.mkdir()
    (old_dir / "config.yaml").write_text(
        "machine: legacy-machine\n", encoding="utf-8"
    )
    (old_dir / "machines").mkdir()
    (old_dir / "machines" / "legacy-machine.yaml").write_text(
        "id: legacy-machine\nport: 50200\n", encoding="utf-8"
    )
    new_dir.mkdir()
    (new_dir / "config.yaml").write_text(
        "machine: active-machine\n", encoding="utf-8"
    )
    (new_dir / "machines").mkdir()
    (new_dir / "machines" / "active-machine.yaml").write_text(
        "id: active-machine\nport: 50201\n", encoding="utf-8"
    )

    copied = import_legacy_config(old_dir, new_dir)

    # The currently active config/machine is left completely untouched.
    assert (new_dir / "config.yaml").read_text(
        encoding="utf-8"
    ) == "machine: active-machine\n"
    assert (new_dir / "machines" / "active-machine.yaml").read_text(
        encoding="utf-8"
    ) == "id: active-machine\nport: 50201\n"

    # The legacy machine profile was copied in alongside it.
    assert (new_dir / "machines" / "legacy-machine.yaml").read_text(
        encoding="utf-8"
    ) == "id: legacy-machine\nport: 50200\n"
    assert "machines/legacy-machine.yaml" in copied

    # The legacy dir itself is untouched - copy only, never delete.
    assert (old_dir / "config.yaml").read_text(
        encoding="utf-8"
    ) == "machine: legacy-machine\n"
    assert (old_dir / "machines" / "legacy-machine.yaml").exists()

    # A marker is now present, and a second offer is suppressed.
    assert (new_dir / MIGRATION_MARKER_FILENAME).exists()
    assert should_offer_legacy_import(old_dir, new_dir) is False


def test_import_legacy_config_is_offered_and_performed_exactly_once(
    tmp_path,
):
    old_dir = tmp_path / "rayforge"
    new_dir = tmp_path / "swiftcut"
    old_dir.mkdir()
    (old_dir / "notes.txt").write_text("hello\n", encoding="utf-8")
    new_dir.mkdir()

    assert should_offer_legacy_import(old_dir, new_dir) is True
    first_copy = import_legacy_config(old_dir, new_dir)
    assert first_copy == ["notes.txt"]

    # The marker now suppresses any further offer, so a second, later
    # import call finds nothing left to copy.
    assert should_offer_legacy_import(old_dir, new_dir) is False
    second_copy = import_legacy_config(old_dir, new_dir)
    assert second_copy == []

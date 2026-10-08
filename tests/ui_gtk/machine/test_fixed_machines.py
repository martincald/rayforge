"""The two bundled machines are the only ones: no UI path creates,
deletes, renames or imports a machine.

A grep gate over every .py file under swiftcut/ui_gtk and under
swiftcut/builtin_addons (its tests excluded), plus the two
settings pages that used to offer a rename (the General page's name
entry) and an import (the Device page's "Import settings from
Rayforge" banner). The manager's own refusals are tested in
tests/machine/models/test_machine_manager.py.
"""

import re
from pathlib import Path

import pytest

from swiftcut.machine.models.machine import Machine

SWIFTCUT = Path(__file__).resolve().parents[3] / "swiftcut"
UI_CODE_DIRS = (SWIFTCUT / "ui_gtk", SWIFTCUT / "builtin_addons")

_MACHINE_MANAGEMENT = re.compile(
    r"\.(add_machine|remove_machine|create_default_machine|create_machine"
    r"|load_new_machines)\("
    r"|machine\.set_name\("
    r"|import_legacy|legacy_import"
)


def _ui_code_files():
    for root in UI_CODE_DIRS:
        assert root.is_dir()
        for path in sorted(root.rglob("*.py")):
            # Addon tests build their own machines in fixtures.
            if "tests" not in path.relative_to(root).parts:
                yield path


def test_no_ui_code_creates_deletes_renames_or_imports_a_machine():
    offenders = [
        f"{path.relative_to(SWIFTCUT)}:{number}: {line.strip()}"
        for path in _ui_code_files()
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _MACHINE_MANAGEMENT.search(line)
    ]

    assert offenders == []


def test_the_gate_reads_the_addon_code():
    """The addon dir is really scanned, its tests are not."""
    files = list(_ui_code_files())
    addons = SWIFTCUT / "builtin_addons"

    assert any(addons in path.parents for path in files)
    assert not any(
        "tests" in path.relative_to(addons).parts
        for path in files
        if addons in path.parents
    )


def _descendants(widget, kind):
    found = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, kind):
            found.append(child)
        found.extend(_descendants(child, kind))
        child = child.get_next_sibling()
    return found


@pytest.mark.ui
def test_the_general_page_shows_the_name_read_only(ui_context_initializer):
    from gi.repository import Adw

    from swiftcut.ui_gtk.machine.general_preferences_page import (
        GeneralPreferencesPage,
    )

    machine = Machine(ui_context_initializer)
    machine.name = "ilab-626"
    ui_context_initializer.machine_mgr.add_machine(machine)
    page = GeneralPreferencesPage(machine)

    assert _descendants(page, Adw.EntryRow) == []
    assert [
        row.get_subtitle()
        for row in _descendants(page, Adw.ActionRow)
        if row.get_title() == "Name"
    ] == ["ilab-626"]


@pytest.mark.ui
def test_the_device_page_offers_no_import(ui_context_initializer):
    from gi.repository import Adw

    from swiftcut.ui_gtk.machine.device_settings_page import (
        DeviceSettingsPage,
    )

    machine = Machine(ui_context_initializer)
    ui_context_initializer.machine_mgr.add_machine(machine)
    page = DeviceSettingsPage(machine=machine)

    assert _descendants(page, Adw.Banner) == []
    assert not hasattr(page, "import_legacy_banner")

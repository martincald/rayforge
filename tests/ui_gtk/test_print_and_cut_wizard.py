"""The Print & Cut wizard (Tools > Align to Physical Position) opens."""

from unittest.mock import MagicMock

import gi
import pytest

gi.require_version("Gtk", "4.0")

from swiftcut.core.workpiece import WorkPiece  # noqa: E402
from swiftcut.machine.models.machine import Machine  # noqa: E402


@pytest.mark.ui
def test_the_wizard_builds_its_window(ui_context_initializer):
    """
    Opening the wizard built a window whose spacing names were never
    imported, so the menu item raised NameError (REVIEW-0.1.1 F-01).
    """
    from print_and_cut.wizard import PrintAndCutWizard

    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    ui_context_initializer.machine_mgr.add_machine(machine)

    wizard = PrintAndCutWizard(
        parent=None,
        item=WorkPiece(name="part"),
        machine=machine,
        machine_cmd=MagicMock(is_job_running=False),
        editor=MagicMock(),
    )
    try:
        assert wizard.get_title() == "Print & Cut"
    finally:
        wizard.destroy()

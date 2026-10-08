"""UI tests for the Machine Settings dialog as the ilab-614 profile
sees it: no driver-maturity warning."""

import copy

import pytest
from gi.repository import Adw, Gtk

from swiftcut.machine.driver import DriverMaturity, RuidaDriver
from swiftcut.machine.models.controller import MachineController
from swiftcut.machine.models.default_profile import ILAB_614_PROFILE
from swiftcut.machine.models.machine import Machine


@pytest.fixture(autouse=True)
def no_rebuild(monkeypatch):
    """Editing the profile schedules a driver rebuild; it is stubbed so
    no test opens a real socket or serial port."""

    async def _noop_rebuild(self, ctx=None):
        return

    monkeypatch.setattr(MachineController, "rebuild_driver", _noop_rebuild)


def _ilab_614(context) -> Machine:
    machine = Machine.from_dict(
        copy.deepcopy(ILAB_614_PROFILE), context=context
    )
    machine.auto_connect = False
    context.machine_mgr.add_machine(machine)
    return machine


def _dialog(context, **kwargs):
    from swiftcut.ui_gtk.machine.settings_dialog import MachineSettingsDialog

    return MachineSettingsDialog(machine=_ilab_614(context), **kwargs)


def _texts(widget) -> list[str]:
    """Every label, title and subtitle under widget."""
    found = []
    if isinstance(widget, Gtk.Label):
        found.append(widget.get_text())
    if isinstance(widget, Adw.PreferencesRow):
        found.append(widget.get_title())
    if isinstance(widget, Adw.ActionRow):
        found.append(widget.get_subtitle() or "")
    if isinstance(widget, Adw.PreferencesGroup):
        found.append(widget.get_title() or "")
        found.append(widget.get_description() or "")
    child = widget.get_first_child()
    while child is not None:
        found.extend(_texts(child))
        child = child.get_next_sibling()
    return found


def test_ruida_driver_is_stable():
    assert RuidaDriver.maturity is DriverMaturity.STABLE


@pytest.mark.ui
def test_no_driver_warning(ui_context_initializer):
    dialog = _dialog(ui_context_initializer)

    texts = " ".join(_texts(dialog)).lower()
    assert "experimental" not in texts
    assert "buggy" not in texts
    assert "at your own risk" not in texts
    dialog.destroy()

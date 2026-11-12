# flake8: noqa: E402
"""Tests for the SpinRow generic row."""

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gdk, Gtk

from swiftcut.core.undo import history as history_module
from swiftcut.ui_gtk.doceditor.step_settings.rows import SpinRow


def _spin_row(editor, step):
    return SpinRow(
        editor, step, "count", "Count", None, 1, 10, 1, 0, is_int=True
    )


@pytest.mark.ui
def test_syncs_value_from_step(editor, step):
    row = _spin_row(editor, step)
    assert row.widget.get_value() == 3
    step.count = 7
    step.updated.send(step)
    assert row.widget.get_value() == 7


@pytest.mark.ui
def test_commit_writes_to_step(editor, step):
    row = _spin_row(editor, step)
    row.commit(5)
    assert step.count == 5


@pytest.mark.ui
def test_change_schedules_debounced_commit(editor, step):
    row = _spin_row(editor, step)
    row.widget.get_adjustment().set_value(9)
    assert row._debounce_timer != 0
    row.cleanup()


@pytest.mark.ui
def test_external_update_does_not_clobber_pending_edit(editor, step):
    row = _spin_row(editor, step)
    row.widget.get_adjustment().set_value(9)
    assert row._debounce_timer != 0

    step.power = 0.4
    step.updated.send(step)

    assert row.widget.get_value() == 9
    assert row._debounce_timer != 0
    row.cleanup()


@pytest.mark.ui
def test_set_range(editor, step):
    row = _spin_row(editor, step)
    row.set_range(0, 20)
    adj = row.widget.get_adjustment()
    assert adj.get_lower() == 0
    assert adj.get_upper() == 20


def _press(row, keyval):
    controller = row.widget.numeric_entry.key_controller
    return controller.emit("key-pressed", keyval, 0, Gdk.ModifierType(0))


@pytest.mark.ui
def test_a_typed_commit_updates_the_step_at_once(editor, step):
    row = _spin_row(editor, step)
    history = editor.history_manager
    entries = len(history.undo_stack)

    row.widget.get_spin_button().set_text("7")
    assert step.count == 3

    row.widget.numeric_entry.commit()

    assert step.count == 7
    assert row._debounce_timer == 0
    assert len(history.undo_stack) == entries + 1


@pytest.mark.ui
def test_two_arrow_presses_are_two_undo_steps(editor, step, monkeypatch):
    """No timer merges them. (The history itself merges changes to one
    property made within COALESCE_THRESHOLD; that is set aside here.)"""
    monkeypatch.setattr(history_module, "COALESCE_THRESHOLD", 0.0)
    row = _spin_row(editor, step)
    history = editor.history_manager
    entries = len(history.undo_stack)

    assert _press(row, Gdk.KEY_Up) is True
    assert _press(row, Gdk.KEY_Up) is True

    assert step.count == 5
    assert row._debounce_timer == 0
    assert len(history.undo_stack) == entries + 2


@pytest.mark.ui
def test_a_field_committing_as_its_dialog_closes_is_kept(editor, step):
    """The step dialog cancels its rows' timers on close-request,
    before the field being edited commits; that commit does not wait
    for one."""
    row = _spin_row(editor, step)
    rows = Gtk.ListBox()
    rows.append(row.widget)
    win = Gtk.Window()
    win.set_child(rows)
    win.connect("close-request", lambda w: row.cleanup() or False)
    win.present()
    try:
        row.widget.get_spin_button().grab_focus()
        row.widget.get_spin_button().set_text("8")

        win.close()

        assert step.count == 8
    finally:
        win.destroy()

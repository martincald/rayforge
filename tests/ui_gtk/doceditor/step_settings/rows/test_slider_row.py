# flake8: noqa: E402
"""Tests for the SliderRow generic row."""

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gdk, GLib

from swiftcut.core.undo import history as history_module
from swiftcut.ui_gtk.doceditor.step_settings.rows import SliderRow
from swiftcut.ui_gtk.shared.gtk import SPINROW_SCROLL_GUARD_NAME


def _slider_row(editor, step):
    return SliderRow(editor, step, "power", "Power", None, 0.0, 1.0, 0.01, 2)


def _percent_row(editor, step):
    """The Power row as the laser pages build it: 0-100 %."""
    return SliderRow(
        editor,
        step,
        "power",
        "Power",
        None,
        0.0,
        1.0,
        1.0,
        1,
        display_scale=100.0,
        suffix="%",
    )


@pytest.mark.ui
def test_commit_writes_to_step(editor, step):
    row = _slider_row(editor, step)
    row.commit(0.8)
    assert step.power == pytest.approx(0.8)


@pytest.mark.ui
def test_syncs_value_from_step(editor, step):
    row = _slider_row(editor, step)
    step.power = 0.9
    step.updated.send(step)
    assert row._adj.get_value() == pytest.approx(0.9)


@pytest.mark.ui
def test_change_schedules_debounced_commit(editor, step):
    row = _slider_row(editor, step)
    row._adj.set_value(0.7)
    assert row._debounce_timer != 0
    row.cleanup()


@pytest.mark.ui
def test_spin_button_carries_the_scroll_guard(editor, step):
    """
    The spin button shares one adjustment with the slider, so an
    unguarded wheel event over it edits the value - and commits it -
    exactly as scrolling the guarded slider would, bypassing the
    guard create_slider installs on its sibling.
    """
    row = _slider_row(editor, step)
    names = [c.get_name() for c in row._spin.observe_controllers()]
    assert SPINROW_SCROLL_GUARD_NAME in names


@pytest.mark.ui
def test_a_typed_value_commits_at_once(editor, step):
    row = _slider_row(editor, step)
    history = editor.history_manager
    entries = len(history.undo_stack)

    row._spin.set_text("0.2+0.5")
    assert step.power == pytest.approx(0.5)

    row.numeric_entry.commit()

    assert step.power == pytest.approx(0.7)
    assert row._debounce_timer == 0
    assert len(history.undo_stack) == entries + 1


@pytest.mark.ui
def test_two_arrow_presses_are_two_undo_steps(editor, step, monkeypatch):
    """No timer merges them. (The history itself merges changes to one
    property made within COALESCE_THRESHOLD; that is set aside here.)"""
    monkeypatch.setattr(history_module, "COALESCE_THRESHOLD", 0.0)
    row = _percent_row(editor, step)
    history = editor.history_manager
    entries = len(history.undo_stack)
    controller = row.numeric_entry.key_controller

    for _ in range(2):
        assert controller.emit(
            "key-pressed", Gdk.KEY_Up, 0, Gdk.ModifierType(0)
        )

    assert step.power == pytest.approx(0.52)
    assert len(history.undo_stack) == entries + 2


@pytest.mark.ui
def test_a_slider_drag_still_coalesces(editor, step):
    row = _slider_row(editor, step)
    history = editor.history_manager
    entries = len(history.undo_stack)

    for value in (0.6, 0.65, 0.7):
        row._adj.set_value(value)
    assert step.power == pytest.approx(0.5)
    assert row._debounce_timer != 0

    context = GLib.MainContext.default()
    while row._debounce_timer:
        context.iteration(True)

    assert step.power == pytest.approx(0.7)
    assert len(history.undo_stack) == entries + 1

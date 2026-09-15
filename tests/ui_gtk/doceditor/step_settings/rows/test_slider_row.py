# flake8: noqa: E402
"""Tests for the SliderRow generic row."""

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from swiftcut.ui_gtk.doceditor.step_settings.rows import SliderRow
from swiftcut.ui_gtk.shared.gtk import SPINROW_SCROLL_GUARD_NAME


def _slider_row(editor, step):
    return SliderRow(editor, step, "power", "Power", None, 0.0, 1.0, 0.01, 2)


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

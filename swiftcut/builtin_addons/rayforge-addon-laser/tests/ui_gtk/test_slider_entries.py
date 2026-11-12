# flake8: noqa: E402
"""UI tests: the value entries beside the raster and test grid sliders.

The ``stores`` tests use only what the entry had before it committed
typed values (type, then leave the field), so they run unchanged
against the earlier code: what a typed value stores must not change.
"""

import time

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gdk, GLib, Gtk
from laser_essentials.widgets.material_test_grid_page import (
    MaterialTestGridSettingsPage,
)
from laser_essentials.widgets.raster_page import RasterSettingsPage

from swiftcut.core.step_registry import step_registry

SHIFT = Gdk.ModifierType.SHIFT_MASK
ALT = Gdk.ModifierType.ALT_MASK
NO_MODIFIER = Gdk.ModifierType(0)


def _iterate(condition, timeout=1.0):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        context.iteration(False)
        if condition():
            return True
        time.sleep(0.001)
    return condition()


def _entry(row):
    """The value entry in a slider row."""
    stack = [row]
    while stack:
        widget = stack.pop()
        if isinstance(widget, Gtk.Entry):
            return widget
        child = widget.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    raise AssertionError("no value entry in the row")


@pytest.fixture
def show():
    """Present a page beside a focus sink; return the sink."""
    windows = []

    def _show(page):
        sink = Gtk.Button(label="sink")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(page)
        box.append(sink)
        win = Gtk.Window()
        win.set_default_size(600, 900)
        win.set_child(box)
        win.present()
        windows.append(win)
        return sink

    yield _show
    for win in windows:
        win.destroy()


def _raster_page(editor, ui_context):
    step = step_registry.get("EngraveStep").create(ui_context)
    step.min_power_level = 0.1
    step.max_power_level = 1.0
    step.threshold = 10
    page = RasterSettingsPage(editor, step)
    for row in (page.min_power_row, page.max_power_row, page.threshold_row):
        row.set_visible(True)
    return page, step


def _type_and_leave(entry, sink, text):
    entry.grab_focus()
    entry.set_text(text)
    sink.grab_focus()


@pytest.mark.ui
def test_min_power_stores_a_typed_percent(
    editor, laser_machine, ui_context, show
):
    page, step = _raster_page(editor, ui_context)
    sink = show(page)

    _type_and_leave(_entry(page.min_power_row), sink, "50")

    assert _iterate(lambda: abs(step.min_power_level - 0.5) < 1e-9)


@pytest.mark.ui
def test_min_power_stores_nothing_for_a_percent_sign(
    editor, laser_machine, ui_context, show
):
    page, step = _raster_page(editor, ui_context)
    sink = show(page)
    entry = _entry(page.min_power_row)

    _type_and_leave(entry, sink, "50%")

    assert not _iterate(lambda: step.min_power_level != 0.1, timeout=0.4)
    assert entry.get_text() == "10.0"


@pytest.mark.ui
@pytest.mark.parametrize("text, stored", [("128", 128), ("300", 255)])
def test_threshold_stores_a_typed_level(
    editor, laser_machine, ui_context, show, text, stored
):
    page, step = _raster_page(editor, ui_context)
    sink = show(page)

    _type_and_leave(_entry(page.threshold_row), sink, text)

    assert _iterate(lambda: step.threshold == stored)


@pytest.mark.ui
def test_test_grid_fixed_power_stores_a_typed_percent(
    editor, laser_machine, ui_context, show
):
    step = step_registry.get("MaterialTestStep").create(ui_context)
    step.fixed_power = 20.0
    page = MaterialTestGridSettingsPage(editor, step)
    page.fixed_power_row.set_visible(True)
    sink = show(page)

    _type_and_leave(_entry(page.fixed_power_row), sink, "50")

    assert _iterate(lambda: abs(step.fixed_power - 50.0) < 1e-9)


def _press(numeric_entry, keyval, state=NO_MODIFIER):
    return numeric_entry.key_controller.emit("key-pressed", keyval, 0, state)


@pytest.mark.ui
def test_min_power_entry_commits_typed_values(
    editor, laser_machine, ui_context
):
    page, step = _raster_page(editor, ui_context)
    numeric_entry = page.min_power_row.numeric_entry
    assert numeric_entry is not None
    entry = _entry(page.min_power_row)
    history = editor.history_manager
    entries = len(history.undo_stack)

    for text in ("1", "12", "45"):
        entry.set_text(text)
    assert step.min_power_level == pytest.approx(0.1)
    assert len(history.undo_stack) == entries

    assert _press(numeric_entry, Gdk.KEY_Return) is True
    assert step.min_power_level == pytest.approx(0.45)
    assert len(history.undo_stack) == entries + 1
    assert page.min_power_scale.get_value() == pytest.approx(45.0)
    assert entry.get_text() == "45.0"

    entry.set_text("77")
    assert _press(numeric_entry, Gdk.KEY_Escape) is True
    assert entry.get_text() == "45.0"
    assert step.min_power_level == pytest.approx(0.45)


@pytest.mark.ui
@pytest.mark.parametrize(
    "text, stored, note",
    [
        ("10+5*2", 0.20, None),
        ("100/4", 0.25, None),
        ("150", 1.0, "Max 100"),
        ("-5", 0.0, "Min 0"),
        ("abc", 0.10, None),
    ],
)
def test_min_power_entry_expressions(
    editor, laser_machine, ui_context, text, stored, note
):
    page, step = _raster_page(editor, ui_context)
    numeric_entry = page.min_power_row.numeric_entry
    assert numeric_entry is not None

    _entry(page.min_power_row).set_text(text)
    numeric_entry.commit()

    assert step.min_power_level == pytest.approx(stored)
    assert page.min_power_scale.get_value() == pytest.approx(stored * 100)
    assert numeric_entry.note == note


@pytest.mark.ui
def test_min_power_entry_arrow_steps(editor, laser_machine, ui_context):
    page, step = _raster_page(editor, ui_context)
    numeric_entry = page.min_power_row.numeric_entry
    assert numeric_entry is not None

    for state, expected in (
        (NO_MODIFIER, 11.0),
        (SHIFT, 21.0),
        (ALT, 21.1),
    ):
        assert _press(numeric_entry, Gdk.KEY_Up, state) is True
        assert step.min_power_level == pytest.approx(expected / 100)
        assert page.min_power_scale.get_value() == pytest.approx(expected)
    assert _press(numeric_entry, Gdk.KEY_Down) is True
    assert step.min_power_level == pytest.approx(0.201)


@pytest.mark.ui
def test_only_the_value_entries_of_the_step_pages_commit(
    editor, laser_machine, ui_context
):
    page, _step = _raster_page(editor, ui_context)
    for row in (page.min_power_row, page.max_power_row, page.threshold_row):
        assert row.numeric_entry is not None
    grid = MaterialTestGridSettingsPage(
        editor, step_registry.get("MaterialTestStep").create(ui_context)
    )
    for row in (
        grid.fixed_power_row,
        grid.min_power_row,
        grid.max_power_row,
        grid.label_power_row,
    ):
        assert row.numeric_entry is not None

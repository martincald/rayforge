# flake8: noqa: E402
"""UI tests for commit-on-confirm numeric entry (NumericEntry)."""

import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import pytest
from gi.repository import Gdk, GLib, Gtk

from swiftcut.ui_gtk.shared import numeric_entry as numeric_entry_module
from swiftcut.ui_gtk.shared.numeric_entry import (
    BUTTON_COMMIT_NAME,
    OUTSIDE_PRESS_NAME,
    NumericEntry,
)
from swiftcut.ui_gtk.shared.pref_rows import LengthSpinRow, SpinRow

SHIFT = Gdk.ModifierType.SHIFT_MASK
ALT = Gdk.ModifierType.ALT_MASK
NO_MODIFIER = Gdk.ModifierType(0)


@pytest.fixture
def mm(ui_context_initializer):
    ui_context_initializer.config.unit_preferences["length"] = "mm"
    return ui_context_initializer


def _width_row(value=50.0):
    row = LengthSpinRow("Width", lower=1, upper=10000, value_in_base=value)
    row.attach_numeric_entry()
    return row


def _spin_row(title="Value", **kwargs):
    row = SpinRow(title, **kwargs)
    row.attach_numeric_entry()
    return row


def _recorder(row):
    received = []
    row.value_changed.connect(lambda r: received.append(r), weak=False)
    return received


def _press(row, keyval, state=NO_MODIFIER):
    controller = row.numeric_entry.key_controller
    return controller.emit("key-pressed", keyval, 0, state)


def _iterate(condition, timeout=1.0):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        context.iteration(False)
        if condition():
            return True
        time.sleep(0.001)
    return condition()


@pytest.fixture
def window():
    """A presented toplevel holding a row beside a focus sink."""
    windows = []

    def show(row):
        sink = Gtk.Button(label="sink")
        rows = Gtk.ListBox()
        rows.append(row)
        box = Gtk.Box()
        box.append(rows)
        box.append(sink)
        win = Gtk.Window()
        win.set_child(box)
        win.present()
        windows.append(win)
        return sink

    yield show
    for win in windows:
        win.destroy()


@pytest.mark.ui
def test_a_spin_row_is_left_alone_until_it_opts_in(ui_context_initializer):
    row = SpinRow("Count", lower=0, upper=100, numeric=True, value=5)
    assert row.numeric_entry is None
    assert row.get_spin_button().get_numeric() is True

    entry = row.attach_numeric_entry()

    assert isinstance(entry, NumericEntry)
    assert row.attach_numeric_entry() is entry
    # Typed "+", "/" and unit letters must reach the field.
    assert row.get_spin_button().get_numeric() is False


@pytest.mark.ui
def test_typing_emits_nothing_until_commit(mm):
    row = _width_row()
    received = _recorder(row)
    spin = row.get_spin_button()
    for text in ("1", "12", "125"):
        spin.set_text(text)
        assert received == []
        assert row.get_value() == pytest.approx(50.0)

    row.numeric_entry.commit()
    assert len(received) == 1
    assert row.get_value_in_base_units() == pytest.approx(125.0)

    row.numeric_entry.commit()
    assert len(received) == 1


@pytest.mark.ui
def test_committing_the_same_value_emits_nothing(mm):
    row = _width_row()
    received = _recorder(row)
    row.get_spin_button().set_text("50.000")
    row.numeric_entry.commit()
    assert received == []
    assert row.get_spin_button().get_text() == "50.00"


@pytest.mark.ui
def test_cancel_restores_without_committing(mm):
    row = _width_row()
    received = _recorder(row)
    spin = row.get_spin_button()
    spin.set_text("125")

    assert row.numeric_entry.cancel() is True
    assert spin.get_text() == "50.00"
    assert received == []
    assert row.numeric_entry.cancel() is False


@pytest.mark.ui
def test_enter_through_key_handling_commits_once(mm, window):
    row = _width_row()
    received = _recorder(row)
    spin = row.get_spin_button()
    window(row)
    spin.grab_focus()
    spin.set_text("10+5")

    # Consumed: GTK's own parser would read the text as 10.
    assert _press(row, Gdk.KEY_Return) is True

    assert len(received) == 1
    assert row.get_value() == pytest.approx(15.0)
    assert spin.get_text() == "15.00"


@pytest.mark.ui
@pytest.mark.parametrize(
    "keyval, state",
    [
        (Gdk.KEY_Return, NO_MODIFIER),
        (Gdk.KEY_Return, SHIFT),
        (Gdk.KEY_KP_Enter, Gdk.ModifierType.CONTROL_MASK),
    ],
)
def test_enter_on_an_unedited_field_changes_nothing(mm, keyval, state):
    row = _width_row()
    row.set_value_in_base_units(33.3333)
    received = _recorder(row)
    spin = row.get_spin_button()

    assert _press(row, keyval, state) is True

    assert received == []
    assert spin.get_value() == pytest.approx(33.3333, abs=1e-9)
    assert spin.get_text() == "33.33"


@pytest.mark.ui
def test_page_keys_step_by_the_page_increment(ui_context_initializer):
    row = _spin_row("Value", lower=0, upper=1000, digits=2, value=50)
    received = _recorder(row)

    assert _press(row, Gdk.KEY_Page_Up) is True
    assert row.get_value() == pytest.approx(60.0)
    assert _press(row, Gdk.KEY_Page_Down) is True
    assert row.get_value() == pytest.approx(50.0)
    assert len(received) == 2
    # Other combinations stay GTK's.
    assert _press(row, Gdk.KEY_Page_Up, Gdk.ModifierType.CONTROL_MASK) is False


@pytest.mark.ui
def test_esc_through_key_handling_reverts(mm, window):
    row = _width_row()
    received = _recorder(row)
    spin = row.get_spin_button()
    window(row)
    spin.grab_focus()
    spin.set_text("125")

    assert _press(row, Gdk.KEY_Escape) is True
    assert spin.get_text() == "50.00"
    assert received == []
    # With nothing to revert, Esc is left for the dialog to close on.
    assert _press(row, Gdk.KEY_Escape) is False


@pytest.mark.ui
def test_focus_loss_commits_once(mm, window):
    row = _width_row()
    received = _recorder(row)
    spin = row.get_spin_button()
    sink = window(row)
    spin.grab_focus()
    spin.set_text("100/3")

    sink.grab_focus()

    assert len(received) == 1
    assert row.get_value() == pytest.approx(33.33)
    assert spin.get_text() == "33.33"


@pytest.mark.ui
def test_focus_round_trip_without_edit_changes_nothing(mm, window):
    """GTK re-parses the shown text on focus loss; unedited, that
    must neither round the value nor commit."""
    row = _width_row()
    row.set_value_in_base_units(33.3333)
    received = _recorder(row)
    spin = row.get_spin_button()
    sink = window(row)

    spin.grab_focus()
    sink.grab_focus()

    assert received == []
    assert spin.get_value() == pytest.approx(33.3333, abs=1e-9)
    assert spin.get_text() == "33.33"


@pytest.mark.ui
def test_closing_the_window_commits_the_field_being_edited(mm):
    row = _width_row()
    received = _recorder(row)
    spin = row.get_spin_button()
    rows = Gtk.ListBox()
    rows.append(row)
    win = Gtk.Window()
    win.set_child(rows)
    win.present()
    try:
        spin.grab_focus()
        spin.set_text("77")

        # The window controls' close button takes no focus.
        win.close()

        assert len(received) == 1
        assert row.get_value() == pytest.approx(77.0)
    finally:
        win.destroy()


def _outside_press(window):
    return [
        c
        for c in window.observe_controllers()
        if c.get_name() == OUTSIDE_PRESS_NAME
    ]


def _press_on(gesture, widget):
    """Deliver a press at the centre of widget to a window gesture."""
    ok, bounds = widget.compute_bounds(gesture.get_widget())
    assert ok
    x = bounds.get_x() + bounds.get_width() / 2
    y = bounds.get_y() + bounds.get_height() / 2
    gesture.emit("pressed", 1, x, y)


@pytest.mark.ui
def test_a_press_elsewhere_commits_before_it_moves_focus(mm, window):
    """A control can act on its press before it takes focus; the
    window sees the press first, in its capture phase."""
    row = _width_row()
    received = _recorder(row)
    spin = row.get_spin_button()
    sink = window(row)
    win = sink.get_root()
    assert _iterate(lambda: spin.get_width() > 0 and sink.get_width() > 0)
    assert _outside_press(win) == []

    spin.grab_focus()
    spin.set_text("10+5")
    (press,) = _outside_press(win)
    assert press.get_propagation_phase() == Gtk.PropagationPhase.CAPTURE

    _press_on(press, spin)
    assert received == []

    _press_on(press, sink)
    assert len(received) == 1
    assert row.get_value() == pytest.approx(15.0)

    sink.grab_focus()
    assert len(received) == 1
    assert _outside_press(win) == []


@pytest.mark.ui
def test_selects_all_text_on_focus(mm, window):
    row = _width_row()
    spin = row.get_spin_button()
    window(row)
    spin.grab_focus()
    # A click puts the cursor at the pointer after focus arrives.
    spin.select_region(1, 1)

    assert _iterate(lambda: spin.get_selection_bounds() == (0, 5))


@pytest.mark.ui
@pytest.mark.parametrize(
    "text, expected, note",
    [
        ("10+5", 15.0, None),
        ("100/3", 33.33, None),
        ("2*(3+4)", 14.0, None),
        ("12.5", 12.5, None),
        ("1.25 * 2", 2.5, None),
        ("  7  ", 7.0, None),
        ("8-3", 5.0, None),
        ("50mm", 50.0, None),
        ("2in", 50.8, None),
        ("5 cm", 50.0, None),
        ("0.5m", 500.0, None),
        ("1+1mm", 2.0, None),
        ("abc", 50.0, None),
        ("", 50.0, None),
        ("1/0", 50.0, None),
        ("(1+2", 50.0, None),
        ("2**3", 50.0, None),
        ("1cm+", 50.0, None),
        ("pi", 50.0, None),
        ("__import__('os')", 50.0, None),
        ("20000", 10000.0, "Max 10000 mm"),
        ("-5", 1.0, "Min 1 mm"),
    ],
)
def test_expression_table(mm, text, expected, note):
    row = _width_row()
    received = _recorder(row)
    row.get_spin_button().set_text(text)

    row.numeric_entry.commit()

    assert row.get_value_in_base_units() == pytest.approx(expected)
    assert len(received) == (0 if expected == 50.0 else 1)
    assert row.numeric_entry.note == note


@pytest.mark.ui
def test_bad_entry_restores_the_text(mm):
    row = _width_row()
    spin = row.get_spin_button()
    spin.set_text("12abc")
    row.numeric_entry.commit()
    assert spin.get_text() == "50.00"


@pytest.mark.ui
def test_locale_decimal_comma_is_accepted(mm, monkeypatch):
    monkeypatch.setattr(
        numeric_entry_module.locale,
        "localeconv",
        lambda: {"decimal_point": ","},
    )
    row = _width_row()
    row.get_spin_button().set_text("12,5+0.5")
    row.numeric_entry.commit()
    assert row.get_value_in_base_units() == pytest.approx(13.0)


@pytest.mark.ui
def test_unit_suffix_converts_into_the_display_unit(ui_context_initializer):
    ui_context_initializer.config.unit_preferences["length"] = "in"
    row = _width_row(value=25.4)
    assert row.get_value() == pytest.approx(1.0)

    row.get_spin_button().set_text("50.8mm")
    row.numeric_entry.commit()

    assert row.get_value() == pytest.approx(2.0)
    assert row.get_value_in_base_units() == pytest.approx(50.8)


@pytest.mark.ui
def test_unitless_row_rejects_a_unit_suffix(ui_context_initializer):
    row = _spin_row("Count", lower=0, upper=100, value=5)
    row.get_spin_button().set_text("50mm")
    row.numeric_entry.commit()
    assert row.get_value() == pytest.approx(5.0)


@pytest.mark.ui
@pytest.mark.parametrize(
    "keyval, state, expected",
    [
        (Gdk.KEY_Up, NO_MODIFIER, 51.0),
        (Gdk.KEY_Down, NO_MODIFIER, 49.0),
        (Gdk.KEY_Up, SHIFT, 60.0),
        (Gdk.KEY_Down, SHIFT, 40.0),
        (Gdk.KEY_Up, ALT, 50.1),
        (Gdk.KEY_Down, ALT, 49.9),
        (Gdk.KEY_KP_Up, NO_MODIFIER, 51.0),
    ],
)
def test_arrow_step_sizes(ui_context_initializer, keyval, state, expected):
    row = _spin_row("Value", lower=0, upper=1000, digits=2, value=50)
    received = _recorder(row)

    assert _press(row, keyval, state) is True

    assert row.get_value() == pytest.approx(expected)
    assert len(received) == 1


@pytest.mark.ui
def test_each_arrow_press_is_one_commit(ui_context_initializer):
    row = _spin_row("Value", lower=0, upper=1000, digits=2, value=50)
    received = _recorder(row)
    for _ in range(3):
        _press(row, Gdk.KEY_Up)
    assert row.get_value() == pytest.approx(53.0)
    assert len(received) == 3


@pytest.mark.ui
def test_step_starts_from_the_typed_value(ui_context_initializer):
    row = _spin_row("Value", lower=0, upper=1000, digits=2, value=50)
    row.get_spin_button().set_text("10+5")
    row.numeric_entry.step(1.0)
    assert row.get_value() == pytest.approx(16.0)


@pytest.mark.ui
def test_step_past_the_limit_clamps_with_a_note(ui_context_initializer):
    row = _spin_row("Power", lower=1, upper=100, value=95)
    row.numeric_entry.step(10.0)
    assert row.get_value() == pytest.approx(100.0)
    assert row.numeric_entry.note == "Max 100"


@pytest.mark.ui
def test_note_clears_after_its_time(mm, monkeypatch):
    monkeypatch.setattr(numeric_entry_module, "NOTE_MS", 10)
    row = _width_row()
    row.get_spin_button().set_text("20000")
    row.numeric_entry.commit()
    assert row.numeric_entry.note == "Max 10000 mm"
    assert _iterate(lambda: row.numeric_entry.note is None)


@pytest.mark.ui
def test_note_shows_beside_the_field_without_taking_focus(
    mm, window, monkeypatch
):
    monkeypatch.setattr(numeric_entry_module, "NOTE_MS", 50)
    row = _width_row()
    spin = row.get_spin_button()
    sink = window(row)
    spin.grab_focus()
    spin.set_text("20000")

    sink.grab_focus()

    popover = row.numeric_entry._note_popover
    assert popover is not None
    assert popover.get_parent() is spin
    label = popover.get_child()
    assert isinstance(label, Gtk.Label)
    assert label.get_label() == "Max 10000 mm"
    root = sink.get_root()
    assert root.get_focus() is sink
    assert _iterate(lambda: row.numeric_entry._note_popover is None)
    assert root.get_focus() is sink


@pytest.mark.ui
def test_programmatic_set_keeps_an_edit_when_unchanged(mm):
    row = _width_row()
    spin = row.get_spin_button()
    spin.set_text("12")
    row.set_value_in_base_units(50.0)
    assert spin.get_text() == "12"
    row.set_value_in_base_units(60.0)
    assert spin.get_text() == "60.00"


@pytest.mark.ui
def test_plus_button_commits_the_typed_text_first(mm):
    row = _width_row()
    received = _recorder(row)
    spin = row.get_spin_button()
    up = spin.get_last_child()
    assert isinstance(up, Gtk.Button)
    ours = [
        c
        for c in up.observe_controllers()
        if c.get_name() == BUTTON_COMMIT_NAME
    ]
    assert len(ours) == 1
    assert ours[0].get_propagation_phase() == Gtk.PropagationPhase.CAPTURE
    spin.set_text("10+5")

    ours[0].emit("pressed", 1, 1.0, 1.0)

    assert row.get_value() == pytest.approx(15.0)
    assert len(received) == 1

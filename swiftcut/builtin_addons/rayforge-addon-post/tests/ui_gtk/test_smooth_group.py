# flake8: noqa: E402
"""UI tests: the smooth group's Smoothness entry.

The ``stores`` test uses only what the entry had before it committed
typed values (type, then leave the field), so it runs unchanged against
the earlier code: what a typed value sends must not change.
"""

import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import pytest
from gi.repository import Gdk, GLib, Gtk
from post_processors.transformers import Smooth
from post_processors.widgets.smooth_group import SmoothSettingsGroup

SHIFT = Gdk.ModifierType.SHIFT_MASK
ALT = Gdk.ModifierType.ALT_MASK
NO_MODIFIER = Gdk.ModifierType(0)


class _Page:
    use_expanders = True


def _descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


def _amount(ui_context, amount=20):
    """The group, its Smoothness row, entry and scale, and what it sends."""
    group = SmoothSettingsGroup("Smooth", Smooth(amount=amount), _Page())
    row = next(
        r
        for r in group._rows
        if any(isinstance(w, Gtk.Scale) for w in _descendants(r))
    )
    entry = next(w for w in _descendants(row) if isinstance(w, Gtk.Entry))
    scale = next(w for w in _descendants(row) if isinstance(w, Gtk.Scale))
    sent = []
    group.param_changed.connect(
        lambda sender, **kw: sent.append((kw["key"], kw["value"])),
        weak=False,
    )
    return group, row, entry, scale, sent


def _iterate(condition, timeout=1.0):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        context.iteration(False)
        if condition():
            return True
        time.sleep(0.001)
    return condition()


@pytest.mark.ui
def test_amount_stores_a_typed_value(ui_context):
    _group, row, entry, _scale, sent = _amount(ui_context)
    sink = Gtk.Button(label="sink")
    rows = Gtk.ListBox()
    rows.append(row)
    box = Gtk.Box()
    box.append(rows)
    box.append(sink)
    win = Gtk.Window()
    win.set_child(box)
    win.present()
    try:
        entry.grab_focus()
        entry.set_text("60")
        sink.grab_focus()

        assert _iterate(lambda: sent == [("amount", 60)])
    finally:
        win.destroy()


def _press(row, keyval, state=NO_MODIFIER):
    controller = row.numeric_entry.key_controller
    return controller.emit("key-pressed", keyval, 0, state)


@pytest.mark.ui
def test_amount_commits_typed_values(ui_context):
    _group, row, entry, scale, sent = _amount(ui_context)
    assert row.numeric_entry is not None

    for text in ("1", "12", "45"):
        entry.set_text(text)
    assert sent == []

    assert _press(row, Gdk.KEY_Return) is True
    assert sent == [("amount", 45)]
    assert scale.get_value() == pytest.approx(45)
    assert entry.get_text() == "45"

    entry.set_text("77")
    assert _press(row, Gdk.KEY_Escape) is True
    assert entry.get_text() == "45"
    assert sent == [("amount", 45)]


@pytest.mark.ui
@pytest.mark.parametrize(
    "text, value, note",
    [
        ("10*3", 30, None),
        ("(50+10)/2", 30, None),
        ("150", 100, "Max 100"),
        ("-1", 0, "Min 0"),
        ("", None, None),
    ],
)
def test_amount_expressions(ui_context, text, value, note):
    _group, row, entry, scale, sent = _amount(ui_context)

    entry.set_text(text)
    row.numeric_entry.commit()

    assert sent == ([] if value is None else [("amount", value)])
    assert scale.get_value() == pytest.approx(20 if value is None else value)
    assert row.numeric_entry.note == note


@pytest.mark.ui
def test_amount_arrow_steps(ui_context):
    _group, row, _entry, scale, sent = _amount(ui_context)

    assert _press(row, Gdk.KEY_Up) is True
    assert _press(row, Gdk.KEY_Up, SHIFT) is True
    assert _press(row, Gdk.KEY_Down) is True
    # A tenth is below what the field shows: no change.
    assert _press(row, Gdk.KEY_Up, ALT) is True

    assert sent == [("amount", 21), ("amount", 31), ("amount", 30)]
    assert scale.get_value() == pytest.approx(30)

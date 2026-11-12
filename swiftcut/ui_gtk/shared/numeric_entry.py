"""Commit-on-confirm editing for numeric fields."""

import locale
import math
import re
from collections.abc import Callable
from gettext import gettext as _

from gi.repository import Gdk, GLib, Gtk

from ...core.expression import compile_expression, safe_evaluate
from ...shared.units.definitions import Unit, get_units_for_quantity
from ...shared.util.glib import discrete_edit

NOTE_MS = 2000
BUTTON_COMMIT_NAME = "numeric-entry-button-commit"
OUTSIDE_PRESS_NAME = "numeric-entry-outside-press"
_EPSILON = 1e-9
_ARITHMETIC = re.compile(r"[0-9.+\-*/()\s]+")
_ENTER_KEYS = (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter)
_PAGE_KEYS = {
    Gdk.KEY_Page_Up: 1.0,
    Gdk.KEY_KP_Page_Up: 1.0,
    Gdk.KEY_Page_Down: -1.0,
    Gdk.KEY_KP_Page_Down: -1.0,
}
_STEP_KEYS = {
    Gdk.KEY_Up: 1.0,
    Gdk.KEY_KP_Up: 1.0,
    Gdk.KEY_Down: -1.0,
    Gdk.KEY_KP_Down: -1.0,
}


def evaluate(text: str, unit: Unit | None = None) -> float | None:
    """
    Return the value typed into a field, in the field's display unit.

    Accepts + - * / and parentheses, a "." or the locale's decimal
    separator, and, when the field has a unit, a trailing unit of the
    same quantity ("50mm", "2 in"), converted through the unit objects.
    Returns None for anything else.
    """
    text = text.strip()
    source = unit
    if unit is not None:
        text, source = _split_unit(text, unit)
    point = locale.localeconv()["decimal_point"]
    if point != ".":
        text = text.replace(str(point), ".")
    if not text or "**" in text or not _ARITHMETIC.fullmatch(text):
        return None
    try:
        compile_expression(text)
        value = safe_evaluate(text, {})
    except (SyntaxError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if unit is not None and source is not None and source is not unit:
        value = unit.from_base(source.to_base(value))
    return value


def _split_unit(text: str, unit: Unit) -> tuple[str, Unit]:
    """Split a trailing unit of the field's quantity off the text."""
    suffixes = sorted(
        (
            (suffix, candidate)
            for candidate in get_units_for_quantity(unit.quantity)
            for suffix in {candidate.name, candidate.label}
        ),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    for suffix, candidate in suffixes:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip(), candidate
    return text, unit


class NumericEntry:
    """
    Commit-on-confirm editing for a Gtk.SpinButton, or for a Gtk.Entry
    that shows a Gtk.Adjustment (a slider's value).

    Typing only edits the text: nothing is parsed, clamped or
    reformatted until the value commits on Enter, Tab or focus loss
    (commit()). Esc puts the last committed value back (cancel()), and
    Up/Down step the value by 1, Shift x10, Alt x0.1 display units,
    Page Up/Down by the page increment, one commit per press (step()).
    A commit sets the adjustment's value, so its owner hears about it
    through "value-changed": once, and not at all when the value is the
    same. It is a discrete edit (shared.util.glib.discrete_edit), so a
    debounced owner applies it at once.

    A spin button's own parser would read "10+5" as 10. Enter and the
    step keys never reach it; focus loss and the +/- buttons still run
    it, so those commit first and leave it nothing to parse but the
    exact value.

    Two ways of leaving a field move no focus first: a press on a
    control that acts before it takes focus, or never takes it (a
    window's close button), and closing the window. While the field
    has focus, either one commits it.
    """

    def __init__(
        self,
        field: Gtk.SpinButton | Gtk.Entry,
        get_unit: Callable[[], Unit | None] | None = None,
        *,
        adjustment: Gtk.Adjustment | None = None,
        digits: int = 0,
        render: Callable[[], None] | None = None,
        suffix: str = "",
    ):
        """
        Drive a spin button, or an entry that shows ``adjustment`` at
        ``digits``: ``render`` writes the adjustment's value back into
        the entry's text, ``suffix`` (such as "%") included.
        """
        self._field = field
        self._spin = field if isinstance(field, Gtk.SpinButton) else None
        self._adjustment = adjustment
        self._entry_digits = digits
        self._render = render
        self._suffix = suffix
        self._get_unit = get_unit or (lambda: None)
        if self._spin is not None:
            # Numeric mode refuses "+", "/" and unit letters as they are
            # typed.
            self._spin.set_numeric(False)
        self.note: str | None = None
        self._note_popover: Gtk.Popover | None = None
        self._note_timer = 0
        self._select_idle = 0
        self._window: Gtk.Window | None = None
        self._outside_press: Gtk.GestureClick | None = None
        self._close_handler = 0

        self.key_controller = Gtk.EventControllerKey()
        self.key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.key_controller.connect("key-pressed", self._on_key_pressed)
        field.add_controller(self.key_controller)

        focus = Gtk.EventControllerFocus()
        focus.connect("enter", self._on_focus_enter)
        focus.connect("leave", self._on_focus_leave)
        field.add_controller(focus)

        child = self._spin.get_first_child() if self._spin else None
        while child is not None:
            if isinstance(child, Gtk.Button):
                click = Gtk.GestureClick()
                click.set_name(BUTTON_COMMIT_NAME)
                click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
                click.connect("pressed", lambda *_a: self._commit_before_gtk())
                child.add_controller(click)
            child = child.get_next_sibling()

        field.connect("destroy", self._on_destroy)

    @property
    def value(self) -> float:
        """The committed value, as the field shows it."""
        return round(self._adj().get_value(), self._digits())

    def set_value(self, value: float) -> None:
        """Set the value from code; an unchanged value keeps an edit."""
        if abs(value - self._adj().get_value()) > _EPSILON:
            self._adj().set_value(value)

    def commit(self) -> None:
        """Commit the typed text; a bad entry restores the last value."""
        value = self._typed()
        if value is None:
            self._show_committed()
            return
        self._set(value)

    def cancel(self) -> bool:
        """Restore the last committed value; True if the text changed."""
        before = self._field.get_text()
        self._show_committed()
        return self._field.get_text() != before

    def step(self, delta: float) -> None:
        """Step the typed (or else committed) value by delta, and commit."""
        value = self._typed()
        start = self.value if value is None else value
        self._set(round(start + delta, self._digits()))

    def _adj(self) -> Gtk.Adjustment:
        if self._spin is not None:
            return self._spin.get_adjustment()
        assert self._adjustment is not None
        return self._adjustment

    def _digits(self) -> int:
        if self._spin is not None:
            return self._spin.get_digits()
        return self._entry_digits

    def _typed(self) -> float | None:
        text = self._field.get_text()
        if self._suffix and text.endswith(self._suffix):
            text = text[: -len(self._suffix)]
        return evaluate(text, self._get_unit())

    def _set(self, value: float) -> None:
        adj = self._adj()
        lower, upper = adj.get_lower(), adj.get_upper()
        if value > upper:
            self._show_note(_("Max {limit}").format(limit=self._limit(upper)))
        elif value < lower:
            self._show_note(_("Min {limit}").format(limit=self._limit(lower)))
        value = min(max(value, lower), upper)
        current = adj.get_value()
        if self._spin is not None:
            # A spin button holds what it shows: its own parser reads
            # the shown digits back.
            value = round(value, self._digits())
            current = self.value
        if abs(value - current) < _EPSILON:
            self._show_committed()
            return
        with discrete_edit():
            adj.set_value(value)

    def _show_committed(self) -> None:
        if self._render is not None:
            self._render()
        elif self._spin is not None:
            # An unchanged value makes GTK render the text again, and
            # only that: it emits nothing.
            self._spin.set_value(self._spin.get_value())

    def _commit_before_gtk(self) -> None:
        # A spin button parses its text right after this and sets what
        # it reads. A value with more digits than it shows (33.3333
        # shown as "33.33") would come back rounded, a change nobody
        # typed; the exact value as the text makes that parse a no-op,
        # and GTK then shows the value at its digits again.
        if not self._field.get_editable():
            return
        self.commit()
        if self._spin is None:
            return
        exact = self._spin.get_value()
        if abs(exact - self.value) > _EPSILON:
            self._spin.set_text(repr(exact))

    def _on_key_pressed(self, _controller, keyval, _keycode, state) -> bool:
        if not self._field.get_editable():
            return False
        if keyval in _ENTER_KEYS:
            self.commit()
            return True
        if keyval == Gdk.KEY_Escape:
            # Only an edit swallows Esc; otherwise it still closes the
            # dialog the field sits in.
            return self.cancel()
        plain = not state & Gtk.accelerator_get_default_mod_mask()
        if keyval in _PAGE_KEYS and plain:
            page = self._adj().get_page_increment()
            self.step(_PAGE_KEYS[keyval] * page)
            return True
        direction = _STEP_KEYS.get(keyval)
        if direction is None:
            return False
        if state & Gdk.ModifierType.SHIFT_MASK:
            direction *= 10.0
        elif state & Gdk.ModifierType.ALT_MASK:
            direction *= 0.1
        self.step(direction)
        return True

    def _on_focus_enter(self, _controller) -> None:
        # A click places the cursor after focus arrives, so the
        # selection waits for the click to finish.
        if not self._select_idle:
            self._select_idle = GLib.idle_add(self._select_all)
        root = self._field.get_root()
        if isinstance(root, Gtk.Window) and root is not self._window:
            self._watch_window(root)

    def _on_focus_leave(self, _controller) -> None:
        self._unwatch_window()
        self._commit_before_gtk()

    def _watch_window(self, window: Gtk.Window) -> None:
        self._unwatch_window()
        self._window = window
        # Capture phase on the window, so the commit lands before the
        # pressed widget's own handlers run.
        self._outside_press = Gtk.GestureClick()
        self._outside_press.set_name(OUTSIDE_PRESS_NAME)
        self._outside_press.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._outside_press.connect("pressed", self._on_window_pressed)
        window.add_controller(self._outside_press)
        self._close_handler = window.connect(
            "close-request", self._on_close_request
        )

    def _on_close_request(self, _window) -> bool:
        self.commit()
        return False

    def _unwatch_window(self) -> None:
        if self._window is None:
            return
        press = self._outside_press
        if press is not None and press.get_widget() is self._window:
            self._window.remove_controller(press)
        self._window.disconnect(self._close_handler)
        self._window = None
        self._outside_press = None
        self._close_handler = 0

    def _on_window_pressed(self, gesture, _n_press, x, y) -> None:
        target = gesture.get_widget().pick(x, y, Gtk.PickFlags.DEFAULT)
        if target is None or not (
            target is self._field or target.is_ancestor(self._field)
        ):
            self.commit()

    def _select_all(self) -> bool:
        self._select_idle = 0
        if self._field.get_state_flags() & Gtk.StateFlags.FOCUS_WITHIN:
            self._field.select_region(0, -1)
        return GLib.SOURCE_REMOVE

    def _limit(self, limit: float) -> str:
        text = f"{limit:.{self._digits()}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        unit = self._get_unit()
        return f"{text} {unit.label}" if unit else text

    def _show_note(self, text: str) -> None:
        self.note = text
        if self._note_timer:
            GLib.source_remove(self._note_timer)
        self._note_timer = GLib.timeout_add(NOTE_MS, self._hide_note)
        if not self._field.get_mapped():
            return
        if self._note_popover is None:
            self._note_popover = Gtk.Popover(autohide=False)
            self._note_popover.set_can_focus(False)
            self._note_popover.set_parent(self._field)
        self._note_popover.set_child(Gtk.Label(label=text))
        self._note_popover.popup()

    def _hide_note(self) -> bool:
        self._note_timer = 0
        self.note = None
        self._drop_popover()
        return GLib.SOURCE_REMOVE

    def _drop_popover(self) -> None:
        if self._note_popover is not None:
            self._note_popover.popdown()
            self._note_popover.unparent()
            self._note_popover = None

    def _on_destroy(self, _widget) -> None:
        for source in (self._note_timer, self._select_idle):
            if source:
                GLib.source_remove(source)
        self._note_timer = 0
        self._select_idle = 0
        self._drop_popover()
        self._unwatch_window()

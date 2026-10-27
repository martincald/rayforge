"""
Plays a guided tour over the main window.

A tour is a list of steps. Each points at a target (targets.py), or
at nothing for a bubble in the middle of the window, and says in a
sentence or two what it is about. A step can wait for the user to do
what it says: it names the triggers that may mean they did, and a
done predicate that tells. Next, Back and Skip are always there, so a
step whose control is missing or off never holds the tour up.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from gettext import gettext as _
from typing import TYPE_CHECKING

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from ...context import get_context
from ...core.config import TOUR_COMPLETED, TOUR_SEEN
from ..machine.start_position_dialog import start_chosen
from . import targets
from .overlay import (
    Rect,
    TourBubble,
    TourMask,
    TourShield,
    bounds_in,
    target_hole,
)

if TYPE_CHECKING:
    from ...core.doc import Doc
    from ...machine.models.machine import Machine
    from ..mainwindow import MainWindow

logger = logging.getLogger(__name__)

# What a step can wait for, and the details its done predicate is
# given as keywords:
# - "connection": the active machine's connection changed (status=);
# - "machine": the active machine's settings changed (a start corner);
# - "doc-added": something was added to the document, or moved to
#   another layer (origin=, parent_of_origin=, and moved_from=, the
#   parent a moved item was taken from, or None for a new one);
# - "doc-updated": something in the document changed, a step switched
#   on or off or a layer hidden (origin=, parent_of_origin=);
# - "start": a Start was chosen in this window (machine=);
# - "home": the dock's Home was clicked (button=);
# - "jog": a dock jog arrow was clicked (button=);
# - "window": a window opened, such as Cut Scale's (window=).
TRIGGERS = frozenset(
    {
        "connection",
        "machine",
        "doc-added",
        "doc-updated",
        "start",
        "home",
        "jog",
        "window",
    }
)


@dataclass(frozen=True)
class Step:
    """
    One stop of a tour.

    target is an id in targets.TARGETS, or None for a bubble in the
    middle of the window. Once one of advance_on's triggers fires, the
    step moves on if done, given the window and the trigger's details,
    says the user did what it asks; with no done, any of its triggers
    moves it on. unavailable says why the target cannot be pointed at
    when it is missing, hidden or off. connection_status shows the
    laser's live connection state in the bubble. note is a small
    caption under the text.
    """

    heading: str
    body: str
    target: str | None = None
    advance_on: tuple[str, ...] = ()
    done: Callable[..., bool] | None = None
    unavailable: str = ""
    connection_status: bool = False
    note: str = ""

    def __post_init__(self):
        if self.target is not None and self.target not in targets.TARGETS:
            raise ValueError(f"Unknown tour target: {self.target}")
        unknown = set(self.advance_on) - TRIGGERS
        if unknown:
            raise ValueError(f"Unknown tour triggers: {sorted(unknown)}")


@dataclass(frozen=True)
class Tour:
    """A tour's steps, and the id its end is recorded under."""

    id: str
    title: str
    steps: tuple[Step, ...]


class TourRunner:
    """
    Plays one tour over win, until Done, Skip or Esc.

    One tour plays at a time: starting one ends the one playing. The
    tour sends the machine nothing; it only watches what the user does.
    """

    def __init__(self, win: "MainWindow", tour: Tour):
        self.win = win
        self.tour = tour
        self.index = -1
        self.mask = TourMask()
        self.shield = TourShield(targets.pass_through(win))
        self.bubble = TourBubble()
        self.bubble.back_button.connect("clicked", lambda b: self.back())
        self.bubble.skip_button.connect("clicked", lambda b: self.skip())
        self.bubble.next_button.connect("clicked", lambda b: self.next())
        # Esc ends the tour before anything in the window sees it.
        self.keys = Gtk.EventControllerKey(
            propagation_phase=Gtk.PropagationPhase.CAPTURE
        )
        self.keys.connect("key-pressed", self._on_key_pressed)
        self._tick_id: int | None = None
        self._handlers: list[tuple[GObject.Object, int]] = []
        self._doc: Doc | None = None
        # The item last taken out of the document, and its parent: an
        # item moved to another parent is taken from the old one just
        # before it is added to the new.
        self._removed: tuple = (None, None)
        self._machine: Machine | None = None
        # What the mask, shield and bubble show now: the hole, the
        # reason there is none, the overlay's size, and where the
        # controls the bubble keeps off are.
        self._layout: tuple | None = None
        self._scrolled = False
        self.suspended = False

    @property
    def active(self) -> bool:
        return self.win.tour is self

    @property
    def step(self) -> Step:
        return self.tour.steps[self.index]

    def start(self):
        if self.win.tour is not None:
            self.win.tour.stop()
        self.win.tour = self
        overlay = self.win.tour_overlay
        overlay.add_overlay(self.shield)
        overlay.add_overlay(self.mask)
        self.bubble.set_parent(self.mask)
        self.win.add_controller(self.keys)
        self._connect_signals()
        self._tick_id = self.win.add_tick_callback(self._on_tick)
        self._go(0)
        self._on_page_changed()

    def next(self):
        if self.index == len(self.tour.steps) - 1:
            self.finish()
        else:
            self._go(self.index + 1)

    def back(self):
        if self.index > 0:
            self._go(self.index - 1)

    def skip(self):
        """End the tour part way, with Skip or Esc."""
        self._end(TOUR_SEEN)

    def finish(self):
        """End the tour at its last step."""
        self._end(TOUR_COMPLETED)

    def stop(self):
        """Take the tour off the window, recording nothing."""
        if not self.active:
            return
        self.win.tour = None
        if self._tick_id is not None:
            self.win.remove_tick_callback(self._tick_id)
            self._tick_id = None
        self._disconnect_signals()
        self.win.remove_controller(self.keys)
        self.bubble.popdown()
        self.bubble.connection_status.set_machine(None)
        self.bubble.unparent()
        self.win.tour_overlay.remove_overlay(self.mask)
        self.win.tour_overlay.remove_overlay(self.shield)

    def _end(self, state: str):
        if not self.active:
            return
        get_context().config.mark_tour(self.tour.id, state)
        self.stop()

    def _go(self, index: int):
        self.index = index
        step = self.step
        if step.target is not None:
            targets.prepare(self.win, step.target)
        self.bubble.show_step(
            step.heading,
            step.body,
            index + 1,
            len(self.tour.steps),
            note=step.note,
        )
        self.bubble.connection_status.set_visible(step.connection_status)
        self.bubble.connection_status.set_machine(
            self._machine if step.connection_status else None
        )
        # Laid out afresh on the next frame, once prepare has shown
        # what it had to.
        self._layout = None
        self._scrolled = False

    # --- Layout, every frame ------------------------------------------

    def _on_tick(self, widget, clock):
        if not self.suspended:
            self._relayout()
        return GLib.SOURCE_CONTINUE

    def _relayout(self):
        """Move the hole and the bubble to the target, if it moved."""
        overlay = self.win.tour_overlay
        widget, reason = self._target()
        hole = None
        if widget is not None:
            if not self._scrolled:
                targets.scroll_into_view(widget)
                self._scrolled = True
            hole = target_hole(widget, overlay)
            if hole is None:
                reason = self._unavailable()
        keep_clear = self._keep_clear()
        layout = (
            hole,
            reason,
            overlay.get_width(),
            overlay.get_height(),
            keep_clear,
        )
        if layout != self._layout:
            self._layout = layout
            self.mask.set_hole(hole)
            self.shield.hole = hole
            self.bubble.set_reason(reason)
            self.bubble.point_at(hole, layout[2], layout[3], keep_clear)
            self.mask.queue_allocate()
        if not self.bubble.get_visible():
            self.bubble.popup()

    def _keep_clear(self) -> tuple[Rect, ...]:
        """
        Where the controls the shield lets through are, on or off: the
        bubble is a window above the shield, and one that is off now
        may turn on while the bubble stands.
        """
        rects = []
        for widget in self.shield.passes():
            if widget.get_mapped():
                bounds = bounds_in(widget, self.win.tour_overlay)
                if bounds is not None:
                    rects.append(bounds)
        return tuple(rects)

    def _target(self) -> tuple[Gtk.Widget | None, str]:
        """The step's target if it can be pointed at, else why not."""
        target_id = self.step.target
        if target_id is None:
            return None, ""
        widget = targets.find(self.win, target_id)
        if (
            widget is None
            or not widget.get_mapped()
            or not widget.is_sensitive()
            or widget.get_native() is not self.win
        ):
            return None, self._unavailable()
        return widget, ""

    def _unavailable(self) -> str:
        return self.step.unavailable or _(
            "This control is not available right now. Press Next to go on."
        )

    def _on_page_changed(self, *args):
        """
        Hide the tour while a page other than the main one shows, such
        as the Sketcher, and bring it back after.
        """
        suspended = self.win.main_stack.get_visible_child_name() != "main"
        if suspended == self.suspended:
            return
        self.suspended = suspended
        self.mask.set_visible(not suspended)
        self.shield.set_visible(not suspended)
        if suspended:
            self.bubble.popdown()
        self._layout = None

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        # A page the tour is hidden behind keeps its own Esc.
        if keyval != Gdk.KEY_Escape or self.suspended:
            return False
        # Not from inside the controller's own handler, which skip
        # removes from the window.
        GLib.idle_add(self._skip_once)
        return True

    def _skip_once(self) -> bool:
        self.skip()
        return GLib.SOURCE_REMOVE

    # --- Triggers -----------------------------------------------------

    def _fire(self, trigger: str, **details):
        """Move on if the step waits for this trigger and is done."""
        if not self.active or trigger not in self.step.advance_on:
            return
        done = self.step.done
        try:
            if done is not None and not done(self.win, **details):
                return
        except Exception:
            # It runs inside the signal; it must not break the sender.
            logger.exception("A tour step's done predicate failed")
            return
        # After the signal, not inside it: the next step's prepare may
        # rebuild what the signal is still being delivered to.
        GLib.idle_add(self._advance_from, self.index)

    def _advance_from(self, index: int) -> bool:
        if self.active and self.index == index:
            self.next()
        return GLib.SOURCE_REMOVE

    def _connect(self, source: GObject.Object, name: str, handler, *args):
        self._handlers.append((source, source.connect(name, handler, *args)))

    def _connect_signals(self):
        win = self.win
        config = get_context().config
        config.changed.connect(self._on_config_changed)
        win.doc_editor.document_changed.connect(self._on_document_changed)
        start_chosen.connect(self._on_start_chosen)
        self._bind_doc(win.doc_editor.doc)
        self._bind_machine(config.machine)

        jog = win.bottom_panel.jog_widget
        self._connect(jog.home_all_btn, "clicked", self._on_clicked, "home")
        for name in targets.JOG_ARROWS:
            self._connect(
                getattr(jog, name), "clicked", self._on_clicked, "jog"
            )
        self._connect(
            Gtk.Window.get_toplevels(),
            "items-changed",
            self._on_toplevels_changed,
        )
        self._connect(
            win.main_stack, "notify::visible-child-name", self._on_page_changed
        )
        self._connect(
            Adw.StyleManager.get_default(),
            "notify::dark",
            lambda *args: self.mask.queue_draw(),
        )
        # A window closed under a tour takes the tour with it. Its
        # destroy signal waits for the last reference to go; unrealize
        # comes as it is closed.
        self._connect(win, "unrealize", lambda *args: self.stop())

    def _disconnect_signals(self):
        config = get_context().config
        config.changed.disconnect(self._on_config_changed)
        self.win.doc_editor.document_changed.disconnect(
            self._on_document_changed
        )
        start_chosen.disconnect(self._on_start_chosen)
        self._bind_doc(None)
        self._bind_machine(None)
        for source, handler_id in self._handlers:
            source.disconnect(handler_id)
        self._handlers.clear()

    def _bind_doc(self, doc: "Doc | None"):
        if self._doc is not None:
            self._doc.descendant_added.disconnect(self._on_doc_added)
            self._doc.descendant_removed.disconnect(self._on_doc_removed)
            self._doc.descendant_updated.disconnect(self._on_doc_updated)
        self._doc = doc
        self._removed = (None, None)
        if doc is not None:
            doc.descendant_added.connect(self._on_doc_added)
            doc.descendant_removed.connect(self._on_doc_removed)
            doc.descendant_updated.connect(self._on_doc_updated)

    def _bind_machine(self, machine: "Machine | None"):
        if self._machine is not None:
            self._machine.connection_status_changed.disconnect(
                self._on_connection_changed
            )
            self._machine.changed.disconnect(self._on_machine_changed)
        self._machine = machine
        if machine is not None:
            machine.connection_status_changed.connect(
                self._on_connection_changed
            )
            machine.changed.connect(self._on_machine_changed)
        if self.index >= 0 and self.step.connection_status:
            self.bubble.connection_status.set_machine(machine)

    def _on_config_changed(self, sender, **details):
        machine = get_context().config.machine
        if machine is not self._machine:
            self._bind_machine(machine)

    def _on_document_changed(self, sender, **details):
        self._bind_doc(self.win.doc_editor.doc)

    def _on_doc_added(self, sender, **details):
        removed, parent = self._removed
        self._removed = (None, None)
        moved_from = parent if details.get("origin") is removed else None
        self._fire("doc-added", moved_from=moved_from, **details)

    def _on_doc_removed(self, sender, **details):
        self._removed = (
            details.get("origin"),
            details.get("parent_of_origin"),
        )

    def _on_doc_updated(self, sender, **details):
        self._fire("doc-updated", **details)

    def _on_connection_changed(self, sender, **details):
        self._fire("connection", **details)

    def _on_machine_changed(self, sender, **details):
        self._fire("machine", **details)

    def _on_start_chosen(self, sender, **details):
        if sender is self.win:
            self._fire("start", **details)

    def _on_clicked(self, button: Gtk.Button, trigger: str):
        self._fire(trigger, button=button)

    def _on_toplevels_changed(self, toplevels, position, removed, added):
        for index in range(position, position + added):
            self._fire("window", window=toplevels.get_item(index))

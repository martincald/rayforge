"""
What a tour step points at: one stable id per control the tours show.

The ids are the tour's own. Each is found again in the window as it is
now, every frame, by the action a toolbar button runs or the attribute
the window already keeps, so a tour survives a change of layout. The
layer cards are rebuilt on every change to the document's structure,
which is why the card a step points at is never kept.

A target may live in a part of the window that is hidden or scrolled
away; its prepare shows that part first.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gi.repository import GLib, Gtk

if TYPE_CHECKING:
    from ..mainwindow import MainWindow

Find = Callable[["MainWindow"], Gtk.Widget | None]


def _nothing(win: "MainWindow"):
    pass


@dataclass(frozen=True)
class Target:
    find: Find
    prepare: Callable[["MainWindow"], None] = _nothing


def _walk(widget: Gtk.Widget) -> Iterator[Gtk.Widget]:
    """
    Every descendant of widget in its own window, depth first.

    A popover is a window of its own, and a menu's holds a widget for
    every item; nothing in one can be pointed at.
    """
    child = widget.get_first_child()
    while child is not None:
        if not isinstance(child, Gtk.Native):
            yield child
            yield from _walk(child)
        child = child.get_next_sibling()


def _toolbar(action_name: str) -> Find:
    """The toolbar button that runs this action."""

    def find(win):
        for widget in _walk(win.toolbar):
            if (
                isinstance(widget, Gtk.Actionable)
                and widget.get_action_name() == action_name
            ):
                return widget
        return None

    return find


def _active_column(win: "MainWindow") -> Gtk.Widget | None:
    """The layer card column of the active layer, as built now."""
    layer = win.doc_editor.doc.active_layer
    column = win.bottom_panel.layers_tab.columns_box.get_first_child()
    while column is not None:
        if getattr(column, "layer", None) is layer:
            return column
        column = column.get_next_sibling()
    return None


def _in_active_column(attribute: str) -> Find:
    def find(win):
        column = _active_column(win)
        return getattr(column, attribute) if column is not None else None

    return find


def _jog(attribute: str) -> Find:
    return lambda win: getattr(win.bottom_panel.jog_widget, attribute)


def _step_switch(win: "MainWindow") -> Gtk.Widget | None:
    """The on/off switch of the first step in the step list."""
    row = win.workflowview.draglist.get_first_child()
    while row is not None:
        stepbox = getattr(row, "stepbox", None)
        if stepbox is not None:
            return stepbox.visibility_switch
        row = row.get_next_sibling()
    return None


def _show_panel(action_name: str):
    """Turn a panel's View toggle on, as the user would."""

    def show(win):
        action = win.action_manager.get_action(action_name)
        if not action.get_state().get_boolean():
            action.change_state(GLib.Variant.new_boolean(True))

    return show


_show_dock = _show_panel("toggle_bottom_panel")
_show_right_pane = _show_panel("toggle_right_panel")


def _dock_tab(name: str):
    """Show the dock, with this tab the one open in its area."""

    def prepare(win):
        _show_dock(win)
        area = win.bottom_panel.dock_layout.find_item_area(name)
        if area is not None:
            area.set_active_item(name)

    return prepare


TARGETS: dict[str, Target] = {
    "toolbar.import": Target(_toolbar("win.import")),
    "canvas": Target(lambda win: win.surface_overlay),
    "layers.tab": Target(
        lambda win: win.bottom_panel.layers_tab, _dock_tab("layers")
    ),
    "layers.active-card": Target(
        _in_active_column("card"), _dock_tab("layers")
    ),
    "layers.active-eye": Target(
        _in_active_column("visibility_button"), _dock_tab("layers")
    ),
    "layers.active-material": Target(
        _in_active_column("material_picker"), _dock_tab("layers")
    ),
    "pane.step-switch": Target(_step_switch, _show_right_pane),
    # Built only when the window opened with a machine.
    "dock.start-corner": Target(
        lambda win: getattr(win.bottom_panel, "start_corner_row", None),
        _dock_tab("controls"),
    ),
    "jog.pad": Target(
        lambda win: win.bottom_panel.jog_widget, _dock_tab("controls")
    ),
    "jog.home": Target(_jog("home_all_btn"), _dock_tab("controls")),
    "jog.go-scale": Target(_jog("go_scale_btn"), _dock_tab("controls")),
    "jog.cut-scale": Target(_jog("cut_scale_btn"), _dock_tab("controls")),
    "jog.start": Target(_jog("start_btn"), _dock_tab("controls")),
}

# The jog buttons that move the head, for a step that waits for a jog.
JOG_ARROWS = (
    "north_west_btn",
    "north_btn",
    "north_east_btn",
    "west_btn",
    "east_btn",
    "south_west_btn",
    "south_btn",
    "south_east_btn",
    "z_plus_btn",
    "z_minus_btn",
)


def find(win: "MainWindow", target_id: str) -> Gtk.Widget | None:
    return TARGETS[target_id].find(win)


def prepare(win: "MainWindow", target_id: str):
    TARGETS[target_id].prepare(win)


def scroll_into_view(widget: Gtk.Widget):
    """Scroll every scroller widget sits in until it shows."""
    viewport = widget.get_ancestor(Gtk.Viewport)
    while viewport is not None:
        viewport.scroll_to(widget, None)
        parent = viewport.get_parent()
        viewport = parent.get_ancestor(Gtk.Viewport) if parent else None


def pass_through(win: "MainWindow") -> Callable[[], list[Gtk.Widget]]:
    """
    The controls no tour ever covers: Stop and Pause in the dock and
    the toolbar, Go Scale while it is the Stop of a running scale, and
    the window's own buttons.

    They are built with the window and never rebuilt, so they are
    found once; the function returned lists them as they stand now.
    """
    jog = win.bottom_panel.jog_widget
    fixed = [jog.stop_btn, jog.pause_btn]
    for action_name in ("win.machine-cancel", "win.machine-hold"):
        button = _toolbar(action_name)(win)
        if button is not None:
            fixed.append(button)
    fixed.extend(
        widget
        for widget in _walk(win.header_bar)
        if isinstance(widget, Gtk.WindowControls)
    )

    def now() -> list[Gtk.Widget]:
        if jog.go_scale_btn.has_css_class("destructive-action"):
            return [*fixed, jog.go_scale_btn]
        return fixed

    return now

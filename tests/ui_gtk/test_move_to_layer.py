# flake8: noqa: E402
"""
Right-click a shape on the canvas, or its row in the layers panel:
"Move to Layer" lists every layer in document order and moves the whole
selection there, in one undo step.
"""

import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

if sys.platform.startswith("linux"):
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    if not os.environ.get("DISPLAY"):
        pytest.skip(
            "DISPLAY not set on Linux, skipping UI tests. Run with xvfb-run.",
            allow_module_level=True,
        )

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib
from raygeo.geo import Geometry

from swiftcut.core.layer import Layer
from swiftcut.core.workpiece import WorkPiece
from swiftcut.ui_gtk.canvas2d import context_menu
from swiftcut.ui_gtk.mainwindow import MainWindow

pytestmark = pytest.mark.ui


def _iterate(duration: float = 0.2):
    """Runs the main loop for a while."""
    context = GLib.main_context_default()
    end = time.monotonic() + duration
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


@pytest.fixture
def win(ui_context_initializer, request):
    """The main window; its active layer is renamed A, and layers B and
    C come after the document's own."""

    class TestApp(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)
            self.win.set_default_size(1280, 800)

    test_name = request.node.name.replace("_", "-")
    app = TestApp(application_id=f"org.swiftcut.swiftcut.test.{test_name}")
    app.register(None)
    app.activate()
    window = app.win
    window.present()
    _iterate(0.5)

    doc = window.doc_editor.doc
    doc.active_layer.set_name("A")
    doc.add_child(Layer(name="B"))
    doc.add_child(Layer(name="C"))
    _iterate()

    yield window

    window.doc_editor.cleanup()
    # The document has unsaved changes: closing would leave an Unsaved
    # Changes dialog open for the tests after this one.
    window.destroy()
    app.quit()
    _iterate()


def _layer(win, name) -> Layer:
    return next(lyr for lyr in win.doc_editor.doc.layers if lyr.name == name)


def _shape(win, layer_name, pos=(50, 50)) -> WorkPiece:
    """A 20 mm square on the named layer."""
    geo = Geometry()
    geo.move_to(0.0, 0.0)
    geo.line_to(1.0, 0.0)
    geo.line_to(1.0, 1.0)
    geo.line_to(0.0, 1.0)
    geo.close_path()
    wp = WorkPiece(name="square")
    wp._edited_boundaries = geo
    wp.set_size(20, 20)
    wp.pos = pos
    _layer(win, layer_name).add_child(wp)
    _iterate()
    return wp


def _submenu(menu: Gio.MenuModel, label: str) -> Gio.MenuModel | None:
    """The submenu of the top-level entry with this label."""
    for i in range(menu.get_n_items()):
        value = menu.get_item_attribute_value(
            i, Gio.MENU_ATTRIBUTE_LABEL, GLib.VariantType.new("s")
        )
        if value is not None and value.get_string() == label:
            return menu.get_item_link(i, Gio.MENU_LINK_SUBMENU)
    return None


def _entries(submenu: Gio.MenuModel) -> list[tuple[str, str, str]]:
    """(label, action, layer UID) of each entry."""
    entries = []
    string = GLib.VariantType.new("s")
    for i in range(submenu.get_n_items()):
        label = submenu.get_item_attribute_value(
            i, Gio.MENU_ATTRIBUTE_LABEL, string
        )
        action = submenu.get_item_attribute_value(
            i, Gio.MENU_ATTRIBUTE_ACTION, string
        )
        target = submenu.get_item_attribute_value(
            i, Gio.MENU_ATTRIBUTE_TARGET, string
        )
        entries.append(
            (label.get_string(), action.get_string(), target.get_string())
        )
    return entries


def _canvas_menu(win, item) -> Gio.MenuModel:
    """The menu a right-click on a shape on the canvas shows."""
    with patch.object(context_menu, "_show_popover") as show:
        context_menu.show_item_context_menu(
            win.surface, MagicMock(), item=item
        )
    return show.call_args.args[2]


def _column(win, layer_name):
    tab = win.bottom_panel.layers_tab
    return next(c for c in tab._columns if c.layer.name == layer_name)


def _panel_menu(win, item) -> Gio.MenuModel:
    """The menu a right-click on the item's row in the layers panel
    shows, after the click selected that row."""
    column = _column(win, item.layer.name)
    column.select_items_requested.send(column, items=[item], extend=False)
    _iterate()
    with patch.object(column, "_popup_context_menu") as popup:
        column._show_item_context_menu(MagicMock())
    return popup.call_args.args[0]


def _choose(win, submenu: Gio.MenuModel, layer_name: str):
    """Activates the submenu's entry for the named layer."""
    for label, action, uid in _entries(submenu):
        if label == layer_name:
            win.activate_action(action, GLib.Variant.new_string(uid))
            _iterate()
            return
    raise AssertionError(f"no entry for {layer_name}")


class TestTheCanvasMenu:
    def test_lists_every_layer_in_order_hidden_ones_too(self, win):
        wp = _shape(win, "A")
        _layer(win, "C").set_visible(False)
        win.surface.select_items([wp])

        menu = _canvas_menu(win, wp)

        entries = _entries(_submenu(menu, "Move to Layer"))
        assert entries == [
            (layer.name, "win.move-to-layer", layer.uid)
            for layer in win.doc_editor.doc.layers
        ]
        assert [e[0] for e in entries][-2:] == ["B", "C"]
        # The neighbour moves stay beside it.
        labels = [
            menu.get_item_attribute_value(
                i, Gio.MENU_ATTRIBUTE_LABEL, GLib.VariantType.new("s")
            )
            for i in range(3)
        ]
        assert [v.get_string() for v in labels] == [
            "Move Up a Layer",
            "Move Down a Layer",
            "Move to Layer",
        ]

    def test_moves_the_whole_selection_in_one_undo_step(self, win):
        wp1 = _shape(win, "A", (20, 20))
        wp2 = _shape(win, "A", (80, 20))
        win.surface.select_items([wp1, wp2])
        _iterate()
        history = win.doc_editor.history_manager
        before = len(history.undo_stack)

        _choose(win, _submenu(_canvas_menu(win, wp1), "Move to Layer"), "B")

        assert wp1.layer is _layer(win, "B")
        assert wp2.layer is _layer(win, "B")
        assert set(win.surface.get_selected_items()) == {wp1, wp2}
        assert len(history.undo_stack) == before + 1

        history.undo()
        assert wp1.layer is _layer(win, "A")
        assert wp2.layer is _layer(win, "A")

    def test_a_selection_on_two_layers_moves_and_undoes_at_once(self, win):
        on_a = _shape(win, "A", (20, 20))
        on_c = _shape(win, "C", (80, 20))
        win.surface.select_items([on_a, on_c])
        _iterate()
        history = win.doc_editor.history_manager
        before = len(history.undo_stack)

        _choose(win, _submenu(_canvas_menu(win, on_a), "Move to Layer"), "B")

        assert on_a.layer is _layer(win, "B")
        assert on_c.layer is _layer(win, "B")
        assert len(history.undo_stack) == before + 1

        history.undo()
        assert on_a.layer is _layer(win, "A")
        assert on_c.layer is _layer(win, "C")

    def test_its_own_layer_changes_nothing(self, win):
        wp = _shape(win, "A")
        win.surface.select_items([wp])
        _iterate()
        history = win.doc_editor.history_manager
        before = len(history.undo_stack)

        _choose(win, _submenu(_canvas_menu(win, wp), "Move to Layer"), "A")

        assert wp.layer is _layer(win, "A")
        assert len(history.undo_stack) == before


class TestThePanelMenu:
    def test_has_the_same_submenu(self, win):
        wp = _shape(win, "A")

        menu = _panel_menu(win, wp)

        assert _entries(_submenu(menu, "Move to Layer")) == _entries(
            context_menu.build_move_to_layer_menu(win.doc_editor.doc)
        )

    def test_moves_the_rows_selection_in_one_undo_step(self, win):
        wp1 = _shape(win, "A", (20, 20))
        wp2 = _shape(win, "A", (80, 20))
        win.surface.select_items([wp1, wp2])
        _iterate()
        history = win.doc_editor.history_manager
        before = len(history.undo_stack)

        # A right-click on a row that is already selected keeps the
        # selection, so both rows move.
        column = _column(win, "A")
        assert wp1.uid in column._selected_uids
        with patch.object(column, "_popup_context_menu") as popup:
            column._show_item_context_menu(MagicMock())
        _choose(win, _submenu(popup.call_args.args[0], "Move to Layer"), "C")

        assert wp1.layer is _layer(win, "C")
        assert wp2.layer is _layer(win, "C")
        assert len(history.undo_stack) == before + 1

        history.undo()
        assert wp1.layer is _layer(win, "A")
        assert wp2.layer is _layer(win, "A")

    def test_a_right_clicked_row_moves(self, win):
        wp = _shape(win, "A")
        _shape(win, "A", (80, 20))

        _choose(win, _submenu(_panel_menu(win, wp), "Move to Layer"), "B")

        assert wp.layer is _layer(win, "B")

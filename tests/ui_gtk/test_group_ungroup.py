# flake8: noqa: E402
"""
Group takes two or more shapes on one layer; Ungroup dissolves a group
or splits a shape into its paths. Both are on the right-click menu of a
shape, also when the click lands on one of its paths.
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

from swiftcut.core.group import Group
from swiftcut.core.layer import Layer
from swiftcut.core.workpiece import WorkPiece
from swiftcut.shared.tasker import task_mgr
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


def _iterate_until_idle(timeout: float = 10.0):
    """Runs the main loop until no task is left."""
    deadline = time.monotonic() + timeout
    while task_mgr.has_tasks():
        assert time.monotonic() < deadline, "tasks did not finish"
        _iterate(0.05)
    _iterate()


@pytest.fixture
def win(ui_context_initializer, request):
    """The main window, with a second layer B."""

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

    window.doc_editor.doc.add_child(Layer(name="B"))
    _iterate()

    yield window

    window.doc_editor.cleanup()
    # The document has unsaved changes: closing would leave an Unsaved
    # Changes dialog open for the tests after this one.
    window.destroy()
    app.quit()
    _iterate()


def _rect(geo, x0, y0, x1, y1):
    geo.move_to(x0, y0)
    geo.line_to(x1, y0)
    geo.line_to(x1, y1)
    geo.line_to(x0, y1)
    geo.close_path()


def _shape(layer, pos, paths=1) -> WorkPiece:
    """A 20 mm shape of a square, plus a line when paths is 2."""
    geo = Geometry()
    _rect(geo, 0.0, 0.0, 0.5, 1.0)
    if paths == 2:
        geo.move_to(0.8, 0.0)
        geo.line_to(1.0, 1.0)
    wp = WorkPiece(name="shape")
    wp._edited_boundaries = geo
    wp.set_size(20, 20)
    wp.pos = pos
    layer.add_child(wp)
    _iterate()
    return wp


def _enabled(win, name) -> bool:
    return win.action_manager.get_action(name).get_enabled()


def _actions(menu: Gio.MenuModel) -> list[str]:
    """Every action in the menu, its sections and submenus, in order."""
    actions = []
    string = GLib.VariantType.new("s")
    for i in range(menu.get_n_items()):
        action = menu.get_item_attribute_value(
            i, Gio.MENU_ATTRIBUTE_ACTION, string
        )
        if action is not None:
            actions.append(action.get_string())
        for link in (Gio.MENU_LINK_SECTION, Gio.MENU_LINK_SUBMENU):
            linked = menu.get_item_link(i, link)
            if linked is not None:
                actions.extend(_actions(linked))
    return actions


def _screen(win, wp, local_x, local_y):
    """A point in the shape's local space, on screen."""
    surface = win.surface
    elem = surface.find_by_data(wp)
    to_screen = surface.view_transform @ elem.get_world_transform()
    return to_screen.transform_point((local_x, local_y))


class TestThePathMenu:
    def test_has_group_ungroup_and_add_tab(self, win):
        wp = _shape(win.doc_editor.doc.active_layer, (50, 50))

        with patch.object(context_menu, "_show_popover") as show:
            context_menu.show_geometry_context_menu(
                win.surface, MagicMock(), item=wp
            )

        actions = _actions(show.call_args.args[2])
        assert actions[0] == "win.tab-add"
        for action in ("win.group", "win.ungroup", "win.move-to-layer"):
            assert action in actions

    def test_a_right_click_on_a_path_selects_its_shape(self, win):
        layer = win.doc_editor.doc.active_layer
        other = _shape(layer, (10, 10))
        wp = _shape(layer, (50, 50), paths=2)
        win.surface.select_items([other])
        _iterate()
        # On the square's left edge, a hair inside: a point exactly on
        # the frame can round to just outside it at some zoom levels.
        x, y = _screen(win, wp, 0.01, 0.5)

        with patch.object(context_menu, "_show_popover") as show:
            win.surface.on_right_click_pressed(MagicMock(), 1, x, y)
        _iterate()

        assert win.surface.right_click_context["type"] == "geometry"
        assert list(win.surface.get_selected_items()) == [wp]
        actions = _actions(show.call_args.args[2])
        assert "win.tab-add" in actions and "win.ungroup" in actions
        assert _enabled(win, "tab-add")
        assert _enabled(win, "ungroup")

    def test_a_right_click_on_a_selected_path_keeps_the_selection(self, win):
        layer = win.doc_editor.doc.active_layer
        a = _shape(layer, (10, 10))
        b = _shape(layer, (50, 50))
        win.surface.select_items([a, b])
        _iterate()
        x, y = _screen(win, b, 0.01, 0.5)

        with patch.object(context_menu, "_show_popover"):
            win.surface.on_right_click_pressed(MagicMock(), 1, x, y)
        _iterate()

        assert win.surface.right_click_context["type"] == "geometry"
        assert set(win.surface.get_selected_items()) == {a, b}
        assert _enabled(win, "group")


class TestSensitivity:
    def test_group_needs_two_shapes_on_one_layer(self, win):
        doc = win.doc_editor.doc
        layer_b = next(lyr for lyr in doc.layers if lyr.name == "B")
        a = _shape(doc.active_layer, (10, 10))
        b = _shape(doc.active_layer, (50, 10))
        on_b = _shape(layer_b, (90, 10))

        win.surface.select_items([a])
        _iterate()
        assert not _enabled(win, "group")

        win.surface.select_items([a, b])
        _iterate()
        assert _enabled(win, "group")

        win.surface.select_items([a, on_b])
        _iterate()
        assert not _enabled(win, "group")

    def test_ungroup_needs_a_group_or_a_shape_of_several_paths(self, win):
        layer = win.doc_editor.doc.active_layer
        single = _shape(layer, (10, 10))
        several = _shape(layer, (50, 10), paths=2)

        win.surface.select_items([single])
        _iterate()
        assert not _enabled(win, "ungroup")

        win.surface.select_items([several])
        _iterate()
        assert _enabled(win, "ungroup")


class TestTheActions:
    def test_group_selects_the_new_group(self, win):
        layer = win.doc_editor.doc.active_layer
        a = _shape(layer, (10, 10))
        b = _shape(layer, (50, 10))
        win.surface.select_items([a, b])
        _iterate()

        win.activate_action("win.group", None)
        _iterate_until_idle()

        (group,) = layer.get_content_items()
        assert isinstance(group, Group)
        assert list(win.surface.get_selected_items()) == [group]
        assert _enabled(win, "ungroup")

    def test_ungroup_selects_the_pieces_in_one_undo_step(self, win):
        layer = win.doc_editor.doc.active_layer
        wp = _shape(layer, (50, 10), paths=2)
        win.surface.select_items([wp])
        _iterate()
        history = win.doc_editor.history_manager
        entries = len(history.undo_stack)

        win.activate_action("win.ungroup", None)
        _iterate()

        pieces = layer.get_content_items()
        assert len(pieces) == 2 and wp not in pieces
        assert set(win.surface.get_selected_items()) == set(pieces)
        assert len(history.undo_stack) == entries + 1

        history.undo()
        _iterate()
        assert layer.get_content_items() == [wp]

# flake8: noqa: E402
"""
Right-click a shape on the canvas: the menu's Select section picks
shapes for fixing an import by hand. Select Inside takes the selected
closed shapes; Select Similar and Select All on This Layer the
right-clicked shape. Each replaces the selection, and none ever picks a
hidden layer's shapes.
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
    H, hidden, come after the document's own."""

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
    hidden = doc.add_child(Layer(name="H"))
    window.doc_editor.layer.set_layer_visibility(hidden, False)
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


def _shape(win, layer_name, pos, size=(10, 10), geo=None, **source):
    """A shape of the given world box on the named layer; a closed
    square unless geo says otherwise."""
    if geo is None:
        geo = Geometry()
        geo.move_to(0.0, 0.0)
        geo.line_to(1.0, 0.0)
        geo.line_to(1.0, 1.0)
        geo.line_to(0.0, 1.0)
        geo.close_path()
    wp = WorkPiece(name="shape")
    wp._edited_boundaries = geo
    wp.set_size(*size)
    wp.pos = pos
    for name, value in source.items():
        setattr(wp, name, value)
    _layer(win, layer_name).add_child(wp)
    _iterate()
    return wp


def _right_click(win, item, local=(0.5, 0.5)) -> Gio.MenuModel:
    """Right-clicks the item on the canvas at a point in its own unit
    box; returns the menu it shows."""
    s = win.surface
    to_screen = s.view_transform @ s.find_by_data(item).get_world_transform()
    x, y = to_screen.transform_point(local)
    with patch.object(context_menu, "_show_popover") as show:
        s.on_right_click_pressed(MagicMock(), 1, x, y)
    _iterate()
    return show.call_args.args[2]


def _enabled(win, name) -> bool:
    return win.action_manager.get_action(name).get_enabled()


def _activate(win, name):
    win.activate_action(f"win.{name}", None)
    _iterate()


def _selected(win):
    return set(win.surface.get_selected_items())


def _labels(menu: Gio.MenuModel) -> list[tuple[str | None, str | None]]:
    """(label, action) of each entry; a section has neither."""
    string = GLib.VariantType.new("s")
    entries = []
    for i in range(menu.get_n_items()):
        label = menu.get_item_attribute_value(
            i, Gio.MENU_ATTRIBUTE_LABEL, string
        )
        action = menu.get_item_attribute_value(
            i, Gio.MENU_ATTRIBUTE_ACTION, string
        )
        entries.append(
            (
                label.get_string() if label else None,
                action.get_string() if action else None,
            )
        )
    return entries


class TestTheMenu:
    def test_ends_with_the_select_section(self, win):
        wp = _shape(win, "A", (50, 50))

        menu = _right_click(win, wp)

        last = menu.get_n_items() - 1
        section = menu.get_item_link(last, Gio.MENU_LINK_SECTION)
        assert _labels(section) == [
            ("Select Inside", "win.select-inside"),
            ("Select Similar", None),
            ("Select All on This Layer", "win.select-all-on-layer"),
        ]
        similar = section.get_item_link(1, Gio.MENU_LINK_SUBMENU)
        assert _labels(similar) == [
            ("By Color", "win.select-similar-color"),
            ("By Source Layer", "win.select-similar-layer"),
            ("By Size", "win.select-similar-size"),
        ]
        # The standard items stay first.
        assert [label for label, _ in _labels(menu)[:3]] == [
            "Move Up a Layer",
            "Move Down a Layer",
            "Move to Layer",
        ]


class TestSelectInside:
    def test_replaces_the_selection_with_the_shapes_inside(self, win):
        plate = _shape(win, "A", (20, 20), (100, 100))
        inside = _shape(win, "A", (40, 40))
        on_b_inside = _shape(win, "B", (80, 80))
        outside = _shape(win, "A", (150, 40))
        hidden_inside = _shape(win, "H", (60, 90))

        # A right-click on the unselected plate, inside its outline.
        _right_click(win, plate, (0.05, 0.5))
        assert _selected(win) == {plate}
        assert _enabled(win, "select-inside")

        _activate(win, "select-inside")

        assert _selected(win) == {inside, on_b_inside}
        assert outside not in _selected(win)
        assert hidden_inside not in _selected(win)

    def test_is_disabled_for_open_lines(self, win):
        line = Geometry()
        line.move_to(0.0, 0.0)
        line.line_to(1.0, 1.0)
        open_shape = _shape(win, "A", (20, 20), (100, 100), line)
        _shape(win, "A", (60, 30))
        win.surface.select_items([open_shape])
        _iterate()

        assert not _enabled(win, "select-inside")


class TestSelectSimilar:
    def test_by_color(self, win):
        red = _shape(win, "A", (20, 20), source_color="#ff0000")
        red_on_b = _shape(win, "B", (60, 20), source_color="#ff0000")
        _shape(win, "A", (100, 20), source_color="#000000")
        _shape(win, "H", (140, 20), source_color="#ff0000")

        _right_click(win, red)
        assert _enabled(win, "select-similar-color")
        _activate(win, "select-similar-color")

        assert _selected(win) == {red, red_on_b}

    def test_by_color_is_disabled_without_one(self, win):
        plain = _shape(win, "A", (20, 20))

        _right_click(win, plain)

        assert not _enabled(win, "select-similar-color")
        assert not _enabled(win, "select-similar-layer")
        assert _enabled(win, "select-similar-size")
        assert _enabled(win, "select-all-on-layer")

    def test_by_source_layer(self, win):
        cut = _shape(win, "A", (20, 20), source_layer="Cut")
        cut_on_b = _shape(win, "B", (60, 20), source_layer="Cut")
        _shape(win, "A", (100, 20), source_layer="Engrave")
        _shape(win, "H", (140, 20), source_layer="Cut")

        _right_click(win, cut)
        assert _enabled(win, "select-similar-layer")
        _activate(win, "select-similar-layer")

        assert _selected(win) == {cut, cut_on_b}

    def test_by_size(self, win):
        reference = _shape(win, "A", (20, 20), (10, 10))
        bigger = _shape(win, "B", (40, 20), (12, 10))
        _shape(win, "A", (60, 20), (13, 10))
        _shape(win, "H", (80, 20), (10, 10))

        _right_click(win, reference)
        _activate(win, "select-similar-size")

        assert _selected(win) == {reference, bigger}


class TestSelectAllOnThisLayer:
    def test_selects_the_right_clicked_shapes_layer(self, win):
        first = _shape(win, "A", (20, 20))
        second = _shape(win, "A", (60, 20))
        _shape(win, "B", (100, 20))

        _right_click(win, first)
        _activate(win, "select-all-on-layer")

        assert _selected(win) == {first, second}

    def test_is_disabled_once_that_layer_is_hidden(self, win):
        first = _shape(win, "A", (20, 20))
        _shape(win, "B", (60, 20))
        _right_click(win, first)

        win.doc_editor.layer.set_layer_visibility(_layer(win, "A"), False)
        _iterate()

        assert not _enabled(win, "select-all-on-layer")
        _activate(win, "select-all-on-layer")
        assert _selected(win) == set()

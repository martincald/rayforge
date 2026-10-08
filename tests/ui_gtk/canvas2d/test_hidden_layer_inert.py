"""A hidden layer is inert: its shapes cannot be hit, selected (click,
rubber band, double-click, right-click, select all, a panel row), show
no selection box, cannot be dragged or nudged, and nothing is pasted or
duplicated into it. Hiding a layer drops its shapes from the selection;
shapes on other layers stay selected.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from gi.repository import Gdk, Gtk
from raygeo.geo import Geometry

from swiftcut.core.layer import Layer
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.canvas.region import ElementRegion
from swiftcut.ui_gtk.canvas2d import context_menu
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface
from swiftcut.ui_gtk.mainwindow import MainWindow

pytestmark = pytest.mark.ui


def _square():
    """A closed square filling the workpiece's box."""
    geo = Geometry()
    geo.move_to(0.0, 0.0)
    geo.line_to(1.0, 0.0)
    geo.line_to(1.0, 1.0)
    geo.line_to(0.0, 1.0)
    geo.close_path()
    return geo


@pytest.fixture
def surface(ui_context_initializer, ui_task_mgr):
    """A real editor and an 800x600 surface with layers A (active) and
    B; returns them with a function adding a square to a layer."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    s = WorkSurface(editor, Gtk.Window(), machine)
    s.get_width = lambda: 800
    s.get_height = lambda: 600
    s._rebuild_view_transform()
    layer_a = editor.doc.active_layer
    layer_b = Layer(name="B")
    editor.doc.add_child(layer_b)
    s.update_from_doc()

    def add(layer, pos):
        wp = WorkPiece(name="square")
        wp._edited_boundaries = _square()
        wp.set_size(40, 30)
        wp.pos = pos
        layer.add_child(wp)
        s.update_from_doc()
        assert s.find_by_data(wp) is not None
        return wp

    yield editor, s, layer_a, layer_b, add

    editor.cleanup()


def _hide(editor, layer):
    """The eye button's path: an undoable visibility change."""
    editor.layer.set_layer_visibility(layer, False)


def _screen(s, wp, local_x, local_y):
    """A point in the shape's local space, on screen."""
    elem = s.find_by_data(wp)
    to_screen = s.view_transform @ elem.get_world_transform()
    return to_screen.transform_point((local_x, local_y))


def _hover(s, x, y):
    s._update_hover_state(*s._get_world_coords(x, y))
    return s._hovered_region, s._hovered_elem


def _press(s, x, y, n_press=1):
    gesture = MagicMock()
    gesture.get_current_event.return_value = None
    gesture.get_button.return_value = Gdk.BUTTON_PRIMARY
    gesture.get_start_point.return_value = (True, x, y)
    s._drag_gesture = gesture
    s.on_button_press(gesture, n_press, x, y)
    return gesture


def _click(s, x, y):
    gesture = _press(s, x, y)
    s.on_click_released(gesture, 1, x, y)


def _selected(s):
    return set(s.get_selected_items())


class TestNotHit:
    def test_the_pointer_finds_nothing(self, surface):
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        inside = _screen(s, wp, 0.5, 0.5)
        stroke = _screen(s, wp, 0.0, 0.5)
        assert _hover(s, *inside) == (ElementRegion.BODY, s.find_by_data(wp))

        _hide(editor, layer_a)

        assert _hover(s, *inside) == (ElementRegion.NONE, None)
        assert _hover(s, *stroke) == (ElementRegion.NONE, None)
        world = s._get_world_coords(*inside)
        assert s.root.get_elem_hit(*world) is not s.find_by_data(wp)

    def test_a_click_does_not_select_it(self, surface):
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        _hide(editor, layer_a)

        _click(s, *_screen(s, wp, 0.5, 0.5))

        assert _selected(s) == set()

    def test_a_double_click_does_not_edit_it(self, surface):
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        _hide(editor, layer_a)

        _press(s, *_screen(s, wp, 0.0, 0.5), n_press=2)

        assert s.edit_context is None
        assert _selected(s) == set()

    def test_a_right_click_shows_the_empty_canvas_menu(self, surface):
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        _hide(editor, layer_a)

        with (
            patch.object(context_menu, "show_item_context_menu") as item,
            patch.object(
                context_menu, "show_background_context_menu"
            ) as background,
        ):
            s.on_right_click_pressed(MagicMock(), 1, *_screen(s, wp, 0.5, 0.5))

        item.assert_not_called()
        background.assert_called_once()
        assert s.right_click_context is None
        assert _selected(s) == set()


class TestNotSelectable:
    def test_a_rubber_band_passes_over_it(self, surface):
        editor, s, layer_a, layer_b, add = surface
        hidden = add(layer_a, (60, 50))
        shown = add(layer_b, (110, 50))
        _hide(editor, layer_a)
        left, top = _screen(s, hidden, 0.0, 1.0)
        right, bottom = _screen(s, shown, 1.0, 0.0)

        gesture = _press(s, left - 30, top - 30)
        s.on_mouse_drag(gesture, right - left + 60, bottom - top + 60)

        assert s._framing_selection
        assert _selected(s) == {shown}

    def test_select_all_leaves_it_out(self, surface):
        editor, s, layer_a, layer_b, add = surface
        hidden = add(layer_a, (60, 50))
        shown = add(layer_b, (110, 50))
        _hide(editor, layer_a)

        s.select_all()

        assert _selected(s) == {shown}
        assert hidden not in _selected(s)

    def test_a_panel_row_click_selects_nothing(self, surface):
        """A row click in the layers panel goes through select_items."""
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        _hide(editor, layer_a)

        s.select_items([wp])

        assert _selected(s) == set()


class TestHidingDropsItsSelection:
    def test_only_its_shapes_leave_the_selection(self, surface):
        editor, s, layer_a, layer_b, add = surface
        on_a = add(layer_a, (60, 50))
        on_b = add(layer_b, (110, 50))
        s.select_items([on_a, on_b])
        assert s._selection_group is not None
        sent = []

        def on_selection_changed(sender, elements, **kwargs):
            sent.append(elements)

        s.selection_changed.connect(on_selection_changed)

        _hide(editor, layer_a)

        assert _selected(s) == {on_b}
        assert s._selection_group is None
        assert [e.data for e in sent[-1]] == [on_b]

    def test_no_selection_box_is_drawn(self, surface):
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        s.select_items([wp])
        elem = s.find_by_data(wp)

        with patch.object(s, "_draw_selection_frame") as frame:
            s._render_selection_overlay(MagicMock(), s.root)
        assert [c.args[1] for c in frame.call_args_list] == [elem]

        _hide(editor, layer_a)

        with (
            patch.object(s, "_draw_selection_frame") as frame,
            patch.object(s, "_render_multi_selection_overlay") as multi,
        ):
            s._render_selection_overlay(MagicMock(), s.root)
        frame.assert_not_called()
        multi.assert_not_called()

    def test_hiding_while_editing_a_shape_leaves_edit_mode(self, surface):
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        s.enter_edit_mode(s.find_by_data(wp))
        assert s.edit_context is not None

        _hide(editor, layer_a)

        assert s.edit_context is None
        assert _selected(s) == set()


class TestNotMoved:
    def test_a_drag_does_not_move_it(self, surface):
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        _hide(editor, layer_a)
        start = wp.matrix.get_translation()
        x, y = _screen(s, wp, 0.0, 0.5)

        gesture = _press(s, x, y)
        s.on_mouse_drag(gesture, 30, -20)
        s.on_drag_end(gesture, 30, -20)

        assert wp.matrix.get_translation() == pytest.approx(start)
        assert _selected(s) == set()

    def test_an_arrow_key_does_not_nudge_it(self, surface):
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        s.select_items([wp])
        _hide(editor, layer_a)
        start = wp.matrix.get_translation()

        s.on_key_pressed(MagicMock(), Gdk.KEY_Right, 0, Gdk.ModifierType(0))

        assert wp.matrix.get_translation() == pytest.approx(start)


class TestShownAgain:
    def test_showing_the_layer_makes_it_selectable(self, surface):
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        _hide(editor, layer_a)
        editor.layer.set_layer_visibility(layer_a, True)

        _click(s, *_screen(s, wp, 0.5, 0.5))

        assert _selected(s) == {wp}

    def test_undoing_the_hide_makes_it_selectable(self, surface):
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        _hide(editor, layer_a)

        editor.history_manager.undo()

        assert layer_a.visible
        s.select_items([wp])
        assert _selected(s) == {wp}

    def test_a_shape_moved_onto_a_hidden_layer_is_selectable_once_shown(
        self, surface
    ):
        editor, s, layer_a, layer_b, add = surface
        wp = add(layer_a, (60, 50))
        _hide(editor, layer_b)
        editor.layer.move_items_to_layer([wp], layer_b)
        s.select_items([wp])
        assert _selected(s) == set()

        editor.layer.set_layer_visibility(layer_b, True)
        s.select_items([wp])

        assert _selected(s) == {wp}


class TestNothingGoesIn:
    """The window's paste and duplicate handlers, on a hidden active
    layer: refused with a notice, and the selection is kept."""

    def _window(self, editor, s):
        return SimpleNamespace(
            doc_editor=editor,
            surface=s,
            drag_drop_cmd=MagicMock(),
            _update_actions_and_ui=MagicMock(),
        )

    def test_paste_is_refused_with_a_notice(self, surface):
        editor, s, layer_a, _, add = surface
        wp = add(layer_a, (60, 50))
        editor.edit.copy_items([wp])
        _hide(editor, layer_a)
        window = self._window(editor, s)
        notices = []

        def on_notice(sender, message, **kwargs):
            notices.append(message)

        editor.notification_requested.connect(on_notice)
        undo_depth = len(editor.history_manager.undo_stack)

        MainWindow.on_paste_requested(window, s)

        # Not even an image on the system clipboard goes in.
        window.drag_drop_cmd.handle_clipboard_paste.assert_not_called()
        assert layer_a.workpieces == [wp]
        assert len(editor.history_manager.undo_stack) == undo_depth
        assert len(notices) == 1 and "hidden" in notices[0]

    def test_duplicate_is_refused_and_keeps_the_selection(self, surface):
        editor, s, layer_a, layer_b, add = surface
        wp = add(layer_b, (110, 50))
        # The active layer, A, is hidden; the selection is on B.
        _hide(editor, layer_a)
        s.select_items([wp])
        window = self._window(editor, s)
        notices = []

        def on_notice(sender, message, **kwargs):
            notices.append(message)

        editor.notification_requested.connect(on_notice)

        MainWindow.on_menu_duplicate(window, None, None)

        assert layer_a.workpieces == []
        assert layer_b.workpieces == [wp]
        assert _selected(s) == {wp}
        assert len(notices) == 1 and "hidden" in notices[0]

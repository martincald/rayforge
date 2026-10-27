"""A group across layers is selected as one: a click, shift-click,
frame, lasso or select_items on one member selects all its members on
visible layers, and a drag moves them all in one undo step. A double-
click enters the group: there one member is selected and moved alone,
until Escape, a click outside, a new document or the last visible member
going ends it. A hidden member is inert but moves with its group, and a
moving group snaps as one object. Ctrl+Page Down moves the whole group
to the next layer, inside a group only the selected member.
"""

from unittest.mock import MagicMock, patch

import pytest
from gi.repository import Gdk, Gtk
from raygeo.geo import Geometry

from swiftcut.core.doc import Doc
from swiftcut.core.layer import Layer
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.canvas.region import ElementRegion
from swiftcut.ui_gtk.canvas2d import surface as surface_module
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface
from swiftcut.ui_gtk.shared.keyboard import PRIMARY_MODIFIER_MASK

pytestmark = pytest.mark.ui

NO_MODS = Gdk.ModifierType(0)


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
    """A real editor and an 800x600 surface on a 200x200 bed, object
    snapping off: the active layer A, and layers B and C after the
    document's own. Returns them with a function adding a 20 mm square
    to a layer."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    s = WorkSurface(editor, Gtk.Window(), machine)
    s.get_width = lambda: 800
    s.get_height = lambda: 600
    s._rebuild_view_transform()
    s.object_snap_enabled = False
    layer_a = editor.doc.active_layer
    layer_b = Layer(name="B")
    layer_c = Layer(name="C")
    editor.doc.add_child(layer_b)
    editor.doc.add_child(layer_c)
    s.update_from_doc()

    def add(layer, pos):
        wp = WorkPiece(name="square")
        wp._edited_boundaries = _square()
        wp.set_size(20, 20)
        wp.pos = pos
        layer.add_child(wp)
        s.update_from_doc()
        assert s.find_by_data(wp) is not None
        return wp

    yield editor, s, (layer_a, layer_b, layer_c), add

    editor.cleanup()


@pytest.fixture
def grouped(surface):
    """Square a on A and b on B in a group, and c on A in none."""
    editor, s, (layer_a, layer_b, _), add = surface
    a = add(layer_a, (20, 20))
    b = add(layer_b, (60, 20))
    c = add(layer_a, (140, 120))
    group = editor.group.group_items([a, b])
    assert group is not None
    return editor, s, group, a, b, c


def _screen(s, wp, local_x=0.5, local_y=0.5):
    """A point in the shape's local space, on screen."""
    elem = s.find_by_data(wp)
    to_screen = s.view_transform @ elem.get_world_transform()
    return to_screen.transform_point((local_x, local_y))


def _gesture(s, x, y, mods=None):
    gesture = MagicMock()
    if mods is None:
        gesture.get_current_event.return_value = None
    else:
        event = MagicMock()
        event.get_modifier_state.return_value = mods
        gesture.get_current_event.return_value = event
    gesture.get_button.return_value = Gdk.BUTTON_PRIMARY
    gesture.get_start_point.return_value = (True, x, y)
    s._drag_gesture = gesture
    return gesture


def _click(s, x, y, n_press=1):
    gesture = _gesture(s, x, y)
    s.on_button_press(gesture, n_press, x, y)
    s.on_click_released(gesture, n_press, x, y)


def _double_click(s, wp):
    x, y = _screen(s, wp)
    _click(s, x, y)
    _click(s, x, y, n_press=2)


def _drag(s, wp, dx_mm, dy_mm):
    """Presses on the shape's middle and drags it by (dx_mm, dy_mm)."""
    x, y = _screen(s, wp)
    gesture = _gesture(s, x, y)
    s.on_button_press(gesture, 1, x, y)
    wx, wy = s._get_world_coords(x, y)
    tx, ty = s.view_transform.transform_point((wx + dx_mm, wy + dy_mm))
    s.on_mouse_drag(gesture, tx - x, ty - y)
    s.on_drag_end(gesture, tx - x, ty - y)


def _key(s, keyval, state=NO_MODS):
    return s.on_key_pressed(MagicMock(), keyval, 0, state)


def _selected(s):
    return set(s.get_selected_items())


def _at(wp):
    return wp.matrix.get_translation()


def _union(s, *items):
    """The world box (x, y, w, h) around the shapes' elements."""
    boxes = [s.find_by_data(i).get_world_bounding_box() for i in items]
    left = min(x for x, _y, _w, _h in boxes)
    bottom = min(y for _x, y, _w, _h in boxes)
    right = max(x + w for x, _y, w, _h in boxes)
    top = max(y + h for _x, y, _w, h in boxes)
    return left, bottom, right - left, top - bottom


class TestAGroupIsSelectedAsOne:
    def test_a_click_on_a_member_selects_both_in_one_box(self, grouped):
        _, s, _, a, b, _ = grouped

        _click(s, *_screen(s, a))

        assert _selected(s) == {a, b}
        assert s._selection_group is not None
        assert s._selection_group._bounding_box == pytest.approx(
            _union(s, a, b)
        )

    def test_shift_click_toggles_the_whole_group(self, grouped):
        _, s, _, a, b, c = grouped
        s.select_items([c])
        s._shift_pressed = True

        _click(s, *_screen(s, a))
        assert _selected(s) == {a, b, c}

        _click(s, *_screen(s, b))
        assert _selected(s) == {c}

    def test_a_frame_touching_one_member_selects_both(self, grouped):
        _, s, _, a, b, _ = grouped
        # From empty canvas below and left of a into a's lower half.
        x0, y0 = s.view_transform.transform_point((5, 5))
        x1, y1 = _screen(s, a, 0.5, 0.3)
        gesture = _gesture(s, x0, y0)
        s.on_button_press(gesture, 1, x0, y0)
        s.on_mouse_drag(gesture, x1 - x0, y1 - y0)
        s.on_drag_end(gesture, x1 - x0, y1 - y0)

        assert _selected(s) == {a, b}

    def test_a_lasso_around_one_member_selects_both(self, grouped):
        _, s, _, a, b, _ = grouped
        corners = [(10, 10), (50, 10), (50, 50), (10, 50)]
        points = [s.view_transform.transform_point(p) for p in corners]
        x0, y0 = points[0]
        gesture = _gesture(s, x0, y0, Gdk.ModifierType.ALT_MASK)
        s.on_button_press(gesture, 1, x0, y0)
        for x, y in points[1:] + points[:1]:
            s.on_mouse_drag(gesture, x - x0, y - y0)
        s.on_drag_end(gesture, 0, 0)

        assert _selected(s) == {a, b}

    def test_select_items_with_one_member_selects_both(self, grouped):
        _, s, _, a, b, _ = grouped

        s.select_items([b])

        assert _selected(s) == {a, b}

    def test_a_drag_from_an_unselected_member_moves_both_at_once(
        self, grouped
    ):
        editor, s, _, a, b, _ = grouped
        a_at, b_at = _at(a), _at(b)
        history = editor.history_manager
        entries = len(history.undo_stack)

        _drag(s, a, 10, 5)

        assert _at(a) == pytest.approx((a_at[0] + 10, a_at[1] + 5))
        assert _at(b) == pytest.approx((b_at[0] + 10, b_at[1] + 5))
        assert len(history.undo_stack) == entries + 1

        history.undo()
        assert _at(a) == pytest.approx(a_at)
        assert _at(b) == pytest.approx(b_at)


class TestEditingInsideAGroup:
    def test_a_double_click_enters_it_with_that_member_alone(self, grouped):
        _, s, group, a, _, _ = grouped

        _double_click(s, a)

        assert s.editing_group is group
        assert _selected(s) == {a}
        assert s.edit_context is None

    def test_a_drag_moves_only_that_member(self, grouped):
        _, s, _, a, b, _ = grouped
        _double_click(s, a)
        a_at, b_at = _at(a), _at(b)

        _drag(s, a, 10, 5)

        assert _at(a) == pytest.approx((a_at[0] + 10, a_at[1] + 5))
        assert _at(b) == pytest.approx(b_at)

    def test_a_nudge_moves_only_that_member(self, grouped):
        _, s, _, a, b, _ = grouped
        _double_click(s, a)
        a_at, b_at = _at(a), _at(b)

        _key(s, Gdk.KEY_Right)

        assert _at(a) == pytest.approx((a_at[0] + 1, a_at[1]))
        assert _at(b) == pytest.approx(b_at)

    def test_a_click_on_another_member_selects_it_alone(self, grouped):
        _, s, group, a, b, _ = grouped
        _double_click(s, a)

        _click(s, *_screen(s, b))

        assert s.editing_group is group
        assert _selected(s) == {b}

    def test_escape_leaves_and_selects_the_whole_group(self, grouped):
        _, s, _, a, b, _ = grouped
        _double_click(s, a)

        assert _key(s, Gdk.KEY_Escape)

        assert s.editing_group is None
        assert _selected(s) == {a, b}

    def test_a_click_on_empty_canvas_leaves(self, grouped):
        _, s, _, a, _, _ = grouped
        _double_click(s, a)

        _click(s, *s.view_transform.transform_point((100, 180)))

        assert s.editing_group is None
        assert _selected(s) == set()

    def test_a_click_on_a_shape_outside_leaves_and_selects_it(self, grouped):
        _, s, _, a, _, c = grouped
        _double_click(s, a)

        _click(s, *_screen(s, c))

        assert s.editing_group is None
        assert _selected(s) == {c}

    def test_select_all_leaves(self, grouped):
        _, s, _, a, b, c = grouped
        _double_click(s, a)

        s.select_all()

        assert s.editing_group is None
        assert _selected(s) == {a, b, c}

    def test_a_nested_group_is_entered_with_a_second_double_click(
        self, grouped
    ):
        editor, s, inner, a, b, c = grouped
        outer = editor.group.group_items([a, c])
        assert outer is not None

        _double_click(s, a)
        assert s.editing_group is outer
        # One level below the outer group: the inner one, whole.
        assert _selected(s) == {a, b}

        _click(s, *_screen(s, a), n_press=2)
        assert s.editing_group is inner
        assert _selected(s) == {a}

        _key(s, Gdk.KEY_Escape)
        assert s.editing_group is None
        assert _selected(s) == {a, b, c}

    def test_a_double_click_on_an_edited_member_edits_its_shape(self, grouped):
        _, s, group, a, _, _ = grouped
        _double_click(s, a)

        _click(s, *_screen(s, a), n_press=2)

        assert s.edit_context is s.find_by_data(a)
        assert s.editing_group is group

    def test_it_ends_when_no_member_is_visible(self, grouped):
        editor, s, group, a, b, _ = grouped
        _double_click(s, a)

        editor.layer.set_layer_visibility(b.layer, False)
        assert s.editing_group is group

        editor.layer.set_layer_visibility(a.layer, False)
        assert s.editing_group is None

    def test_it_ends_with_the_document(self, grouped):
        editor, s, _, a, _, _ = grouped
        _double_click(s, a)

        editor.set_doc(Doc())

        assert s.editing_group is None

    def test_its_box_is_drawn_dashed_around_the_visible_members(self, grouped):
        editor, s, _, a, b, _ = grouped
        with patch.object(surface_module, "render_selection_frame") as frame:
            s._render_overlays(MagicMock())
        frame.assert_not_called()

        _double_click(s, a)
        with patch.object(surface_module, "render_selection_frame") as frame:
            s._render_overlays(MagicMock())
        (box,) = [c.args[1] for c in frame.call_args_list]
        assert box._bounding_box == pytest.approx(_union(s, a, b))

        editor.layer.set_layer_visibility(b.layer, False)
        with patch.object(surface_module, "render_selection_frame") as frame:
            s._render_overlays(MagicMock())
        (box,) = [c.args[1] for c in frame.call_args_list]
        assert box._bounding_box == pytest.approx(_union(s, a))


class TestAHiddenMember:
    def test_hiding_its_layer_shrinks_the_selection(self, grouped):
        editor, s, _, a, b, _ = grouped
        s.select_items([a])
        assert _selected(s) == {a, b}

        editor.layer.set_layer_visibility(b.layer, False)

        assert _selected(s) == {a}
        assert s._selection_group is None

    def test_it_moves_with_the_visible_member(self, grouped):
        editor, s, _, a, b, _ = grouped
        editor.layer.set_layer_visibility(b.layer, False)
        a_at, b_at = _at(a), _at(b)

        _drag(s, a, 10, 5)

        assert _at(a) == pytest.approx((a_at[0] + 10, a_at[1] + 5))
        assert _at(b) == pytest.approx((b_at[0] + 10, b_at[1] + 5))

    def test_it_cannot_be_hit(self, grouped):
        editor, s, _, _, b, _ = grouped
        editor.layer.set_layer_visibility(b.layer, False)
        x, y = _screen(s, b)

        s._update_hover_state(*s._get_world_coords(x, y))
        assert (s._hovered_region, s._hovered_elem) == (
            ElementRegion.NONE,
            None,
        )

        _click(s, x, y)
        assert _selected(s) == set()


class TestSnapping:
    def test_a_moving_group_is_one_box_and_snaps_to_none_of_its_own(
        self, surface
    ):
        editor, s, (layer_a, layer_b, layer_c), add = surface
        s.object_snap_enabled = True
        a = add(layer_a, (20, 20))
        b = add(layer_b, (60, 40))
        hidden = add(layer_c, (100, 60))
        other = add(layer_a, (140, 120))
        editor.group.group_items([a, b, hidden])
        editor.layer.set_layer_visibility(layer_c, False)
        start = _union(s, a, b)
        boxes = {
            wp: s.find_by_data(wp).get_world_bounding_box()
            for wp in (a, b, hidden, other)
        }
        x, y = _screen(s, a)
        gesture = _gesture(s, x, y)
        s.on_button_press(gesture, 1, x, y)
        s.on_mouse_drag(gesture, 20, 0)

        assert s._moving
        assert s._moving_box() == pytest.approx(start)
        sources = s._snap_sources()
        for member in (a, b, hidden):
            assert boxes[member] not in sources
        assert boxes[other] in sources

        s.on_drag_end(gesture, 20, 0)


class TestCtrlPageDown:
    def test_moves_the_whole_group_hidden_member_too_in_one_step(
        self, surface
    ):
        editor, s, (layer_a, _, layer_c), add = surface
        a = add(layer_a, (20, 20))
        hidden = add(layer_c, (60, 20))
        group = editor.group.group_items([a, hidden])
        editor.layer.set_layer_visibility(layer_c, False)
        s.select_items([a])
        layers = editor.doc.layers
        after_a = layers[layers.index(layer_a) + 1]
        history = editor.history_manager
        entries = len(history.undo_stack)

        _key(s, Gdk.KEY_Page_Down, PRIMARY_MODIFIER_MASK)

        assert a.layer is after_a
        assert hidden.layer is after_a
        assert editor.doc.item_groups.items_of(group) == [a, hidden]
        assert _selected(s) == {a, hidden}
        assert len(history.undo_stack) == entries + 1

        history.undo()
        assert a.layer is layer_a
        assert hidden.layer is layer_c

    def test_inside_a_group_only_the_selected_member_moves(self, surface):
        editor, s, (layer_a, layer_b, layer_c), add = surface
        a = add(layer_a, (20, 20))
        on_c = add(layer_c, (60, 20))
        group = editor.group.group_items([a, on_c])
        # On its way to B, on_c is for a moment in no layer, and the
        # group then has no visible item: that does not end the mode.
        editor.layer.set_layer_visibility(layer_a, False)
        _double_click(s, on_c)

        _key(s, Gdk.KEY_Page_Up, PRIMARY_MODIFIER_MASK)

        assert on_c.layer is layer_b
        assert a.layer is layer_a
        assert editor.doc.item_groups.items_of(group) == [a, on_c]
        assert s.editing_group is group
        assert _selected(s) == {on_c}

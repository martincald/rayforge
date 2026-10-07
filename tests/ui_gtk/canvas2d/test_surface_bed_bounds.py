"""The work surface keeps what a drag moves, resizes, rotates or shears
inside the bed: a move pins at the edge, a resize, rotate or shear
stops there, a snap to a bed edge still lands exactly, and a drag or
nudge the edge blocks adds no undo step."""

import math
from unittest.mock import MagicMock

import pytest
from gi.repository import Gdk, Gtk
from raygeo.geo import Geometry

from swiftcut.core.group import Group
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.canvas import CanvasElement
from swiftcut.ui_gtk.canvas.region import ElementRegion
from swiftcut.ui_gtk.canvas.worldsurface import WorldSurface
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface

pytestmark = pytest.mark.ui

NO_MODS = Gdk.ModifierType(0)
EPS = 1e-6
# A drag that stops at an edge bisects to 1/65536 of the drag.
STOP = 0.01

# A drag far past the bed in each direction, and where the moved
# box's low corner ends: on the edge it hits, else where it was.
FAR = 500.0
DIRECTIONS = [
    (-FAR, 0.0),
    (FAR, 0.0),
    (0.0, -FAR),
    (0.0, FAR),
    (-FAR, -FAR),
    (FAR, -FAR),
    (-FAR, FAR),
    (FAR, FAR),
]


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
    """A real editor and an 800x600 surface on a 200x200 bed; add()
    puts a workpiece of a size at a position, turned by an angle, on
    it."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    s = WorkSurface(editor, Gtk.Window(), machine)
    s.get_width = lambda: 800
    s.get_height = lambda: 600
    s._rebuild_view_transform()

    def add(size, pos, angle=0.0):
        wp = WorkPiece(name="wp")
        wp._edited_boundaries = _square()
        wp.set_size(*size)
        wp.pos = pos
        wp.angle = angle
        editor.doc.active_layer.add_child(wp)
        s.update_from_doc()
        elem = s.find_by_data(wp)
        assert elem is not None
        return wp, elem

    yield editor, s, add

    editor.cleanup()


def _select(s, *elems):
    for elem in elems:
        elem.selected = True
    s._finalize_selection_state()


def _press(s, elem, local=(0.5, 0.5)):
    """Presses on elem at a point of its unit square."""
    x, y = (s.view_transform @ elem.get_world_transform()).transform_point(
        local
    )
    gesture = MagicMock()
    gesture.get_current_event.return_value = None
    gesture.get_button.return_value = Gdk.BUTTON_PRIMARY
    gesture.get_start_point.return_value = (True, x, y)
    s._drag_gesture = gesture
    s.on_button_press(gesture, 1, x, y)
    return gesture, (x, y)


def _drag(s, gesture, start, world_point):
    """Drags the pointer from the press to a WORLD point."""
    tx, ty = s.view_transform.transform_point(world_point)
    offset = (tx - start[0], ty - start[1])
    s.on_mouse_drag(gesture, *offset)
    return offset


def _drag_by(s, gesture, start, dx, dy):
    wx, wy = s._get_world_coords(*start)
    return _drag(s, gesture, start, (wx + dx, wy + dy))


def _box(elems):
    boxes = [elem.get_world_bounding_box() for elem in elems]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return x0, y0, x1, y1


def _inside(elems):
    x0, y0, x1, y1 = _box(elems)
    return x0 >= -EPS and y0 >= -EPS and x1 <= 200 + EPS and y1 <= 200 + EPS


def _pinned(start, size, delta):
    """Where a box's low corner pins after a move by delta."""
    return tuple(
        0.0 if d < 0 else 200.0 - size[i] if d > 0 else start[i]
        for i, d in enumerate(delta)
    )


class TestMove:
    @pytest.mark.parametrize("delta", DIRECTIONS)
    def test_a_move_past_an_edge_or_corner_pins_there(self, surface, delta):
        editor, s, add = surface
        wp, elem = add((30, 20), (85, 90))
        _select(s, elem)
        history = editor.history_manager
        steps = len(history.undo_stack)

        gesture, start = _press(s, elem)
        offset = _drag_by(s, gesture, start, *delta)
        s.on_drag_end(gesture, *offset)

        assert wp.pos == pytest.approx(_pinned((85, 90), (30, 20), delta))
        assert len(history.undo_stack) == steps + 1
        history.undo()
        assert wp.pos == pytest.approx((85, 90))

    @pytest.mark.parametrize("delta", DIRECTIONS)
    def test_a_group_move_past_an_edge_or_corner_pins_there(
        self, surface, delta
    ):
        _, s, add = surface
        wp_a, elem_a = add((30, 20), (60, 90))
        wp_c, elem_c = add((20, 20), (110, 90))
        _select(s, elem_a, elem_c)

        gesture, start = _press(s, elem_a)
        offset = _drag_by(s, gesture, start, *delta)
        s.on_drag_end(gesture, *offset)

        x, y = _pinned((60, 90), (70, 20), delta)
        assert wp_a.pos == pytest.approx((x, y))
        assert wp_c.pos == pytest.approx((x + 50, y))

    @pytest.mark.parametrize("delta", DIRECTIONS)
    def test_a_document_group_moved_past_an_edge_pins_there(
        self, surface, delta
    ):
        editor, s, add = surface
        wp_a, _ = add((30, 20), (60, 90))
        wp_c, _ = add((20, 20), (110, 90))
        layer = editor.doc.active_layer
        result = Group.create_from_items([wp_a, wp_c], layer)
        assert result is not None
        group = result.new_group
        layer.add_child(group)
        layer.remove_children([wp_a, wp_c])
        group.add_children([wp_a, wp_c])
        for wp in (wp_a, wp_c):
            wp.matrix = result.child_matrices[wp.uid]
        s.update_from_doc()
        elem = s.find_by_data(group)
        assert elem is not None
        _select(s, elem)

        # On A, inside the group's frame.
        gesture, start = _press(s, elem, (0.2, 0.5))
        assert s._drag_target is elem
        offset = _drag_by(s, gesture, start, *delta)
        s.on_drag_end(gesture, *offset)

        x, y = _pinned((60, 90), (70, 20), delta)
        assert wp_a.pos == pytest.approx((x, y))
        assert wp_c.pos == pytest.approx((x + 50, y))

    def test_a_move_pulls_a_piece_already_outside_back_in(self, surface):
        _, s, add = surface
        wp, elem = add((30, 20), (-40, 90))
        _select(s, elem)

        gesture, start = _press(s, elem)
        offset = _drag_by(s, gesture, start, 10, 0)
        s.on_drag_end(gesture, *offset)

        assert wp.pos == pytest.approx((0, 90))

    def test_a_drag_the_edge_blocks_adds_no_undo_step(self, surface):
        editor, s, add = surface
        wp, elem = add((30, 20), (0, 90))
        _select(s, elem)
        before = wp.matrix.copy()
        history = editor.history_manager
        steps = len(history.undo_stack)

        gesture, start = _press(s, elem)
        offset = _drag_by(s, gesture, start, -50, 0)
        s.on_drag_end(gesture, *offset)

        assert wp.matrix == before
        assert len(history.undo_stack) == steps

    @pytest.mark.parametrize(
        "pos, dx, x",
        [
            # The left edge half a millimetre short of, or past, the
            # bed's; the right edge the same.
            ((20, 90), -19.5, 0.0),
            ((20, 90), -20.5, 0.0),
            ((150, 90), 19.6, 170.0),
            ((150, 90), 20.4, 170.0),
        ],
    )
    def test_a_snap_to_a_bed_edge_lands_exactly(self, surface, pos, dx, x):
        _, s, add = surface
        wp, elem = add((30, 20), pos)
        _select(s, elem)

        gesture, start = _press(s, elem)
        offset = _drag_by(s, gesture, start, dx, 0)

        edge = 0.0 if dx < 0 else 200.0
        assert ((edge, 0.0), (edge, 200.0)) in s._snap_guides
        s.on_drag_end(gesture, *offset)
        assert wp.pos[0] == pytest.approx(x, abs=1e-9)

    def test_a_snap_the_edge_overrules_loses_its_guide(self, surface):
        _, s, add = surface
        add((30, 20), (-20, 50))
        wp, elem = add((30, 20), (20, 140))
        _select(s, elem)

        # The left edge snaps to the other piece's, 20 mm off the bed.
        gesture, start = _press(s, elem)
        offset = _drag_by(s, gesture, start, -39.5, 0)

        assert s._snap_guides == []
        s.on_drag_end(gesture, *offset)
        assert wp.pos == pytest.approx((0, 140))

    def test_the_snap_override_still_clamps(self, surface):
        _, s, add = surface
        wp, elem = add((30, 20), (20, 90))
        _select(s, elem)

        gesture, start = _press(s, elem)
        s._snap_override = True
        offset = _drag_by(s, gesture, start, -100, 0)
        s.on_drag_end(gesture, *offset)

        assert wp.pos == pytest.approx((0, 90))


class TestResize:
    @pytest.mark.parametrize(
        "region, delta, edge",
        [
            # The edge dragged past the bed's stops on it; the opposite
            # edge stays. Edges: 0 left, 1 bottom, 2 right, 3 top.
            (ElementRegion.MIDDLE_RIGHT, (300, 0), 2),
            (ElementRegion.MIDDLE_LEFT, (-300, 0), 0),
            (ElementRegion.TOP_MIDDLE, (0, 300), 3),
            (ElementRegion.BOTTOM_MIDDLE, (0, -300), 1),
        ],
    )
    @pytest.mark.parametrize("group", [False, True])
    def test_a_resize_past_an_edge_stops_on_it(
        self, surface, region, delta, edge, group
    ):
        editor, s, add = surface
        _, elem = add((30, 20), (85, 90))
        elems = [elem]
        if group:
            elems.append(add((10, 10), (100, 95))[1])
        _select(s, *elems)
        before = _box(elems)
        bed = (0, 0, 200, 200)
        history = editor.history_manager
        steps = len(history.undo_stack)

        gesture, start = _press(s, elem)
        s._active_region = region
        offset = _drag_by(s, gesture, start, *delta)
        s.on_drag_end(gesture, *offset)

        after = _box(elems)
        assert _inside(elems)
        assert after[edge] == pytest.approx(bed[edge], abs=STOP)
        opposite = (edge + 2) % 4
        assert after[opposite] == pytest.approx(before[opposite])
        assert len(history.undo_stack) == steps + 1

    @pytest.mark.parametrize(
        "region, pos, delta",
        [
            # The dragged corner 20 mm from both edges of the bed's
            # corner it is dragged past, so it reaches both at once.
            (ElementRegion.TOP_LEFT, (20, 160), (-300, 300)),
            (ElementRegion.TOP_RIGHT, (150, 160), (300, 300)),
            (ElementRegion.BOTTOM_LEFT, (20, 20), (-300, -300)),
            (ElementRegion.BOTTOM_RIGHT, (150, 20), (300, -300)),
        ],
    )
    @pytest.mark.parametrize("group", [False, True])
    def test_a_corner_resize_past_a_bed_corner_stops_in_it(
        self, surface, region, pos, delta, group
    ):
        editor, s, add = surface
        _, elem = add((30, 20), pos)
        elems = [elem]
        if group:
            elems.append(add((10, 10), (pos[0] + 10, pos[1] + 5))[1])
        _select(s, *elems)
        before = _box(elems)
        bed = (0, 0, 200, 200)
        history = editor.history_manager
        steps = len(history.undo_stack)

        gesture, start = _press(s, elem)
        s._active_region = region
        offset = _drag_by(s, gesture, start, *delta)
        s.on_drag_end(gesture, *offset)

        after = _box(elems)
        assert _inside(elems)
        # Edges: 0 left, 1 bottom, 2 right, 3 top.
        for edge in (0 if delta[0] < 0 else 2, 1 if delta[1] < 0 else 3):
            assert after[edge] == pytest.approx(bed[edge], abs=STOP)
            opposite = (edge + 2) % 4
            assert after[opposite] == pytest.approx(before[opposite])
        assert len(history.undo_stack) == steps + 1

    @pytest.mark.parametrize(
        "region, delta",
        [
            (ElementRegion.TOP_LEFT, (-300, 300)),
            (ElementRegion.TOP_RIGHT, (300, 300)),
            (ElementRegion.BOTTOM_LEFT, (-300, -300)),
            (ElementRegion.BOTTOM_RIGHT, (300, -300)),
        ],
    )
    def test_a_corner_resize_of_a_turned_piece_stops_on_an_edge(
        self, surface, region, delta
    ):
        editor, s, add = surface
        _, elem = add((30, 20), (85, 90), 30.0)
        _select(s, elem)
        history = editor.history_manager
        steps = len(history.undo_stack)

        gesture, start = _press(s, elem)
        s._active_region = region
        offset = _drag_by(s, gesture, start, *delta)
        s.on_drag_end(gesture, *offset)

        x0, y0, x1, y1 = _box([elem])
        assert _inside([elem])
        assert min(x0, y0, 200 - x1, 200 - y1) == pytest.approx(0, abs=STOP)
        assert len(history.undo_stack) == steps + 1


def _rotate_by(s, elem, target, degrees):
    """Presses on elem off its centre as on a rotate handle of target,
    and drags the pointer `degrees` counterclockwise about its pivot."""
    gesture, start = _press(s, elem, (0.9, 0.5))
    s._active_region = ElementRegion.ROTATE_TOP_RIGHT
    wx, wy = s._get_world_coords(*start)
    s._start_rotation(target, wx, wy)
    px, py = s._rotation_pivot
    a = math.radians(degrees)
    rx = px + (wx - px) * math.cos(a) - (wy - py) * math.sin(a)
    ry = py + (wx - px) * math.sin(a) + (wy - py) * math.cos(a)
    return gesture, _drag(s, gesture, start, (rx, ry))


# A 40 mm square 5 mm from the bed edges it is near, centred between
# the others, and those edges (0 left, 1 bottom, 2 right, 3 top). A
# turn grows the square's box alike on both axes, 5 mm at 17 degrees,
# so a turn of 30 or 45 either way stops on them, in a corner on both.
NEAR_EDGES = [
    ((5, 80), (0,)),
    ((155, 80), (2,)),
    ((80, 5), (1,)),
    ((80, 155), (3,)),
    ((5, 5), (0, 1)),
    ((155, 5), (2, 1)),
    ((5, 155), (0, 3)),
    ((155, 155), (2, 3)),
]
TURNS = [45, -45, 30, -30]


class TestRotate:
    @pytest.mark.parametrize("pos, edges", NEAR_EDGES)
    @pytest.mark.parametrize("degrees", TURNS)
    def test_a_rotate_near_each_edge_and_corner_stops_on_it(
        self, surface, pos, edges, degrees
    ):
        editor, s, add = surface
        wp, elem = add((40, 40), pos)
        _select(s, elem)
        bed = (0, 0, 200, 200)
        history = editor.history_manager
        steps = len(history.undo_stack)

        gesture, offset = _rotate_by(s, elem, elem, degrees)

        rotation = elem.get_world_transform().get_rotation()
        assert 0 < rotation / degrees < 1
        assert _inside([elem])
        for edge in edges:
            assert _box([elem])[edge] == pytest.approx(bed[edge], abs=STOP)
        assert s._rotation_readout[0] == pytest.approx(-rotation)

        s.on_drag_end(gesture, *offset)
        assert wp.angle == pytest.approx(rotation)
        assert len(history.undo_stack) == steps + 1

    @pytest.mark.parametrize("pos, edges", NEAR_EDGES)
    @pytest.mark.parametrize("degrees", TURNS)
    def test_a_group_rotate_near_each_edge_and_corner_stops_on_it(
        self, surface, pos, edges, degrees
    ):
        editor, s, add = surface
        # The square's two halves, turned as one about its centre.
        _, elem_a = add((40, 20), pos)
        _, elem_c = add((40, 20), (pos[0], pos[1] + 20))
        _select(s, elem_a, elem_c)
        bed = (0, 0, 200, 200)
        history = editor.history_manager
        steps = len(history.undo_stack)

        gesture, offset = _rotate_by(s, elem_c, s._selection_group, degrees)
        s.on_drag_end(gesture, *offset)

        rotation = elem_a.get_world_transform().get_rotation()
        assert 0 < rotation / degrees < 1
        assert _inside([elem_a, elem_c])
        for edge in edges:
            box = _box([elem_a, elem_c])
            assert box[edge] == pytest.approx(bed[edge], abs=STOP)
        assert len(history.undo_stack) == steps + 1

    def test_a_rotate_near_an_edge_stops_on_it(self, surface):
        editor, s, add = surface
        wp, elem = add((100, 20), (50, 170))
        _select(s, elem)
        history = editor.history_manager
        steps = len(history.undo_stack)

        gesture, offset = _rotate_by(s, elem, elem, 90)

        rotation = elem.get_world_transform().get_rotation()
        assert 0 < rotation < 90
        assert _inside([elem])
        assert _box([elem])[3] == pytest.approx(200, abs=STOP)
        # The readout shows where the piece stopped, not the pointer.
        assert s._rotation_readout[0] == pytest.approx(-rotation)

        s.on_drag_end(gesture, *offset)
        assert wp.angle == pytest.approx(rotation)
        assert len(history.undo_stack) == steps + 1

    def test_a_rotate_clear_of_the_edges_is_whole(self, surface):
        _, s, add = surface
        _, elem = add((30, 20), (85, 90))
        _select(s, elem)

        _rotate_by(s, elem, elem, 90)

        rotation = elem.get_world_transform().get_rotation()
        assert rotation == pytest.approx(90)
        assert s._rotation_readout[0] == pytest.approx(-90)

    def test_a_group_rotate_near_an_edge_stops_on_it(self, surface):
        _, s, add = surface
        _, elem_a = add((40, 10), (60, 185))
        _, elem_c = add((40, 10), (110, 185))
        _select(s, elem_a, elem_c)

        gesture, offset = _rotate_by(s, elem_c, s._selection_group, 90)
        s.on_drag_end(gesture, *offset)

        assert _inside([elem_a, elem_c])
        assert _box([elem_a, elem_c])[3] == pytest.approx(200, abs=STOP)
        rotation = elem_a.get_world_transform().get_rotation()
        assert 0 < rotation < 90


def test_a_shear_past_an_edge_stops_on_it(surface):
    _, s, add = surface
    _, elem = add((30, 20), (10, 90))
    _select(s, elem)

    gesture, start = _press(s, elem)
    s._active_region = ElementRegion.SHEAR_TOP
    offset = _drag_by(s, gesture, start, -50, 0)
    s.on_drag_end(gesture, *offset)

    assert _inside([elem])
    assert _box([elem])[0] == pytest.approx(0, abs=STOP)
    assert elem.get_world_transform().decompose()[5] != pytest.approx(0)


def test_a_nudge_at_an_edge_is_a_no_op_without_an_undo_step(surface):
    editor, s, add = surface
    wp, elem = add((30, 20), (0, 90))
    _select(s, elem)
    history = editor.history_manager
    steps = len(history.undo_stack)

    assert s.on_key_pressed(None, Gdk.KEY_Left, 0, NO_MODS) is True

    assert wp.pos == pytest.approx((0, 90))
    assert len(history.undo_stack) == steps


def test_a_nudge_past_an_edge_stops_on_it(surface):
    _, s, add = surface
    wp, elem = add((30, 20), (5, 90))
    _select(s, elem)

    s.on_key_pressed(None, Gdk.KEY_Left, 0, Gdk.ModifierType.SHIFT_MASK)

    assert wp.pos == pytest.approx((0, 90))


def test_a_plain_world_surface_does_not_hold_a_move():
    """Bounds are opt-in: only the work surface has them."""
    s = WorldSurface(width_mm=200.0, height_mm=200.0)
    s.get_width = lambda: 800
    s.get_height = lambda: 600
    s._rebuild_view_transform()
    elem = CanvasElement(10.0, 10.0, 10.0, 8.0, canvas=s, parent=s.root)
    s.root.add(elem)
    s._drag_target = elem
    s._active_region = ElementRegion.BODY
    s._initial_world_transform = elem.get_world_transform()
    gesture = MagicMock()
    gesture.get_start_point.return_value = (True, 400.0, 300.0)
    s._drag_gesture = gesture

    s.on_mouse_drag(gesture, -2000.0, 0.0)

    assert s._drag_bounds() is None
    assert elem.get_world_bounding_box()[0] < -100

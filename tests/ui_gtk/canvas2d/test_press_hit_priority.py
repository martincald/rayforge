"""What a press on the canvas grabs, by priority: a selection's rotate
zone, then its resize handles, then the stroke of any path within
STROKE_HIT_DISTANCE screen pixels, then the inside of a closed shape or
of a selected object's box; empty canvas starts a rubber band.
"""

import math
from unittest.mock import MagicMock

import pytest
from gi.repository import Gdk, Gtk
from raygeo.geo import Geometry

from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.canvas.canvas import SelectionMode
from swiftcut.ui_gtk.canvas.element import CanvasElement
from swiftcut.ui_gtk.canvas.hittest import STROKE_HIT_DISTANCE
from swiftcut.ui_gtk.canvas.region import ElementRegion
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface

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


def _vee():
    """An open V: up from the bottom-left corner to the top middle, and
    down to the bottom-right."""
    geo = Geometry()
    geo.move_to(0.0, 0.0)
    geo.line_to(0.5, 1.0)
    geo.line_to(1.0, 0.0)
    return geo


@pytest.fixture
def surface(ui_context_initializer, ui_task_mgr):
    """A real editor and an 800x600 surface; returns them with a
    function adding a workpiece with a path, on top of the rest."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    s = WorkSurface(editor, Gtk.Window(), machine)
    s.get_width = lambda: 800
    s.get_height = lambda: 600
    s._rebuild_view_transform()

    def add(geometry, pos, size):
        wp = WorkPiece(name="wp")
        wp._edited_boundaries = geometry
        wp.set_size(*size)
        wp.pos = pos
        editor.doc.active_layer.add_child(wp)
        s.update_from_doc()
        elem = s.find_by_data(wp)
        assert elem is not None
        return wp, elem

    yield editor, s, add

    editor.cleanup()


def _screen(s, elem, local_x, local_y):
    """A point in an element's local space, on screen."""
    to_screen = s.view_transform @ elem.get_world_transform()
    return to_screen.transform_point((local_x, local_y))


def _hover(s, x, y):
    """What the pointer at screen (x, y) would grab."""
    s._update_hover_state(*s._get_world_coords(x, y))
    return s._hovered_region, s._hovered_elem


def _select(s, elem):
    elem.selected = True
    s._finalize_selection_state()


def _press(s, x, y):
    gesture = MagicMock()
    gesture.get_current_event.return_value = None
    gesture.get_button.return_value = Gdk.BUTTON_PRIMARY
    gesture.get_start_point.return_value = (True, x, y)
    s._drag_gesture = gesture
    s.on_button_press(gesture, 1, x, y)
    return gesture


def _click(s, x, y):
    """A press and a release at screen (x, y), with no drag between."""
    gesture = _press(s, x, y)
    s.on_click_released(gesture, 1, x, y)


class TestClickTogglesTheMode:
    def test_a_click_on_the_stroke_outside_the_box_toggles(self, surface):
        _, s, add = surface
        _, elem = add(_square(), (60, 50), (60, 40))
        x, y = _screen(s, elem, 0.0, 0.25)  # On the left edge.

        # The first click selects; only a click on the selection toggles.
        _click(s, x - 5, y)
        assert elem.selected
        assert s._selection_mode == SelectionMode.RESIZE

        _click(s, x - 5, y)
        assert s._selection_mode == SelectionMode.ROTATE_SHEAR

        corner_x, corner_y = _screen(s, elem, 0.0, 1.0)
        _click(s, corner_x + 2, corner_y + 2)  # The top-left handle.
        assert s._selection_mode == SelectionMode.RESIZE

    def test_a_release_off_the_stroke_outside_the_box_does_not_toggle(
        self, surface
    ):
        _, s, add = surface
        _, elem = add(_square(), (60, 50), (60, 40))
        _select(s, elem)
        x, y = _screen(s, elem, 0.0, 1.0)  # The top-left corner.

        # 20 pixels out along the diagonal: beyond the rotate zone and
        # the stroke's reach. A press there starts a rubber band, so the
        # release alone is what reaches the toggle.
        d = 20 / math.sqrt(2)
        s.on_click_released(MagicMock(), 1, x - d, y - d)

        assert s._selection_mode == SelectionMode.RESIZE

    def test_a_click_in_the_rotate_zone_on_the_stroke_does_not_toggle(
        self, surface
    ):
        _, s, add = surface
        _, elem = add(_square(), (60, 50), (60, 40))
        _select(s, elem)
        x, y = _screen(s, elem, 0.0, 1.0)  # The top-left corner.

        # 5 pixels left of the left edge, 12 below the corner: on the
        # stroke, but in the rotate zone, which the press grabs.
        assert _hover(s, x - 5, y + 12) == (
            ElementRegion.ROTATE_TOP_LEFT,
            elem,
        )
        _click(s, x - 5, y + 12)

        assert s._selection_mode == SelectionMode.RESIZE


class TestHitPriority:
    def test_a_rotate_zone_wins_over_the_stroke(self, surface):
        _, s, add = surface
        _, elem = add(_square(), (60, 50), (60, 40))
        _select(s, elem)
        x, y = _screen(s, elem, 0.0, 1.0)  # The top-left corner.

        # 7 pixels out along the diagonal: in the ring, and on the stroke.
        d = 7 / math.sqrt(2)
        assert _hover(s, x - d, y - d) == (
            ElementRegion.ROTATE_TOP_LEFT,
            elem,
        )

    def test_a_resize_handle_wins_over_the_stroke(self, surface):
        _, s, add = surface
        _, elem = add(_square(), (60, 50), (60, 40))
        _select(s, elem)
        x, y = _screen(s, elem, 0.0, 1.0)

        assert _hover(s, x + 2, y + 2) == (ElementRegion.TOP_LEFT, elem)

    @pytest.mark.parametrize("selected", [False, True])
    def test_the_stroke_is_grabbed_from_outside_the_box(
        self, surface, selected
    ):
        _, s, add = surface
        _, elem = add(_square(), (60, 50), (60, 40))
        if selected:
            _select(s, elem)
        x, y = _screen(s, elem, 0.0, 0.25)  # On the left edge.

        assert _hover(s, x - 5, y) == (ElementRegion.BODY, elem)

    @pytest.mark.parametrize("zoom", [1.0, 2.0])
    def test_the_stroke_reaches_eight_screen_pixels(self, surface, zoom):
        _, s, add = surface
        _, elem = add(_square(), (60, 50), (60, 40))
        s.set_zoom(zoom)
        x, y = _screen(s, elem, 0.0, 0.25)

        reach = STROKE_HIT_DISTANCE
        assert _hover(s, x - (reach - 1), y) == (ElementRegion.BODY, elem)
        assert _hover(s, x - (reach + 1), y) == (ElementRegion.NONE, None)

    def test_the_inside_of_a_closed_shape_is_grabbed(self, surface):
        _, s, add = surface
        _, elem = add(_square(), (60, 50), (60, 40))
        x, y = _screen(s, elem, 0.5, 0.5)

        # Nothing is painted there: the shape, not a pixel, is hit.
        assert not elem.is_pixel_opaque(0.5, 0.5)
        assert _hover(s, x, y) == (ElementRegion.BODY, elem)

    def test_a_hole_is_not_inside(self, surface):
        _, s, add = surface
        ring = _square()
        ring.move_to(0.25, 0.25)
        ring.line_to(0.75, 0.25)
        ring.line_to(0.75, 0.75)
        ring.line_to(0.25, 0.75)
        ring.close_path()
        _, elem = add(ring, (60, 50), (60, 40))

        assert _hover(s, *_screen(s, elem, 0.1, 0.5)) == (
            ElementRegion.BODY,
            elem,
        )
        assert _hover(s, *_screen(s, elem, 0.5, 0.5)) == (
            ElementRegion.NONE,
            None,
        )

    def test_an_open_path_is_empty_inside_until_selected(self, surface):
        _, s, add = surface
        _, elem = add(_vee(), (60, 50), (60, 40))
        # Between the legs of the V, clear of the bottom resize handle.
        x, y = _screen(s, elem, 0.5, 0.35)

        assert _hover(s, x, y) == (ElementRegion.NONE, None)
        _select(s, elem)
        assert _hover(s, x, y) == (ElementRegion.BODY, elem)

    def test_a_stroke_wins_over_the_inside_of_a_shape_on_top(self, surface):
        _, s, add = surface
        _, vee = add(_vee(), (80, 60), (30, 20))
        # Added last, so drawn on top, and covering the V.
        _, frame = add(_square(), (50, 40), (100, 70))

        on_the_vee = _screen(s, vee, 0.25, 0.5)
        assert _hover(s, *on_the_vee) == (ElementRegion.BODY, vee)
        between_its_legs = _screen(s, vee, 0.5, 0.1)
        assert _hover(s, *between_its_legs) == (ElementRegion.BODY, frame)

    def test_a_draggable_child_on_the_stroke_still_wins(self, surface):
        _, s, add = surface
        _, elem = add(_square(), (60, 50), (60, 40))
        # A small draggable child, as a tab handle is, on the left edge.
        handle = CanvasElement(
            -0.05, 0.2, 0.1, 0.1, selectable=True, draggable=True
        )
        elem.add(handle)

        x, y = _screen(s, elem, 0.0, 0.25)
        assert _hover(s, x, y) == (ElementRegion.BODY, handle)

    def test_empty_canvas_starts_a_rubber_band(self, surface):
        _, s, add = surface
        _, elem = add(_square(), (60, 50), (60, 40))
        _select(s, elem)
        x, y = _screen(s, elem, 0.0, 0.25)

        gesture = _press(s, x - 40, y)
        s.on_mouse_drag(gesture, 20, 20)

        assert s._framing_selection
        assert s._selection_frame_rect == (x - 40, y, 20, 20)
        assert not elem.selected


class TestDragFromTheStroke:
    def test_moves_the_object_by_the_pointer_delta(self, surface):
        _, s, add = surface
        wp, elem = add(_square(), (60, 50), (60, 40))
        x, y = _screen(s, elem, 0.0, 0.25)
        start = wp.matrix.get_translation()
        # Its centre lands a pixel off the bed's; unsnapped, it moves by
        # the pointer delta alone.
        s.object_snap_enabled = False

        # 5 pixels outside the box, on an object not yet selected.
        gesture = _press(s, x - 5, y)
        assert elem.selected
        s.on_mouse_drag(gesture, 30, -20)
        s.on_drag_end(gesture, 30, -20)

        wx0, wy0 = s._get_world_coords(x - 5, y)
        wx1, wy1 = s._get_world_coords(x - 5 + 30, y - 20)
        end = wp.matrix.get_translation()
        assert end[0] - start[0] == pytest.approx(wx1 - wx0)
        assert end[1] - start[1] == pytest.approx(wy1 - wy0)

    def test_ctrl_still_snaps_the_move_to_the_grid(self, surface):
        _, s, add = surface
        wp, elem = add(_square(), (60.3, 50.3), (60, 40))
        x, y = _screen(s, elem, 0.0, 0.25)
        s._ctrl_pressed = True

        gesture = _press(s, x - 5, y)
        s.on_mouse_drag(gesture, 23, -17)
        s.on_drag_end(gesture, 23, -17)

        left, bottom = wp.matrix.get_translation()
        width, height = wp.size
        grid = s.grid_size

        def on_grid(value):
            return abs(value / grid - round(value / grid)) < 1e-6

        assert on_grid(left) or on_grid(left + width)
        assert on_grid(bottom) or on_grid(bottom + height)

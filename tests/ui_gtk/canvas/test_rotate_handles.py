"""The rotate zones of a selection: a ring 6 to 14 screen pixels outside
each corner of the frame, offered on a fresh selection, found by the
cursor rather than drawn, rotating about the center with an arc and
the angle drawn while dragging, snapping with Shift, and making one
undo step.

Hit-testing takes the widget's logical coordinates, as GTK delivers
them; the display's scale factor only enters when drawing.
"""

import math
from unittest.mock import MagicMock

import cairo
import numpy as np
import pytest
from gi.repository import Gdk, Gtk

from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.canvas import canvas as canvas_module
from swiftcut.ui_gtk.canvas.element import CanvasElement
from swiftcut.ui_gtk.canvas.region import (
    ROTATE_HANDLES,
    ROTATE_ZONE_INNER,
    ROTATE_ZONE_OUTER,
    ElementRegion,
)
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface
from swiftcut.ui_gtk.layout import ROTATION_ARC_RADIUS

pytestmark = pytest.mark.ui

# Each rotate zone's outward diagonal on screen (Y down).
OUTWARD = {
    ElementRegion.ROTATE_TOP_LEFT: (-1, -1),
    ElementRegion.ROTATE_TOP_RIGHT: (1, -1),
    ElementRegion.ROTATE_BOTTOM_LEFT: (-1, 1),
    ElementRegion.ROTATE_BOTTOM_RIGHT: (1, 1),
}

RESIZE_CORNER = {
    ElementRegion.ROTATE_TOP_LEFT: ElementRegion.TOP_LEFT,
    ElementRegion.ROTATE_TOP_RIGHT: ElementRegion.TOP_RIGHT,
    ElementRegion.ROTATE_BOTTOM_LEFT: ElementRegion.BOTTOM_LEFT,
    ElementRegion.ROTATE_BOTTOM_RIGHT: ElementRegion.BOTTOM_RIGHT,
}


def _selected(s, x=60.0, y=50.0, w=60.0, h=40.0, angle=0.0):
    """Adds a selected element to a surface, as a click would leave it."""
    elem = CanvasElement(
        x, y, w, h, canvas=s, parent=s.root, selected=True, angle=angle
    )
    s.root.add(elem)
    s._finalize_selection_state()
    return elem


def _screen_frame(s, elem):
    """The selection frame on screen: (left, top, right, bottom)."""
    to_screen = s.view_transform @ elem.get_world_transform()
    points = [
        to_screen.transform_point(p)
        for p in (
            (0, 0),
            (elem.width, 0),
            (elem.width, elem.height),
            (0, elem.height),
        )
    ]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _corner(frame, region):
    left, top, right, bottom = frame
    dx, dy = OUTWARD[region]
    return (left if dx < 0 else right), (top if dy < 0 else bottom)


def _ring_point(s, elem, region, distance):
    """The screen point `distance` pixels out along a corner's diagonal;
    negative is inside the frame."""
    cx, cy = _corner(_screen_frame(s, elem), region)
    dx, dy = OUTWARD[region]
    d = distance / math.sqrt(2)
    return cx + dx * d, cy + dy * d


def _hover(s, x, y):
    """The region the pointer at screen (x, y) hovers."""
    s._update_hover_state(*s._get_world_coords(x, y))
    return s._hovered_region


def _gesture(start_x, start_y):
    gesture = MagicMock()
    gesture.get_current_event.return_value = None
    gesture.get_button.return_value = Gdk.BUTTON_PRIMARY
    gesture.get_start_point.return_value = (True, start_x, start_y)
    return gesture


def _rotated_about(s, x, y, pivot, degrees):
    """Screen (x, y) rotated about a WORLD pivot by degrees, counter-
    clockwise in the Y-up world."""
    wx, wy = s._get_world_coords(x, y)
    px, py = pivot
    a = math.radians(degrees)
    rx = px + (wx - px) * math.cos(a) - (wy - py) * math.sin(a)
    ry = py + (wx - px) * math.sin(a) + (wy - py) * math.cos(a)
    return s.view_transform.transform_point((rx, ry))


def _angle_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


class TestRotateZoneHits:
    @pytest.mark.parametrize("zoom", [1.0, 2.0])
    @pytest.mark.parametrize("region", sorted(ROTATE_HANDLES, key=str))
    def test_the_ring_outside_each_corner_rotates(
        self, world_surface_factory, zoom, region
    ):
        s = world_surface_factory()
        s.set_zoom(zoom)
        elem = _selected(s)

        for distance in (6.5, 10.0, 13.5):
            point = _ring_point(s, elem, region, distance)
            assert _hover(s, *point) == region, distance

    @pytest.mark.parametrize("zoom", [1.0, 2.0])
    @pytest.mark.parametrize("region", sorted(ROTATE_HANDLES, key=str))
    def test_the_ring_ends_at_six_and_fourteen_pixels(
        self, world_surface_factory, zoom, region
    ):
        s = world_surface_factory()
        s.set_zoom(zoom)
        elem = _selected(s)

        # Inside the ring is the corner's resize handle, which straddles
        # the corner; outside it is nothing.
        inside = _ring_point(s, elem, region, ROTATE_ZONE_INNER - 2)
        assert _hover(s, *inside) == RESIZE_CORNER[region]
        outside = _ring_point(s, elem, region, ROTATE_ZONE_OUTER + 1)
        assert _hover(s, *outside) == ElementRegion.NONE

    @pytest.mark.parametrize("region", sorted(ROTATE_HANDLES, key=str))
    def test_inside_the_corner_still_resizes(
        self, world_surface_factory, region
    ):
        s = world_surface_factory()
        elem = _selected(s)

        point = _ring_point(s, elem, region, -3.0)
        assert _hover(s, *point) == RESIZE_CORNER[region]

    def test_the_ring_is_round_not_only_diagonal(self, world_surface_factory):
        s = world_surface_factory()
        elem = _selected(s)
        cx, cy = _corner(_screen_frame(s, elem), ElementRegion.ROTATE_TOP_LEFT)

        # Straight above the corner, and straight left of it.
        assert _hover(s, cx, cy - 10) == ElementRegion.ROTATE_TOP_LEFT
        assert _hover(s, cx - 10, cy) == ElementRegion.ROTATE_TOP_LEFT

    def test_a_fresh_selection_shows_the_rotate_cursor(
        self, world_surface_factory, monkeypatch
    ):
        s = world_surface_factory()
        elem = _selected(s)
        regions = []
        real = canvas_module.get_cursor_for_region

        def spy(region, *args, **kwargs):
            regions.append(region)
            return real(region, *args, **kwargs)

        monkeypatch.setattr(canvas_module, "get_cursor_for_region", spy)

        point = _ring_point(s, elem, ElementRegion.ROTATE_BOTTOM_RIGHT, 10)
        s.on_motion(None, *point)

        assert regions == [ElementRegion.ROTATE_BOTTOM_RIGHT]


def _paint_overlays(s, scale):
    """Paints the surface's overlays on a transparent image at a device
    scale factor; returns the alpha of each device pixel."""
    width, height = s.get_width(), s.get_height()
    image = cairo.ImageSurface(
        cairo.FORMAT_ARGB32, width * scale, height * scale
    )
    image.set_device_scale(scale, scale)
    ctx = cairo.Context(image)
    s._render_overlays(ctx)
    image.flush()
    data = np.frombuffer(image.get_data(), dtype=np.uint8)
    rows = data.reshape(height * scale, image.get_stride())
    # ARGB32 is native-endian; on little-endian hosts alpha is byte 3.
    return rows[:, : width * scale * 4].reshape(
        height * scale, width * scale, 4
    )[:, :, 3]


def _painted_at_radius(alpha, center, radius):
    """How many pixels are painted within 1.5 pixels of a circle."""
    rows, cols = np.indices(alpha.shape)
    distance = np.hypot(cols + 0.5 - center[0], rows + 0.5 - center[1])
    return int(((np.abs(distance - radius) <= 1.5) & (alpha > 0)).sum())


class TestRotateHandlesDrawn:
    def test_hidden_while_rotating_with_the_angle_beside_the_pointer(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        elem = _selected(s)
        pivot = s.view_transform.transform_point(elem.get_world_center())
        # Idle, nothing is drawn around the centre.
        idle = _paint_overlays(s, 1)
        assert _painted_at_radius(idle, pivot, ROTATION_ARC_RADIUS) == 0

        x, y = _ring_point(s, elem, ElementRegion.ROTATE_TOP_RIGHT, 10)
        gesture = _gesture(x, y)
        s._drag_gesture = gesture
        s.on_button_press(gesture, 1, x, y)
        tx, ty = _rotated_about(s, x, y, elem.get_world_center(), 30)
        s.on_mouse_drag(gesture, tx - x, ty - y)

        alpha = _paint_overlays(s, 1)

        # The readout's tag sits below and right of the pointer.
        tag = alpha[int(ty) + 16 : int(ty) + 30, int(tx) + 16 : int(tx) + 40]
        assert (tag > 128).sum() > 100
        # The arc about the centre, from the press to the pointer.
        assert _painted_at_radius(alpha, pivot, ROTATION_ARC_RADIUS) > 10


class TestRotateDrag:
    def test_press_on_the_ring_then_drag_rotates_about_the_center(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        elem = _selected(s)
        center = elem.get_world_center()
        x, y = _ring_point(s, elem, ElementRegion.ROTATE_TOP_RIGHT, 10)
        gesture = _gesture(x, y)
        s._drag_gesture = gesture

        s.on_button_press(gesture, 1, x, y)
        assert s._active_region == ElementRegion.ROTATE_TOP_RIGHT
        tx, ty = _rotated_about(s, x, y, center, 30)
        s.on_mouse_drag(gesture, tx - x, ty - y)

        assert s._rotating
        assert elem.get_world_center() == pytest.approx(center)
        assert elem.get_world_transform().get_rotation() == pytest.approx(30)
        # Counterclockwise on screen: the Angle field reads -30.
        assert s._rotation_readout[0] == pytest.approx(-30)
        assert s._rotation_readout[1] == pytest.approx((tx, ty))

        s.on_drag_end(gesture, tx - x, ty - y)
        assert not s._rotating
        assert s._rotation_readout is None

    def _rotate(self, s, elem, degrees, shift=False, ctrl=False):
        """Drags the pointer `degrees` about the element's center, from
        a point to its right."""
        center = elem.get_world_center()
        start = s.view_transform.transform_point((center[0] + 50.0, center[1]))
        s._drag_target = elem
        s._active_region = ElementRegion.ROTATE_TOP_RIGHT
        s._initial_world_transform = elem.get_world_transform()
        s._shift_pressed = shift
        s._ctrl_pressed = ctrl
        s._start_rotation(elem, *s._get_world_coords(*start))
        gesture = _gesture(*start)
        s._drag_gesture = gesture
        tx, ty = _rotated_about(s, start[0], start[1], center, degrees)
        s.on_mouse_drag(gesture, tx - start[0], ty - start[1])
        return center

    @pytest.mark.parametrize(
        "initial, degrees, shift, ctrl, final",
        [
            (0.0, 37.0, False, False, 37.0),
            (0.0, 37.0, True, False, 30.0),
            (0.0, 38.0, True, False, 45.0),
            (0.0, -52.0, True, False, -45.0),
            # Shift snaps the angle the selection ends at, not the drag.
            (10.0, 37.0, True, False, 45.0),
            (0.0, 37.0, False, True, 35.0),
            # Shift wins over Ctrl.
            (0.0, 37.0, True, True, 30.0),
        ],
    )
    def test_the_selection_ends_at_the_snapped_angle(
        self, world_surface_factory, initial, degrees, shift, ctrl, final
    ):
        s = world_surface_factory()
        elem = _selected(s, angle=initial)
        assert (
            _angle_diff(elem.get_world_transform().get_rotation(), initial)
            < 1e-6
        )

        center = self._rotate(s, elem, degrees, shift, ctrl)

        rotation = elem.get_world_transform().get_rotation()
        assert _angle_diff(rotation, final) < 1e-6
        assert elem.get_world_center() == pytest.approx(center)
        assert s._rotation_readout[0] == pytest.approx(-final)

    @pytest.mark.parametrize(
        "initial, degrees, readout",
        [
            # Past 180 the readout wraps, as the Angle field does.
            (170.0, 20.0, 170.0),
            (-170.0, -20.0, -170.0),
            # A hair clockwise of zero reads as a small positive angle.
            (20.0, -20.4, 0.4),
        ],
    )
    def test_the_readout_is_the_clockwise_angle_wrapped(
        self, world_surface_factory, initial, degrees, readout
    ):
        s = world_surface_factory()
        elem = _selected(s, angle=initial)

        self._rotate(s, elem, degrees)

        assert s._rotation_readout[0] == pytest.approx(readout)


@pytest.fixture
def work_surface(ui_context_initializer, ui_task_mgr):
    """A real editor and surface with one selected workpiece."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    wp = WorkPiece(name="wp")
    wp.set_size(60, 40)
    wp.pos = (60, 50)
    editor.doc.active_layer.add_child(wp)

    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    surface = WorkSurface(editor, Gtk.Window(), machine)
    surface.get_width = lambda: 800
    surface.get_height = lambda: 600
    surface._rebuild_view_transform()
    surface.update_from_doc()
    elem = surface.find_by_data(wp)
    assert elem is not None
    elem.selected = True
    surface._finalize_selection_state()

    yield editor, surface, elem, wp

    editor.cleanup()


def test_a_rotate_drag_is_one_undo_step(work_surface):
    editor, s, elem, wp = work_surface
    history = editor.history_manager
    before = wp.matrix.copy()
    steps = len(history.undo_stack)
    x, y = _ring_point(s, elem, ElementRegion.ROTATE_TOP_LEFT, 10)
    gesture = _gesture(x, y)
    s._drag_gesture = gesture

    s.on_button_press(gesture, 1, x, y)
    assert s._active_region == ElementRegion.ROTATE_TOP_LEFT
    # Several updates, as a real drag sends.
    for degrees in (5, 12, 20, 25):
        tx, ty = _rotated_about(s, x, y, elem.get_world_center(), degrees)
        s.on_mouse_drag(gesture, tx - x, ty - y)
    s.on_drag_end(gesture, tx - x, ty - y)

    assert len(history.undo_stack) == steps + 1
    assert _angle_diff(wp.matrix.get_rotation(), 25) < 1e-6

    history.undo()
    assert wp.matrix == before

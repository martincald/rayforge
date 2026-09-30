"""The haptic hook: "alignment" once each time a Ctrl-drag lands on a
new grid or angle snap, never again while it stays there, and
"generic" on zoom-to-fit."""

import math
from unittest.mock import MagicMock, call

import pytest

from swiftcut.ui_gtk.canvas.element import CanvasElement
from swiftcut.ui_gtk.canvas.region import ElementRegion

pytestmark = pytest.mark.ui

START_PX = (100.0, 100.0)


def _surface(factory):
    s = factory()
    s.haptic_hook = MagicMock()
    elem = CanvasElement(37.3, 61.7, 10.0, 8.0, canvas=s, parent=s.root)
    s.root.add(elem)
    return s, elem


def _begin(s, elem, region=ElementRegion.BODY, ctrl=True):
    """Sets up a press on elem, as on_button_press would leave it."""
    s._drag_target = elem
    s._active_region = region
    s._initial_world_transform = elem.get_world_transform()
    s._ctrl_pressed = ctrl
    s._shift_pressed = False
    gesture = MagicMock()
    gesture.get_start_point.return_value = (True, *START_PX)
    s._drag_gesture = gesture


def _move_to(s, elem, x_mm, y_mm):
    """Drags so the element's unsnapped origin lands at (x_mm, y_mm)."""
    ix, iy = s._initial_world_transform.get_translation()
    world = s._get_world_coords(*START_PX)
    sx, sy = s.view_transform.transform_point(
        (world[0] + x_mm - ix, world[1] + y_mm - iy)
    )
    s.on_mouse_drag(s._drag_gesture, sx - START_PX[0], sy - START_PX[1])
    return elem.transform.get_translation()


class TestGridSnap:
    def test_fires_once_per_new_grid_line(self, world_surface_factory):
        s, elem = _surface(world_surface_factory)
        _begin(s, elem)

        first = _move_to(s, elem, 40.1, 62.1)
        same = _move_to(s, elem, 39.9, 62.2)
        assert first == pytest.approx((40.0, 62.0))
        assert same == pytest.approx(first)
        assert s.haptic_hook.mock_calls == [call("alignment")]

        other = _move_to(s, elem, 42.2, 62.1)
        assert other == pytest.approx((42.0, 62.0))
        assert s.haptic_hook.mock_calls == [call("alignment")] * 2

    def test_no_ctrl_no_call(self, world_surface_factory):
        s, elem = _surface(world_surface_factory)
        _begin(s, elem, ctrl=False)

        _move_to(s, elem, 40.1, 62.1)
        _move_to(s, elem, 42.2, 62.1)

        s.haptic_hook.assert_not_called()

    def test_a_new_drag_fires_again(self, world_surface_factory):
        s, elem = _surface(world_surface_factory)
        _begin(s, elem)
        _move_to(s, elem, 40.1, 62.1)
        s.on_drag_end(s._drag_gesture, 0.0, 0.0)

        # A twin where elem started lands on the snap the last drag
        # ended on.
        twin = CanvasElement(37.3, 61.7, 10.0, 8.0, canvas=s, parent=s.root)
        s.root.add(twin)
        _begin(s, twin)
        again = _move_to(s, twin, 40.2, 62.1)

        assert again == pytest.approx((40.0, 62.0))
        assert s.haptic_hook.mock_calls == [call("alignment")] * 2

    def test_releasing_ctrl_mid_drag_rearms(self, world_surface_factory):
        s, elem = _surface(world_surface_factory)
        _begin(s, elem)
        _move_to(s, elem, 40.1, 62.1)

        s._ctrl_pressed = False
        _move_to(s, elem, 40.2, 62.1)
        s._ctrl_pressed = True
        _move_to(s, elem, 40.1, 62.1)

        assert s.haptic_hook.mock_calls == [call("alignment")] * 2


def _rotate_to(s, start_px, pivot, radius_mm, degrees):
    """Drags the pointer to `degrees` counter-clockwise about the pivot,
    `radius_mm` from it."""
    a = math.radians(degrees)
    x, y = s.view_transform.transform_point(
        (
            pivot[0] + radius_mm * math.cos(a),
            pivot[1] + radius_mm * math.sin(a),
        )
    )
    s.on_mouse_drag(s._drag_gesture, x - start_px[0], y - start_px[1])


def test_ctrl_rotate_fires_once_per_new_angle(world_surface_factory):
    s, elem = _surface(world_surface_factory)
    pivot = elem.get_world_center()
    radius_mm = 30.0
    start_world = (pivot[0] + radius_mm, pivot[1])
    start_px = s.view_transform.transform_point(start_world)
    _begin(s, elem, region=ElementRegion.ROTATE_TOP_LEFT)
    s._drag_gesture.get_start_point.return_value = (True, *start_px)
    s._start_rotation(elem, *start_world)

    calls = []
    for degrees in (11.0, 9.0, 12.0, 22.0):
        _rotate_to(s, start_px, pivot, radius_mm, degrees)
        calls.append(len(s.haptic_hook.mock_calls))

    # 11, 9 and 12 degrees all snap to 10; 22 snaps to 20.
    assert calls == [1, 1, 1, 2]
    assert s.haptic_hook.mock_calls == [call("alignment")] * 2


def test_zoom_to_fit_plays_generic(world_surface_factory):
    s, _ = _surface(world_surface_factory)

    s.zoom_to_fit()

    s.haptic_hook.assert_called_once_with("generic")

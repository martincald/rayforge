"""Unit tests for the Camera model (Package D, stages 2 and 3).

Camera is a plain Python object with no GTK dependency, so these tests
run in the default (non-UI) suite, matching test_region.py.
"""

import random

import pytest

from rayforge.ui_gtk.canvas.camera import Camera


class TestCameraDefaults:
    def test_defaults_to_identity_view(self):
        c = Camera()
        assert c.zoom == 1.0
        assert c.pan_x_mm == 0.0
        assert c.pan_y_mm == 0.0


class TestCameraSetPan:
    def test_set_pan_updates_both_axes(self):
        c = Camera()
        c.set_pan(12.5, -7.25)
        assert c.pan_x_mm == 12.5
        assert c.pan_y_mm == -7.25


class TestCameraSetZoom:
    def test_set_zoom_is_unclamped_by_default(self):
        """With no bounds set, the default range is [0, inf)."""
        c = Camera()
        c.set_zoom(3.25)
        assert c.zoom == 3.25

    def test_set_zoom_clamps_to_configured_bounds(self):
        c = Camera()
        c.set_zoom_bounds(0.1, 26.2)
        c.set_zoom(-5.0)
        assert c.zoom == pytest.approx(0.1)
        c.set_zoom(1000.0)
        assert c.zoom == pytest.approx(26.2)
        c.set_zoom(5.0)
        assert c.zoom == 5.0

    def test_changing_bounds_reclamps_future_calls(self):
        c = Camera()
        c.set_zoom_bounds(0.1, 10.0)
        c.set_zoom(10.0)
        assert c.zoom == 10.0

        c.set_zoom_bounds(0.1, 2.0)
        c.set_zoom(10.0)
        assert c.zoom == pytest.approx(2.0)


class TestCameraPanByPixelOffset:
    def test_matches_the_documented_formula(self):
        """
        Pins the exact formula shared by middle-drag and space+drag
        panning: new_pan = start_pan -/+ (offset_px / scale), with the
        y-inversion sign flip baked in (see WorldSurface.on_pan_update
        for why the signs differ between axes).
        """
        c = Camera()
        new_x, new_y = c.pan_by_pixel_offset(
            start_pan_x_mm=5.0,
            start_pan_y_mm=-3.0,
            offset_x_px=38.1,
            offset_y_px=-19.05,
            scale_x_px_per_mm=3.81,
            scale_y_px_per_mm=3.81,
        )
        assert new_x == pytest.approx(5.0 - 10.0)
        assert new_y == pytest.approx(-3.0 - 5.0)

    def test_zero_offset_is_a_no_op(self):
        c = Camera()
        new_x, new_y = c.pan_by_pixel_offset(1.0, 2.0, 0.0, 0.0, 3.81, 3.81)
        assert new_x == 1.0
        assert new_y == 2.0


def _world_point_under_pointer(
    pointer_x: float,
    pointer_y: float,
    zoom: float,
    pan_x: float,
    pan_y: float,
    base_scale_x: float,
    base_scale_y: float,
    content_x: float,
    content_y: float,
    content_h: float,
) -> tuple[float, float]:
    """
    Independently solves WorldSurface's screen<->world relationship
    (see Camera.zoom_about_point's docstring) for the world point at a
    given screen point, given an explicit camera/layout state. Used to
    verify the zoom-about-point invariant without relying on the
    method under test to also report it correctly.
    """
    sx = zoom * base_scale_x
    sy = zoom * base_scale_y
    world_x = pan_x + (pointer_x - content_x) / sx
    world_y = pan_y + (content_y + zoom * content_h - pointer_y) / sy
    return world_x, world_y


class TestCameraZoomAboutPoint:
    def test_does_not_mutate_the_camera(self):
        """zoom_about_point returns a result; callers apply it explicitly."""
        c = Camera()
        c.set_pan(5.0, -3.0)
        c.zoom_about_point(100.0, 50.0, 2.0, 3.81, 3.81, 25.0, 10.75, 571.5)
        assert c.zoom == 1.0
        assert c.pan_x_mm == 5.0
        assert c.pan_y_mm == -3.0

    def test_clamps_to_configured_bounds(self):
        c = Camera()
        c.set_zoom_bounds(0.1, 5.0)
        zoom, _, _ = c.zoom_about_point(
            100.0, 50.0, 50.0, 3.81, 3.81, 25.0, 10.75, 571.5
        )
        assert zoom == pytest.approx(5.0)

    def test_no_op_when_new_zoom_equals_current_zoom(self):
        c = Camera()
        c.set_pan(5.0, -3.0)
        zoom, pan_x, pan_y = c.zoom_about_point(
            100.0, 50.0, 1.0, 3.81, 3.81, 25.0, 10.75, 571.5
        )
        assert zoom == 1.0
        assert pan_x == 5.0
        assert pan_y == -3.0

    def test_world_point_under_pointer_is_unchanged_by_a_single_step(self):
        """
        A concrete, hand-checkable case: zooming a 200x150mm/800x600px
        WorldSurface-like layout in from 1.0 to 2.0 about a specific
        screen point must leave the world point under that point fixed.
        """
        c = Camera()
        content_x, content_y, content_h = 25.0, 10.75, 571.5
        base_scale = 3.81
        pointer = (300.0, 250.0)

        world_before = _world_point_under_pointer(
            *pointer, c.zoom, c.pan_x_mm, c.pan_y_mm,
            base_scale, base_scale, content_x, content_y, content_h,
        )
        zoom, pan_x, pan_y = c.zoom_about_point(
            *pointer, 2.0, base_scale, base_scale,
            content_x, content_y, content_h,
        )
        world_after = _world_point_under_pointer(
            *pointer, zoom, pan_x, pan_y,
            base_scale, base_scale, content_x, content_y, content_h,
        )
        assert world_after[0] == pytest.approx(world_before[0], abs=1e-9)
        assert world_after[1] == pytest.approx(world_before[1], abs=1e-9)

    def test_property_world_point_under_pointer_is_invariant(self):
        """
        REQUIRED PROPERTY TEST (Package D stage 3): for randomised
        (pointer p, old scale s, new scale s'), the world point under p
        is unchanged after zoom, tolerance 1e-6. Randomised over a wide
        range of zoom levels (1e-3 .. 1e3, three orders of magnitude
        past the real MIN_ZOOM_FACTOR/soft-max-zoom range), pan,
        pointer position (including off-content-area points), and
        view layout (base scale, content offset/height).
        """
        rng = random.Random(20260904)
        max_err = 0.0
        for _ in range(2000):
            old_zoom = 10 ** rng.uniform(-3, 3)
            new_zoom = 10 ** rng.uniform(-3, 3)
            pan_x = rng.uniform(-1000.0, 1000.0)
            pan_y = rng.uniform(-1000.0, 1000.0)
            pointer_x = rng.uniform(-1500.0, 2300.0)
            pointer_y = rng.uniform(-1500.0, 2300.0)
            base_scale_x = 10 ** rng.uniform(-2, 2)
            base_scale_y = 10 ** rng.uniform(-2, 2)
            content_x = rng.uniform(-200.0, 900.0)
            content_y = rng.uniform(-200.0, 900.0)
            content_h = 10 ** rng.uniform(1, 3.5)

            c = Camera()
            c.set_zoom_bounds(0.0, float("inf"))
            c.set_zoom(old_zoom)
            c.set_pan(pan_x, pan_y)

            world_before = _world_point_under_pointer(
                pointer_x, pointer_y, old_zoom, pan_x, pan_y,
                base_scale_x, base_scale_y, content_x, content_y, content_h,
            )
            zoom, new_pan_x, new_pan_y = c.zoom_about_point(
                pointer_x, pointer_y, new_zoom,
                base_scale_x, base_scale_y, content_x, content_y, content_h,
            )
            world_after = _world_point_under_pointer(
                pointer_x, pointer_y, zoom, new_pan_x, new_pan_y,
                base_scale_x, base_scale_y, content_x, content_y, content_h,
            )

            err = max(
                abs(world_after[0] - world_before[0]),
                abs(world_after[1] - world_before[1]),
            )
            max_err = max(max_err, err)
            assert err < 1e-6, (
                f"world point drifted by {err} for old_zoom={old_zoom}, "
                f"new_zoom={new_zoom}, pointer=({pointer_x}, {pointer_y})"
            )

        # Sanity: the achieved precision is comfortably tighter than
        # the required 1e-6 tolerance across the whole randomised range.
        assert max_err < 1e-7

"""Unit tests for the Camera model (Package D, stage 2).

Camera is a plain Python object with no GTK dependency, so these tests
run in the default (non-UI) suite, matching test_region.py.
"""

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

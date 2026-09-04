"""Unit tests for CameraAnimator (Package D, stage 3).

CameraAnimator is a plain Python object with no GTK dependency (see its
module docstring), so these tests run in the default (non-UI) suite,
matching test_camera.py.
"""

import pytest

from rayforge.ui_gtk.canvas.camera import Camera
from rayforge.ui_gtk.canvas.camera_animator import (
    DEFAULT_DURATION_MS,
    CameraAnimator,
    ease_out_cubic,
)


class TestEaseOutCubic:
    def test_starts_at_zero_and_ends_at_one(self):
        assert ease_out_cubic(0.0) == pytest.approx(0.0)
        assert ease_out_cubic(1.0) == pytest.approx(1.0)

    def test_clamps_outside_the_unit_interval(self):
        assert ease_out_cubic(-1.0) == pytest.approx(0.0)
        assert ease_out_cubic(2.0) == pytest.approx(1.0)

    def test_is_monotonically_increasing(self):
        samples = [ease_out_cubic(t / 10.0) for t in range(11)]
        assert samples == sorted(samples)


class TestCameraAnimatorStart:
    def test_is_running_after_start(self):
        c = Camera()
        a = CameraAnimator(c)
        assert not a.is_running
        a.start(2.0, 10.0, -5.0, now_ms=0.0)
        assert a.is_running

    def test_stop_cancels_without_changing_the_camera(self):
        c = Camera()
        a = CameraAnimator(c)
        a.start(2.0, 10.0, -5.0, now_ms=0.0)
        a.stop()
        assert not a.is_running
        assert c.zoom == 1.0
        assert c.pan_x_mm == 0.0
        assert c.pan_y_mm == 0.0


class TestCameraAnimatorAdvance:
    def test_advance_with_no_animation_is_a_no_op(self):
        c = Camera()
        a = CameraAnimator(c)
        assert a.advance(1000.0) is False
        assert c.zoom == 1.0

    def test_at_t_zero_the_camera_is_unchanged(self):
        c = Camera()
        a = CameraAnimator(c)
        a.start(2.0, 10.0, -5.0, now_ms=100.0)
        still_running = a.advance(100.0)
        assert still_running is True
        assert c.zoom == pytest.approx(1.0)
        assert c.pan_x_mm == pytest.approx(0.0)
        assert c.pan_y_mm == pytest.approx(0.0)

    def test_partway_through_the_camera_is_between_start_and_target(self):
        c = Camera()
        a = CameraAnimator(c, duration_ms=200.0)
        a.start(2.0, 10.0, -5.0, now_ms=0.0)
        still_running = a.advance(100.0)
        assert still_running is True
        assert 1.0 < c.zoom < 2.0
        assert 0.0 < c.pan_x_mm < 10.0
        assert -5.0 < c.pan_y_mm < 0.0

    def test_converges_to_its_target_within_the_stated_duration(self):
        """
        REQUIRED TEST (Package D stage 3): the animation must reach
        its target within the documented 150-200ms window.
        """
        c = Camera()
        a = CameraAnimator(c, duration_ms=200.0)
        a.start(2.5, 12.0, -8.0, now_ms=1000.0)

        # Exactly at the duration boundary, the animation must report
        # completion and snap to the exact target.
        still_running = a.advance(1000.0 + 200.0)
        assert still_running is False
        assert not a.is_running
        assert c.zoom == pytest.approx(2.5)
        assert c.pan_x_mm == pytest.approx(12.0)
        assert c.pan_y_mm == pytest.approx(-8.0)

    def test_further_advances_after_completion_are_no_ops(self):
        c = Camera()
        a = CameraAnimator(c, duration_ms=200.0)
        a.start(2.5, 12.0, -8.0, now_ms=0.0)
        a.advance(300.0)  # finishes
        assert a.advance(400.0) is False
        assert c.zoom == pytest.approx(2.5)

    def test_default_duration_is_within_the_150_to_200ms_window(self):
        assert 150.0 <= DEFAULT_DURATION_MS <= 200.0

    def test_restarting_mid_flight_starts_from_the_current_live_state(self):
        """
        A new start() call (e.g. a second wheel notch before the first
        finishes) must ease from wherever the live camera currently is,
        not from the original start point.
        """
        c = Camera()
        a = CameraAnimator(c, duration_ms=200.0)
        a.start(2.0, 10.0, 0.0, now_ms=0.0)
        a.advance(100.0)  # halfway
        mid_zoom = c.zoom
        assert 1.0 < mid_zoom < 2.0

        a.start(4.0, 20.0, 0.0, now_ms=100.0)
        a.advance(100.0)  # t=0 of the new animation
        assert c.zoom == pytest.approx(mid_zoom)


class TestCameraAnimatorClamping:
    def test_target_is_clamped_by_the_cameras_bounds(self):
        """
        set_zoom/set_pan on the underlying Camera still clamp zoom to
        its configured bounds, so an animation cannot ease past them.
        """
        c = Camera()
        c.set_zoom_bounds(0.1, 5.0)
        a = CameraAnimator(c, duration_ms=200.0)
        a.start(50.0, 0.0, 0.0, now_ms=0.0)
        a.advance(200.0)
        assert c.zoom == pytest.approx(5.0)

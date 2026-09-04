"""Tests for the D5 fix: the "keep >=20% of the bed visible" rule is a
SOFT PAN clamp (MIN_VISIBLE_BED_FRACTION), not a max-zoom ceiling.

Max-zoom coverage lives in test_worldsurface_pan_zoom.py
(TestMaxZoomOnLargeBed) and test_worldsurface_navigation.py
(TestZoomClampsAtExtremes). This file covers:

(a) panning far in any direction settles with at least
    MIN_VISIBLE_BED_FRACTION of the bed still inside the viewport;
(b) the clamp is soft: an active gesture may transiently overshoot
    it, and it eases back only once the gesture ends;
(c) trackpad-flick inertia that carries the view past the limit
    settles at the boundary instead of oscillating or sticking
    outside it.
"""

from unittest.mock import MagicMock

import pytest
from gi.repository import GLib

pytestmark = pytest.mark.ui


def _visible_bed_fraction(s) -> tuple[float, float]:
    """
    Returns the fraction of the bed's width/height that is currently
    visible in the viewport, computed independently from the pan
    clamp implementation under test (from width_mm/height_mm, zoom
    and pan alone, mirroring WorldSurface._update_pan_bounds's own
    "visible = size / zoom" derivation).
    """
    zoom = s.zoom_level
    visible_w = s.width_mm / zoom
    visible_h = s.height_mm / zoom
    overlap_x = min(s.pan_x_mm + visible_w, s.width_mm) - max(
        s.pan_x_mm, 0.0
    )
    overlap_y = min(s.pan_y_mm + visible_h, s.height_mm) - max(
        s.pan_y_mm, 0.0
    )
    return (
        max(overlap_x, 0.0) / s.width_mm,
        max(overlap_y, 0.0) / s.height_mm,
    )


def _drag_pan(s, offset_x: float, offset_y: float) -> MagicMock:
    """Drives a middle-drag pan gesture (begin/update) by a large
    pixel offset, without ending it."""
    gesture = MagicMock()
    s.on_pan_begin(gesture, 0.0, 0.0)
    gesture.get_offset.return_value = (True, offset_x, offset_y)
    s.on_pan_update(gesture, 0.0, 0.0)
    return gesture


class TestPanClampKeepsBedReachable:
    """REQUIRED TEST (part a)."""

    @pytest.mark.parametrize(
        "offset_x, offset_y",
        [
            (100_000.0, 0.0),
            (-100_000.0, 0.0),
            (0.0, 100_000.0),
            (0.0, -100_000.0),
        ],
    )
    def test_settles_with_min_visible_bed_fraction(
        self, world_surface_factory, finish_animation, offset_x, offset_y
    ):
        s = world_surface_factory()
        gesture = _drag_pan(s, offset_x, offset_y)
        s.on_pan_end(gesture, 0.0, 0.0)
        finish_animation(s)

        frac_x, frac_y = _visible_bed_fraction(s)
        assert frac_x >= s.MIN_VISIBLE_BED_FRACTION - 1e-6
        assert frac_y >= s.MIN_VISIBLE_BED_FRACTION - 1e-6


class TestPanClampIsSoft:
    """REQUIRED TEST (part b)."""

    def test_overshoots_during_the_gesture_then_eases_back_on_release(
        self, world_surface_factory, finish_animation
    ):
        s = world_surface_factory()
        gesture = _drag_pan(s, 100_000.0, 0.0)

        # Still mid-gesture: the live pan is allowed to overshoot the
        # soft clamp, and no easing animation has started yet.
        frac_x, _ = _visible_bed_fraction(s)
        assert frac_x < s.MIN_VISIBLE_BED_FRACTION
        assert not s._camera_animator.is_running

        s.on_pan_end(gesture, 0.0, 0.0)
        assert s._camera_animator.is_running

        finish_animation(s)
        frac_x, _ = _visible_bed_fraction(s)
        assert frac_x >= s.MIN_VISIBLE_BED_FRACTION - 1e-6

    def test_pan_within_bounds_does_not_start_an_easing_animation(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        gesture = _drag_pan(s, 5.0, 5.0)
        s.on_pan_end(gesture, 0.0, 0.0)
        assert not s._camera_animator.is_running


class TestPanClampAndInertia:
    """REQUIRED TEST (part c)."""

    def test_inertia_settles_at_the_boundary_instead_of_oscillating(
        self, world_surface_factory, finish_animation
    ):
        s = world_surface_factory()

        # A hard, fast flick far beyond the visible-bed-fraction bound.
        s.on_scroll_decelerate(MagicMock(), -6000.0, 0.0)
        assert s._inertia_tick_id is not None

        # Drive the inertia tick loop to completion. It self-
        # terminates as soon as it crosses the clamp boundary (see
        # WorldSurface._on_inertia_tick / _ease_pan_into_bounds),
        # instead of coasting further out or fighting an ease-back.
        frame_clock = MagicMock()
        for _ in range(500):
            if s._inertia_tick_id is None:
                break
            result = s._on_inertia_tick(s, frame_clock)
            if result == GLib.SOURCE_REMOVE:
                break
        assert s._inertia_tick_id is None

        # The clamp hand-off started an ease-back animation rather
        # than leaving the view stuck out of bounds.
        assert s._camera_animator.is_running
        finish_animation(s)

        frac_x, _ = _visible_bed_fraction(s)
        assert frac_x >= s.MIN_VISIBLE_BED_FRACTION - 1e-6

        # Settling is monotonic once eased -- no oscillation back out
        # of bounds afterwards.
        finish_animation(s)
        frac_x, _ = _visible_bed_fraction(s)
        assert frac_x >= s.MIN_VISIBLE_BED_FRACTION - 1e-6

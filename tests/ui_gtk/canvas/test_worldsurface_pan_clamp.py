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
    outside it;
(d) after zooming in, a pan that stays on the bed ends exactly where
    the gesture left it: no snap-back, and no reversing glide.
"""

from itertools import pairwise
from unittest.mock import MagicMock

import pytest
from gi.repository import Gdk, GLib

pytestmark = pytest.mark.ui


def _visible_bed_fraction(s) -> tuple[float, float]:
    """
    Returns the fraction of the bed's width/height that is currently
    visible in the viewport, computed independently from the pan
    clamp implementation under test: the content area's corners are
    mapped to world space through the live view transform.
    """
    content_x, content_y, content_w, content_h = (
        s._axis_renderer.get_content_layout(s.get_width(), s.get_height())
    )
    left, top = s._get_world_coords(content_x, content_y)
    right, bottom = s._get_world_coords(
        content_x + content_w, content_y + content_h
    )
    overlap_x = min(right, s.width_mm) - max(left, 0.0)
    overlap_y = min(top, s.height_mm) - max(bottom, 0.0)
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


def _pinch_zoom(s, scale: float) -> None:
    """Pinch-zooms by ``scale`` about the widget centre, which lies
    over the bed, so the zoomed-in view stays entirely on it."""
    gesture = MagicMock()
    gesture.get_bounding_box_center.return_value = (
        True,
        s.get_width() / 2.0,
        s.get_height() / 2.0,
    )
    s.on_pinch_begin(gesture, None)
    s.on_pinch_scale_changed(gesture, scale)
    s.on_pinch_end(gesture, None)


def _surface_scroll_controller() -> MagicMock:
    controller = MagicMock()
    controller.get_unit.return_value = Gdk.ScrollUnit.SURFACE
    controller.get_current_event_state.return_value = Gdk.ModifierType(0)
    return controller


def _run_inertia(s) -> list[tuple[float, float]]:
    """Drives the inertia tick loop to completion; returns the pan
    after every tick."""
    pans = []
    for _ in range(500):
        if s._inertia_tick_id is None:
            break
        result = s._on_inertia_tick(s, MagicMock())
        pans.append((s.pan_x_mm, s.pan_y_mm))
        if result == GLib.SOURCE_REMOVE:
            break
    assert s._inertia_tick_id is None
    return pans


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


class TestNoSnapBackAfterZoom:
    """REQUIRED TEST (part d): the macOS snap-back report."""

    @pytest.mark.parametrize("zoom", [0.5, 2.0, 4.0, 8.0])
    def test_a_view_on_the_bed_is_within_the_clamp_at_any_zoom(
        self, world_surface_factory, zoom
    ):
        s = world_surface_factory()
        _pinch_zoom(s, zoom)
        # Zoomed in, the viewport lies wholly on the bed; zoomed out,
        # the whole bed is in view.
        frac_x, frac_y = _visible_bed_fraction(s)
        assert frac_x == pytest.approx(min(1.0, 1.0 / zoom))
        assert frac_y == pytest.approx(min(1.0, 1.0 / zoom))

        assert s._ease_pan_into_bounds() is False
        assert not s._camera_animator.is_running

    @pytest.mark.parametrize("zoom", [2.0, 4.0, 8.0])
    def test_two_finger_pan_after_zoom_stays_where_it_ended(
        self, world_surface_factory, finish_animation, zoom
    ):
        s = world_surface_factory()
        _pinch_zoom(s, zoom)

        controller = _surface_scroll_controller()
        s.on_scroll_begin(controller)
        for _ in range(5):
            s.on_scroll(controller, 0.0, 4.0)
        ended_at = (s.zoom_level, s.pan_x_mm, s.pan_y_mm)

        # Fingers lift with no flick velocity.
        s.on_scroll_decelerate(controller, 0.0, 0.0)
        _run_inertia(s)
        finish_animation(s)

        assert (s.zoom_level, s.pan_x_mm, s.pan_y_mm) == ended_at

    @pytest.mark.parametrize("zoom", [2.0, 4.0, 8.0])
    def test_middle_drag_after_zoom_stays_where_it_ended(
        self, world_surface_factory, finish_animation, zoom
    ):
        s = world_surface_factory()
        _pinch_zoom(s, zoom)

        gesture = _drag_pan(s, 0.0, 40.0)
        ended_at = (s.zoom_level, s.pan_x_mm, s.pan_y_mm)
        s.on_pan_end(gesture, 0.0, 0.0)
        finish_animation(s)

        assert (s.zoom_level, s.pan_x_mm, s.pan_y_mm) == ended_at

    def test_inertia_glide_after_zoom_ends_without_reversal(
        self, world_surface_factory, finish_animation
    ):
        s = world_surface_factory()
        _pinch_zoom(s, 4.0)
        start_y = s.pan_y_mm

        controller = _surface_scroll_controller()
        s.on_scroll_begin(controller)
        s.on_scroll(controller, 0.0, 4.0)
        s.on_scroll_decelerate(controller, 0.0, 600.0)
        pans = _run_inertia(s)
        glide_end = (s.pan_x_mm, s.pan_y_mm)
        finish_animation(s)

        # Fingers down move the content up: pan_y only ever falls.
        ys = [start_y] + [y for _, y in pans]
        assert len(ys) > 2
        assert all(b <= a for a, b in pairwise(ys))
        assert ys[-1] < start_y
        assert (s.pan_x_mm, s.pan_y_mm) == glide_end

"""Tests for Package D's navigation features (stage 3, D2-D5):

- D2: zoom about pointer via wheel (discrete), trackpad Ctrl+scroll
  (continuous), and pinch (continuous).
- D3: discrete zoom steps and zoom-to-fit ease in via CameraAnimator;
  continuous gestures update the live camera with zero lag.
- D4: two-finger trackpad pan, and flick inertia.
- D5: zoom limits (hard MIN_ZOOM_FACTOR, soft MIN_VISIBLE_BED_FRACTION)
  and shortcuts (zoom_to_fit, zoom_to_actual_size, zoom_in/out,
  double-click-to-fit).

D6's gesture-state-leak tests live in
test_worldsurface_gesture_leaks.py.
"""

from unittest.mock import MagicMock

import pytest
from gi.repository import Gdk

from rayforge.ui_gtk.canvas.worldsurface import (
    DISCRETE_ZOOM_FACTOR,
    _decay_pan_velocity,
)

pytestmark = pytest.mark.ui


def make_surface_scroll_controller(
    unit: Gdk.ScrollUnit, ctrl_held: bool = False
) -> MagicMock:
    controller = MagicMock()
    controller.get_unit.return_value = unit
    controller.get_current_event_state.return_value = (
        Gdk.ModifierType.CONTROL_MASK if ctrl_held else Gdk.ModifierType(0)
    )
    return controller


class TestDiscreteWheelZoomFactor:
    def test_one_notch_in_is_exactly_the_discrete_factor(
        self, world_surface_factory, wheel_scroll_controller, finish_animation
    ):
        s = world_surface_factory()
        s._mouse_pos = (400.0, 300.0)
        s.on_scroll(wheel_scroll_controller(), 0.0, -1.0)
        finish_animation(s)
        assert s.zoom_level == pytest.approx(DISCRETE_ZOOM_FACTOR)

    def test_one_notch_out_is_exactly_the_inverse_factor(
        self, world_surface_factory, wheel_scroll_controller, finish_animation
    ):
        s = world_surface_factory()
        s._mouse_pos = (400.0, 300.0)
        s.on_scroll(wheel_scroll_controller(), 0.0, 1.0)
        finish_animation(s)
        assert s.zoom_level == pytest.approx(1.0 / DISCRETE_ZOOM_FACTOR)

    def test_wheel_zoom_is_animated_not_instant(
        self, world_surface_factory, wheel_scroll_controller
    ):
        """A wheel notch must not change the live camera immediately --
        it eases in via CameraAnimator (Package D3)."""
        s = world_surface_factory()
        s._mouse_pos = (400.0, 300.0)
        s.on_scroll(wheel_scroll_controller(), 0.0, -1.0)
        assert s.zoom_level == pytest.approx(1.0)
        assert s._camera_animator.is_running


class TestTrackpadContinuousZoom:
    """Ctrl/Cmd + smooth trackpad scroll: continuous, zero-lag zoom."""

    def test_ctrl_smooth_scroll_zooms_the_live_camera_immediately(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        s._mouse_pos = (400.0, 300.0)
        controller = make_surface_scroll_controller(
            Gdk.ScrollUnit.SURFACE, ctrl_held=True
        )
        s.on_scroll(controller, 0.0, -1.0)

        # No animation in flight: the change already happened.
        assert not s._camera_animator.is_running
        assert s.zoom_level != pytest.approx(1.0)

    def test_world_point_under_cursor_is_stable(self, world_surface_factory):
        s = world_surface_factory()
        cursor_px = (250.0, 180.0)
        s._mouse_pos = cursor_px
        world_before = s._get_world_coords(*cursor_px)

        controller = make_surface_scroll_controller(
            Gdk.ScrollUnit.SURFACE, ctrl_held=True
        )
        s.on_scroll(controller, 0.0, -3.0)

        world_after = s._get_world_coords(*cursor_px)
        assert world_after[0] == pytest.approx(world_before[0], abs=1e-6)
        assert world_after[1] == pytest.approx(world_before[1], abs=1e-6)

    def test_a_pending_discrete_animation_is_pre_empted(
        self, world_surface_factory, wheel_scroll_controller
    ):
        s = world_surface_factory()
        s._mouse_pos = (400.0, 300.0)
        s.on_scroll(wheel_scroll_controller(), 0.0, -1.0)
        assert s._camera_animator.is_running

        controller = make_surface_scroll_controller(
            Gdk.ScrollUnit.SURFACE, ctrl_held=True
        )
        s.on_scroll(controller, 0.0, -1.0)
        assert not s._camera_animator.is_running


class TestTwoFingerScrollPan:
    """Trackpad two-finger scroll (SURFACE unit, no modifier) pans."""

    def test_pans_the_live_camera_with_zero_lag(self, world_surface_factory):
        s = world_surface_factory()
        controller = make_surface_scroll_controller(Gdk.ScrollUnit.SURFACE)
        s.on_scroll(controller, 20.0, -10.0)

        assert not s._camera_animator.is_running
        assert (s.pan_x_mm, s.pan_y_mm) != (0.0, 0.0)

    def test_matches_the_shared_pan_by_pixel_offset_formula(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        scale_x, scale_y = s.get_view_scale()
        expected_x, expected_y = s._camera.pan_by_pixel_offset(
            0.0, 0.0, 20.0, -10.0, scale_x, scale_y
        )

        controller = make_surface_scroll_controller(Gdk.ScrollUnit.SURFACE)
        s.on_scroll(controller, 20.0, -10.0)

        assert s.pan_x_mm == pytest.approx(expected_x)
        assert s.pan_y_mm == pytest.approx(expected_y)


class TestPinchZoom:
    def test_scale_changed_zooms_about_the_gesture_centre_with_zero_lag(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        gesture = MagicMock()
        gesture.get_bounding_box_center.return_value = (True, 200.0, 150.0)

        s.on_pinch_begin(gesture, None)
        s.on_pinch_scale_changed(gesture, 2.0)

        assert not s._camera_animator.is_running
        assert s.zoom_level == pytest.approx(2.0)

    def test_world_point_under_the_gesture_centre_is_stable(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        center = (350.0, 220.0)
        world_before = s._get_world_coords(*center)

        gesture = MagicMock()
        gesture.get_bounding_box_center.return_value = (True, *center)
        s.on_pinch_begin(gesture, None)
        s.on_pinch_scale_changed(gesture, 1.7)

        world_after = s._get_world_coords(*center)
        assert world_after[0] == pytest.approx(world_before[0], abs=1e-6)
        assert world_after[1] == pytest.approx(world_before[1], abs=1e-6)

    def test_scale_changed_before_begin_is_ignored(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        gesture = MagicMock()
        gesture.get_bounding_box_center.return_value = (True, 200.0, 150.0)
        s.on_pinch_scale_changed(gesture, 2.0)
        assert s.zoom_level == pytest.approx(1.0)


class TestPanInertiaDecay:
    """Pins the exact decay formula: velocity *= 0.92/frame, stop < 0.5."""

    def test_decays_by_the_documented_factor(self):
        result = _decay_pan_velocity(10.0, -20.0)
        assert result == pytest.approx((9.2, -18.4))

    def test_stops_once_both_axes_are_below_the_threshold(self):
        assert _decay_pan_velocity(0.4, 0.3) is None
        assert _decay_pan_velocity(0.4, -0.3) is None

    def test_keeps_running_while_either_axis_is_above_the_threshold(self):
        assert _decay_pan_velocity(0.6, 0.0) is not None
        assert _decay_pan_velocity(0.0, -0.6) is not None

    def test_repeated_decay_eventually_stops(self):
        vx, vy = 100.0, 50.0
        for _ in range(1000):
            result = _decay_pan_velocity(vx, vy)
            if result is None:
                return
            vx, vy = result
        pytest.fail("velocity never decayed below the stop threshold")


class TestPanInertiaToggle:
    def test_defaults_to_enabled(self, world_surface_factory):
        s = world_surface_factory()
        assert s.pan_inertia_enabled is True

    def test_decelerate_starts_inertia_when_enabled(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        s.on_scroll_decelerate(MagicMock(), 600.0, 0.0)
        assert s._inertia_tick_id is not None
        assert s._pan_velocity_x == pytest.approx(10.0)

    def test_decelerate_does_nothing_when_disabled(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        s.pan_inertia_enabled = False
        s.on_scroll_decelerate(MagicMock(), 600.0, 0.0)
        assert s._inertia_tick_id is None
        assert s._pan_velocity_x == 0.0


class TestZoomShortcuts:
    """REQUIRED TEST: each shortcut yields its expected scale."""

    def test_zoom_to_fit_resets_zoom_and_pan(
        self, world_surface_factory, finish_animation
    ):
        s = world_surface_factory()
        s.set_zoom(3.0)
        s.set_pan(40.0, -20.0)

        s.zoom_to_fit()
        finish_animation(s)

        assert s.zoom_level == pytest.approx(1.0)
        assert s.pan_x_mm == pytest.approx(0.0)
        assert s.pan_y_mm == pytest.approx(0.0)

    def test_zoom_to_actual_size_sets_zoom_to_one_and_keeps_view_centred(
        self, world_surface_factory, finish_animation
    ):
        s = world_surface_factory()
        s.set_zoom(3.0)
        widget_center = (
            s.get_width() / 2.0,
            s.get_height() / 2.0,
        )
        world_center_before = s._get_world_coords(*widget_center)

        s.zoom_to_actual_size()
        finish_animation(s)

        assert s.zoom_level == pytest.approx(1.0)
        world_center_after = s._get_world_coords(*widget_center)
        assert world_center_after[0] == pytest.approx(
            world_center_before[0], abs=1e-6
        )
        assert world_center_after[1] == pytest.approx(
            world_center_before[1], abs=1e-6
        )

    def test_zoom_in_multiplies_zoom_by_the_discrete_factor(
        self, world_surface_factory, finish_animation
    ):
        s = world_surface_factory()
        s.zoom_in()
        finish_animation(s)
        assert s.zoom_level == pytest.approx(DISCRETE_ZOOM_FACTOR)

    def test_zoom_out_divides_zoom_by_the_discrete_factor(
        self, world_surface_factory, finish_animation
    ):
        s = world_surface_factory()
        s.zoom_out()
        finish_animation(s)
        assert s.zoom_level == pytest.approx(1.0 / DISCRETE_ZOOM_FACTOR)

    def test_zoom_in_and_out_are_anchored_at_the_viewport_centre(
        self, world_surface_factory, finish_animation
    ):
        s = world_surface_factory()
        widget_center = (s.get_width() / 2.0, s.get_height() / 2.0)
        world_center_before = s._get_world_coords(*widget_center)

        s.zoom_in()
        finish_animation(s)

        world_center_after = s._get_world_coords(*widget_center)
        assert world_center_after[0] == pytest.approx(
            world_center_before[0], abs=1e-6
        )
        assert world_center_after[1] == pytest.approx(
            world_center_before[1], abs=1e-6
        )


class TestDoubleClickToFit:
    def test_double_click_on_empty_canvas_fits_the_view(
        self, world_surface_factory, finish_animation
    ):
        s = world_surface_factory()
        s.set_zoom(3.0)
        s.set_pan(40.0, -20.0)

        gesture = MagicMock()
        gesture.get_current_event.return_value = None
        s.on_button_press(gesture, 2, 5.0, 5.0)
        finish_animation(s)

        assert s.zoom_level == pytest.approx(1.0)
        assert s.pan_x_mm == pytest.approx(0.0)
        assert s.pan_y_mm == pytest.approx(0.0)

    def test_single_click_does_not_fit(self, world_surface_factory):
        s = world_surface_factory()
        s.set_zoom(3.0)

        gesture = MagicMock()
        gesture.get_current_event.return_value = None
        s.on_button_press(gesture, 1, 5.0, 5.0)

        assert s.zoom_level == pytest.approx(3.0)
        assert not s._camera_animator.is_running


class TestZoomClampsAtExtremes:
    """REQUIRED TEST: clamps hold at both extremes."""

    def test_repeated_zoom_in_stops_at_the_visible_bed_fraction(
        self, world_surface_factory, finish_animation
    ):
        s = world_surface_factory()
        for _ in range(50):
            s.zoom_in()
            finish_animation(s)
        assert s.zoom_level == pytest.approx(
            1.0 / s.MIN_VISIBLE_BED_FRACTION
        )

    def test_repeated_zoom_out_stops_at_min_zoom_factor(
        self, world_surface_factory, finish_animation
    ):
        s = world_surface_factory()
        for _ in range(50):
            s.zoom_out()
            finish_animation(s)
        assert s.zoom_level == pytest.approx(s.MIN_ZOOM_FACTOR)

    def test_pinch_zoom_in_is_also_clamped(self, world_surface_factory):
        s = world_surface_factory()
        gesture = MagicMock()
        gesture.get_bounding_box_center.return_value = (True, 400.0, 300.0)
        s.on_pinch_begin(gesture, None)
        s.on_pinch_scale_changed(gesture, 1000.0)
        assert s.zoom_level == pytest.approx(
            1.0 / s.MIN_VISIBLE_BED_FRACTION
        )

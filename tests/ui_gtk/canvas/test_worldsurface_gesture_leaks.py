"""D6: no gesture-state leaks (Package D, stage 3).

Navigation gesture state (Space+drag, pinch tracking, trackpad-flick
inertia) must be cleared on: button release, pointer leave, widget
unmap, and focus loss. One test per condition, as required.
"""

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.ui


def _start_pinch_and_inertia(s) -> None:
    """Puts a surface into a state with active pinch tracking and
    in-progress inertia, so a reset can be observed."""
    gesture = MagicMock()
    gesture.get_bounding_box_center.return_value = (True, 200.0, 150.0)
    s.on_pinch_begin(gesture, None)
    assert s._pinch_start_zoom is not None

    s.on_scroll_decelerate(MagicMock(), 600.0, 600.0)
    assert s._inertia_tick_id is not None


class TestGestureStateClearedOnRelease:
    """Condition 1: button/gesture release."""

    def test_pan_gesture_release_stops_in_progress_inertia(
        self, world_surface_factory
    ):
        """
        Starting a new middle-drag pan (on_pan_begin/on_pan_end) must
        not leave a PREVIOUS trackpad flick still coasting underneath
        it.
        """
        s = world_surface_factory()
        s.on_scroll_decelerate(MagicMock(), 600.0, 600.0)
        assert s._inertia_tick_id is not None

        gesture = MagicMock()
        s.on_pan_begin(gesture, 0.0, 0.0)
        s.on_pan_end(gesture, 0.0, 0.0)

        assert s._inertia_tick_id is None
        assert s._pan_velocity_x == 0.0
        assert s._pan_velocity_y == 0.0

    def test_pinch_gesture_release_clears_pinch_tracking(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        gesture = MagicMock()
        gesture.get_bounding_box_center.return_value = (True, 200.0, 150.0)
        s.on_pinch_begin(gesture, None)
        assert s._pinch_start_zoom is not None

        s.on_pinch_end(gesture, None)

        assert s._pinch_start_zoom is None

    def test_space_drag_release_does_not_clear_space_pressed(
        self, world_surface_factory
    ):
        """
        Releasing the mouse button while Space is still held must NOT
        cancel Space+drag capability -- only the Space key's own
        release should do that. This is the one deliberate asymmetry:
        "release" clears transient per-gesture state (pinch, inertia)
        but not _space_pressed.
        """
        s = world_surface_factory()
        s._space_pressed = True
        gesture = MagicMock()
        gesture.get_offset.return_value = (True, 5.0, 5.0)
        s.on_drag_end(gesture, 5.0, 5.0)
        assert s._space_pressed is True


class TestGestureStateClearedOnPointerLeave:
    """Condition 2: pointer leave."""

    def test_leave_clears_space_pinch_and_inertia(self, world_surface_factory):
        s = world_surface_factory()
        s._space_pressed = True
        _start_pinch_and_inertia(s)

        s.on_motion_leave(MagicMock())

        assert s._space_pressed is False
        assert s._pinch_start_zoom is None
        assert s._inertia_tick_id is None


class TestGestureStateClearedOnUnmap:
    """Condition 3: widget unmap."""

    def test_unmap_clears_gesture_state_and_cancels_the_animation_tick(
        self, world_surface_factory, wheel_scroll_controller
    ):
        s = world_surface_factory()
        s._space_pressed = True
        _start_pinch_and_inertia(s)

        # Also put a discrete-zoom animation in flight.
        s._mouse_pos = (400.0, 300.0)
        s.on_scroll(wheel_scroll_controller(), 0.0, -1.0)
        assert s._camera_animator.is_running
        assert s._animation_tick_id is not None

        s.on_unmap(s)

        assert s._space_pressed is False
        assert s._pinch_start_zoom is None
        assert s._inertia_tick_id is None
        assert not s._camera_animator.is_running
        assert s._animation_tick_id is None


class TestGestureStateClearedOnFocusLoss:
    """Condition 4: focus loss."""

    def test_focus_leave_clears_space_pinch_and_inertia(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        s._space_pressed = True
        _start_pinch_and_inertia(s)

        s.on_focus_leave(MagicMock())

        assert s._space_pressed is False
        assert s._pinch_start_zoom is None
        assert s._inertia_tick_id is None

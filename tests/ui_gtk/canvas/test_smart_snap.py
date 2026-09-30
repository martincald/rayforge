"""Object snapping on a move: each axis lands on an edge or centre of
another object or the bed within 8 screen pixels, at any zoom; it wins
over Ctrl's grid snap, Alt (Cmd on macOS) turns both off, and View >
Snapping turns it off alone."""

import sys
from unittest.mock import MagicMock, call

import pytest
from gi.repository import Gdk

from swiftcut.ui_gtk.canvas.element import CanvasElement
from swiftcut.ui_gtk.canvas.region import ElementRegion
from swiftcut.ui_gtk.canvas.snapping import SNAP_DISTANCE_PX
from swiftcut.ui_gtk.shared.keyboard import SNAP_OVERRIDE_MASK

pytestmark = pytest.mark.ui

START_PX = (100.0, 100.0)
OVERRIDE_KEY = Gdk.KEY_Meta_L if sys.platform == "darwin" else Gdk.KEY_Alt_L

BED = (0.0, 0.0, 200.0, 150.0)
B = (60.3, 40.3, 30.0, 20.0)
C = (120.6, 100.6, 10.0, 10.0)
# Where the moving box's features lie clear of every line.
FREE_X, FREE_Y = 35.0, 20.0


@pytest.fixture
def scene(world_surface_factory):
    """A 200x150 bed with A, which moves, B and C, and a hidden D."""
    s = world_surface_factory()
    s.haptic_hook = MagicMock()
    a = CanvasElement(10.0, 10.0, 20.0, 8.0, canvas=s, parent=s.root)
    s.root.add(a)
    for rect in (B, C):
        s.root.add(CanvasElement(*rect, canvas=s, parent=s.root))
    s.root.add(
        CanvasElement(
            150.0, 120.0, 10.0, 10.0, canvas=s, parent=s.root, visible=False
        )
    )
    return s, a


def _begin(s, elem, ctrl=False):
    """Sets up a press on elem, as on_button_press would leave it."""
    s._drag_target = elem
    s._active_region = ElementRegion.BODY
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


def _px(s, pixels):
    """A distance of so many screen pixels, in mm."""
    return pixels / s.view_transform.get_abs_scale()[0]


def test_the_candidates_are_the_bed_and_every_other_visible_object(scene):
    s, a = scene
    _begin(s, a)
    _move_to(s, a, FREE_X, FREE_Y)

    sources = s._snap_sources()

    assert sources == [pytest.approx(r) for r in (BED, B, C)]
    xs, ys = s._snap_lines
    assert [line.value for line in xs] == pytest.approx(
        [0, 100, 200, 60.3, 75.3, 90.3, 120.6, 125.6, 130.6]
    )
    assert [line.value for line in ys] == pytest.approx(
        [0, 75, 150, 40.3, 50.3, 60.3, 100.6, 105.6, 110.6]
    )


def test_selected_objects_are_no_candidates(scene):
    s, _ = scene
    s.root.children[1].selected = True

    assert s._snap_sources() == [
        pytest.approx(r) for r in (BED, (10.0, 10.0, 20.0, 8.0), C)
    ]


@pytest.mark.parametrize("zoom", [1.0, 4.0])
def test_the_reach_is_eight_screen_pixels_at_any_zoom(scene, zoom):
    s, a = scene
    s.set_zoom(zoom)
    s._rebuild_view_transform()
    assert s.zoom_level == pytest.approx(zoom)
    _begin(s, a)

    inside = _move_to(s, a, B[0] + _px(s, SNAP_DISTANCE_PX - 1), FREE_Y)
    assert inside == pytest.approx((B[0], FREE_Y))

    outside_x = B[0] + _px(s, SNAP_DISTANCE_PX + 1)
    outside = _move_to(s, a, outside_x, FREE_Y)
    assert outside == pytest.approx((outside_x, FREE_Y))


def test_a_distance_in_reach_at_1x_is_out_of_reach_at_4x(scene):
    s, a = scene
    near_x = B[0] + _px(s, SNAP_DISTANCE_PX - 1)
    s.set_zoom(4.0)
    s._rebuild_view_transform()
    _begin(s, a)

    assert _move_to(s, a, near_x, FREE_Y) == pytest.approx((near_x, FREE_Y))


def test_the_axes_snap_each_on_its_own(scene):
    s, a = scene
    _begin(s, a)

    assert _move_to(s, a, 61.0, FREE_Y) == pytest.approx((60.3, FREE_Y))
    assert _move_to(s, a, FREE_X, 41.0) == pytest.approx((FREE_X, 40.3))
    assert _move_to(s, a, 61.0, 41.0) == pytest.approx((60.3, 40.3))


def test_centres_and_the_bed_are_snapped_to(scene):
    s, a = scene
    _begin(s, a)

    # A's centre, 10 mm in, on B's.
    assert _move_to(s, a, 65.8, FREE_Y) == pytest.approx((65.3, FREE_Y))
    # A's left edge on the bed's.
    assert _move_to(s, a, 1.0, FREE_Y) == pytest.approx((0.0, FREE_Y))
    # A's centre, 4 mm up, on the bed's.
    assert _move_to(s, a, FREE_X, 71.3) == pytest.approx((FREE_X, 71.0))


def test_an_object_in_reach_wins_over_the_grid(scene):
    s, a = scene
    _begin(s, a, ctrl=True)

    # x: B's left edge at 60.3, not the grid's 61; y: nothing in
    # reach, so the grid.
    assert _move_to(s, a, 61.0, 20.4) == pytest.approx((60.3, 20.0))


def test_alt_or_cmd_held_snaps_to_nothing(scene):
    s, a = scene
    _begin(s, a, ctrl=True)

    s.on_key_pressed(None, OVERRIDE_KEY, 0, Gdk.ModifierType(0))
    assert _move_to(s, a, 61.0, 20.4) == pytest.approx((61.0, 20.4))
    assert s._snap_guides == []
    s.haptic_hook.assert_not_called()

    s.on_key_released(None, OVERRIDE_KEY, 0, Gdk.ModifierType(0))
    s._ctrl_pressed = True
    assert _move_to(s, a, 61.0, 20.4) == pytest.approx((60.3, 20.0))


def test_the_press_reads_the_override_from_the_modifiers(scene):
    s, _ = scene
    gesture = MagicMock()
    gesture.get_button.return_value = Gdk.BUTTON_PRIMARY
    event = gesture.get_current_event.return_value

    event.get_modifier_state.return_value = SNAP_OVERRIDE_MASK
    s.on_button_press(gesture, 1, 700.0, 50.0)
    assert s._snap_override is True

    event.get_modifier_state.return_value = Gdk.ModifierType(0)
    s.on_button_press(gesture, 1, 700.0, 50.0)
    assert s._snap_override is False


def test_the_snapping_toggle_turns_off_objects_but_not_the_grid(scene):
    s, a = scene
    s.object_snap_enabled = False

    _begin(s, a, ctrl=True)
    assert _move_to(s, a, 61.0, 20.4) == pytest.approx((61.0, 20.0))

    s._ctrl_pressed = False
    assert _move_to(s, a, 61.0, 20.4) == pytest.approx((61.0, 20.4))


def test_haptics_fire_once_per_new_object_snap(scene):
    s, a = scene
    _begin(s, a)

    _move_to(s, a, 61.0, FREE_Y)
    _move_to(s, a, 61.5, FREE_Y)
    assert s.haptic_hook.mock_calls == [call("alignment")]

    _move_to(s, a, 65.8, FREE_Y)
    assert s.haptic_hook.mock_calls == [call("alignment")] * 2


def test_a_snap_draws_a_guide_from_the_box_to_the_source(scene):
    s, a = scene
    _begin(s, a)

    _move_to(s, a, 61.0, FREE_Y)

    assert len(s._snap_guides) == 1
    (x1, y1), (x2, y2) = s._snap_guides[0]
    # Along B's left edge, from A's bottom to B's top.
    assert (x1, y1, x2, y2) == pytest.approx((60.3, FREE_Y, 60.3, 60.3))

    _move_to(s, a, FREE_X, FREE_Y)
    assert s._snap_guides == []


def test_release_clears_the_guides_and_the_candidates(scene):
    s, a = scene
    _begin(s, a)
    _move_to(s, a, 61.0, FREE_Y)

    s.on_drag_end(s._drag_gesture, 0.0, 0.0)

    assert s._snap_guides == []
    assert s._snap_lines is None


def test_candidates_are_built_once_per_drag_until_invalidated(
    scene, monkeypatch
):
    s, a = scene
    sources = MagicMock(wraps=s._snap_sources)
    monkeypatch.setattr(s, "_snap_sources", sources)
    _begin(s, a)

    _move_to(s, a, FREE_X, FREE_Y)
    _move_to(s, a, FREE_X + 1, FREE_Y)
    assert sources.call_count == 1

    # A new object mid-drag counts once the candidates are invalidated.
    s.root.add(CanvasElement(150.3, 10.0, 5.0, 5.0, canvas=s, parent=s.root))
    s.invalidate_snap_candidates()
    assert _move_to(s, a, 151.0, FREE_Y) == pytest.approx((150.3, FREE_Y))
    assert sources.call_count == 2

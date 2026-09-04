"""Characterization tests for grid/rotation snapping and view-scale
dependent selection geometry (Package D, stage 1).

These tests pin the CURRENT, ACTUAL behaviour of:
  - Canvas._calculate_snap_offset and its wiring into the ctrl+drag move
    path of Canvas.on_mouse_drag, at the 1.0mm grid_size WorldSurface
    actually uses.
  - The SNAP_ANGLE_DEGREES=5.0 rotation snapping wired into the same
    ctrl+drag handler.
  - get_region_rect's scale/flip compensation (the geometry shared by
    both selection-handle rendering in overlays.py and hit-testing in
    element.py / multiselect.py), and MultiSelectionGroup.check_region_hit
    wiring it up against a real, mandatory-Y-flipped view_transform.
"""

from unittest.mock import MagicMock

import pytest

from rayforge.ui_gtk.canvas.element import CanvasElement
from rayforge.ui_gtk.canvas.multiselect import MultiSelectionGroup
from rayforge.ui_gtk.canvas.region import (
    MOVE_HANDLES,
    RESIZE_HANDLES,
    ElementRegion,
    get_region_rect,
)

pytestmark = pytest.mark.ui


class TestCalculateSnapOffset:
    """Direct tests of Canvas._calculate_snap_offset at grid_size=1.0mm."""

    @pytest.mark.parametrize(
        "target_pos, size, expected_offset",
        [
            # Already on-grid: no adjustment needed.
            (10.0, 5.0, 0.0),
            # Start edge (10.2) is 0.2mm from a grid line; end edge
            # (10.2 + 4.5 = 14.7) is 0.3mm from one. The smaller-
            # magnitude adjustment (start) wins: offset -0.2.
            (10.2, 4.5, pytest.approx(-0.2)),
            # Start (10.3 -> 10.0, delta -0.3) and end (15.3 -> 15.0,
            # delta -0.3) are exactly tied in magnitude. The current
            # code's tie-break is "not strictly smaller wins", i.e. the
            # *end* edge's delta is returned -- captured here as-is,
            # not asserted as an ideal.
            (10.3, 5.0, pytest.approx(-0.3)),
            # Negative positions snap the same way.
            (-3.4, 2.0, pytest.approx(0.4)),
        ],
    )
    def test_offset_picks_the_smaller_magnitude_edge_adjustment(
        self, world_surface_factory, target_pos, size, expected_offset
    ):
        s = world_surface_factory()
        offset = s._calculate_snap_offset(target_pos, size, 1.0)
        assert offset == expected_offset

    def test_zero_grid_size_returns_zero(self, world_surface_factory):
        s = world_surface_factory()
        assert s._calculate_snap_offset(10.3, 5.0, 0.0) == 0.0

    def test_worldsurface_grid_size_defaults_to_one_mm(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        assert s.grid_size == 1.0


class TestCtrlDragSnapsToGrid:
    """
    Integration test driving the real Canvas.on_mouse_drag ctrl+drag
    single-element move path, proving the wiring to
    _calculate_snap_offset holds end-to-end (not just that the pure
    function is correct in isolation).
    """

    def _drag(self, factory, ctrl_pressed, start_px, offset_px):
        s = factory()
        elem = CanvasElement(37.3, 61.7, 10.0, 8.0, canvas=s, parent=s.root)
        s.root.add(elem)
        initial_world = elem.get_world_transform()

        s._drag_target = elem
        s._active_region = ElementRegion.BODY
        s._initial_world_transform = initial_world
        s._ctrl_pressed = ctrl_pressed
        s._shift_pressed = False

        mock_gesture = MagicMock()
        mock_gesture.get_start_point.return_value = (True, *start_px)
        s._drag_gesture = mock_gesture

        s.on_mouse_drag(mock_gesture, *offset_px)
        return s, elem, initial_world

    def test_ctrl_move_matches_calculate_snap_offset(
        self, world_surface_factory
    ):
        start_px = (100.0, 100.0)
        offset_px = (23.0, -17.0)

        # First, an unsnapped drag to learn the raw (pre-snap) delta.
        _, elem_raw, initial = self._drag(
            world_surface_factory, False, start_px, offset_px
        )
        ix, iy = initial.get_translation()
        raw_dx, raw_dy = (
            elem_raw.transform.get_translation()[0] - ix,
            elem_raw.transform.get_translation()[1] - iy,
        )

        # Then the ctrl+drag, and compare against an independent call
        # to _calculate_snap_offset using the same raw target AABB.
        s_snap, elem_snap, _ = self._drag(
            world_surface_factory, True, start_px, offset_px
        )
        w, h = elem_snap.width, elem_snap.height
        expected_offset_x = s_snap._calculate_snap_offset(
            ix + raw_dx, w, 1.0
        )
        expected_offset_y = s_snap._calculate_snap_offset(
            iy + raw_dy, h, 1.0
        )

        tx, ty = elem_snap.transform.get_translation()
        assert tx == pytest.approx(ix + raw_dx + expected_offset_x)
        assert ty == pytest.approx(iy + raw_dy + expected_offset_y)


class TestCtrlDragSnapsRotation:
    """
    Integration test driving the real Canvas.on_mouse_drag ctrl+drag
    rotate path, proving the wiring of SNAP_ANGLE_DEGREES=5.0 holds
    end-to-end.
    """

    def _rotate(self, factory, ctrl_pressed, start_px, offset_px):
        s = factory()
        elem = CanvasElement(50.0, 50.0, 20.0, 10.0, canvas=s, parent=s.root)
        s.root.add(elem)
        initial_world = elem.get_world_transform()

        s._drag_target = elem
        s._active_region = ElementRegion.ROTATE_TOP_LEFT
        s._initial_world_transform = initial_world
        s._ctrl_pressed = ctrl_pressed
        s._shift_pressed = False

        start_world = s._get_world_coords(*start_px)
        s._start_rotation(elem, *start_world)

        mock_gesture = MagicMock()
        mock_gesture.get_start_point.return_value = (True, *start_px)
        s._drag_gesture = mock_gesture

        s.on_mouse_drag(mock_gesture, *offset_px)
        return s, elem

    @pytest.mark.parametrize(
        "start_px, offset_px",
        [
            ((500.0, 100.0), (10.0, 60.0)),
            ((200.0, 400.0), (-40.0, 15.0)),
        ],
    )
    def test_ctrl_rotate_matches_snap_angle_degrees(
        self, world_surface_factory, start_px, offset_px
    ):
        s0, elem0 = self._rotate(
            world_surface_factory, False, start_px, offset_px
        )
        raw_angle = elem0.transform.get_rotation() % 360

        s1, elem1 = self._rotate(
            world_surface_factory, True, start_px, offset_px
        )
        snapped_angle = elem1.transform.get_rotation() % 360

        expected_snapped = (
            round(raw_angle / s0.SNAP_ANGLE_DEGREES)
            * s0.SNAP_ANGLE_DEGREES
        ) % 360

        angular_diff = abs(
            ((snapped_angle - expected_snapped + 180) % 360) - 180
        )
        assert angular_diff < 1e-6


class TestGetRegionRectFlipCompensation:
    """
    Direct tests of get_region_rect's flip compensation for resize
    handles. This app's view_transform ALWAYS has a negative Y scale
    (the mandatory world-Y-up to screen-Y-down flip), so
    scale_compensation[1] < 0 is the realistic case for this canvas.
    """

    def test_top_left_handle_moves_to_the_bottom_when_y_is_flipped(self):
        base_handle_size = 20.0
        w, h = 100.0, 80.0

        flipped = get_region_rect(
            ElementRegion.TOP_LEFT, w, h, base_handle_size, (2.0, -3.0)
        )
        unflipped = get_region_rect(
            ElementRegion.TOP_LEFT, w, h, base_handle_size, (2.0, 3.0)
        )

        # Handle dimensions: effective_hw = min(20/2, 100/3) = 10.0;
        # effective_hh = min(20/3, 80/3) = 6.666...
        assert flipped == pytest.approx((0.0, 80.0 - 20.0 / 3.0, 10.0,
                                          20.0 / 3.0))
        # Unflipped, TOP_LEFT stays at the local origin.
        assert unflipped == pytest.approx((0.0, 0.0, 10.0, 20.0 / 3.0))

    def test_bottom_left_handle_moves_to_the_top_when_y_is_flipped(self):
        base_handle_size = 20.0
        w, h = 100.0, 80.0

        flipped = get_region_rect(
            ElementRegion.BOTTOM_LEFT, w, h, base_handle_size, (2.0, -3.0)
        )

        assert flipped == pytest.approx((0.0, 0.0, 10.0, 20.0 / 3.0))


class TestMultiSelectionCheckRegionHit:
    """
    Integration test proving MultiSelectionGroup.check_region_hit wires
    the real canvas.view_transform's flip into get_region_rect's
    scale_compensation (multiselect.py:170), using the same candidates
    on_motion's hover detection actually passes (RESIZE_HANDLES |
    MOVE_HANDLES, i.e. never BODY alongside handles).
    """

    def test_hit_test_respects_the_mandatory_view_flip(
        self, world_surface_factory
    ):
        s = world_surface_factory()
        e1 = CanvasElement(
            10.0, 10.0, 20.0, 20.0, canvas=s, parent=s.root, selected=True
        )
        e2 = CanvasElement(
            60.0, 40.0, 15.0, 15.0, canvas=s, parent=s.root, selected=True
        )
        s.root.add(e1)
        s.root.add(e2)

        group = MultiSelectionGroup([e1, e2], s)
        min_x, min_y, w, h = group._bounding_box
        scale_compensation = s.view_transform.get_scale()
        assert scale_compensation[1] < 0, (
            "WorldSurface's view_transform is expected to always carry "
            "the mandatory Y-flip"
        )

        rx, ry, rw, rh = get_region_rect(
            ElementRegion.TOP_LEFT, w, h, s.BASE_HANDLE_SIZE,
            scale_compensation,
        )
        world_x = min_x + rx + rw / 2
        world_y = min_y + ry + rh / 2

        hit = group.check_region_hit(
            world_x, world_y, candidates=RESIZE_HANDLES | MOVE_HANDLES
        )
        assert hit == ElementRegion.TOP_LEFT

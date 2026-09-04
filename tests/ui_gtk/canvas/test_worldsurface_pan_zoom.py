"""Characterization tests for WorldSurface pan/zoom (Package D, stage 1).

These tests pin the CURRENT, ACTUAL behaviour of the pan/zoom code paths
in ``rayforge/ui_gtk/canvas/worldsurface.py`` and
``rayforge/ui_gtk/canvas/canvas.py`` before any refactor touches them.
Where the observed behaviour is surprising, the test says so in its
docstring rather than "fixing" it.
"""

from unittest.mock import MagicMock

import pytest
from raygeo.geo import Matrix

pytestmark = pytest.mark.ui


class TestSetZoomAndRebuildViewTransform:
    """Pins the exact view_transform produced by set_zoom/set_pan."""

    def test_identity_zoom_no_pan_matches_documented_composition(
        self, world_surface_factory
    ):
        """
        For a 200x150mm world surface in an 800x600px widget at
        zoom=1.0, pan=(0,0), the content layout is
        (x=25.0, y=10.75, w=762.0, h=571.5) (from AxisRenderer margins),
        giving scale_x = scale_y = 3.81 px/mm. The resulting matrix is
        pinned literally here so a refactor cannot silently change the
        composition order.
        """
        s = world_surface_factory()

        m = s.view_transform
        assert m.get(0, 0) == pytest.approx(3.81)
        assert m.get(0, 1) == pytest.approx(0.0)
        assert m.get(0, 2) == pytest.approx(25.0)
        assert m.get(1, 0) == pytest.approx(0.0)
        assert m.get(1, 1) == pytest.approx(-3.81)
        assert m.get(1, 2) == pytest.approx(582.25)
        assert m.get(2, 0) == pytest.approx(0.0)
        assert m.get(2, 1) == pytest.approx(0.0)
        assert m.get(2, 2) == pytest.approx(1.0)

    @pytest.mark.parametrize(
        "zoom, pan",
        [
            (1.0, (0.0, 0.0)),
            (2.0, (10.0, -5.0)),
            (0.5, (-30.0, 40.0)),
            (3.25, (0.0, 0.0)),
        ],
    )
    def test_matches_documented_composition_formula(
        self, world_surface_factory, zoom, pan
    ):
        """
        Rebuilds the expected matrix independently from the exact
        composition documented for _rebuild_view_transform:

            final = m_offset @ m_zoom @ m_scale @ pan_transform
            m_offset = translation(content_x, content_y)
            m_zoom = scale(zoom, zoom)
            m_scale = translation(0, content_h) @ scale(sx, -sy)
            pan_transform = translation(-pan_x, -pan_y)

        using only the real AxisRenderer layout and the public Matrix
        API -- not by calling _rebuild_view_transform's internals.
        """
        s = world_surface_factory()
        s.set_zoom(zoom)
        s.set_pan(*pan)

        content_x, content_y, content_w, content_h = (
            s._axis_renderer.get_content_layout(800, 600)
        )
        effective_height = s._axis_renderer.get_effective_height()
        scale_x = content_w / s.width_mm
        scale_y = content_h / effective_height

        m_offset = Matrix.translation(content_x, content_y)
        m_zoom = Matrix.scale(zoom, zoom)
        m_scale = Matrix.translation(0, content_h) @ Matrix.scale(
            scale_x, -scale_y
        )
        pan_transform = Matrix.translation(-pan[0], -pan[1])
        expected = m_offset @ m_zoom @ m_scale @ pan_transform

        assert s.view_transform.is_close(expected, tol=1e-9)

    def test_set_zoom_clamps_to_min_zoom_factor(self, world_surface_factory):
        """
        Package D stage 2 moved zoom clamping from the caller (on_scroll)
        into the Camera, so it cannot be bypassed by calling set_zoom
        directly. This intentionally changes the previous "unclamped"
        behaviour: a value a real caller (on_scroll) would never produce,
        like -5.0, is now clamped to MIN_ZOOM_FACTOR instead of being
        applied as-is.
        """
        s = world_surface_factory()
        s.set_zoom(-5.0)
        assert s.zoom_level == pytest.approx(s.MIN_ZOOM_FACTOR)


class TestScrollZoomClamping:
    """
    Pins on_scroll's zoom bounds: MIN_ZOOM_FACTOR and the
    MAX_PIXELS_PER_MM pixel-density ceiling (~26.2 for this
    800x600px / 200x150mm setup). Package D5's "keep >=20% of the bed
    visible" rule is a SOFT PAN clamp, not a zoom bound -- see
    test_worldsurface_pan_clamp.py -- so it does not affect max zoom
    here.

    Wheel-notch zoom is an animated discrete step (Package D3) instead
    of an instant jump, so each step's ~180ms animation must be
    finished (via the finish_animation fixture) before the next
    scroll, for a loop of repeated notches to reach the clamp.
    """

    def test_zoom_in_is_clamped_to_max_pixels_per_mm(
        self, world_surface_factory, wheel_scroll_controller, finish_animation
    ):
        s = world_surface_factory()
        s._mouse_pos = (400.0, 300.0)
        controller = wheel_scroll_controller()
        base_ppm = s._axis_renderer.get_base_pixels_per_mm(800, 600)

        # Scroll "up" (dy < 0 means zoom in) far more than enough steps
        # to hit the clamp.
        for _ in range(200):
            s.on_scroll(controller, 0.0, -1.0)
            finish_animation(s)

        achieved_ppm = base_ppm * s.zoom_level
        assert achieved_ppm == pytest.approx(s.MAX_PIXELS_PER_MM)

    def test_zoom_out_is_clamped_to_min_zoom_factor(
        self, world_surface_factory, wheel_scroll_controller, finish_animation
    ):
        s = world_surface_factory()
        s._mouse_pos = (400.0, 300.0)
        controller = wheel_scroll_controller()

        # Scroll "down" (dy > 0 means zoom out) far more than enough
        # steps to hit the clamp.
        for _ in range(200):
            s.on_scroll(controller, 0.0, 1.0)
            finish_animation(s)

        assert s.zoom_level == pytest.approx(s.MIN_ZOOM_FACTOR)


class TestMaxZoomOnLargeBed:
    """
    REQUIRED REGRESSION TEST (Package D5 fix): on a large bed
    (1400x900mm, the bundled ilab-614 profile's size), max zoom must
    be governed by the MAX_PIXELS_PER_MM pixel-density bound, not a
    constant 5.0x ceiling -- that was the D5 rejection: making the
    MIN_VISIBLE_BED_FRACTION rule a max-zoom ceiling instead of a pan
    clamp made 5.0x the closest zoom reachable on any realistic bed.
    """

    def test_max_zoom_is_the_density_bound_not_a_constant_ceiling(
        self, world_surface_factory
    ):
        s = world_surface_factory(width_mm=1400.0, height_mm=900.0)
        base_ppm = s._axis_renderer.get_base_pixels_per_mm(
            s.get_width(), s.get_height()
        )
        expected_max_zoom = s.MAX_PIXELS_PER_MM / base_ppm

        s.set_zoom(1_000_000.0)

        assert s.zoom_level == pytest.approx(expected_max_zoom)
        assert s.zoom_level > 50.0  # far greater than the old 5.0 cap


class TestScrollZoomAboutCursor:
    """Pins on_scroll's zoom-about-pointer invariant."""

    def test_world_point_under_cursor_is_stable_across_a_zoom_step(
        self, world_surface_factory, wheel_scroll_controller, finish_animation
    ):
        """
        Package D3 made wheel-notch zoom an animated discrete step, so
        this invariant now holds once the animation completes (fast-
        forwarded here via finish_animation), rather than immediately
        after on_scroll returns as in stage 1. The achieved precision
        (within 1e-9) is unchanged: Package D2's exact closed-form
        zoom-about-point (Camera.zoom_about_point) is algebraically
        equivalent to stage 1's world-coordinate round-trip.
        """
        s = world_surface_factory()
        cursor_px = (300.0, 250.0)
        s._mouse_pos = cursor_px
        world_before = s._get_world_coords(*cursor_px)

        controller = wheel_scroll_controller()
        s.on_scroll(controller, 0.0, -1.0)
        finish_animation(s)

        world_after = s._get_world_coords(*cursor_px)
        assert world_after[0] == pytest.approx(world_before[0], abs=1e-9)
        assert world_after[1] == pytest.approx(world_before[1], abs=1e-9)


class TestPanEquivalence:
    """
    Pins that set_pan, middle-drag (on_pan_update) and space+drag
    (on_mouse_drag) all agree, since on_mouse_drag's space+drag branch
    duplicates on_pan_update's math rather than sharing it.
    """

    def test_set_pan_updates_pan_attributes(self, world_surface_factory):
        s = world_surface_factory()
        s.set_pan(12.5, -7.25)
        assert s.pan_x_mm == 12.5
        assert s.pan_y_mm == -7.25
        # The exact effect on view_transform is pinned by
        # test_matches_documented_composition_formula above.

    @pytest.mark.parametrize(
        "offset_x, offset_y",
        [
            (37.0, -21.0),
            (0.0, 0.0),
            (-120.3, 84.9),
        ],
    )
    def test_middle_drag_matches_space_drag(
        self, world_surface_factory, offset_x, offset_y
    ):
        s1 = world_surface_factory()
        s1.set_zoom(1.3)
        s1.set_pan(5.0, -3.0)
        s1._pan_start = (s1.pan_x_mm, s1.pan_y_mm)
        g1 = MagicMock()
        g1.get_offset.return_value = (True, offset_x, offset_y)
        s1.on_pan_update(g1, 0.0, 0.0)

        s2 = world_surface_factory()
        s2.set_zoom(1.3)
        s2.set_pan(5.0, -3.0)
        s2._space_pressed = True
        s2._pan_start = (s2.pan_x_mm, s2.pan_y_mm)
        g2 = MagicMock()
        g2.get_offset.return_value = (True, offset_x, offset_y)
        s2.on_mouse_drag(g2, offset_x, offset_y)

        assert s1.pan_x_mm == s2.pan_x_mm
        assert s1.pan_y_mm == s2.pan_y_mm


class TestScreenWorldRoundTrip:
    """Pins Canvas._get_world_coords for several zoom/pan states."""

    @pytest.mark.parametrize(
        "zoom, pan",
        [
            (1.0, (0.0, 0.0)),
            (2.0, (10.0, -5.0)),
            (0.3, (50.0, 50.0)),
            (5.0, (-20.0, 30.0)),
        ],
    )
    def test_roundtrip_through_the_forward_matrix(
        self, world_surface_factory, zoom, pan
    ):
        s = world_surface_factory()
        s.set_zoom(zoom)
        s.set_pan(*pan)

        for px, py in [(0.0, 0.0), (800.0, 600.0), (400.0, 300.0),
                       (123.4, 55.1)]:
            wx, wy = s._get_world_coords(px, py)
            back_x, back_y = s.view_transform.transform_point((wx, wy))
            assert back_x == pytest.approx(px, abs=1e-6)
            assert back_y == pytest.approx(py, abs=1e-6)

    def test_degenerate_matrix_raises_instead_of_falling_back(
        self, world_surface_factory
    ):
        """
        _get_world_coords catches ``numpy.linalg.LinAlgError`` and
        falls back to returning the raw pixel coordinates 1:1 when the
        matrix cannot be inverted. However, the raygeo Matrix binding
        actually raises a plain ``ValueError`` ("Matrix is singular
        (zero scale) and cannot be inverted") for a non-invertible
        matrix, not ``numpy.linalg.LinAlgError``. The except clause
        therefore never catches in practice, and a degenerate
        view_transform currently propagates a ValueError instead of
        silently falling back. This is captured here as CURRENT
        behaviour, not corrected.
        """
        s = world_surface_factory()
        s.view_transform = Matrix.scale(0.0, 0.0)

        with pytest.raises(ValueError):
            s._get_world_coords(123.0, 456.0)


class TestViewScaleAgreement:
    """
    Pins whether WorldSurface.get_view_scale (which recomputes scale
    from get_content_layout * zoom_level) agrees with the scale
    encoded in view_transform (the ONLY writer of which is
    _rebuild_view_transform). These are two parallel code paths that
    could drift; today, for a plain WorldSurface, they agree.
    """

    @pytest.mark.parametrize(
        "width_mm, height_mm, widget_w, widget_h, zoom, pan",
        [
            (200.0, 150.0, 800, 600, 1.0, (0.0, 0.0)),
            (200.0, 150.0, 800, 600, 2.5, (10.0, -5.0)),
            (100.0, 100.0, 500, 500, 0.5, (0.0, 0.0)),
            (300.0, 100.0, 900, 600, 1.7, (20.0, 30.0)),
            (100.0, 300.0, 900, 600, 1.7, (20.0, 30.0)),
        ],
    )
    def test_get_view_scale_matches_matrix_abs_scale(
        self,
        world_surface_factory,
        width_mm,
        height_mm,
        widget_w,
        widget_h,
        zoom,
        pan,
    ):
        s = world_surface_factory(
            width_mm=width_mm,
            height_mm=height_mm,
            widget_w=widget_w,
            widget_h=widget_h,
        )
        s.set_zoom(zoom)
        s.set_pan(*pan)

        view_scale = s.get_view_scale()
        matrix_scale = s.view_transform.get_abs_scale()

        assert view_scale[0] == pytest.approx(matrix_scale[0])
        assert view_scale[1] == pytest.approx(matrix_scale[1])

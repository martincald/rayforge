"""A selection's handles, as design software draws them.

Eight small white squares with an accent outline, on the corners and
the edge midpoints, each centred on the point it resizes from. Nothing
else: no move handle (the object itself is dragged), and nothing drawn
for rotation until a rotate drag starts; the ring outside each corner
is found by its cursor. Sizes are the layout tokens, and the handles
no longer take the layer's colour.
"""

import re
from pathlib import Path

import cairo
import numpy as np
import pytest

from swiftcut.ui_gtk import layout
from swiftcut.ui_gtk.canvas.canvas import Canvas
from swiftcut.ui_gtk.canvas.element import CanvasElement
from swiftcut.ui_gtk.canvas.overlays import ACCENT_RGB
from swiftcut.ui_gtk.canvas.region import (
    CORNER_RESIZE_HANDLES,
    RESIZE_HANDLES,
    ROTATE_HANDLES,
    ROTATE_ZONE_INNER,
    ROTATE_ZONE_OUTER,
    ElementRegion,
    _rotate_corner,
    get_region_rect,
    handle_anchor,
)

W, H = 100.0, 80.0

# Where each handle sits, with the frame's visual top at y = 0.
ANCHORS = {
    ElementRegion.TOP_LEFT: (0.0, 0.0),
    ElementRegion.TOP_MIDDLE: (W / 2, 0.0),
    ElementRegion.TOP_RIGHT: (W, 0.0),
    ElementRegion.MIDDLE_LEFT: (0.0, H / 2),
    ElementRegion.MIDDLE_RIGHT: (W, H / 2),
    ElementRegion.BOTTOM_LEFT: (0.0, H),
    ElementRegion.BOTTOM_MIDDLE: (W / 2, H),
    ElementRegion.BOTTOM_RIGHT: (W, H),
}

ROTATE_OF = {
    ElementRegion.TOP_LEFT: ElementRegion.ROTATE_TOP_LEFT,
    ElementRegion.TOP_RIGHT: ElementRegion.ROTATE_TOP_RIGHT,
    ElementRegion.BOTTOM_LEFT: ElementRegion.ROTATE_BOTTOM_LEFT,
    ElementRegion.BOTTOM_RIGHT: ElementRegion.ROTATE_BOTTOM_RIGHT,
}

UI_GTK = Path(layout.__file__).parent


class TestGeometry:
    @pytest.mark.parametrize("flipped", [False, True])
    def test_anchors_are_the_corners_and_edge_midpoints(self, flipped):
        for region, (x, y) in ANCHORS.items():
            # Flipped, the visual top is at y = H.
            expected = (x, H - y) if flipped else (x, y)
            assert handle_anchor(region, W, H, flipped) == expected, region

    @pytest.mark.parametrize("flipped", [False, True])
    def test_a_corner_square_sits_where_its_rotate_ring_is_centred(
        self, flipped
    ):
        for region in CORNER_RESIZE_HANDLES:
            assert handle_anchor(region, W, H, flipped) == _rotate_corner(
                ROTATE_OF[region], W, H, flipped
            )

    @pytest.mark.parametrize("flipped", [False, True])
    def test_corner_hit_rects_are_centred_on_the_corner(self, flipped):
        scale = (2.0, -3.0 if flipped else 3.0)
        for region in CORNER_RESIZE_HANDLES:
            x, y, w, h = get_region_rect(
                region, W, H, layout.HANDLE_HIT_SIZE, scale
            )
            # The pointer target, not the drawn square: HANDLE_HIT_SIZE
            # screen pixels, in local units.
            assert (w, h) == pytest.approx(
                (layout.HANDLE_HIT_SIZE / 2.0, layout.HANDLE_HIT_SIZE / 3.0)
            )
            assert (x + w / 2, y + h / 2) == pytest.approx(
                handle_anchor(region, W, H, flipped)
            )


def test_the_tokens_have_the_design_values():
    assert layout.HANDLE_SIZE == 8
    assert layout.HANDLE_STROKE == 1
    assert layout.HANDLE_HIT_SIZE == 20
    assert layout.ROTATION_ARC_RADIUS == 24
    assert layout.START_CORNER_MARKER == 12
    assert layout.START_CORNER_TICK == 24
    assert Canvas.BASE_HANDLE_SIZE == layout.HANDLE_HIT_SIZE


_GONE = re.compile(
    r"_get_handle_color|hex_to_rgba\(layer|00ccff|MOVE_HANDLES"
    r"|ElementRegion\.MOVE\b",
    re.IGNORECASE,
)


def test_no_layer_coloured_handles_or_move_handle_remain():
    offenders = [
        f"{path.relative_to(UI_GTK)}:{number}: {line.strip()}"
        for package in ("canvas", "canvas2d")
        for path in sorted((UI_GTK / package).rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _GONE.search(line)
    ]

    assert offenders == []


def _selected(s, x=60.0, y=50.0, w=60.0, h=40.0, angle=0.0):
    """Adds a selected element to a surface, as a click would leave it."""
    elem = CanvasElement(
        x, y, w, h, canvas=s, parent=s.root, selected=True, angle=angle
    )
    s.root.add(elem)
    s._finalize_selection_state()
    return elem


def _screen_frame(s, elem):
    """The selection frame on screen: (left, top, right, bottom)."""
    to_screen = s.view_transform @ elem.get_world_transform()
    points = [
        to_screen.transform_point(p)
        for p in (
            (0, 0),
            (elem.width, 0),
            (elem.width, elem.height),
            (0, elem.height),
        )
    ]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _paint_overlays(s, scale):
    """Paints the surface's overlays on a transparent image at a device
    scale factor; returns each device pixel's B, G, R, A."""
    width, height = s.get_width(), s.get_height()
    image = cairo.ImageSurface(
        cairo.FORMAT_ARGB32, width * scale, height * scale
    )
    image.set_device_scale(scale, scale)
    ctx = cairo.Context(image)
    s._render_overlays(ctx)
    image.flush()
    data = np.frombuffer(image.get_data(), dtype=np.uint8)
    rows = data.reshape(height * scale, image.get_stride())
    # ARGB32 is native-endian; on little-endian hosts that is B, G, R, A.
    return rows[:, : width * scale * 4].reshape(
        height * scale, width * scale, 4
    )


def _anchors_on_screen(s, elem):
    to_screen = s.view_transform @ elem.get_world_transform()
    flipped = to_screen.is_flipped()
    return {
        region: to_screen.transform_point(
            handle_anchor(region, elem.width, elem.height, flipped)
        )
        for region in RESIZE_HANDLES
    }


def _logical_centres(shape, scale):
    """Each device pixel's centre in the widget's logical pixels."""
    rows, cols = np.indices(shape[:2])
    return (cols + 0.5) / scale, (rows + 0.5) / scale


@pytest.mark.ui
class TestDrawn:
    @pytest.mark.parametrize("scale", [1, 2])
    def test_a_white_square_on_each_corner_and_edge_midpoint(
        self, world_surface_factory, scale
    ):
        s = world_surface_factory()
        elem = _selected(s)
        pixels = _paint_overlays(s, scale)
        xs, ys = _logical_centres(pixels.shape, scale)
        # Rounded onto the pixel grid, the square is within half a
        # pixel of its anchor, so it covers all of this window.
        half = layout.HANDLE_SIZE / 2 - 0.5
        accent = np.array([round(c * 255) for c in ACCENT_RGB[::-1]])

        for region, (sx, sy) in _anchors_on_screen(s, elem).items():
            inside = (np.abs(xs - sx) <= half) & (np.abs(ys - sy) <= half)
            square = pixels[inside]
            opaque = square[square[:, 3] == 255]
            side = (layout.HANDLE_SIZE - 1) * scale
            assert len(opaque) >= side * side, region
            assert len(opaque) == len(square), region
            # White inside, the accent around it; nothing else.
            white = (opaque[:, :3] == 255).all(axis=1)
            outline = (np.abs(opaque[:, :3] - accent) <= 2).all(axis=1)
            assert white.sum() > 0, region
            assert outline.sum() > 0, region
            assert (white | outline).all(), region

    @pytest.mark.parametrize("scale", [1, 2])
    @pytest.mark.parametrize("region", sorted(ROTATE_HANDLES, key=str))
    def test_nothing_is_drawn_in_the_rotate_ring_when_idle(
        self, world_surface_factory, scale, region
    ):
        s = world_surface_factory()
        elem = _selected(s)
        alpha = _paint_overlays(s, scale)[:, :, 3]
        xs, ys = _logical_centres(alpha.shape, scale)
        left, top, right, bottom = _screen_frame(s, elem)
        corner = {
            ElementRegion.ROTATE_TOP_LEFT: (left, top),
            ElementRegion.ROTATE_TOP_RIGHT: (right, top),
            ElementRegion.ROTATE_BOTTOM_LEFT: (left, bottom),
            ElementRegion.ROTATE_BOTTOM_RIGHT: (right, bottom),
        }[region]
        cx, cy = corner

        distance = np.hypot(xs - cx, ys - cy)
        in_ring = (distance >= ROTATE_ZONE_INNER) & (
            distance <= ROTATE_ZONE_OUTER
        )
        # Outside the frame and its own dashed stroke, and clear of the
        # corner's square.
        on_frame = (
            (xs >= left - 1.5)
            & (xs <= right + 1.5)
            & (ys >= top - 1.5)
            & (ys <= bottom + 1.5)
        )
        reach = layout.HANDLE_SIZE / 2 + 1
        on_square = (np.abs(xs - cx) <= reach) & (np.abs(ys - cy) <= reach)
        band = in_ring & ~on_frame & ~on_square
        assert band.sum() > 0

        assert int((alpha[band] > 0).sum()) == 0

from __future__ import annotations

import math
from typing import (
    TYPE_CHECKING,
    Any,
)

import cairo
from raygeo.geo import Matrix

from ...core.color import hex_to_rgba
from ..layout import HANDLE_SIZE, HANDLE_STROKE
from ..theme import ACCENT_HEX
from .region import (
    CORNER_RESIZE_HANDLES,
    MIDDLE_RESIZE_HANDLES,
    RESIZE_HANDLES,
    ROTATE_SHEAR_HANDLES,
    SHEAR_HANDLES,
    ElementRegion,
    handle_anchor,
)

if TYPE_CHECKING:
    from .canvas import CanvasElement, MultiSelectionGroup, SelectionMode

#: The selection's ink: blue-brand, the stylesheet's sc_accent.
ACCENT_RGB = hex_to_rgba(ACCENT_HEX)[:3]


def _draw_handle_square(
    ctx: cairo.Context, sx: float, sy: float, hovered: bool
):
    """
    Draws a resize handle: a HANDLE_SIZE square centred on the screen
    point (sx, sy), white with an accent outline, or accent filled
    while hovered. The outline lies on the pixel grid so it is crisp,
    and the square's outer edge is HANDLE_SIZE across.
    """
    side = HANDLE_SIZE - HANDLE_STROKE
    x = round(sx - HANDLE_SIZE / 2) + HANDLE_STROKE / 2
    y = round(sy - HANDLE_SIZE / 2) + HANDLE_STROKE / 2
    ctx.save()
    ctx.rectangle(x, y, side, side)
    if hovered:
        ctx.set_source_rgb(*ACCENT_RGB)
    else:
        ctx.set_source_rgb(1.0, 1.0, 1.0)
    ctx.fill_preserve()
    ctx.set_source_rgb(*ACCENT_RGB)
    ctx.set_line_width(HANDLE_STROKE)
    ctx.stroke()
    ctx.restore()


def _draw_arrow_handle(
    ctx: cairo.Context,
    width: float,
    height: float,
    is_hovered: bool,
):
    """
    Draws a bidirectional arrow, white with an accent outline like the
    resize squares. Uses average of width/height for size.
    """
    size = (width + height) / 2.0
    length, head = size * 0.4, size * 0.25
    barb, shaft = head * 0.7, size * 0.06

    ctx.move_to(-length, 0)
    ctx.line_to(-length + head, -barb)
    ctx.line_to(-length + head, -shaft)
    ctx.line_to(length - head, -shaft)
    ctx.line_to(length - head, -barb)
    ctx.line_to(length, 0)
    ctx.line_to(length - head, barb)
    ctx.line_to(length - head, shaft)
    ctx.line_to(-length + head, shaft)
    ctx.line_to(-length + head, barb)
    ctx.close_path()
    if is_hovered:
        ctx.set_source_rgb(*ACCENT_RGB)
    else:
        ctx.set_source_rgb(1.0, 1.0, 1.0)
    ctx.fill_preserve()
    ctx.set_source_rgb(*ACCENT_RGB)
    ctx.set_line_width(HANDLE_STROKE)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


def path_rounded_square(
    ctx: cairo.Context,
    x: float,
    y: float,
    w: float,
    h: float,
    r: float,
):
    """Draws a rounded-rectangle path centered at origin coordinates."""
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


HANDLE_DRAW_INFO: dict[ElementRegion, dict[str, Any]] = {
    ElementRegion.SHEAR_TOP: {
        "draw": _draw_arrow_handle,
        "get_angle": lambda t, r: t.get_x_axis_angle(),
    },
    ElementRegion.SHEAR_BOTTOM: {
        "draw": _draw_arrow_handle,
        "get_angle": lambda t, r: t.get_x_axis_angle(),
    },
    ElementRegion.SHEAR_LEFT: {
        "draw": _draw_arrow_handle,
        "get_angle": lambda t, r: t.get_y_axis_angle(),
        "swap_dims": True,
    },
    ElementRegion.SHEAR_RIGHT: {
        "draw": _draw_arrow_handle,
        "get_angle": lambda t, r: t.get_y_axis_angle(),
        "swap_dims": True,
    },
}


def render_selection_frame(
    ctx: cairo.Context,
    target: CanvasElement | MultiSelectionGroup,
    transform_to_screen: Matrix,
):
    """
    Draws the dashed selection frame for a target.

    Args:
        ctx: The cairo context (in screen space).
        target: The CanvasElement or MultiSelectionGroup to draw frame for.
        transform_to_screen: The matrix to transform from local to screen.
    """
    ctx.save()
    w, h = target.width, target.height
    corners_local = [(0, 0), (w, 0), (w, h), (0, h)]
    corners_screen = [
        transform_to_screen.transform_point(p) for p in corners_local
    ]

    # Draw the dashed outline connecting the screen-space corners.
    # Line width and dash pattern are now in fixed pixels.
    ctx.set_source_rgb(0.4, 0.4, 0.4)
    ctx.set_line_width(1.0)
    ctx.set_dash((5, 5))

    ctx.move_to(*corners_screen[0])
    ctx.line_to(*corners_screen[1])
    ctx.line_to(*corners_screen[2])
    ctx.line_to(*corners_screen[3])
    ctx.close_path()
    ctx.stroke()
    ctx.restore()


def _render_handles(
    ctx: cairo.Context,
    target: CanvasElement | MultiSelectionGroup,
    transform_to_screen: Matrix,
    regions: list[ElementRegion],
    hovered_region: ElementRegion,
    base_handle_size: float,
    scale_compensation: tuple[float, float],
):
    sx_abs, sy_abs = transform_to_screen.get_abs_scale()
    is_flipped_y = scale_compensation[1] < 0

    for region in regions:
        # A resize handle is a square on screen, on its corner or edge
        # midpoint, whatever the frame's rotation or shear. Shear
        # handles are glyphs rotated to align with the frame.
        if region in RESIZE_HANDLES:
            anchor = handle_anchor(
                region, target.width, target.height, is_flipped_y
            )
            screen_x, screen_y = transform_to_screen.transform_point(anchor)
            _draw_handle_square(
                ctx, screen_x, screen_y, region == hovered_region
            )
        else:  # Shear handles
            draw_info = HANDLE_DRAW_INFO.get(region)
            if not draw_info:
                continue

            lx, ly, lw, lh = target.get_region_rect(
                region, base_handle_size, scale_compensation
            )
            if lw <= 0 or lh <= 0:
                continue

            center_local = (lx + lw / 2, ly + lh / 2)
            screen_x, screen_y = transform_to_screen.transform_point(
                center_local
            )
            angle_rad = math.radians(
                draw_info["get_angle"](transform_to_screen, region)
            )

            screen_width = lw * sx_abs
            screen_height = lh * sy_abs

            draw_w, draw_h = screen_width, screen_height
            if draw_info.get("swap_dims", False):
                draw_w, draw_h = screen_height, screen_width

            ctx.save()
            ctx.translate(screen_x, screen_y)
            ctx.rotate(angle_rad)
            draw_info["draw"](
                ctx,
                draw_w,
                draw_h,
                is_hovered=(region == hovered_region),
            )
            ctx.restore()


def render_selection_handles(
    ctx: cairo.Context,
    target: CanvasElement | MultiSelectionGroup,
    transform_to_screen: Matrix,
    mode: SelectionMode,
    hovered_region: ElementRegion,
    base_handle_size: float,
    with_labels: bool = False,
):
    """
    Renders selection handles for a target based on the current interaction
    mode.

    In RESIZE mode that is the eight resize squares, on the corners and
    the edge midpoints. The rotate zones outside the corners are not
    drawn; the pointer finds them by the cursor. In ROTATE_SHEAR mode it
    is the four shear arrows.

    This function understands the application logic (modes, regions) but is
    "dumb" regarding transformations; it requires a pre-computed matrix to
    map the target's local coordinates to the screen.

    Args:
        ctx: The cairo context (in screen space).
        target: The CanvasElement or MultiSelectionGroup to draw handles for.
        transform_to_screen: The matrix to transform from local to screen.
        mode: The current SelectionMode.
        hovered_region: The currently hovered region, for hover effects.
        base_handle_size: The pointer target's size in screen pixels,
            which sizes and places the shear arrows.
        with_labels: If True, draws debug text labels on the handles.
    """
    from .canvas import SelectionMode  # Avoid circular import at module level

    if transform_to_screen.has_zero_scale():
        return

    sx_abs, sy_abs = transform_to_screen.get_abs_scale()
    is_view_flipped = transform_to_screen.is_flipped()
    scale_compensation = (sx_abs, -sy_abs if is_view_flipped else sy_abs)

    # Determine regions to draw. The corners go last, so on a small
    # selection they sit on top of the edge squares.
    regions_to_draw = []
    if mode == SelectionMode.RESIZE:
        regions_to_draw.extend(MIDDLE_RESIZE_HANDLES)
        regions_to_draw.extend(CORNER_RESIZE_HANDLES)
    elif mode == SelectionMode.ROTATE_SHEAR:
        regions_to_draw.extend(SHEAR_HANDLES)

    if regions_to_draw:
        _render_handles(
            ctx,
            target,
            transform_to_screen,
            regions_to_draw,
            hovered_region,
            base_handle_size,
            scale_compensation,
        )

    if with_labels:
        _render_debug_labels(
            ctx,
            target,
            transform_to_screen,
            regions_to_draw,
            base_handle_size,
            scale_compensation,
        )


def render_angle_readout(
    ctx: cairo.Context, angle_deg: float, x: float, y: float
):
    """
    Draws a rotate drag's angle beside the pointer at (x, y), in screen
    space: light text on a dark tag, which reads on the light canvas
    and the dark alike.
    """
    # Rounded first, so that a hair below zero reads "0.0", not "-0.0".
    text = f"{round(angle_deg, 1) + 0.0:.1f}°"
    pad = 4.0
    ctx.save()
    ctx.set_font_size(12)
    extents = ctx.text_extents(text)
    left, top = x + 16.0, y + 16.0
    path_rounded_square(
        ctx,
        left,
        top,
        extents.x_advance + 2 * pad,
        extents.height + 2 * pad,
        pad,
    )
    ctx.set_source_rgba(0.1, 0.1, 0.1, 0.85)
    ctx.fill()
    ctx.set_source_rgb(1.0, 1.0, 1.0)
    ctx.move_to(left + pad, top + pad - extents.y_bearing)
    ctx.show_text(text)
    ctx.restore()


def render_rotation_arc(
    ctx: cairo.Context,
    pivot: tuple[float, float],
    start: tuple[float, float],
    pointer: tuple[float, float],
    radius: float,
):
    """
    Draws a rotate drag in screen space: a dot on the pivot, a hairline
    from it to the pointer, and an arc of `radius` about it from where
    the drag started to where the pointer is, the short way round, as
    the angle readout counts it.
    """
    px, py = pivot
    start_angle = math.atan2(start[1] - py, start[0] - px)
    end_angle = math.atan2(pointer[1] - py, pointer[0] - px)
    # Wrapped to (-pi, pi]: positive is clockwise on screen, as the
    # readout's positive angle is.
    delta = math.pi - (math.pi - (end_angle - start_angle)) % (2 * math.pi)

    ctx.save()
    ctx.set_source_rgb(*ACCENT_RGB)
    ctx.set_line_width(HANDLE_STROKE)
    ctx.move_to(px, py)
    ctx.line_to(*pointer)
    ctx.stroke()
    ctx.new_sub_path()
    if delta >= 0:
        ctx.arc(px, py, radius, start_angle, start_angle + delta)
    else:
        ctx.arc_negative(px, py, radius, start_angle, start_angle + delta)
    ctx.stroke()
    # A dot two logical pixels in radius on the pivot.
    ctx.arc(px, py, 2.0, 0.0, 2 * math.pi)
    ctx.fill()
    ctx.restore()


def render_snap_guides(
    ctx: cairo.Context,
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
):
    """
    Draws the guides of a snap in screen space: a 1 px accent line for
    each segment, on the pixel grid so it is crisp.
    """
    ctx.save()
    ctx.set_source_rgb(*ACCENT_RGB)
    ctx.set_line_width(1.0)
    for (x1, y1), (x2, y2) in segments:
        ctx.move_to(round(x1) + 0.5, round(y1) + 0.5)
        ctx.line_to(round(x2) + 0.5, round(y2) + 0.5)
    ctx.stroke()
    ctx.restore()


def _render_debug_labels(
    ctx, target, transform, regions, base_size, scale_comp
):
    """Helper to draw debug text labels on handles."""
    _region_letters = {
        r: chr(ord("A") + i)
        for i, r in enumerate(RESIZE_HANDLES | ROTATE_SHEAR_HANDLES)
    }
    ctx.save()
    ctx.set_source_rgb(1, 0, 0)
    ctx.select_font_face(
        "Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD
    )
    ctx.set_font_size(10)
    for region in regions:
        letter = _region_letters.get(region)
        if not letter:
            continue
        lx, ly, lw, lh = target.get_region_rect(region, base_size, scale_comp)
        sx, sy = transform.transform_point((lx + lw / 2, ly + lh / 2))
        ext = ctx.text_extents(letter)
        ctx.move_to(
            sx - (ext.width / 2 + ext.x_bearing),
            sy - (ext.height / 2 + ext.y_bearing),
        )
        ctx.show_text(letter)
    ctx.restore()

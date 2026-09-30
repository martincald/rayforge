from __future__ import annotations

import math
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from raygeo.geo.types import Rect

# The rotate zone: a ring outside each corner of the selection frame,
# from 6 to 14 screen pixels from the corner. Screen pixels are the
# widget's logical ones, whatever the display's scale factor.
ROTATE_ZONE_INNER = 6.0
ROTATE_ZONE_OUTER = 14.0


class ElementRegion(Enum):
    """Defines interactive regions for selection frames."""

    NONE = auto()
    BODY = auto()
    # Resize handles (on the corners and the edges)
    TOP_LEFT = auto()
    TOP_MIDDLE = auto()
    TOP_RIGHT = auto()
    MIDDLE_LEFT = auto()
    MIDDLE_RIGHT = auto()
    BOTTOM_LEFT = auto()
    BOTTOM_MIDDLE = auto()
    BOTTOM_RIGHT = auto()
    # Rotate & Shear handles (outside)
    ROTATE_TOP_LEFT = auto()
    ROTATE_TOP_RIGHT = auto()
    ROTATE_BOTTOM_LEFT = auto()
    ROTATE_BOTTOM_RIGHT = auto()
    SHEAR_TOP = auto()
    SHEAR_RIGHT = auto()
    SHEAR_BOTTOM = auto()
    SHEAR_LEFT = auto()


RESIZE_HANDLES: set[ElementRegion] = {
    ElementRegion.TOP_LEFT,
    ElementRegion.TOP_MIDDLE,
    ElementRegion.TOP_RIGHT,
    ElementRegion.MIDDLE_LEFT,
    ElementRegion.MIDDLE_RIGHT,
    ElementRegion.BOTTOM_LEFT,
    ElementRegion.BOTTOM_MIDDLE,
    ElementRegion.BOTTOM_RIGHT,
}

BBOX_REGIONS: set[ElementRegion] = {ElementRegion.BODY} | RESIZE_HANDLES

ROTATE_HANDLES: set[ElementRegion] = {
    ElementRegion.ROTATE_TOP_LEFT,
    ElementRegion.ROTATE_TOP_RIGHT,
    ElementRegion.ROTATE_BOTTOM_LEFT,
    ElementRegion.ROTATE_BOTTOM_RIGHT,
}

SHEAR_HANDLES: set[ElementRegion] = {
    ElementRegion.SHEAR_TOP,
    ElementRegion.SHEAR_RIGHT,
    ElementRegion.SHEAR_BOTTOM,
    ElementRegion.SHEAR_LEFT,
}

ROTATE_SHEAR_HANDLES: set[ElementRegion] = ROTATE_HANDLES | SHEAR_HANDLES

LEFT_HANDLES: set[ElementRegion] = {
    ElementRegion.TOP_LEFT,
    ElementRegion.MIDDLE_LEFT,
    ElementRegion.BOTTOM_LEFT,
}

RIGHT_HANDLES: set[ElementRegion] = {
    ElementRegion.TOP_RIGHT,
    ElementRegion.MIDDLE_RIGHT,
    ElementRegion.BOTTOM_RIGHT,
}

TOP_HANDLES: set[ElementRegion] = {
    ElementRegion.TOP_LEFT,
    ElementRegion.TOP_MIDDLE,
    ElementRegion.TOP_RIGHT,
}

BOTTOM_HANDLES: set[ElementRegion] = {
    ElementRegion.BOTTOM_LEFT,
    ElementRegion.BOTTOM_MIDDLE,
    ElementRegion.BOTTOM_RIGHT,
}

CORNER_RESIZE_HANDLES: set[ElementRegion] = (TOP_HANDLES | BOTTOM_HANDLES) & (
    LEFT_HANDLES | RIGHT_HANDLES
)

MIDDLE_RESIZE_HANDLES: set[ElementRegion] = (
    RESIZE_HANDLES - CORNER_RESIZE_HANDLES
)


def _rotate_corner(
    region: ElementRegion, width: float, height: float, is_flipped_y: bool
) -> tuple[float, float]:
    """The corner of the frame, in local coordinates, a rotate zone rings."""
    left = region in (
        ElementRegion.ROTATE_TOP_LEFT,
        ElementRegion.ROTATE_BOTTOM_LEFT,
    )
    top = region in (
        ElementRegion.ROTATE_TOP_LEFT,
        ElementRegion.ROTATE_TOP_RIGHT,
    )
    # In a flipped system the visual top is at y=h.
    return 0.0 if left else width, height if top == is_flipped_y else 0.0


def handle_anchor(
    region: ElementRegion, width: float, height: float, is_flipped_y: bool
) -> tuple[float, float]:
    """
    The point, in local coordinates, a resize handle is drawn on: its
    corner of the frame, or the midpoint of its edge.
    """
    if region in LEFT_HANDLES:
        x = 0.0
    elif region in RIGHT_HANDLES:
        x = width
    else:
        x = width / 2.0
    # In a flipped system the visual top is at y=h.
    if region in TOP_HANDLES:
        y = height if is_flipped_y else 0.0
    elif region in BOTTOM_HANDLES:
        y = 0.0 if is_flipped_y else height
    else:
        y = height / 2.0
    return x, y


def _in_rotate_zone(
    region: ElementRegion,
    local_x: float,
    local_y: float,
    width: float,
    height: float,
    scale_x: float,
    scale_y: float,
) -> bool:
    """
    Whether a local point is in a corner's rotate zone: outside the
    frame, and ROTATE_ZONE_INNER to ROTATE_ZONE_OUTER screen pixels from
    the corner.
    """
    if 0 <= local_x <= width and 0 <= local_y <= height:
        return False
    corner_x, corner_y = _rotate_corner(region, width, height, scale_y < 0)
    distance = math.hypot(
        (local_x - corner_x) * abs(scale_x),
        (local_y - corner_y) * abs(scale_y),
    )
    return ROTATE_ZONE_INNER <= distance <= ROTATE_ZONE_OUTER


def get_region_rect(
    region: ElementRegion,
    width: float,
    height: float,
    base_handle_size: float,
    scale_compensation: float | tuple[float, float] = 1.0,
) -> Rect:
    """
    A generic function to calculate the rectangle (x, y, w, h) for a given
    region, relative to a bounding box of a given width and height. For
    a handle it is the pointer target, not the square drawn on it.

    It compensates for scale to keep handle sizes visually consistent and
    adapts to flipped coordinate systems by checking the sign of the
    scale_compensation.

    Args:
        region: The ElementRegion to calculate.
        width: The width of the bounding box.
        height: The height of the bounding box.
        base_handle_size: The pointer target's size in screen pixels.
        scale_compensation: The signed scale factor(s) of the context.
                            A negative y-scale indicates a flipped axis.
    """
    w, h = width, height

    if isinstance(scale_compensation, tuple):
        scale_x, scale_y = scale_compensation
    else:
        scale_x = scale_y = scale_compensation

    # Check for a flipped Y-axis BEFORE taking the absolute value.
    is_flipped_y = scale_y < 0

    # Use absolute scale for calculating handle *dimensions*.
    abs_scale_x = abs(scale_x)
    abs_scale_y = abs(scale_y)

    if abs_scale_x < 1e-6 or abs_scale_y < 1e-6:
        return (0.0, 0.0, 0.0, 0.0)

    # Calculate local handle dimensions by dividing the desired
    # visual size by the scale factors.
    local_handle_w = base_handle_size / abs_scale_x
    local_handle_h = base_handle_size / abs_scale_y

    # Dynamically calculate handle size to prevent overlap on small elements.
    effective_hw = min(local_handle_w, w / 3.0)
    effective_hh = min(local_handle_h, h / 3.0)

    # Use average scale for distance calculation of rotation handle
    avg_abs_scale = (abs_scale_x + abs_scale_y) / 2.0
    handle_dist = 5.0 / avg_abs_scale  # Visual distance for external handles

    # Conditionally calculate Y positions based on the axis orientation.
    if is_flipped_y:
        # In a flipped system (like WorkSurface), the visual "top" starts
        # at y=h.
        y_start_top = h - effective_hh
        # And the visual "bottom" starts at y=0.
        y_start_bottom = 0.0
    else:
        # In a standard Y-down system, the visual "top" is at y=0.
        y_start_top = 0.0
        # And the visual "bottom" is at y=h.
        y_start_bottom = h - effective_hh

    # Resize handles. A corner's rect is centred on its corner, where
    # its square is drawn; an edge's is a band inside the frame, between
    # the corner rects.
    if region in CORNER_RESIZE_HANDLES:
        corner_x, corner_y = handle_anchor(region, w, h, is_flipped_y)
        return (
            corner_x - effective_hw / 2,
            corner_y - effective_hh / 2,
            effective_hw,
            effective_hh,
        )

    edge_width = max(w - effective_hw, 0)
    edge_height = max(h - effective_hh, 0)
    if region == ElementRegion.TOP_MIDDLE:
        return effective_hw / 2, y_start_top, edge_width, effective_hh
    if region == ElementRegion.BOTTOM_MIDDLE:
        return effective_hw / 2, y_start_bottom, edge_width, effective_hh
    if region == ElementRegion.MIDDLE_LEFT:
        return 0.0, effective_hh / 2, effective_hw, edge_height
    if region == ElementRegion.MIDDLE_RIGHT:
        return w - effective_hw, effective_hh / 2, effective_hw, edge_height

    # Rotate/Shear handles (external)
    if region in ROTATE_HANDLES:
        # Centered on the corner, through the middle of its rotate zone.
        # Nothing is drawn in it; the zone itself is hit as a ring.
        radius = (ROTATE_ZONE_INNER + ROTATE_ZONE_OUTER) / 2.0
        rot_w = 2.0 * radius / abs_scale_x
        rot_h = 2.0 * radius / abs_scale_y
        corner_x, corner_y = _rotate_corner(region, w, h, is_flipped_y)
        return corner_x - rot_w / 2, corner_y - rot_h / 2, rot_w, rot_h

    if region == ElementRegion.SHEAR_TOP:
        y_pos = (
            h + handle_dist if is_flipped_y else -handle_dist - effective_hh
        )
        return w / 2 - effective_hw / 2, y_pos, effective_hw, effective_hh
    if region == ElementRegion.SHEAR_BOTTOM:
        y_pos = (
            -effective_hh - handle_dist if is_flipped_y else h + handle_dist
        )
        return w / 2 - effective_hw / 2, y_pos, effective_hw, effective_hh
    if region == ElementRegion.SHEAR_LEFT:
        y_pos = h / 2 - effective_hh / 2
        return -effective_hw - handle_dist, y_pos, effective_hw, effective_hh
    if region == ElementRegion.SHEAR_RIGHT:
        y_pos = h / 2 - effective_hh / 2
        return w + handle_dist, y_pos, effective_hw, effective_hh
    if region == ElementRegion.BODY:
        return 0.0, 0.0, w, h

    return 0.0, 0.0, 0.0, 0.0  # For NONE or other cases


def check_region_hit(
    local_x: float,
    local_y: float,
    width: float,
    height: float,
    base_handle_size: float,
    scale_compensation: float | tuple[float, float] = 1.0,
    candidates: set[ElementRegion] | None = None,
) -> ElementRegion:
    """
    Checks which interactive region is hit by a point in LOCAL coordinates.
    If `candidates` is provided, it will only check against regions in that
    set.

    Args:
        local_x: The x-coordinate in LOCAL coordinates.
        local_y: The y-coordinate in LOCAL coordinates.
        width: The width of the bounding box.
        height: The height of the bounding box.
        base_handle_size: The desired base size of the handles in pixels.
        scale_compensation: The signed scale factor(s) of the context.
        candidates: Optional set of regions to check against.
    """
    # Determine which handle regions to check based on the candidates.
    # The order of _HIT_TEST_ORDER is crucial to resolve overlap ambiguity.
    regions_to_check = candidates if candidates is not None else BBOX_REGIONS

    # A rotate zone wins over any region it overlaps. It is a ring, not
    # a rectangle.
    if isinstance(scale_compensation, tuple):
        scale_x, scale_y = scale_compensation
    else:
        scale_x = scale_y = scale_compensation
    for region in ROTATE_HANDLES & regions_to_check:
        if _in_rotate_zone(
            region, local_x, local_y, width, height, scale_x, scale_y
        ):
            return region

    for region in regions_to_check - ROTATE_HANDLES:
        # Calculate the hit rectangle for the current region. This ensures
        # the hit-test area matches the rendered handle size.
        rx, ry, rw, rh = get_region_rect(
            region, width, height, base_handle_size, scale_compensation
        )
        if (
            rw > 0
            and rh > 0
            and rx <= local_x < rx + rw
            and ry <= local_y < ry + rh
        ):
            return region

    # If no handle is hit, check the body if it's a candidate.
    if ElementRegion.BODY in regions_to_check and (
        0 <= local_x < width and 0 <= local_y < height
    ):
        return ElementRegion.BODY

    return ElementRegion.NONE

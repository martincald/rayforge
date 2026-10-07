"""
The bed: the one workspace rectangle shared by import scaling,
placement and the workspace bounds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from raygeo.geo.types import Rect

if TYPE_CHECKING:
    from ..machine.models.machine import Machine

# Float slack in mm, so a size equal to the bed still fits.
_EPSILON_MM = 1e-6


def bed_rect(machine: Machine) -> Rect:
    """
    The bed as (x, y, width, height) in world mm: origin bottom-left,
    Y up, spanning the machine's axis extents like the canvas.
    """
    width, height = machine.axis_extents
    return 0.0, 0.0, float(width), float(height)


def fits(size: tuple[float, float], bed: Rect) -> bool:
    """Whether a (width, height) box fits inside the bed."""
    width, height = size
    return width <= bed[2] + _EPSILON_MM and height <= bed[3] + _EPSILON_MM


def inside(box: Rect, bed: Rect) -> bool:
    """Whether an (x, y, width, height) box lies inside the bed."""
    return clamp_offset(box, bed) == (0.0, 0.0) and fits(box[2:], bed)


def clamp_offset(box: Rect, bed: Rect) -> tuple[float, float]:
    """
    The smallest (dx, dy) that moves an (x, y, width, height) box inside
    the bed. On an axis where the box is larger than the bed, its low
    edge goes onto the bed's.
    """
    return (
        _clamp_axis(box[0], box[2], bed[0], bed[2]),
        _clamp_axis(box[1], box[3], bed[1], bed[3]),
    )


def _clamp_axis(
    low: float, size: float, bed_low: float, bed_size: float
) -> float:
    if low < bed_low - _EPSILON_MM or size > bed_size + _EPSILON_MM:
        return bed_low - low
    over = low + size - (bed_low + bed_size)
    return -over if over > _EPSILON_MM else 0.0

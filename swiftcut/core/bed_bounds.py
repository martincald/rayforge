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

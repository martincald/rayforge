"""Shared fixtures for characterizing pan/zoom/snap behaviour.

These fixtures build a real ``WorldSurface`` widget directly (no parent
window, no realized display -- matching the pattern already used by
``tests/ui_gtk/canvas2d/test_surface.py``), then stub ``get_width``/
``get_height`` so the view-transform math has deterministic pixel
dimensions to work with instead of the 0x0 allocation an unrealized
widget would otherwise report.
"""

import pytest

from rayforge.ui_gtk.canvas.worldsurface import WorldSurface


def make_world_surface(
    width_mm: float = 200.0,
    height_mm: float = 150.0,
    widget_w: int = 800,
    widget_h: int = 600,
) -> WorldSurface:
    """Builds a real, unrealized WorldSurface with fixed pixel dimensions."""
    surface = WorldSurface(width_mm=width_mm, height_mm=height_mm)
    surface.get_width = lambda: widget_w
    surface.get_height = lambda: widget_h
    surface._rebuild_view_transform()
    return surface


@pytest.fixture
def world_surface_factory():
    """Returns a factory for building WorldSurface instances in tests."""
    return make_world_surface

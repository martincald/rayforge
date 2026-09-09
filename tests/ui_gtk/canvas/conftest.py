"""Shared fixtures for characterizing pan/zoom/snap behaviour.

These fixtures build a real ``WorldSurface`` widget directly (no parent
window, no realized display -- matching the pattern already used by
``tests/ui_gtk/canvas2d/test_surface.py``), then stub ``get_width``/
``get_height`` so the view-transform math has deterministic pixel
dimensions to work with instead of the 0x0 allocation an unrealized
widget would otherwise report.
"""

from unittest.mock import MagicMock

import pytest
from gi.repository import Gdk

from swiftcut.ui_gtk.canvas.worldsurface import WorldSurface


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


def make_wheel_scroll_controller() -> MagicMock:
    """
    Builds a MagicMock standing in for a Gtk.EventControllerScroll
    delivering a physical mouse-wheel notch (Gdk.ScrollUnit.WHEEL, no
    modifiers held) -- the case WorldSurface.on_scroll routes down its
    discrete (always-zoom) path, regardless of Ctrl/Cmd.
    """
    controller = MagicMock()
    controller.get_unit.return_value = Gdk.ScrollUnit.WHEEL
    controller.get_current_event_state.return_value = Gdk.ModifierType(0)
    return controller


@pytest.fixture
def wheel_scroll_controller():
    """Returns a factory for a mock physical-mouse-wheel scroll controller."""
    return make_wheel_scroll_controller


def finish_camera_animation(surface: WorldSurface) -> None:
    """
    Fast-forwards a WorldSurface's in-progress camera animation (from a
    discrete zoom step) to completion, snapping the live camera exactly
    to its target instead of waiting for real frame-clock ticks.
    """
    surface._camera_animator.advance(float("inf"))


@pytest.fixture
def finish_animation():
    """Returns a function that finishes a WorldSurface's camera animation."""
    return finish_camera_animation

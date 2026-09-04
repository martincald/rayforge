"""The Camera model: single source of truth for pan/zoom state."""

import logging

logger = logging.getLogger(__name__)


class Camera:
    """
    Holds a view's zoom level and pan offset (in mm), plus the zoom
    range it is currently allowed to move within.

    All navigation state for a ``WorldSurface`` (zoom, pan) is owned
    by exactly one ``Camera`` instance. Zoom changes are always
    clamped to the current bounds set via ``set_zoom_bounds``, so
    callers cannot bypass clamping by calling ``set_zoom`` directly.
    """

    def __init__(self) -> None:
        self.zoom: float = 1.0
        self.pan_x_mm: float = 0.0
        self.pan_y_mm: float = 0.0
        self._min_zoom: float = 0.0
        self._max_zoom: float = float("inf")

    def set_zoom_bounds(self, min_zoom: float, max_zoom: float) -> None:
        """Sets the [min_zoom, max_zoom] range used to clamp set_zoom."""
        self._min_zoom = min_zoom
        self._max_zoom = max_zoom

    def set_zoom(self, zoom: float) -> None:
        """Sets the zoom level, clamped to the current bounds."""
        self.zoom = max(self._min_zoom, min(zoom, self._max_zoom))

    def set_pan(self, pan_x_mm: float, pan_y_mm: float) -> None:
        """Sets the pan offset, in mm."""
        self.pan_x_mm = pan_x_mm
        self.pan_y_mm = pan_y_mm

    def pan_by_pixel_offset(
        self,
        start_pan_x_mm: float,
        start_pan_y_mm: float,
        offset_x_px: float,
        offset_y_px: float,
        scale_x_px_per_mm: float,
        scale_y_px_per_mm: float,
    ) -> tuple[float, float]:
        """
        Computes a new (pan_x_mm, pan_y_mm) from a pixel-space drag
        offset, relative to the pan position at the start of the drag,
        and the view's current effective pixels-per-mm scale.

        This is the single code path shared by every pixel-drag-based
        panning gesture (middle-drag, space+drag), so their math
        cannot drift apart.
        """
        delta_x_mm = offset_x_px / scale_x_px_per_mm
        delta_y_mm = offset_y_px / scale_y_px_per_mm
        return (
            start_pan_x_mm - delta_x_mm,
            start_pan_y_mm + delta_y_mm,
        )

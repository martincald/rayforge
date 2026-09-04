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

    def zoom_about_point(
        self,
        pointer_x_px: float,
        pointer_y_px: float,
        new_zoom: float,
        base_scale_x_px_per_mm: float,
        base_scale_y_px_per_mm: float,
        content_x: float,
        content_y: float,
        content_h: float,
    ) -> tuple[float, float, float]:
        """
        Computes the (zoom, pan_x_mm, pan_y_mm) that result from
        zooming this camera to ``new_zoom`` (clamped to the current
        bounds, see ``set_zoom_bounds``) while keeping the world point
        currently under the screen point (pointer_x_px, pointer_y_px)
        fixed under that same screen point. Does not mutate this
        Camera -- callers apply the result via set_zoom/set_pan,
        either immediately (for zero-lag gestures like pinch and
        trackpad Ctrl+scroll) or as an animation target (for discrete
        steps like a wheel notch).

        ``base_scale_x_px_per_mm``/``base_scale_y_px_per_mm`` are the
        view's pixels-per-mm scale at zoom=1.0, and
        ``content_x``/``content_y``/``content_h`` are the content
        area's layout in widget pixels (see
        AxisRenderer.get_content_layout) -- both are independent of
        zoom/pan and describe the same view transform composed by
        WorldSurface._rebuild_view_transform:

            screen_x = content_x + zoom*base_scale_x*(world_x - pan_x)
            screen_y = content_y + zoom*content_h
                       - zoom*base_scale_y*(world_y - pan_y)

        Solving both for the world point under the pointer, before and
        after the zoom change, and requiring it to stay identical,
        gives this closed-form pan update -- exact to floating-point
        precision, with no matrix inversion needed.
        """
        zoom = max(self._min_zoom, min(new_zoom, self._max_zoom))
        old_zoom = self.zoom
        if old_zoom == 0 or zoom == old_zoom:
            return zoom, self.pan_x_mm, self.pan_y_mm

        old_sx = old_zoom * base_scale_x_px_per_mm
        old_sy = old_zoom * base_scale_y_px_per_mm
        world_x = self.pan_x_mm + (pointer_x_px - content_x) / old_sx
        world_y = self.pan_y_mm + (
            content_y + old_zoom * content_h - pointer_y_px
        ) / old_sy

        new_sx = zoom * base_scale_x_px_per_mm
        new_sy = zoom * base_scale_y_px_per_mm
        new_pan_x = world_x - (pointer_x_px - content_x) / new_sx
        new_pan_y = world_y - (
            content_y + zoom * content_h - pointer_y_px
        ) / new_sy

        return zoom, new_pan_x, new_pan_y

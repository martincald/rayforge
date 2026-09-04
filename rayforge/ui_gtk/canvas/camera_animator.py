"""Eases a Camera toward a target state over time (Package D, stage 3).

No GTK dependency: callers (WorldSurface) are responsible for driving
``advance()`` once per frame -- typically from a
``Gtk.Widget.add_tick_callback`` -- and for stopping once it returns
False. This mirrors Camera's own GTK-free design, so the easing math
can be unit tested without a running GTK main loop.
"""

import logging

from .camera import Camera

logger = logging.getLogger(__name__)

# Discrete zoom steps (wheel notch, zoom-to-fit, keyboard shortcuts)
# ease out over this many milliseconds.
DEFAULT_DURATION_MS = 180.0


def ease_out_cubic(t: float) -> float:
    """Ease-out cubic: fast start, smooth settle. t is clamped to [0, 1]."""
    t = min(1.0, max(0.0, t))
    return 1.0 - (1.0 - t) ** 3


class CameraAnimator:
    """
    Eases a live ``Camera`` toward a target (zoom, pan_x_mm, pan_y_mm)
    over ``duration_ms``, using an ease-out-cubic curve.

    Discrete zoom steps and zoom-to-fit are animated through this
    class. Continuous gestures (pinch, two-finger pan/scroll) must
    update the live Camera directly instead, with zero lag.
    """

    def __init__(
        self, camera: Camera, duration_ms: float = DEFAULT_DURATION_MS
    ) -> None:
        self._camera = camera
        self._duration_ms = duration_ms
        self._start_zoom = 0.0
        self._start_pan_x = 0.0
        self._start_pan_y = 0.0
        self._target_zoom = 0.0
        self._target_pan_x = 0.0
        self._target_pan_y = 0.0
        self._start_time_ms = 0.0
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(
        self,
        target_zoom: float,
        target_pan_x: float,
        target_pan_y: float,
        now_ms: float,
    ) -> None:
        """(Re)starts an animation from the camera's current state."""
        self._start_zoom = self._camera.zoom
        self._start_pan_x = self._camera.pan_x_mm
        self._start_pan_y = self._camera.pan_y_mm
        self._target_zoom = target_zoom
        self._target_pan_x = target_pan_x
        self._target_pan_y = target_pan_y
        self._start_time_ms = now_ms
        self._running = True

    def advance(self, now_ms: float) -> bool:
        """
        Applies the eased camera state for ``now_ms``. Returns True if
        the animation is still running (the caller should keep
        ticking), or False once it has reached its target exactly (the
        caller should stop ticking -- no further advance() calls are
        needed until the next start()).
        """
        if not self._running:
            return False

        duration = self._duration_ms
        t = (now_ms - self._start_time_ms) / duration if duration > 0 else 1.0
        if t >= 1.0:
            self._camera.set_zoom(self._target_zoom)
            self._camera.set_pan(self._target_pan_x, self._target_pan_y)
            self._running = False
            return False

        eased = ease_out_cubic(t)
        self._camera.set_zoom(
            self._start_zoom + (self._target_zoom - self._start_zoom) * eased
        )
        self._camera.set_pan(
            self._start_pan_x
            + (self._target_pan_x - self._start_pan_x) * eased,
            self._start_pan_y
            + (self._target_pan_y - self._start_pan_y) * eased,
        )
        return True

    def stop(self) -> None:
        """Cancels any in-progress animation without changing the camera."""
        self._running = False

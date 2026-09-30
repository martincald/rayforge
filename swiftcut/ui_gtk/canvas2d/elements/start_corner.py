import math

import cairo
from gi.repository import GLib

from ....machine.models.machine import StartCorner
from ...canvas import CanvasElement
from ...canvas.overlays import ACCENT_RGB
from ...layout import (
    HANDLE_STROKE,
    START_CORNER_MARKER,
    START_CORNER_TICK,
)

# blue-brand, the selection's accent; the ops preview already draws
# travel moves in orange.
_COLOR = (*ACCENT_RGB, 0.95)
# The tick's dash, on and off, in screen pixels.
_TICK_DASH = 3.0
# How long a corner change keeps the overlay up, then how long it
# takes to fade, one frame at a time; milliseconds.
_HOLD_MS = 1500
_FADE_MS = 250
_FRAME_MS = 16


class StartCornerElement(CanvasElement):
    """
    A non-interactive CanvasElement showing where the head is when the
    job starts and which way the job grows.

    It spans the job's bounding box. A crosshair sits on the selected
    start corner and a dashed tick points from it toward the opposite
    corner, the way the cut extends from the head.

    It is hidden until asked for: while the corner selector is hovered
    (``hovered``, set through :meth:`set_hovered`), and for a moment
    after the corner changes (:meth:`flash`). Then it fades out.
    """

    def __init__(self, **kwargs):
        super().__init__(
            x=0,
            y=0,
            width=0,
            height=0,
            selectable=False,
            draggable=False,
            clip=False,
            visible=False,
            **kwargs,
        )
        self.corner = StartCorner.TOP_LEFT
        self.has_job = False
        # How strongly it is drawn, 1 shown to 0 faded out.
        self.alpha = 1.0
        self._hold_id: int | None = None
        self._fade_id: int | None = None

    def set_job(
        self, rect: tuple[float, float, float, float], corner: StartCorner
    ):
        """
        Cover a job's world (x, y, width, height) box, from a corner.
        Only moves it: whether it shows is up to show, flash and
        set_hovered.
        """
        x, y, width, height = rect
        self.corner = corner
        self.has_job = True
        # Size first: resizing rebuilds the transform from the origin.
        self.set_size(width, height)
        self.set_pos(x, y)

    def clear_job(self):
        """No job to mark: hide, and stay hidden until the next one."""
        self._cancel_timers()
        self.has_job = False
        self.set_visible(False)

    def show(self):
        """Show it at full strength, stopping any hold or fade."""
        self._cancel_timers()
        if not self.has_job:
            return
        self.alpha = 1.0
        self.set_visible(True)

    def flash(self):
        """Show it, then fade it out after a hold, unless hovered."""
        self.show()
        if self.visible:
            self._hold_id = GLib.timeout_add(_HOLD_MS, self._end_hold)

    def set_hovered(self, hovered: bool):
        """
        Follow the corner selector's hover: shown while hovered, faded
        on leaving unless a flash is still holding it up.
        """
        self.hovered = hovered
        if hovered:
            self.show()
        elif self._hold_id is None:
            self._fade()

    def _end_hold(self) -> bool:
        self._hold_id = None
        if not self.hovered:
            self._fade()
        return GLib.SOURCE_REMOVE

    def _fade(self):
        """Ramp the alpha down to 0 over _FADE_MS, then hide."""
        if self._fade_id is not None or not self.visible:
            return
        self._fade_id = GLib.timeout_add(_FRAME_MS, self._fade_step)

    def _fade_step(self) -> bool:
        """One frame of the fade; the GLib source's keep-going flag."""
        self.alpha = max(0.0, self.alpha - _FRAME_MS / _FADE_MS)
        if self.alpha > 0.0:
            if self.canvas:
                self.canvas.queue_draw()
            return GLib.SOURCE_CONTINUE
        self._fade_id = None
        self.set_visible(False)
        return GLib.SOURCE_REMOVE

    def _cancel_timers(self):
        for source_id in (self._hold_id, self._fade_id):
            if source_id is not None:
                GLib.source_remove(source_id)
        self._hold_id = self._fade_id = None

    def head_and_opposite(
        self,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        """
        The head marker and the corner it points at, in local units.

        Local space is y-up like the world, so (0, 0) is the box's
        bottom-left corner.
        """
        left = self.corner in (StartCorner.TOP_LEFT, StartCorner.BOTTOM_LEFT)
        top = self.corner in (StartCorner.TOP_LEFT, StartCorner.TOP_RIGHT)
        head = (0.0 if left else self.width, self.height if top else 0.0)
        opposite = (self.width - head[0], self.height - head[1])
        return head, opposite

    def draw(self, ctx: cairo.Context):
        """
        Renders the crosshair on the head and the tick toward the
        opposite corner, sized in screen pixels so they read the same
        at every zoom.
        """
        (hx, hy), (ox, oy) = self.head_and_opposite()
        pixel = abs(ctx.device_to_user_distance(1.0, 0.0)[0]) or 1.0

        def from_head(dx: float, dy: float) -> tuple[float, float]:
            """The head, moved (dx, dy) screen pixels."""
            ux, uy = ctx.device_to_user_distance(dx, dy)
            return hx + ux, hy + uy

        half = START_CORNER_MARKER / 2
        ctx.save()
        ctx.set_source_rgba(*_COLOR[:3], _COLOR[3] * self.alpha)
        ctx.set_line_width(HANDLE_STROKE * pixel)

        ctx.new_path()
        ctx.move_to(*from_head(-half, 0.0))
        ctx.line_to(*from_head(half, 0.0))
        ctx.move_to(*from_head(0.0, -half))
        ctx.line_to(*from_head(0.0, half))
        ctx.stroke()

        # Toward the opposite corner as it lies on screen, from just
        # outside the crosshair, and no further than that corner.
        dx, dy = ctx.user_to_device_distance(ox - hx, oy - hy)
        length = math.hypot(dx, dy)
        end = min(half + START_CORNER_TICK, length)
        if end > half:
            ux, uy = dx / length, dy / length
            ctx.set_dash((_TICK_DASH * pixel, _TICK_DASH * pixel))
            ctx.move_to(*from_head(ux * half, uy * half))
            ctx.line_to(*from_head(ux * end, uy * end))
            ctx.stroke()

        ctx.restore()

"""
The job preview on the canvas: the job's ops, drawn as far as a time.

Travels are dashed, cuts solid, raster lines thin and solid, so a
raster sweeps across line by line. A cut at zero power draws as the
travel it is. The head is a dot on the segment it is running.

Finished segments are kept in an image of the canvas, so a frame only
adds the segments finished since the last one. Moving the view, a
theme change or scrubbing back starts the image again.
"""

import math
from collections.abc import Sequence

import cairo

from ....context import get_context
from ....pipeline.job_preview import (
    CUT,
    SCAN,
    TRAVEL,
    JobPreviewModel,
    Point,
    PreviewSegment,
)
from ...canvas import CanvasElement
from ...canvas.overlays import ACCENT_RGB

# Screen pixels. Cuts are the widest stroke, so their progress stands
# out on the ops the canvas already draws in the same colours.
_LINE = 1.0
_CUT_LINE = 2.0
_TRAVEL_DASH = (4.0, 3.0)
_HEAD_RADIUS = 3.0

# Drawn in this order, so cuts land on top.
_KINDS = (TRAVEL, SCAN, CUT)


def theme_colors() -> dict[str, tuple] | None:
    """Each kind's colour, from the theme; None until it resolves."""
    color_set = get_context().theme.color_set
    if color_set is None:
        return None
    return {
        TRAVEL: color_set.get_rgba("travel"),
        CUT: color_set.get_rgba("cut"),
        SCAN: color_set.get_rgba("engrave"),
    }


def stroke_paths(
    ctx: cairo.Context,
    view: cairo.Matrix,
    colors: dict[str, tuple],
    kind: str,
    paths: Sequence[Sequence[Point]],
):
    """Strokes world polylines of one kind, styled in screen pixels."""
    ctx.save()
    ctx.transform(view)
    for path in paths:
        ctx.move_to(*path[0])
        for point in path[1:]:
            ctx.line_to(*point)
    # The path is kept in device space, so it is stroked in pixels.
    ctx.restore()
    ctx.save()
    ctx.set_source_rgba(*colors[kind])
    ctx.set_line_width(_CUT_LINE if kind == CUT else _LINE)
    ctx.set_dash(_TRAVEL_DASH if kind == TRAVEL else ())
    ctx.stroke()
    ctx.restore()


def draw_segments(
    ctx: cairo.Context,
    view: cairo.Matrix,
    colors: dict[str, tuple],
    segments: list[PreviewSegment],
):
    """Strokes whole segments, one stroke per kind."""
    for kind in _KINDS:
        paths = [s.points for s in segments if s.kind == kind]
        if paths:
            stroke_paths(ctx, view, colors, kind, paths)


class JobPreviewElement(CanvasElement):
    """
    A non-interactive CanvasElement drawing a JobPreviewModel at a
    time. Hidden until it has a model.
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
        self.model: JobPreviewModel | None = None
        self.time = 0.0
        # The finished segments, drawn for one view: how many and for
        # which view, colours and canvas size.
        self._finished: cairo.ImageSurface | None = None
        self._finished_key: tuple | None = None
        self._finished_count = 0

    def set_model(self, model: JobPreviewModel | None):
        """Show a preview from its start, or none."""
        self.model = model
        self.time = 0.0
        self._finished = None
        self._finished_key = None
        self._finished_count = 0
        self.set_visible(model is not None)

    def set_time(self, t: float):
        """Draw the preview as it is t seconds after Start."""
        self.time = t
        if self.canvas:
            self.canvas.queue_draw()

    def draw(self, ctx: cairo.Context):
        """Nothing in world space: the preview is an overlay."""

    def draw_overlay(self, ctx: cairo.Context):
        model = self.model
        if not self.visible or model is None or not self.canvas:
            return
        colors = theme_colors()
        if colors is None:
            return
        view = cairo.Matrix(*self.canvas.view_transform.for_cairo())
        done = model.index_at(self.time)

        ctx.save()
        ctx.set_source_surface(self._finished_image(view, colors, done), 0, 0)
        ctx.paint()
        path = model.path_at(self.time)
        if len(path) > 1:
            kind = model.segments[done].kind
            stroke_paths(ctx, view, colors, kind, [path])
        head = model.point_at(self.time)
        if head is not None:
            x, y = view.transform_point(*head)
            ctx.set_source_rgb(*ACCENT_RGB)
            ctx.arc(x, y, _HEAD_RADIUS, 0.0, 2.0 * math.pi)
            ctx.fill()
        ctx.restore()

    def _finished_image(
        self, view: cairo.Matrix, colors: dict[str, tuple], done: int
    ) -> cairo.ImageSurface:
        """The image of the first done segments, brought up to date."""
        canvas = self.canvas
        assert canvas is not None and self.model is not None
        width, height = canvas.get_width(), canvas.get_height()
        scale = canvas.get_scale_factor()
        key = (
            tuple(canvas.view_transform.for_cairo()),
            width,
            height,
            scale,
            tuple(colors.items()),
        )
        if (
            self._finished is None
            or key != self._finished_key
            or done < self._finished_count
        ):
            self._finished = cairo.ImageSurface(
                cairo.FORMAT_ARGB32, width * scale, height * scale
            )
            self._finished.set_device_scale(scale, scale)
            self._finished_key = key
            self._finished_count = 0
        if done > self._finished_count:
            draw_segments(
                cairo.Context(self._finished),
                view,
                colors,
                self.model.segments[self._finished_count : done],
            )
            self._finished_count = done
        return self._finished

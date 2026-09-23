import math

import cairo

from ....machine.models.machine import StartCorner
from ...canvas import CanvasElement

# Sizes in screen pixels, so the overlay reads the same at every zoom.
_MARKER_RADIUS_PX = 7.0
_LINE_WIDTH_PX = 2.0
_ARROW_MAX_PX = 90.0
_ARROW_HEAD_PX = 10.0
# blue-brand from docs/design/swift-cut-tokens.md; the ops preview
# already draws travel moves in orange.
_COLOR = (0.184, 0.482, 1.0, 0.95)


class StartCornerElement(CanvasElement):
    """
    A non-interactive CanvasElement showing where the head is when the
    job starts and which way the job grows.

    It spans the job's bounding box. A head marker sits on the selected
    start corner and an arrow points from it toward the opposite
    corner, the way the cut extends from the head.
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

    def set_job(
        self, rect: tuple[float, float, float, float], corner: StartCorner
    ):
        """Cover a job's world (x, y, width, height) box, from a corner."""
        x, y, width, height = rect
        self.corner = corner
        # Size first: resizing rebuilds the transform from the origin.
        self.set_size(width, height)
        self.set_pos(x, y)
        self.set_visible(True)

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
        """Renders the head marker and the arrow."""
        (hx, hy), (ox, oy) = self.head_and_opposite()
        px = abs(ctx.device_to_user_distance(1.0, 0.0)[0]) or 1.0
        radius = _MARKER_RADIUS_PX * px

        ctx.save()
        ctx.set_source_rgba(*_COLOR)
        ctx.set_line_width(_LINE_WIDTH_PX * px)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)

        ctx.new_path()
        ctx.arc(hx, hy, radius, 0.0, 2 * math.pi)
        ctx.stroke()
        ctx.arc(hx, hy, radius * 0.35, 0.0, 2 * math.pi)
        ctx.fill()

        length = math.hypot(ox - hx, oy - hy)
        if length > radius:
            ux, uy = (ox - hx) / length, (oy - hy) / length
            # Capped, so a large job is pointed at rather than crossed.
            reach = max(radius, min(length / 2, _ARROW_MAX_PX * px))
            tip_x, tip_y = hx + ux * reach, hy + uy * reach
            ctx.move_to(hx + ux * radius, hy + uy * radius)
            ctx.line_to(tip_x, tip_y)
            angle = math.atan2(uy, ux)
            head = _ARROW_HEAD_PX * px
            for side in (-1.0, 1.0):
                barb = angle + math.pi + side * math.pi / 6
                ctx.move_to(tip_x, tip_y)
                ctx.line_to(
                    tip_x + head * math.cos(barb),
                    tip_y + head * math.sin(barb),
                )
            ctx.stroke()

        ctx.restore()

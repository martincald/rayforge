import cairo

from ....machine.models.machine import StartCorner
from ...canvas import CanvasElement
from ...canvas.overlays import ACCENT_RGB
from ...layout import HANDLE_STROKE

# The start-corner overlay's accent: the square is cut from the head
# the same way the job is.
_COLOR = (*ACCENT_RGB, 0.95)
# The outline's dash, on and off, in screen pixels.
_DASH = 4.0


def square_from_corner(
    point: tuple[float, float], corner: StartCorner, size: float
) -> tuple[float, float, float, float]:
    """
    The world (x, y, width, height) of a size x size square whose
    ``corner`` is at point, growing toward the opposite corner.
    """
    left = corner in (StartCorner.TOP_LEFT, StartCorner.BOTTOM_LEFT)
    top = corner in (StartCorner.TOP_LEFT, StartCorner.TOP_RIGHT)
    x = point[0] if left else point[0] - size
    y = point[1] - size if top else point[1]
    return x, y, size, size


class TestCutMarkerElement(CanvasElement):
    """
    A non-interactive CanvasElement showing where a test cut goes: a
    dashed square, hidden until asked for.
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

    def set_square(self, rect: tuple[float, float, float, float]):
        """Cover a world (x, y, width, height) square."""
        x, y, width, height = rect
        # Size first: resizing rebuilds the transform from the origin.
        self.set_size(width, height)
        self.set_pos(x, y)

    def draw(self, ctx: cairo.Context):
        """The square's outline, dashed, in screen-pixel widths."""
        pixel = abs(ctx.device_to_user_distance(1.0, 0.0)[0]) or 1.0
        ctx.save()
        ctx.set_source_rgba(*_COLOR)
        ctx.set_line_width(HANDLE_STROKE * pixel)
        ctx.set_dash((_DASH * pixel, _DASH * pixel))
        ctx.rectangle(0.0, 0.0, self.width, self.height)
        ctx.stroke()
        ctx.restore()

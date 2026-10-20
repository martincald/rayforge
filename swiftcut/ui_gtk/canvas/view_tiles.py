"""
The canvas as GPU textures while only the view moves.

GTK rasterizes a widget's cairo node on the CPU and uploads it whole on
every frame, so a canvas drawn as one cairo node pays its full device
pixel area per frame: on a Retina M1 that kept every pan and zoom
frame over the ~5 ms that holds 60 Hz (docs/PERF_AUDIT_M1.md). A pan
or a zoom only moves and scales what is drawn, so the canvas is cut
into square tiles drawn once, at the view they were drawn with (the
base view); a frame places them with the translation and uniform scale
that take the base view to the current one, and the GPU composites
them. Tiles are a fraction of the widget, so the first ones draw
exactly the widget's area, as a plain frame would; tiles a pan brings
into view are drawn as they come, one pass per row.
"""

import math
import sys
from collections.abc import Callable

import cairo
from gi.repository import Gdk, GLib, Graphene, Gtk
from raygeo.geo import Matrix

#: About how wide and high a tile is, in widget (logical) pixels: the
#: widget is cut into this many tiles, rounded, each way.
TILE = 256

#: A zoom further than this from the base view draws new tiles at the
#: current view: scaled textures blur (in) or need too many (out).
MAX_ZOOM_RATIO = 2.0

# cairo's ARGB32 is a native-endian 32-bit word.
_FORMAT = (
    Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED
    if sys.byteorder == "little"
    else Gdk.MemoryFormat.A8R8G8B8_PREMULTIPLIED
)

#: Draws the canvas into ctx as seen through view (a world-to-surface
#: transform), on a surface of the given width and height.
DrawView = Callable[[cairo.Context, Matrix, int, int], None]


class ViewTiles:
    """
    Textures of the base view: tile (i, j) holds the base view's pixels
    from (i * tile width, j * tile height).
    """

    def __init__(self):
        self._key: object = None
        self._base: Matrix | None = None
        self._size = (TILE, TILE)
        self._tiles: dict[tuple[int, int], Gdk.Texture] = {}

    def __len__(self) -> int:
        return len(self._tiles)

    def clear(self):
        self._key = None
        self._base = None
        self._tiles.clear()

    def snapshot(
        self,
        snapshot: Gtk.Snapshot,
        key: object,
        view: Matrix,
        size: tuple[int, int],
        scale: int,
        draw: DrawView,
    ) -> float:
        """
        Appends the tiles covering a widget of the given size seen
        through view. key is everything else the drawing depends on:
        another key, or a view that is not the base view moved and
        uniformly scaled (by at most MAX_ZOOM_RATIO), starts the tiles
        over at this view. Returns the scale from the base view, 1.0
        when only the offset moved.
        """
        width, height = size
        ratio, shift = self._from_base(view)
        if key != self._key or ratio is None:
            self._start(key, view, size)
            ratio, shift = 1.0, (0.0, 0.0)
        if ratio == 1.0:
            # On the device pixel grid, so the textures stay sharp.
            shift = (
                round(shift[0] * scale) / scale,
                round(shift[1] * scale) / scale,
            )
        visible = self._visible(ratio, shift, size)
        missing = [ij for ij in visible if ij not in self._tiles]
        for row in sorted({j for _, j in missing}):
            self._draw_tiles(
                [i for i, j in missing if j == row], row, scale, draw
            )

        snapshot.push_clip(Graphene.Rect().init(0, 0, width, height))
        snapshot.save()
        snapshot.translate(Graphene.Point().init(*shift))
        if ratio != 1.0:
            snapshot.scale(ratio, ratio)
        tw, th = self._size
        for i, j in visible:
            snapshot.append_texture(
                self._tiles[i, j], Graphene.Rect().init(i * tw, j * th, tw, th)
            )
        snapshot.restore()
        snapshot.pop()

        # A long pan leaves tiles behind; keep about one view's worth.
        if len(self._tiles) > 2 * len(visible):
            keep = set(visible)
            for ij in [ij for ij in self._tiles if ij not in keep]:
                del self._tiles[ij]
        return ratio

    def _start(self, key: object, view: Matrix, size: tuple[int, int]):
        """Starts the tiles over at view, cut to fit a widget of size."""
        self.clear()
        self._key, self._base = key, view
        width, height = size
        self._size = (
            math.ceil(width / max(1, round(width / TILE))),
            math.ceil(height / max(1, round(height / TILE))),
        )

    def _visible(
        self, ratio: float, shift: tuple[float, float], size: tuple[int, int]
    ) -> list[tuple[int, int]]:
        """The tiles a widget of size shows, the view at ratio, shift."""
        tw, th = self._size
        width, height = size
        # The widget's rectangle, in base view pixels.
        x0, y0 = -shift[0] / ratio, -shift[1] / ratio
        x1, y1 = (width - shift[0]) / ratio, (height - shift[1]) / ratio
        cols = range(math.floor(x0 / tw), math.ceil(x1 / tw))
        rows = range(math.floor(y0 / th), math.ceil(y1 / th))
        return [(i, j) for j in rows for i in cols]

    def _from_base(
        self, view: Matrix
    ) -> tuple[float | None, tuple[float, float]]:
        """
        The uniform scale and the shift that take base view pixels to
        view pixels (p = ratio * q + shift); (None, ...) when view is
        not the base view moved and scaled within MAX_ZOOM_RATIO.
        """
        if self._base is None:
            return None, (0.0, 0.0)
        bxx, byx, bxy, byy, bx0, by0 = self._base.for_cairo()
        xx, yx, xy, yy, x0, y0 = view.for_cairo()
        if bxx == 0 or byy == 0 or byx or bxy or yx or xy:
            return None, (0.0, 0.0)
        ratio = xx / bxx
        if not math.isclose(yy / byy, ratio, rel_tol=1e-9):
            return None, (0.0, 0.0)
        if math.isclose(ratio, 1.0, rel_tol=1e-12):
            ratio = 1.0
        if not 1 / MAX_ZOOM_RATIO <= ratio <= MAX_ZOOM_RATIO:
            return None, (0.0, 0.0)
        return ratio, (x0 - ratio * bx0, y0 - ratio * by0)

    def _draw_tiles(
        self, cols: list[int], row: int, scale: int, draw: DrawView
    ):
        """
        Draws the given tiles of one row in one pass over the run that
        holds them; each tile's texture shares that pass's pixels.
        """
        assert self._base is not None
        tw, th = self._size
        i0 = min(cols)
        count = max(cols) - i0 + 1
        width, height = tw * scale, th * scale
        surface = cairo.ImageSurface(
            cairo.FORMAT_ARGB32, count * width, height
        )
        surface.set_device_scale(scale, scale)
        view = Matrix.translation(-i0 * tw, -row * th) @ self._base
        draw(cairo.Context(surface), view, count * tw, th)
        surface.flush()
        stride = surface.get_stride()
        pixels = GLib.Bytes.new(bytes(surface.get_data()))
        length = (height - 1) * stride + width * 4
        for i in cols:
            self._tiles[i, row] = Gdk.MemoryTexture.new(
                width,
                height,
                _FORMAT,
                GLib.Bytes.new_from_bytes(
                    pixels, (i - i0) * width * 4, length
                ),
                stride,
            )

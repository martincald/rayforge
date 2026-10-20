"""
View tiles: a frame asked for by a moved view only is composited from
textures (canvas/view_tiles.py), and shows what drawing the canvas
directly shows. Anything else redrawn draws directly.
"""

import numpy as np
import pytest
from gi.repository import Gdk, Graphene, Gsk, Gtk

from swiftcut.ui_gtk.canvas.element import CanvasElement

pytestmark = pytest.mark.ui

WIDGET = (800, 600)
SCALE = 2


@pytest.fixture
def surface(world_surface_factory):
    """A WorldSurface on a scale-2 screen, with something on it."""
    s = world_surface_factory(widget_w=WIDGET[0], widget_h=WIDGET[1])
    s.get_scale_factor = lambda: SCALE
    s.add(CanvasElement(30.0, 40.0, 50.0, 25.0, background=(1, 0, 0, 1)))
    s.add(CanvasElement(120.0, 20.0, 10.0, 90.0, background=(0, 0, 1, 0.5)))
    return s


def _frame(surface) -> np.ndarray:
    """One frame of the surface, as device pixels (RGBA rows)."""
    snapshot = Gtk.Snapshot.new()
    snapshot.scale(SCALE, SCALE)
    surface.do_snapshot(snapshot)
    node = snapshot.to_node()
    display = Gdk.Display.get_default()
    assert display is not None
    renderer = Gsk.CairoRenderer.new()
    renderer.realize_for_display(display)
    try:
        width, height = WIDGET[0] * SCALE, WIDGET[1] * SCALE
        texture = renderer.render_texture(
            node, Graphene.Rect().init(0, 0, width, height)
        )
    finally:
        renderer.unrealize()
    downloader = Gdk.TextureDownloader.new(texture)
    downloader.set_format(Gdk.MemoryFormat.R8G8B8A8_PREMULTIPLIED)
    data, stride = downloader.download_bytes()
    pixels = data.get_data()
    assert pixels is not None
    rows = np.frombuffer(pixels, np.uint8).reshape(height, stride)
    return rows[:, : width * 4].astype(int)


def test_a_panned_frame_is_composited_from_tiles_and_matches(surface):
    _frame(surface)  # the frame before the pan, drawn directly
    surface._pan_by_scroll_delta(37.0, -23.0)

    tiled = _frame(surface)
    assert len(surface._view_tiles) > 0

    surface.queue_draw()  # anything else: drawn directly
    direct = _frame(surface)
    assert len(surface._view_tiles) == 0

    assert np.abs(tiled - direct).max() <= 2


def test_a_second_pan_reuses_the_tiles(surface):
    _frame(surface)
    surface._pan_by_scroll_delta(10.0, 0.0)
    _frame(surface)
    tiles = dict(surface._view_tiles._tiles)

    surface._pan_by_scroll_delta(10.0, 0.0)
    _frame(surface)

    assert all(
        surface._view_tiles._tiles[ij] is texture
        for ij, texture in tiles.items()
        if ij in surface._view_tiles._tiles
    )


def test_a_content_change_with_the_pan_draws_directly(surface):
    _frame(surface)
    surface._pan_by_scroll_delta(10.0, 0.0)
    surface.root.children[-1].set_visible(False)

    _frame(surface)

    assert len(surface._view_tiles) == 0


def test_a_zoom_scales_the_tiles_then_settles_sharp(surface):
    _frame(surface)
    # The first moved frame draws its tiles at its own view: sharp.
    surface._zoom_about_point_live(400.0, 300.0, surface.zoom_level * 1.2)
    _frame(surface)
    assert surface._view_settle_id is None

    # The next shows them scaled, and asks for a sharp frame at rest.
    surface._zoom_about_point_live(400.0, 300.0, surface.zoom_level * 1.2)
    _frame(surface)
    assert len(surface._view_tiles) > 0
    assert surface._view_settle_id is not None

    surface._on_view_settled()
    _frame(surface)
    assert len(surface._view_tiles) == 0


def test_edit_mode_never_uses_tiles(surface):
    _frame(surface)
    surface.edit_context = surface.root.children[-1]
    surface._pan_by_scroll_delta(10.0, 0.0)

    _frame(surface)

    assert len(surface._view_tiles) == 0

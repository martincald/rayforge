"""The canvas overlay and the tooltips that explain the start corner.

The head marker sits on the selected corner of the job's bounding box
and the arrow points toward the opposite corner; each toggle's tooltip
says the same thing in words.
"""

from unittest.mock import MagicMock, patch

import cairo
import pytest

from swiftcut.machine.models.machine import (
    JogDirection,
    Machine,
    StartCorner,
)
from swiftcut.ui_gtk.canvas2d.elements.start_corner import StartCornerElement

WIDTH, HEIGHT = 50.0, 30.0

# Local space is y-up, so the top edge is at y = HEIGHT.
EXPECTED = {
    StartCorner.TOP_LEFT: ((0.0, HEIGHT), (WIDTH, 0.0)),
    StartCorner.TOP_RIGHT: ((WIDTH, HEIGHT), (0.0, 0.0)),
    StartCorner.BOTTOM_LEFT: ((0.0, 0.0), (WIDTH, HEIGHT)),
    StartCorner.BOTTOM_RIGHT: ((WIDTH, 0.0), (0.0, HEIGHT)),
}


def _element(corner: StartCorner) -> StartCornerElement:
    element = StartCornerElement()
    element.set_job((10.0, 20.0, WIDTH, HEIGHT), corner)
    return element


@pytest.mark.parametrize("corner", list(StartCorner))
def test_the_marker_is_on_the_selected_corner(corner):
    head, opposite = _element(corner).head_and_opposite()

    assert (head, opposite) == EXPECTED[corner]


def test_the_overlay_covers_the_job_box():
    element = _element(StartCorner.TOP_LEFT)

    assert element.rect() == (10.0, 20.0, WIDTH, HEIGHT)
    assert element.visible is True


def _alpha_at(surface: cairo.ImageSurface, x: int, y: int) -> int:
    stride = surface.get_stride()
    return surface.get_data()[y * stride + x * 4 + 3]


@pytest.mark.parametrize("corner", list(StartCorner))
def test_it_draws_at_the_head_not_at_the_opposite_corner(corner):
    """Rendered the way the canvas does: mm, y-up, 4 px per mm."""
    element = _element(corner)
    scale = 4.0
    width_px, height_px = int(WIDTH * scale), int(HEIGHT * scale)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width_px, height_px)
    ctx = cairo.Context(surface)
    ctx.translate(0, height_px)
    ctx.scale(scale, -scale)

    element.draw(ctx)
    surface.flush()

    (hx, hy), (ox, oy) = element.head_and_opposite()

    def to_px(x, y):
        return (
            min(int(x * scale), width_px - 1),
            min(int(height_px - y * scale), height_px - 1),
        )

    # The marker's centre dot is filled; the far corner is untouched.
    assert _alpha_at(surface, *to_px(hx, hy)) > 0
    assert _alpha_at(surface, *to_px(ox, oy)) == 0


@pytest.fixture
def surface(lite_context):
    """A WorkSurface without GTK init, holding a real overlay element."""
    from swiftcut.ui_gtk.canvas2d.surface import WorkSurface

    s = WorkSurface.__new__(WorkSurface)
    s._start_corner_element = StartCornerElement()
    s.queue_draw = MagicMock()
    s.editor = MagicMock()
    s.machine = Machine(lite_context)
    return s


def test_the_surface_puts_it_on_the_job_box(surface):
    surface.editor.doc.all_workpieces = [MagicMock()]
    surface.machine.set_start_corner(StartCorner.BOTTOM_RIGHT)

    with patch(
        "swiftcut.ui_gtk.canvas2d.surface.TransformCmd.group_bbox_world",
        return_value=(10.0, 20.0, 60.0, 50.0),
    ):
        surface._update_start_corner_element()

    element = surface._start_corner_element
    assert element.visible is True
    assert element.rect() == (10.0, 20.0, 50.0, 30.0)
    assert element.corner is StartCorner.BOTTOM_RIGHT


def test_no_job_hides_it(surface):
    surface.editor.doc.all_workpieces = []
    surface._start_corner_element.set_visible(True)

    surface._update_start_corner_element()

    assert surface._start_corner_element.visible is False


_WORDS = {
    JogDirection.EAST: "right",
    JogDirection.WEST: "left",
    JogDirection.SOUTH: "bottom",
    JogDirection.NORTH: "top",
}


def test_each_tooltip_names_the_corner_the_job_grows_toward():
    from swiftcut.ui_gtk.doceditor.bottom_panel import _START_CORNER_BUTTONS

    for corner, _icon, tooltip in _START_CORNER_BUTTONS:
        horizontal, vertical = corner.toward_opposite
        toward = f"{_WORDS[vertical]}-{_WORDS[horizontal]}"
        assert tooltip == f"Start here, cut toward {toward}"
    assert [c for c, _i, _t in _START_CORNER_BUTTONS] == list(StartCorner)

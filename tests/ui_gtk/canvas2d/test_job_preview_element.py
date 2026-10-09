"""The job preview on the canvas.

Travels are dashed, cuts and raster lines solid, each in the theme's
colour for it; the preview shows the segments finished at its time,
the one under way as far as the head has got, and the head. Finished
segments are kept in an image that only grows while time moves on and
starts again when the view, the theme or a backwards scrub says so.
"""

from types import SimpleNamespace

import cairo
import pytest
from raygeo.geo import Matrix
from raygeo.ops import Ops

from swiftcut.core.color import ColorSet
from swiftcut.image.util.srgb import create_lut_from_color
from swiftcut.pipeline.job_preview import CUT, SCAN, TRAVEL, JobPreviewModel
from swiftcut.ui_gtk.canvas2d.elements import job_preview
from swiftcut.ui_gtk.canvas2d.elements.job_preview import (
    JobPreviewElement,
    draw_segments,
    stroke_paths,
)

COLORS = {
    TRAVEL: (1.0, 0.4, 0.0, 0.7),
    CUT: (1.0, 0.0, 1.0, 1.0),
    SCAN: (0.0, 0.0, 0.0, 1.0),
}
MACHINE = SimpleNamespace(
    max_cut_speed=600, max_travel_speed=3000, acceleration=1000
)
SIZE = 100


class SpyContext(cairo.Context):
    """A real cairo context that also writes down what it paints."""

    def __init__(self, target):
        # cairo.Context is built in __new__, from the target.
        self.calls: list[tuple] = []

    def stroke(self):
        dashes, _offset = self.get_dash()
        self.calls.append(
            (
                "stroke",
                tuple(dashes),
                self.get_line_width(),
                self.get_source().get_rgba(),
            )
        )
        super().stroke()

    def paint(self):
        self.calls.append(("paint",))
        super().paint()

    def fill(self):
        self.calls.append(("fill", self.get_source().get_rgba()))
        super().fill()

    def strokes(self):
        return [call for call in self.calls if call[0] == "stroke"]


def _context() -> tuple[SpyContext, cairo.ImageSurface]:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
    return SpyContext(surface), surface


def _alpha(surface: cairo.ImageSurface, x: int, y: int) -> int:
    surface.flush()
    return surface.get_data()[y * surface.get_stride() + x * 4 + 3]


def _canvas(view: Matrix | None = None):
    return SimpleNamespace(
        view_transform=view or Matrix.identity(),
        get_width=lambda: SIZE,
        get_height=lambda: SIZE,
        get_scale_factor=lambda: 1,
        queue_draw=lambda: None,
    )


def _model() -> JobPreviewModel:
    """A cut along y=20, a travel to y=50, a cut back, a raster line."""
    ops = Ops()
    ops.set_power(1.0)
    ops.move_to(10.0, 20.0)
    ops.line_to(90.0, 20.0)
    ops.move_to(90.0, 50.0)
    ops.line_to(10.0, 50.0)
    ops.move_to(10.0, 80.0)
    ops.scan_to(90.0, 80.0, 0.0, bytes([255] * 8))
    return JobPreviewModel.from_ops(ops, MACHINE)


@pytest.fixture
def themed(monkeypatch):
    monkeypatch.setattr(job_preview, "theme_colors", lambda: dict(COLORS))


@pytest.fixture
def element(themed):
    element = JobPreviewElement()
    element.canvas = _canvas()
    element.set_model(_model())
    return element


class TestStyles:
    @pytest.mark.parametrize(
        "kind, dash, width",
        [(TRAVEL, (4.0, 3.0), 1.0), (CUT, (), 2.0), (SCAN, (), 1.0)],
    )
    def test_each_kind_has_its_stroke(self, kind, dash, width):
        ctx, _surface = _context()

        stroke_paths(
            ctx, cairo.Matrix(), COLORS, kind, [[(0.0, 0.0), (9.0, 9.0)]]
        )

        assert ctx.strokes() == [
            ("stroke", dash, width, pytest.approx(COLORS[kind]))
        ]

    def test_one_stroke_per_kind_cuts_last(self):
        ctx, _surface = _context()

        draw_segments(ctx, cairo.Matrix(), COLORS, _model().segments)

        assert [call[1:3] for call in ctx.strokes()] == [
            ((4.0, 3.0), 1.0),
            ((), 1.0),
            ((), 2.0),
        ]

    def test_the_path_is_placed_by_the_view_and_stroked_in_pixels(self):
        ctx, surface = _context()
        zoom = cairo.Matrix(xx=4.0, yy=4.0)

        stroke_paths(ctx, zoom, COLORS, CUT, [[(5.0, 5.0), (20.0, 5.0)]])

        # 5 mm is 20 px, and the line is still 2 px wide.
        assert _alpha(surface, 40, 20) > 0
        assert _alpha(surface, 40, 23) == 0
        assert ctx.strokes()[0][2] == 2.0


class TestTheThemeColours:
    def test_none_until_the_theme_resolves(self, monkeypatch):
        theme = SimpleNamespace(color_set=None)
        monkeypatch.setattr(
            job_preview, "get_context", lambda: SimpleNamespace(theme=theme)
        )

        assert job_preview.theme_colors() is None

    def test_travel_cut_and_engrave(self, monkeypatch):
        color_set = ColorSet(
            _data={
                "travel": (1.0, 0.4, 0.0, 0.7),
                "cut": create_lut_from_color((1.0, 0.0, 1.0, 1.0)),
                "engrave": create_lut_from_color((0.0, 0.0, 0.0, 1.0)),
            }
        )
        theme = SimpleNamespace(color_set=color_set)
        monkeypatch.setattr(
            job_preview, "get_context", lambda: SimpleNamespace(theme=theme)
        )

        colors = job_preview.theme_colors()

        assert colors is not None
        assert colors[TRAVEL] == (1.0, 0.4, 0.0, 0.7)
        assert colors[CUT] == pytest.approx((1.0, 0.0, 1.0, 1.0))
        assert colors[SCAN] == pytest.approx((0.0, 0.0, 0.0, 1.0))

    def test_no_theme_draws_nothing(self, monkeypatch):
        monkeypatch.setattr(job_preview, "theme_colors", lambda: None)
        element = JobPreviewElement()
        element.canvas = _canvas()
        element.set_model(_model())
        ctx, _surface = _context()

        element.draw_overlay(ctx)

        assert ctx.calls == []


class TestDrawing:
    def test_hidden_and_inert_until_it_has_a_model(self, themed):
        element = JobPreviewElement()
        element.canvas = _canvas()
        ctx, _surface = _context()

        element.draw_overlay(ctx)

        assert element.visible is False
        assert element.selectable is False
        assert ctx.calls == []

    def test_at_zero_only_the_head_shows(self, element):
        ctx, surface = _context()

        element.draw_overlay(ctx)

        assert element.visible is True
        assert ctx.strokes() == []
        assert _alpha(surface, 50, 20) == 0
        # The head waits on the first point.
        assert [call[0] for call in ctx.calls] == ["paint", "fill"]
        assert _alpha(surface, 10, 20) > 0

    def test_at_the_total_every_segment_is_drawn(self, element):
        model = element.model
        element.set_time(model.total_time)
        ctx, surface = _context()

        element.draw_overlay(ctx)

        assert element._finished_count == len(model.segments)
        # The cuts, the raster line, and the travel between them.
        for x, y in ((50, 20), (50, 50), (50, 80), (90, 35)):
            assert _alpha(surface, x, y) > 0, (x, y)
        # Nothing is under way any more: no partial stroke.
        assert ctx.strokes() == []

    def test_the_segment_under_way_is_drawn_to_the_head(self, element):
        cut = element.model.segments[1]
        element.set_time((cut.t0 + cut.t1) / 2)
        ctx, surface = _context()

        element.draw_overlay(ctx)

        assert ctx.strokes() == [
            ("stroke", (), 2.0, pytest.approx(COLORS[CUT]))
        ]
        assert _alpha(surface, 30, 20) > 0
        assert _alpha(surface, 75, 20) == 0

    def test_cleared_it_hides_and_draws_nothing(self, element):
        element.set_time(element.model.total_time)
        element.set_model(None)
        ctx, _surface = _context()

        element.draw_overlay(ctx)

        assert element.visible is False
        assert ctx.calls == []


class TestFinishedImage:
    def _draw(self, element, t):
        element.set_time(t)
        ctx, _surface = _context()
        element.draw_overlay(ctx)
        return element._finished

    def test_time_moving_on_adds_to_the_same_image(self, element):
        segments = element.model.segments
        image = self._draw(element, segments[1].t1)
        count = element._finished_count

        assert self._draw(element, segments[3].t1) is image
        assert element._finished_count > count

    def test_scrubbing_back_starts_it_again(self, element):
        segments = element.model.segments
        image = self._draw(element, segments[3].t1)

        assert self._draw(element, segments[1].t1) is not image
        assert element._finished_count == 2

    def test_a_view_change_starts_it_again(self, element):
        t = element.model.segments[3].t1
        image = self._draw(element, t)

        element.canvas.view_transform = Matrix.scale(2.0, 2.0)

        assert self._draw(element, t) is not image

    def test_a_theme_change_starts_it_again(self, element, monkeypatch):
        t = element.model.segments[3].t1
        image = self._draw(element, t)

        dark = dict(COLORS, **{SCAN: (1.0, 1.0, 1.0, 1.0)})
        monkeypatch.setattr(job_preview, "theme_colors", lambda: dark)

        assert self._draw(element, t) is not image

    def test_it_is_drawn_at_the_display_scale(self, element):
        element.canvas.get_scale_factor = lambda: 2

        image = self._draw(element, element.model.total_time)

        assert (image.get_width(), image.get_height()) == (2 * SIZE,) * 2
        assert image.get_device_scale() == (2.0, 2.0)

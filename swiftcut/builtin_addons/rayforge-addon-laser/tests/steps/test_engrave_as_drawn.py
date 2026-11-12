"""
Engrave "As drawn": an SVG's filled paths engrave as solid areas (by
their own fill rule), its unfilled ones as outlines. Each case starts
from SVG bytes, goes through the SVG importer (Single) and is measured
on the raster the Engrave step produces: 0 is full power, 255 none.

The files are 100 mm wide in a 100-unit viewBox, a unit a mm, and
import without trim padding, so the raster covers exactly the
drawing's box. The lab machines' 0.1 mm spot makes the raster 20 px
per mm across and 10 down (one row per 0.1 mm raster line).
"""

from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from laser_essentials.steps import EngraveStep, raster_step
from raygeo.geo import Geometry, Matrix

from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.image.svg.importer import SvgImporter

# The ink is black; the base render of the light gray fill used below
# is not: below this, a pixel is inked.
INKED = 128
# A raster line (and the spot): 0.1 mm.
LINE_MM = 0.1


def _svg(body: str) -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        f'width="100mm" height="100mm" viewBox="0 0 100 100">{body}</svg>'
    ).encode()


def _workpiece(body: str) -> WorkPiece:
    """
    The one workpiece an SVG imports as (Single), its source
    resolvable for the base render as in a document.
    """
    result = SvgImporter(_svg(body), Path("drawing.svg")).get_doc_items(
        PassthroughSpec(trim_padding=0.0)
    )
    assert result is not None and result.payload is not None
    (wp,) = result.payload.items
    assert isinstance(wp, WorkPiece)
    source = result.payload.source
    doc = Mock()
    doc.source_assets = {source.uid: source}
    doc.get_source_asset_by_uid.side_effect = doc.source_assets.get
    parent = Mock()
    parent.doc = doc
    parent.get_world_transform.return_value = Matrix.identity()
    wp.parent = parent
    return wp


class _Raster:
    """
    The raster an Engrave step makes of a workpiece, addressed in the
    file's millimetres (x right, y down from the drawing's top left).
    """

    def __init__(self, machine, wp: WorkPiece, mode: str | None = None):
        step = EngraveStep(name="engrave")
        if mode is not None:
            step.engrave_mode = mode
        part, _alpha = raster_step._build_raster_part(step, machine, wp)
        assert part.image_source is not None
        self.ppm_x, self.ppm_y = part.pixels_per_mm
        rows = round(part.size_mm[1] * self.ppm_y)
        image = np.frombuffer(part.image_source.read_all(), np.uint8)
        self.image = image.reshape(rows, -1)
        x0, y0, _x1, _y1 = wp.source_segment.pristine_geometry.rect()
        self.origin = x0, y0

    def region(self, x0, y0, x1, y1) -> np.ndarray:
        """The pixels of a box (file mm), edges rounded inward."""
        ox, oy = self.origin
        c0 = int(np.ceil((x0 - ox) * self.ppm_x))
        c1 = int(np.floor((x1 - ox) * self.ppm_x))
        r0 = int(np.ceil((y0 - oy) * self.ppm_y))
        r1 = int(np.floor((y1 - oy) * self.ppm_y))
        return self.image[r0:r1, c0:c1]

    def inked_span_x(self, y: float) -> tuple[float, float]:
        """The first and last inked x (file mm) on the row at y."""
        ox, oy = self.origin
        row = self.image[int((y - oy) * self.ppm_y)]
        cols = np.flatnonzero(row < INKED)
        return ox + cols[0] / self.ppm_x, ox + (cols[-1] + 1) / self.ppm_x

    def inked_span_y(self, x: float) -> tuple[float, float]:
        """The first and last inked y (file mm) in the column at x."""
        ox, oy = self.origin
        col = self.image[:, int((x - ox) * self.ppm_x)]
        rows = np.flatnonzero(col < INKED)
        return oy + rows[0] / self.ppm_y, oy + (rows[-1] + 1) / self.ppm_y


def _solid(pixels: np.ndarray) -> bool:
    return pixels.size > 0 and bool((pixels < INKED).all())


def _empty(pixels: np.ndarray) -> bool:
    return pixels.size > 0 and bool((pixels == 255).all())


# A filled 20 x 20 mm square (light gray, so only the ink makes it
# black) and, apart from it, a short stroked line that widens the
# drawing so the square's edges are measured inside the raster.
FILLED_SQUARE = (
    '<rect x="10" y="10" width="20" height="20" fill="#cccccc"/>'
    '<path d="M40 40 L45 45" fill="none" stroke="#000" '
    'stroke-width="0.1"/>'
)
# A stroke-only 20 x 20 mm square.
STROKED_SQUARE = (
    '<rect x="10" y="10" width="20" height="20" fill="none" '
    'stroke="#000" stroke-width="0.1"/>'
)


class TestFilledAndUnfilled:
    def test_new_steps_engrave_as_drawn(self):
        assert EngraveStep(name="engrave").engrave_mode == "AS_DRAWN"

    def test_a_filled_square_is_a_solid_area_the_size_of_the_square(
        self, machine
    ):
        wp = _workpiece(FILLED_SQUARE)
        assert wp.source_segment.path_fills == [(1, "nonzero"), (1, None)]
        raster = _Raster(machine, wp)

        assert _solid(raster.region(10, 10, 30, 30))
        for y in (10.5, 20.0, 29.5):
            x0, x1 = raster.inked_span_x(y)
            assert x0 == pytest.approx(10, abs=LINE_MM)
            assert x1 == pytest.approx(30, abs=LINE_MM)
        for x in (10.5, 20.0, 29.5):
            y0, y1 = raster.inked_span_y(x)
            assert y0 == pytest.approx(10, abs=LINE_MM)
            assert y1 == pytest.approx(30, abs=LINE_MM)
        # Nothing inked between the square and the line.
        assert _empty(raster.region(30 + LINE_MM, 10, 39, 30))

    def test_outline_leaves_the_squares_own_gray(self, machine):
        """The solid area is the ink's, not the file's own fill."""
        raster = _Raster(machine, _workpiece(FILLED_SQUARE), "OUTLINE")

        assert not (raster.region(12, 12, 28, 28) < INKED).any()

    def test_a_stroke_only_square_is_an_outline(self, machine):
        wp = _workpiece(STROKED_SQUARE)
        assert wp.source_segment.path_fills == [(1, None)]
        raster = _Raster(machine, wp)

        assert _empty(raster.region(10.5, 10.5, 29.5, 29.5))
        # Each edge inked its 0.2 mm width, inside the square.
        assert _solid(raster.region(11, 10, 29, 10.2))
        assert _solid(raster.region(11, 29.8, 29, 30))
        assert _solid(raster.region(10, 11, 10.2, 29))
        assert _solid(raster.region(29.8, 11, 30, 29))

    def test_both_fills_the_stroke_only_square(self, machine):
        """What As drawn changes: Both fills every closed shape."""
        raster = _Raster(machine, _workpiece(STROKED_SQUARE), "BOTH")

        assert _solid(raster.region(10.5, 10.5, 29.5, 29.5))


class TestFillRule:
    @pytest.mark.parametrize(
        "path, hole",
        [
            # Even-odd: the inner square is a hole.
            (
                (
                    '<path fill="#cccccc" fill-rule="evenodd" '
                    'd="M10 10 H30 V30 H10 Z M15 15 H25 V25 H15 Z"/>'
                ),
                True,
            ),
            # Non-zero, inner square drawn the same way round: solid.
            (
                (
                    '<path fill="#cccccc" '
                    'd="M10 10 H30 V30 H10 Z M15 15 H25 V25 H15 Z"/>'
                ),
                False,
            ),
            # Non-zero, inner square drawn the other way round: a hole.
            (
                (
                    '<path fill="#cccccc" '
                    'd="M10 10 H30 V30 H10 Z M15 15 V25 H25 V15 Z"/>'
                ),
                True,
            ),
        ],
        ids=["evenodd", "nonzero-same-direction", "nonzero-opposite"],
    )
    def test_holes_follow_the_paths_fill_rule(self, machine, path, hole):
        raster = _Raster(machine, _workpiece(path))

        assert _solid(raster.region(10, 10, 30, 15))
        assert _solid(raster.region(10, 25, 30, 30))
        inner = raster.region(15.2, 15.2, 24.8, 24.8)
        assert _empty(inner) if hole else _solid(inner)


class TestOneWorkpieceManyPaths:
    def test_overlapping_filled_paths_do_not_cancel(self, machine):
        """
        Two even-odd squares overlapping in 20..30: filled together,
        even-odd, the overlap would be a hole.
        """
        wp = _workpiece(
            '<rect x="10" y="10" width="20" height="20" fill="#cccccc" '
            'fill-rule="evenodd"/>'
            '<rect x="20" y="20" width="20" height="20" fill="#cccccc" '
            'fill-rule="evenodd"/>'
        )
        assert wp.source_segment.path_fills == [
            (1, "evenodd"),
            (1, "evenodd"),
        ]
        raster = _Raster(machine, wp)

        assert _solid(raster.region(10, 10, 30, 30))
        assert _solid(raster.region(20, 20, 40, 40))
        assert _solid(raster.region(20, 20, 30, 30))

    def test_a_layer_mixing_filled_and_unfilled_paths(self, machine):
        """Single: the layer's two paths are one workpiece."""
        wp = _workpiece(
            '<g id="layer1" inkscape:groupmode="layer" '
            'inkscape:label="Engrave">'
            '<rect x="10" y="10" width="20" height="20" fill="#cccccc"/>'
            '<rect x="40" y="10" width="20" height="20" fill="none" '
            'stroke="#000" stroke-width="0.1"/></g>'
        )
        assert wp.source_segment.path_fills == [(1, "nonzero"), (1, None)]
        raster = _Raster(machine, wp)

        assert _solid(raster.region(10, 10, 30, 30))
        assert _empty(raster.region(40.5, 10.5, 59.5, 29.5))
        # Its left edge, inside the drawing: inked on every row.
        edge = raster.region(39.8, 11, 40.2, 29) < INKED
        assert edge.any(axis=1).all()


class TestWithoutFillData:
    def test_a_workpiece_without_fill_data_engraves_as_both(self, machine):
        """A document saved before there was fill data, for one."""
        wp = _workpiece(STROKED_SQUARE)
        wp.source_segment.path_fills = None

        as_drawn = _Raster(machine, wp)
        both = _Raster(machine, wp, "BOTH")

        assert np.array_equal(as_drawn.image, both.image)
        assert _solid(as_drawn.region(10.5, 10.5, 29.5, 29.5))

    def test_fill_data_that_does_not_count_the_contours_is_ignored(
        self, machine
    ):
        wp = _workpiece(STROKED_SQUARE)
        wp.source_segment.path_fills = [(2, None)]

        as_drawn = _Raster(machine, wp)
        both = _Raster(machine, wp, "BOTH")

        assert np.array_equal(as_drawn.image, both.image)

    def test_a_shape_with_no_source_segment_engraves_as_both(self, machine):
        """A sketch or a DXF shape: geometry, no fill data."""
        geo = Geometry()
        geo.move_to(0, 0)
        geo.line_to(1, 0)
        geo.line_to(1, 1)
        geo.line_to(0, 1)
        geo.close_path()
        wp = WorkPiece(name="shape")
        wp._edited_boundaries = geo
        wp.set_size(20.0, 20.0)

        def blank(self, width, height):
            return None

        images = {}
        for mode in ("AS_DRAWN", "BOTH"):
            step = EngraveStep(name="engrave")
            step.engrave_mode = mode
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(WorkPiece, "render_to_pixels", blank)
                part, _alpha = raster_step._build_raster_part(
                    step, machine, wp
                )
            images[mode] = part.image_source.read_all()

        assert images["AS_DRAWN"] == images["BOTH"]

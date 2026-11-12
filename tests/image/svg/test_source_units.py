"""
The source units of an SVG: the user units per inch that size its px,
unitless and viewBox-only lengths. Illustrator writes a point per user
unit (72 per inch), with or without a width and height; anything else
is read at 96 per inch, and a file in physical units keeps its size.
On the source-units fixtures (tests/fixtures/import), each a 100 x 50
mm outline, filling its page but on illustrator_artboard.svg.
"""

import io
from pathlib import Path

import cairo
import pytest

from swiftcut.core.vectorization_spec import PassthroughSpec, TraceSpec
from swiftcut.image import import_file
from swiftcut.image.svg.importer import SvgImporter
from swiftcut.image.svg.svg_tree import build_svg_tree, visible_svg
from swiftcut.image.svg.svgutil import is_illustrator_svg, units_per_inch

TESTS_DIR = Path(__file__).parent.parent.parent
FIXTURES = TESTS_DIR / "fixtures" / "import"
RESPONSIVE = FIXTURES / "illustrator_responsive.svg"
ARTBOARD = FIXTURES / "illustrator_artboard.svg"
FIXED = FIXTURES / "illustrator_fixed.svg"
SAVE_AS_PX = FIXTURES / "illustrator_save_as_px.svg"
HIDDEN_LAYER = FIXTURES / "illustrator_hidden_layer.svg"
INKSCAPE_MM = FIXTURES / "inkscape_mm.svg"
PLAIN_PX = FIXTURES / "plain_px.svg"
ILLUSTRATOR_FILES = [RESPONSIVE, FIXED, SAVE_AS_PX, HIDDEN_LAYER]
WHOLE_IMAGE = {"threshold": 1.0, "auto_threshold": False}


def _svg(attrs: str, head: str = "") -> bytes:
    return (
        f'{head}<svg xmlns="http://www.w3.org/2000/svg" {attrs}>'
        '<rect width="10" height="10"/></svg>'
    ).encode()


def _size_mm(items) -> tuple[float, float]:
    """The size of the one imported workpiece, in mm."""
    (wp,) = items
    return wp.size


class TestUnitsPerInch:
    @pytest.mark.parametrize(
        "data",
        [
            _svg("", "<!-- Generator: Adobe Illustrator 28.0.0 -->"),
            _svg('id="Layer_1" data-name="Layer 1"'),
            _svg('xmlns:i="http://ns.adobe.com/AdobeIllustrator/10.0/"'),
            (
                b'<svg xmlns="http://www.w3.org/2000/svg"><!-- Generator: '
                b"Adobe Illustrator 30.8.2 --><rect/></svg>"
            ),
        ],
        ids=["comment", "data-name", "xmlns:i", "comment-inside"],
    )
    def test_an_illustrator_file_is_72(self, data):
        assert is_illustrator_svg(data)
        assert units_per_inch(data) == 72.0

    @pytest.mark.parametrize(
        "data",
        [
            _svg('width="100" height="50"'),
            _svg(
                'width="100px" height="50px" xmlns:inkscape='
                '"http://www.inkscape.org/namespaces/inkscape"',
                "<!-- Created with Inkscape (http://www.inkscape.org/) -->",
            ),
            (
                b'<svg xmlns="http://www.w3.org/2000/svg"><!-- a note -->'
                b"<desc>Adobe Illustrator</desc></svg>"
            ),
        ],
        ids=["plain", "inkscape-px", "not-a-comment"],
    )
    def test_any_other_file_is_96(self, data):
        assert not is_illustrator_svg(data)
        assert units_per_inch(data) == 96.0

    @pytest.mark.parametrize("override", [72.0, 96.0, 150.0])
    def test_an_override_wins(self, override):
        assert units_per_inch(RESPONSIVE.read_bytes(), override) == override
        assert units_per_inch(PLAIN_PX.read_bytes(), override) == override

    def test_the_hidden_layer_fixture_tells_it_only_in_its_own_bytes(self):
        """
        visible_svg writes the file again without its hidden layer:
        the comment and xmlns:i are gone, and there is no data-name.
        """
        raw = HIDDEN_LAYER.read_bytes()
        visible = visible_svg(raw)

        assert visible != raw
        assert not is_illustrator_svg(visible)
        assert units_per_inch(raw) == 72.0


class TestTheImporter:
    @pytest.mark.parametrize(
        "path", [*ILLUSTRATOR_FILES, ARTBOARD], ids=lambda p: p.stem
    )
    def test_an_illustrator_file_comes_in_at_its_size(self, path):
        payload = import_file(path)

        assert _size_mm(payload.items) == pytest.approx((100, 50), abs=0.05)

    @pytest.mark.parametrize("path", ILLUSTRATOR_FILES, ids=lambda p: p.stem)
    @pytest.mark.parametrize(
        "trace", [WHOLE_IMAGE, {}], ids=["whole-image", "traced"]
    )
    def test_traced_it_comes_in_at_the_same_size(self, path, trace):
        """
        Tracing (the dialog without Use Original Vectors, the command
        line's --trace and a batch import) reads the file's units too:
        the image is the 100 x 50 mm page.
        """
        payload = import_file(path, vectorization_spec=TraceSpec(**trace))

        (wp,) = payload.items
        assert wp.size == pytest.approx((100, 50), abs=0.05)

    def test_traced_an_artboard_is_trimmed_to_what_it_draws(self):
        """
        A file without width and height is trimmed to what it draws
        too, not traced as its whole A4 page: the outline and its 1 pt
        stroke (0.35 mm), to the trim's render (about 0.07 mm a pixel
        on this page).
        """
        payload = import_file(
            ARTBOARD, vectorization_spec=TraceSpec(**WHOLE_IMAGE)
        )

        (wp,) = payload.items
        assert wp.size == pytest.approx((100.35, 50.35), abs=0.15)
        assert wp.pos == pytest.approx((19.82, 216.82), abs=0.15)

    @pytest.mark.parametrize(
        "path", [INKSCAPE_MM, PLAIN_PX], ids=lambda p: p.stem
    )
    def test_millimetres_and_plain_px_keep_their_size(self, path):
        payload = import_file(path)

        assert _size_mm(payload.items) == pytest.approx((100, 50), abs=0.05)

    def test_96_per_inch_makes_an_illustrator_file_three_quarters(self):
        payload = import_file(
            RESPONSIVE, vectorization_spec=PassthroughSpec(ppi=96.0)
        )

        assert _size_mm(payload.items) == pytest.approx((75, 37.5), abs=0.05)

    def test_72_per_inch_makes_a_plain_file_four_thirds(self):
        payload = import_file(
            PLAIN_PX, vectorization_spec=PassthroughSpec(ppi=72.0)
        )

        assert _size_mm(payload.items) == pytest.approx(
            (400 / 3, 200 / 3), abs=0.05
        )

    def test_explicit_units_ignore_the_override(self):
        payload = import_file(
            INKSCAPE_MM, vectorization_spec=PassthroughSpec(ppi=72.0)
        )

        assert _size_mm(payload.items) == pytest.approx((100, 50), abs=0.05)

    @pytest.mark.parametrize("path", ILLUSTRATOR_FILES, ids=lambda p: p.stem)
    def test_the_scan_gives_the_size_and_asks_for_units(self, path):
        manifest = SvgImporter(path.read_bytes(), path).scan()

        assert manifest.natural_size_mm == pytest.approx((100, 50), abs=0.05)
        assert manifest.is_unitless

    def test_the_tree_reads_the_units_before_hiding_what_is_hidden(self):
        tree = build_svg_tree(HIDDEN_LAYER.read_bytes(), HIDDEN_LAYER)

        assert tree.unit_to_mm == pytest.approx(25.4 / 72)


class TestTheBoxOfALayerlessFile:
    """
    A file without layers comes in as one workpiece boxed to its
    content, as a layer is: the trim padding lies around the box, and
    the shape stays where it is on the page (Y up from its bottom).
    """

    @pytest.mark.parametrize(
        "path, corner",
        [(RESPONSIVE, (0, 0)), (ARTBOARD, (20, 217)), (PLAIN_PX, (0, 0))],
        ids=lambda value: getattr(value, "stem", None),
    )
    def test_the_box_is_the_shape_where_it_is(self, path, corner):
        (wp,) = import_file(path).items

        x, y = corner
        assert wp.get_world_geometry().rect() == pytest.approx(
            (x, y, x + 100, y + 50), abs=0.05
        )
        assert wp.pos == pytest.approx(corner, abs=0.05)
        assert wp.size == pytest.approx((100, 50), abs=0.05)


def _cairo_pdf() -> bytes:
    buf = io.BytesIO()
    surface = cairo.PDFSurface(buf, 100, 100)
    ctx = cairo.Context(surface)
    ctx.rectangle(10, 10, 30, 30)
    ctx.fill()
    surface.finish()
    return buf.getvalue()


@pytest.mark.parametrize(
    "source, mime_type",
    [
        (TESTS_DIR / "image" / "png" / "color.png", None),
        (TESTS_DIR / "image" / "jpg" / "color.jpg", None),
        (TESTS_DIR / "image" / "bmp" / "img-24-bit-gray.bmp", None),
        (_cairo_pdf(), "application/pdf"),
    ],
    ids=["png", "jpg", "bmp", "pdf"],
)
@pytest.mark.parametrize("trace", [WHOLE_IMAGE, {}], ids=["whole", "traced"])
def test_a_bitmap_traces_as_it_did_at_96(source, mime_type, trace):
    """
    A trace spec's ppi is None (Auto) by default now, 96 before; only
    an SVG reads it, so a bitmap comes in exactly as it did.
    """
    results = [
        import_file(
            source,
            mime_type=mime_type,
            vectorization_spec=TraceSpec(ppi=ppi, **trace),
        )
        for ppi in (None, 96.0)
    ]

    auto, at_96 = ([wp.matrix.to_list() for wp in r.items] for r in results)
    assert auto == at_96
    bounds = [
        [wp.boundaries.rect() if wp.boundaries else None for wp in r.items]
        for r in results
    ]
    assert bounds[0] == bounds[1]

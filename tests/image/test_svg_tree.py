import base64
import logging
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import pyvips
from raygeo.geo import Geometry

from swiftcut.core.vectorization_spec import LayerImportMode, PassthroughSpec
from swiftcut.image.import_tree import GroupNode, ImageNode, PathNode
from swiftcut.image.svg.importer import SvgImporter
from swiftcut.image.svg.renderer import SVG_RENDERER
from swiftcut.image.svg.svg_tree import build_svg_tree, visible_svg
from swiftcut.image.svg.svgutil import SVG_NS, extract_layer_manifest

TESTS_DIR = Path(__file__).parent.parent
ILLUSTRATOR = TESTS_DIR / "fixtures" / "import" / "illustrator_two_layers.svg"
TWO_LAYERS = TESTS_DIR / "image" / "svg" / "twolayer.svg"
SHWESHWE = TESTS_DIR / "fixtures" / "import" / "shweshwe.svg"
LOGGER = "swiftcut.image.svg.svg_tree"
# A 1x1 PNG.
PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAAAAgAB"
    "SK+kcQAAAABJRU5ErkJggg=="
)


def _svg(body: str, attrs: str = 'viewBox="0 0 100 100"') -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" {attrs}>{body}</svg>'
    ).encode()


def _union(paths) -> tuple[float, float, float, float]:
    geo = Geometry()
    for path in paths:
        geo.extend(path.geometry)
    return geo.rect()


def _workpieces(path: Path, spec: PassthroughSpec):
    result = SvgImporter(path.read_bytes(), path).get_doc_items(spec)
    assert result is not None and result.payload is not None
    items = result.payload.items
    return result, [
        wp for item in items for wp in getattr(item, "all_workpieces", [item])
    ]


class TestIllustratorFile:
    @pytest.fixture
    def tree(self):
        return build_svg_tree(ILLUSTRATOR.read_bytes(), ILLUSTRATOR, ppi=72)

    def test_layers_named_as_the_file_has_them(self, tree):
        assert [(n.name, n.source_layer) for n in tree.layers()] == [
            ("Cut", "Cut"),
            ("Engrave", "Engrave"),
        ]
        assert tree.unit_to_mm == pytest.approx(25.4 / 72)
        assert tree.warnings == []

    def test_engrave_holds_its_groups_in_order(self, tree):
        _cut, engrave = tree.layers()
        groups = [c for c in engrave.children if isinstance(c, GroupNode)]

        assert [g.name for g in groups] == ["Logo", "Text", "Group"]
        assert [len(list(g.paths())) for g in groups] == [3, 2, 0]
        assert all(p.closed for p in engrave.paths())

    def test_colors_come_from_css_classes(self, tree):
        cut, engrave = tree.layers()
        logo, text, _image = engrave.children

        assert [p.color for p in cut.paths()] == ["#ff0000"]
        assert {p.color for p in logo.paths()} == {"#231f20"}
        # No fill set: SVG's initial fill, black.
        assert {p.color for p in text.paths()} == {"#000000"}

    def test_the_placed_png_is_cut_to_its_clip(self, tree):
        """
        The PNG is 40 x 20 px under translate(216 108) scale(1.8):
        216..288 x 108..144 pt. Its group's class clips it to the rect
        234..270 x 108..144 pt, so it shows 234..270 x 108..144 pt:
        at 25.4/72 mm per pt, x 82.55 mm, y 38.1 mm, 12.7 x 12.7 mm.
        """
        (image,) = tree.root.images()

        assert isinstance(image, ImageNode)
        assert image.source_layer == "Engrave"
        assert image.placement == (0, 0, 40, 20)
        assert image.data.startswith(b"\x89PNG")
        assert tree.rect_mm(image.world_bbox()) == pytest.approx(
            (82.55, 38.1, 12.7, 12.7), abs=0.05
        )

    def test_layer_paths_are_the_importers_geometry(self, tree):
        """
        Each layer's paths cover exactly what the importer gives that
        layer's workpiece, in the same units.
        """
        spec = PassthroughSpec(
            active_layer_ids=["Cut", "Engrave"],
            layer_import_mode=LayerImportMode.NEW_LAYERS,
            ppi=72,
        )
        result, workpieces = _workpieces(ILLUSTRATOR, spec)

        assert tree.unit_to_mm == pytest.approx(
            result.parse_result.native_unit_to_mm, rel=1e-5
        )
        for wp, layer in zip(workpieces, tree.layers(), strict=True):
            segment = wp.source_segment
            assert segment.layer_id == layer.source_layer
            assert _union(layer.paths()) == pytest.approx(
                segment.pristine_geometry.rect(), abs=1e-6
            )


def test_an_inkscape_files_layers_match_the_importers():
    tree = build_svg_tree(TWO_LAYERS.read_bytes(), TWO_LAYERS)
    spec = PassthroughSpec(layer_import_mode=LayerImportMode.NEW_LAYERS)
    result, workpieces = _workpieces(TWO_LAYERS, spec)

    assert [n.name for n in tree.layers()] == ["Calque 1", "Calque 2"]
    assert tree.unit_to_mm == pytest.approx(
        result.parse_result.native_unit_to_mm, rel=1e-5
    )
    for wp, layer in zip(workpieces, tree.layers(), strict=True):
        assert _union(layer.paths()) == pytest.approx(
            wp.source_segment.pristine_geometry.rect(), abs=1e-6
        )


def test_illustrator_layer_names_come_from_data_name():
    data = _svg(
        '<g id="Engrave_1" data-name="Engrave 1">'
        '<rect x="1" y="1" width="5" height="5"/></g>'
    )

    tree = build_svg_tree(data)

    assert [(n.name, n.source_layer) for n in tree.layers()] == [
        ("Engrave 1", "Engrave_1")
    ]
    assert extract_layer_manifest(data)[0]["name"] == "Engrave 1"


def test_nested_transforms_are_flattened():
    data = _svg(
        '<g id="L"><g transform="translate(10 20)"><g id="inner" '
        'transform="scale(2)"><rect x="1" y="1" width="5" height="5"/>'
        "</g></g></g>"
    )

    tree = build_svg_tree(data)
    (layer,) = tree.layers()
    (outer,) = layer.children
    (inner,) = outer.children
    (rect,) = inner.children

    assert inner.name == "inner"
    assert inner.world_transform.transform_point((0, 0)) == (10, 20)
    assert rect.world_transform.transform_point((1, 1)) == (12, 22)
    assert rect.geometry.rect() == pytest.approx((12, 22, 22, 32))


def test_named_groups_beside_shapes_are_groups_not_layers():
    """
    Illustrator's one-layer export has its content under the root: a
    group with an id beside other content is a group, not a layer.
    """
    data = _svg(
        '<g id="Logo"><rect x="1" y="1" width="5" height="5"/></g>'
        '<g><circle cx="50" cy="50" r="5"/></g>'
        '<line x1="0" y1="90" x2="90" y2="90" stroke="#00F"/>'
    )

    tree = build_svg_tree(data)
    logo, unnamed, line = tree.root.children

    assert tree.layers() == []
    assert (type(logo), logo.name) == (GroupNode, "Logo")
    assert (type(unnamed), unnamed.name) == (GroupNode, "Group")
    assert logo.source_layer is None and unnamed.source_layer is None
    assert isinstance(line, PathNode)
    assert (line.closed, line.color) == (False, "#0000ff")


def test_definitions_and_clips_are_never_paths():
    data = _svg(
        "<defs><rect id='r' x='1' y='1' width='5' height='5'/></defs>"
        "<clipPath id='c'><rect x='2' y='2' width='5' height='5'/>"
        "</clipPath><mask id='m'><rect x='3' y='3' width='1' "
        "height='1'/></mask><symbol id='s'><rect x='4' y='4' "
        "width='1' height='1'/></symbol><metadata><rect x='5' y='5' "
        "width='1' height='1'/></metadata>"
        "<rect x='60' y='60' width='10' height='10'/>"
    )

    tree = build_svg_tree(data)

    assert [p.geometry.rect() for p in tree.root.paths()] == [
        pytest.approx((60, 60, 70, 70))
    ]


def test_text_not_outlined_is_skipped_with_a_warning():
    data = _svg(
        '<g id="L"><text x="10" y="50">Hello <tspan>world</tspan></text>'
        '<rect x="1" y="1" width="5" height="5"/></g>'
    )

    tree = build_svg_tree(data)

    assert len(list(tree.root.paths())) == 1
    assert tree.warnings == [
        (
            'Text "Hello world" is not outlined and was not imported. In '
            "Illustrator: Type > Create Outlines."
        )
    ]


def test_a_symbol_instance_is_a_group():
    data = _svg(
        "<defs><symbol id='Star' data-name='Star'><rect x='0' y='0' "
        "width='4' height='4'/></symbol></defs><g id='L'>"
        "<use xlink:href='#Star' x='10' y='20' transform='scale(2)'/>"
        "<use href='#missing'/></g>"
    )

    tree = build_svg_tree(data)
    (layer,) = tree.layers()
    (group,) = layer.children

    assert isinstance(group, GroupNode) and group.name == "Star"
    (rect,) = group.paths()
    assert rect.geometry.rect() == pytest.approx((20, 40, 28, 48))


def test_style_attribute_beats_class_beats_attribute():
    data = _svg(
        "<style>.a{stroke:#00ff00}</style><g id='L' fill='#123456'>"
        "<rect class='a' stroke='#ff0000' x='0' y='0' width='1' "
        "height='1'/><rect class='a' style='stroke:none' x='2' y='0' "
        "width='1' height='1'/><rect stroke='currentColor' "
        "color='#abcdef' x='4' y='0' width='1' height='1'/></g>"
    )

    tree = build_svg_tree(data)

    assert [p.color for p in tree.root.paths()] == [
        "#00ff00",
        "#123456",
        "#abcdef",
    ]


def test_a_paths_fill_and_fill_rule_are_resolved_as_drawn():
    """
    Whether a path is drawn filled, and by which rule, through
    inheritance, CSS classes and style; no fill, transparent or at
    opacity 0 is unfilled.
    """
    rect = "x='0' y='0' width='1' height='1'"
    data = _svg(
        "<style>.eo{fill-rule:evenodd}.clear{fill-opacity:0}</style>"
        "<defs><linearGradient id='g'/></defs>"
        f"<rect id='default' {rect}/>"
        f"<rect id='none' fill='none' stroke='#000' {rect}/>"
        f"<g fill='none'><rect id='inherited-none' stroke='#000' {rect}/>"
        f"<rect id='own-fill' fill='#f00' {rect}/></g>"
        f"<rect id='transparent' fill='transparent' stroke='#000' {rect}/>"
        f"<rect id='zero-opacity' fill='#f00' fill-opacity='0' "
        f"stroke='#000' {rect}/>"
        f"<g class='clear'><rect id='class-zero-opacity' stroke='#000' "
        f"{rect}/></g>"
        f"<rect id='gradient' fill='url(#g)' {rect}/>"
        f"<g fill-rule='evenodd'><rect id='inherited-evenodd' {rect}/>"
        f"<rect id='own-nonzero' fill-rule='nonzero' {rect}/></g>"
        f"<rect id='class-evenodd' class='eo' {rect}/>"
        f"<rect id='style-evenodd' class='eo' style='fill-rule:nonzero;"
        f"fill-rule:evenodd' {rect}/>"
    )

    paths = build_svg_tree(data).root.paths()

    assert {p.name: (p.filled, p.fill_rule) for p in paths} == {
        "default": (True, "nonzero"),
        "none": (False, "nonzero"),
        "inherited-none": (False, "nonzero"),
        "own-fill": (True, "nonzero"),
        "transparent": (False, "nonzero"),
        "zero-opacity": (False, "nonzero"),
        "class-zero-opacity": (False, "nonzero"),
        "gradient": (True, "nonzero"),
        "inherited-evenodd": (True, "evenodd"),
        "own-nonzero": (True, "nonzero"),
        "class-evenodd": (True, "evenodd"),
        "style-evenodd": (True, "evenodd"),
    }


def _imported_rects(data: bytes) -> list[tuple[float, ...]]:
    """The box of each contour the importer reads (Single)."""
    result = SvgImporter(data, Path("drawing.svg")).get_doc_items()
    assert result is not None and result.payload is not None
    geometries = [
        wp.source_segment.pristine_geometry
        for item in result.payload.items
        for wp in getattr(item, "all_workpieces", [item])
    ]
    return [
        tuple(pytest.approx(v) for v in contour.rect())
        for geometry in geometries
        for contour in geometry.split_into_contours()
    ]


# The causes of stray lines (shapes the importer reads that the SVG
# does not show), each beside one visible square at 10..20.
KEEP = "<rect id='keep' x='10' y='10' width='10' height='10'/>"
LAYER = "inkscape:groupmode='layer'"
STRAY_SUSPECTS = {
    # A hidden or template sublayer: visibility hidden by its style or
    # a class rule, inherited by what it holds; a shape in it that a
    # clip refers to still draws nothing there.
    "hidden-sublayers": (
        "<style>.template{visibility:hidden}</style>"
        f"<g id='L1' {LAYER} inkscape:label='Art'>{KEEP}"
        "<g id='sub' style='visibility:hidden'>"
        "<rect id='in-sub' x='50' y='50' width='9' height='9'/>"
        "<g><rect id='deep' x='60' y='60' width='9' height='9'/></g>"
        "<rect id='clip-shape' x='0' y='0' width='99' height='99'/>"
        "</g><g id='tpl' class='template'>"
        "<path id='in-template' d='M70 70 L90 90' stroke='#000'/></g>"
        "</g><clipPath id='c'><use href='#clip-shape'/></clipPath>"
        "<g clip-path='url(#c)'/>"
    ),
    # A guide path a textPath follows, drawn without paint.
    "text-path-guide": (
        f"{KEEP}<path id='guide' d='M30 70 L90 70' fill='none'/>"
        "<text><textPath href='#guide'>Label</textPath></text>"
    ),
    # Definitions outside <defs>, and a clip inside a symbol: the
    # square is the symbol's, placed by a <use>.
    "definitions-outside-defs": (
        "<g clip-path='url(#clip)'><use href='#sym' x='10' y='10'/></g>"
        "<clipPath id='clip'><rect x='5' y='5' width='90' height='90'/>"
        "</clipPath>"
        "<mask id='mask'><rect x='6' y='6' width='88' height='88' "
        "fill='white'/></mask>"
        "<pattern id='pat' width='5' height='5'><rect x='60' y='60' "
        "width='3' height='3'/></pattern>"
        "<marker id='mark'><path d='M70 70 L80 80' stroke='#000'/>"
        "</marker>"
        "<defs><symbol id='sym'><clipPath id='inner'><rect x='0' y='0' "
        "width='5' height='5'/></clipPath><rect id='keep' "
        "clip-path='url(#inner)' x='0' y='0' width='10' height='10'/>"
        "</symbol></defs>"
    ),
    # Inkscape's guides live in its namedview.
    "guides": (
        f"{KEEP}<sodipodi:namedview id='view'>"
        "<sodipodi:guide id='g1' position='50,0' orientation='1,0'/>"
        "<sodipodi:guide id='g2' position='0,50' orientation='0,1'/>"
        "</sodipodi:namedview>"
    ),
    # Strokes that do not show, on shapes with no fill.
    "invisible-strokes": (
        f"{KEEP}<path id='zero-width' d='M30 30 L90 90' fill='none' "
        "stroke='#000' stroke-width='0'/>"
        "<path id='zero-opacity' d='M30 90 L90 30' fill='none' "
        "stroke='#000' stroke-opacity='0'/>"
        "<g stroke-width='0px'><path id='inherited-zero' d='M40 40 "
        "L50 50' fill='none' stroke='#000'/></g>"
        "<rect id='clear-fill' x='50' y='50' width='9' height='9' "
        "fill='#f00' fill-opacity='0'/>"
    ),
}


def _suspect_svg(name: str) -> bytes:
    return _svg(
        STRAY_SUSPECTS[name],
        'width="100mm" height="100mm" viewBox="0 0 100 100" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/'
        'sodipodi-0.dtd"',
    )


class TestStrayLines:
    @pytest.mark.parametrize("name", list(STRAY_SUSPECTS))
    def test_only_what_shows_is_imported(self, name):
        data = _suspect_svg(name)

        assert _imported_rects(data) == [(10, 10, 20, 20)]

    @pytest.mark.parametrize("name", list(STRAY_SUSPECTS))
    def test_only_what_shows_is_in_the_tree(self, name):
        data = _suspect_svg(name)

        assert [p.name for p in build_svg_tree(data).root.paths()] == ["keep"]

    def test_what_is_taken_out_is_logged(self, caplog):
        caplog.set_level(logging.INFO, logger=LOGGER)

        visible_svg(_suspect_svg("invisible-strokes"))

        assert [r.message for r in caplog.records] == [
            f"SVG import: skipped invisible {what} (no fill or stroke)"
            for what in (
                'path "zero-width"',
                'path "zero-opacity"',
                'path "inherited-zero"',
                'rect "clear-fill"',
            )
        ]

    def test_a_hairline_is_kept(self):
        data = _svg(
            "<path d='M10 10 L90 90' fill='none' stroke='#000' "
            "stroke-width='0.001'/>"
        )

        assert _imported_rects(data) == [(10, 10, 90, 90)]

    @pytest.mark.parametrize(
        "path",
        [
            "M10 10 H20 V20 H10 Z M30 30 H40 V40 H30 Z",
            "M10 10 h10 v10 h-10 z m20 20 h10 v10 h-10 z",
            "M10 10 H20 M30 30 H40",
        ],
        ids=["closed", "relative-after-close", "after-open"],
    )
    def test_a_compound_paths_subpaths_stay_apart(self, path):
        """
        Two subpaths are two contours, the importer's and the tree's,
        with nothing joining them.
        """
        data = _svg(f"<path d='{path}' fill='none' stroke='#000'/>")

        (node,) = build_svg_tree(data).root.paths()
        contours = node.geometry.split_into_contours()

        assert [c.rect()[:2] for c in contours] == [(10, 10), (30, 30)]
        assert [r[:2] for r in _imported_rects(data)] == [(10, 10), (30, 30)]


@pytest.mark.xfail(
    strict=True,
    reason="raygeo drops a visible child of a visibility:hidden group "
    "(NEEDS-OWNER)",
)
def test_a_visible_child_of_a_hidden_group_is_imported():
    """
    visibility is inherited, and a child may set it back: the SVG shows
    the child; the tree has it, raygeo's import does not.
    """
    data = _svg(
        f"{KEEP}<g visibility='hidden'><rect id='shown' "
        "visibility='visible' x='50' y='50' width='10' height='10'/></g>"
    )

    assert [p.name for p in build_svg_tree(data).root.paths()] == [
        "keep",
        "shown",
    ]
    assert _imported_rects(data) == [(10, 10, 20, 20), (50, 50, 60, 60)]


@pytest.mark.xfail(
    strict=True,
    reason="raygeo does not apply a symbol's viewBox to its <use> "
    "(NEEDS-OWNER)",
)
def test_a_symbol_instance_fills_the_box_of_its_use():
    """
    Illustrator's symbols: a symbol with a viewBox centred on its
    origin, placed by a <use> of the same size. The SVG shows the
    square at 50..60; raygeo moves it by the use's x and y only.
    """
    data = _svg(
        "<defs><symbol id='sym' viewBox='-5 -5 10 10'><rect x='-5' "
        "y='-5' width='10' height='10'/></symbol></defs>"
        "<use href='#sym' x='-5' y='-5' width='10' height='10' "
        "transform='translate(55 55)'/>"
    )

    assert _imported_rects(data) == [(50, 50, 60, 60)]


class TestImages:
    def test_a_linked_image_is_read_beside_the_svg(self, tmp_path):
        (tmp_path / "pics").mkdir()
        (tmp_path / "pics" / "dot.png").write_bytes(base64.b64decode(PNG))
        svg = tmp_path / "art.svg"
        svg.write_bytes(
            _svg(
                '<g id="L"><image href="pics/dot.png" x="5" y="6" '
                'width="10" height="10"/><image id="gone" '
                'href="nothing.png"/></g>'
            )
        )

        tree = build_svg_tree(svg.read_bytes(), svg)
        (image,) = tree.root.images()

        assert image.world_bbox() == pytest.approx((5, 6, 10, 10))
        assert tree.warnings == [
            (
                'Image "gone" is missing or not a PNG or JPEG and was not '
                "imported."
            )
        ]

    @pytest.mark.parametrize(
        "aspect, placement",
        [
            ("", (0, 25, 100, 50)),
            ("none", (0, 0, 100, 100)),
            ("xMinYMin meet", (0, 0, 100, 50)),
            ("xMaxYMax", (0, 50, 100, 50)),
        ],
    )
    def test_preserve_aspect_ratio(self, aspect, placement):
        """A 2:1 PNG in a 100 x 100 box."""
        png = base64.b64encode(_two_by_one_png()).decode()
        data = _svg(
            f'<image width="100" height="100" preserveAspectRatio="{aspect}"'
            f' href="data:image/png;base64,{png}"/>'
        )

        (image,) = build_svg_tree(data).root.images()

        assert image.placement == pytest.approx(placement)

    def test_slice_covers_its_box_cut_to_it(self):
        png = base64.b64encode(_two_by_one_png()).decode()
        data = _svg(
            '<image width="100" height="100" preserveAspectRatio="xMidYMid '
            f'slice" href="data:image/png;base64,{png}"/>'
        )

        (image,) = build_svg_tree(data).root.images()

        assert image.placement == pytest.approx((-50, 0, 200, 100))
        assert image.world_bbox() == pytest.approx((0, 0, 100, 100))

    def test_clip_is_in_the_user_space_of_the_clipped_element(self):
        """
        clip-path on an image with its own transform: the clipPath's
        shapes go through that transform (and the clipPath's own).
        """
        data = _svg(
            "<clipPath id='c' transform='translate(1 0)'><rect x='2' "
            "y='2' width='4' height='4'/></clipPath>"
            f"<image clip-path='url(#c)' transform='translate(10 10) "
            f"scale(2)' width='10' height='10' "
            f"href='data:image/png;base64,{PNG}'/>"
        )

        (image,) = build_svg_tree(data).root.images()

        assert image.clip.rect() == pytest.approx((16, 14, 24, 22))
        assert image.world_bbox() == pytest.approx((16, 14, 8, 8))


def _two_by_one_png() -> bytes:
    return pyvips.Image.black(2, 1).pngsave_buffer()


def _ids(data: bytes) -> list[str]:
    """The ids in an SVG, in document order."""
    return [e.get("id") for e in ET.fromstring(data).iter() if e.get("id")]


def _defs_ids(data: bytes) -> list[str]:
    """The ids of what the root's first <defs> holds."""
    root = ET.fromstring(data)
    (defs, *_rest) = [c for c in root if c.tag == f"{{{SVG_NS}}}defs"]
    return [c.get("id") for c in defs]


class TestVisibleSvg:
    def test_a_hidden_illustrator_layer_goes_with_its_image(self):
        """
        shweshwe.svg's Layer_1 is hidden through a CSS class
        (.st1{display:none}): the tree has neither it nor its photo.
        """
        data = visible_svg(SHWESHWE.read_bytes())
        tree = build_svg_tree(data, SHWESHWE)

        assert [layer.name for layer in tree.layers()] == ["Layer_2"]
        assert list(tree.root.images()) == []
        assert len(list(tree.root.paths())) == 5
        assert b"ns0:" not in data

    def test_hidden_transparent_and_paintless_elements_go(self, caplog):
        caplog.set_level(logging.INFO, logger=LOGGER)
        data = _svg(
            "<style>.ghost{opacity:0}.hide{display:none}</style>"
            "<rect id='frame' x='0' y='0' width='100' height='100' "
            "fill='none'/>"
            "<rect id='nopaint' x='1' y='1' width='5' height='5' "
            "fill='transparent' stroke='none'/>"
            "<rect id='op' x='1' y='1' width='5' height='5' opacity='0'/>"
            "<rect id='op-class' x='1' y='1' width='5' height='5' "
            "class='ghost'/>"
            "<rect id='op-style' x='1' y='1' width='5' height='5' "
            "style='opacity:0%'/>"
            "<g display='none'><rect id='in-hidden' x='1' y='1' "
            "width='5' height='5'/></g>"
            "<rect id='disp-class' class='hide' x='1' y='1' width='5' "
            "height='5'/>"
            "<image id='hidden-image' visibility='hidden' width='5' "
            f"height='5' href='data:image/png;base64,{PNG}'/>"
            "<rect id='kept' x='1' y='1' width='5' height='5'/>"
        )

        assert _ids(visible_svg(data)) == ["kept"]
        assert [r.message for r in caplog.records] == [
            f"SVG import: skipped {what}"
            for what in (
                'invisible rect "frame" (artboard background)',
                'invisible rect "nopaint" (no fill or stroke)',
                'invisible rect "op" (opacity 0)',
                'invisible rect "op-class" (opacity 0)',
                'invisible rect "op-style" (opacity 0)',
                "hidden g (display:none)",
                'hidden rect "disp-class" (display:none)',
                'hidden image "hidden-image" (visibility:hidden)',
            )
        ]

    def test_fill_stroke_and_visibility_are_inherited(self):
        """
        A fill="none" group keeps its stroked child; a stroke on the
        group keeps its fill-none children; a visible child of a
        hidden group stays.
        """
        data = _svg(
            "<g fill='none'><rect id='stroked' stroke='#000' x='0' y='0' "
            "width='5' height='5'/><rect id='bare' x='0' y='0' "
            "width='5' height='5'/></g>"
            "<g stroke='#f00'><circle id='outlined' fill='none' cx='5' "
            "cy='5' r='2'/></g>"
            "<g visibility='hidden'><rect id='hidden' x='0' y='0' "
            "width='5' height='5'/><rect id='shown' visibility='visible' "
            "x='0' y='0' width='5' height='5'/></g>"
        )

        assert _ids(visible_svg(data)) == ["stroked", "outlined", "shown"]

    def test_what_an_href_points_at_is_kept(self):
        """
        A <use> may give what it shows its paint; what it shows is kept
        even inside a hidden group, or where it draws nothing itself
        (moved into defs, where it still resolves), as is a clip a
        visible element uses.
        """
        data = _svg(
            "<g fill='none'><rect id='r' x='0' y='0' width='5' "
            "height='5'/></g><use href='#r' stroke='#000'/>"
            "<g display='none'><path id='p' d='M0 0 L5 5'/>"
            "<clipPath id='c'><rect x='0' y='0' width='5' height='5'/>"
            "</clipPath></g><use xlink:href='#p' stroke='#000'/>"
            "<g clip-path='url(#c)'><rect id='clipped' x='0' y='0' "
            "width='9' height='9'/></g>"
        )

        out = visible_svg(data)

        assert "r" in _ids(out)
        assert _defs_ids(out) == ["r", "p", "c"]
        assert b'xlink:href="#p"' in out
        assert b"ns0:" not in out
        assert len(list(build_svg_tree(out).root.paths())) == 3

    def test_definitions_are_left_as_they_are(self):
        """
        Nothing a definition holds is taken out; a pattern or a marker
        outside <defs> moves into it whole.
        """
        data = _svg(
            "<defs><rect id='in-defs' fill='none' x='0' y='0' width='1' "
            "height='1'/></defs><symbol id='s'><rect id='in-symbol' "
            "display='none' x='0' y='0' width='1' height='1'/></symbol>"
            "<pattern id='pat'><rect id='in-pattern' fill='none' x='0' "
            "y='0' width='1' height='1'/></pattern><marker id='m'>"
            "<rect id='in-marker' opacity='0' x='0' y='0' width='1' "
            "height='1'/></marker>"
        )

        out = visible_svg(data)

        assert _ids(out) == [
            "in-defs",
            "pat",
            "in-pattern",
            "m",
            "in-marker",
            "s",
            "in-symbol",
        ]
        assert _defs_ids(out) == ["in-defs", "pat", "m"]

    def test_clips_and_masks_outside_defs_move_into_defs(self, caplog):
        """
        Into the root's <defs>, made its first child when there is
        none; a clip still clips there, for the renderer too.
        """
        caplog.set_level(logging.INFO, logger=LOGGER)
        data = _svg(
            "<g><clipPath id='left'><rect x='0' y='0' width='50' "
            "height='100'/></clipPath></g><mask id='m'><rect x='0' "
            "y='0' width='1' height='1' fill='white'/></mask>"
            "<rect clip-path='url(#left)' x='0' y='0' width='100' "
            "height='100'/>"
        )

        out = visible_svg(data)

        root = ET.fromstring(out)
        assert root[0].tag == f"{{{SVG_NS}}}defs"
        assert _defs_ids(out) == ["left", "m"]
        assert [r.message for r in caplog.records] == [
            'SVG import: skipped clipPath "left" (clip definition)',
            'SVG import: skipped mask "m" (mask definition)',
        ]
        image = SVG_RENDERER.render_base_image(out, 10, 10)
        assert image.getpoint(2, 5)[-1] == 255
        assert image.getpoint(7, 5)[-1] == 0

    def test_patterns_and_markers_moved_into_defs_still_paint(self):
        """
        A pattern fill and a marker, both defined outside <defs>,
        render the same from <defs>.
        """
        data = _svg(
            "<g><pattern id='dots' width='10' height='10' "
            "patternUnits='userSpaceOnUse'><rect x='0' y='0' width='5' "
            "height='10' fill='#f00'/></pattern></g>"
            "<marker id='tip' markerWidth='10' markerHeight='10' "
            "markerUnits='userSpaceOnUse' refX='5' refY='5'>"
            "<rect x='0' y='0' width='10' height='10' fill='#00f'/>"
            "</marker>"
            "<rect x='0' y='0' width='100' height='50' fill='url(#dots)'/>"
            "<path d='M10 80 L80 80' stroke='#000' marker-end='url(#tip)'/>"
        )

        out = visible_svg(data)

        assert _defs_ids(out) == ["dots", "tip"]
        before = SVG_RENDERER.render_base_image(data, 100, 100)
        after = SVG_RENDERER.render_base_image(out, 100, 100)
        assert before.getpoint(2, 20) == after.getpoint(2, 20)
        assert after.getpoint(2, 20)[0] == 255
        assert before.getpoint(80, 80) == after.getpoint(80, 80)
        assert after.getpoint(80, 80)[2] == 255
        assert (before == after).min() == 255

    @pytest.mark.parametrize(
        "data",
        [
            b"<svg>Not XML</svg",
            b"<html><rect fill='none' width='1' height='1'/></html>",
            b"",
        ],
    )
    def test_data_that_is_not_an_svg_comes_back_unchanged(self, data):
        assert visible_svg(data) is data

    def test_an_svg_with_nothing_to_take_out_comes_back_unchanged(self):
        data = TWO_LAYERS.read_bytes()

        assert visible_svg(data) is data

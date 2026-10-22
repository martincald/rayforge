import base64
from pathlib import Path

import pytest
import pyvips
from raygeo.geo import Geometry

from swiftcut.core.vectorization_spec import LayerImportMode, PassthroughSpec
from swiftcut.image.import_tree import GroupNode, ImageNode, PathNode
from swiftcut.image.svg.importer import SvgImporter
from swiftcut.image.svg.svg_tree import build_svg_tree
from swiftcut.image.svg.svgutil import extract_layer_manifest

TESTS_DIR = Path(__file__).parent.parent
ILLUSTRATOR = TESTS_DIR / "fixtures" / "import" / "illustrator_two_layers.svg"
TWO_LAYERS = TESTS_DIR / "image" / "svg" / "twolayer.svg"
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

import io
from pathlib import Path

import ezdxf
import pytest
from ezdxf import bbox
from raygeo.geo import Geometry

from swiftcut.core.vectorization_spec import LayerImportMode, PassthroughSpec
from swiftcut.image.dxf.importer import DxfImporter
from swiftcut.image.import_tree import GroupNode, PathNode

TESTS_DIR = Path(__file__).parent.parent
FIXTURES = TESTS_DIR / "fixtures" / "import"
TRACED = FIXTURES / "illustrator_traced.dxf"
PLATES = FIXTURES / "cad_plate.dxf"
MANY = TESTS_DIR / "perf" / "many_shapes.dxf"


def _tree(path: Path):
    return DxfImporter(path.read_bytes(), path).build_tree()


def _dxf_bytes(doc) -> bytes:
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode()


def _rect(path: PathNode):
    x0, y0, x1, y1 = path.geometry.rect()
    return x0, y0, x1 - x0, y1 - y0


def test_a_traced_logo_is_its_outline_and_small_closed_paths():
    tree = _tree(TRACED)
    (layer,) = tree.layers()
    paths = list(layer.paths())

    assert (layer.name, layer.source_layer) == ("0", "0")
    assert (tree.unit_to_mm, tree.is_y_down) == (1.0, False)
    assert len(paths) == 121 and all(p.closed for p in paths)
    outline, *dots = paths
    assert (outline.color, _rect(outline)) == ("#ff0000", (0, 0, 120, 80))
    # ACI 7 (black on paper) and ACI 250.
    assert {p.color for p in dots} == {"#000000"}
    assert all(_rect(p)[2:] == pytest.approx((1.5, 1.5)) for p in dots)


def test_a_cad_outline_of_lines_and_arcs_is_one_closed_path():
    """
    Each plate's outline is four LINEs and four ARCs, written out of
    order, the arcs' ends a hair off the lines'; its holes are
    CIRCLEs.
    """
    tree = _tree(PLATES)
    paths = list(tree.root.paths())

    assert len(paths) == 9 and all(p.closed for p in paths)
    sizes = sorted(_rect(p)[2:] for p in paths)
    assert sizes[-2:] == [
        pytest.approx((80, 50)),
        pytest.approx((100, 60)),
    ]


@pytest.mark.parametrize("path", [TRACED, PLATES, MANY])
def test_the_paths_are_the_importers_geometry(path):
    tree = _tree(path)
    spec = PassthroughSpec(layer_import_mode=LayerImportMode.NEW_LAYERS)
    result = DxfImporter(path.read_bytes(), path).get_doc_items(spec)
    (layer_item,) = result.payload.items
    (wp,) = layer_item.all_workpieces
    union = Geometry()
    for node in tree.root.paths():
        union.extend(node.geometry)

    assert union.rect() == pytest.approx(
        wp.source_segment.pristine_geometry.rect(), abs=1e-6
    )
    assert tree.unit_to_mm == result.parse_result.native_unit_to_mm


def test_nested_inserts_are_nested_groups():
    """
    INNER (a BYBLOCK circle at the origin) inserted BYBLOCK at (10, 0)
    in OUTER, OUTER inserted at (100, 50) in red, on layer CUT (blue).
    """
    doc = ezdxf.new()
    doc.layers.add("CUT", color=5)
    inner = doc.blocks.new("INNER")
    inner.add_circle((0, 0), 2, dxfattribs={"color": 0})
    inner.add_line((5, 0), (6, 0), dxfattribs={"layer": "CUT"})
    outer = doc.blocks.new("OUTER")
    outer.add_blockref("INNER", (10, 0), dxfattribs={"color": 0})
    msp = doc.modelspace()
    msp.add_blockref(
        "OUTER", (100, 50), dxfattribs={"layer": "CUT", "color": 1}
    )
    msp.add_line((0, 0), (1, 0), dxfattribs={"layer": "CUT"})

    tree = DxfImporter(_dxf_bytes(doc)).build_tree()
    (cut,) = tree.layers()
    line, group = cut.children

    assert isinstance(line, PathNode) and line.color == "#0000ff"
    assert isinstance(group, GroupNode) and group.name == "OUTER"
    (nested,) = group.children
    assert nested.name == "INNER"
    assert nested.world_transform.transform_point((0, 0)) == (110, 50)
    circle, tick = nested.children
    assert (circle.source_layer, circle.color) == ("0", "#ff0000")
    assert _rect(circle) == pytest.approx((108, 48, 4, 4))
    assert (tick.source_layer, tick.color) == ("CUT", "#0000ff")


def test_a_turned_insert_in_a_turned_insert_lands_where_cad_draws_it():
    """
    INNER (a 10 x 2 rectangle) inserted turned 90 degrees at (20, 0)
    in OUTER, OUTER inserted turned 30 degrees at (100, 50): the tree
    and the importer's workpiece cover what ezdxf's exact extents say.
    """
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4  # mm
    inner = doc.blocks.new("INNER")
    inner.add_lwpolyline([(0, 0), (10, 0), (10, 2), (0, 2)], close=True)
    outer = doc.blocks.new("OUTER")
    outer.add_blockref("INNER", (20, 0), dxfattribs={"rotation": 90})
    msp = doc.modelspace()
    msp.add_blockref("OUTER", (100, 50), dxfattribs={"rotation": 30})
    extents = bbox.extents(msp, fast=False)
    expected = (*extents.extmin.vec2, *extents.extmax.vec2)
    data = _dxf_bytes(doc)

    tree = DxfImporter(data).build_tree()
    result = DxfImporter(data).get_doc_items(PassthroughSpec())

    (path,) = tree.root.paths()
    assert path.geometry.rect() == pytest.approx(expected, abs=1e-6)
    (wp,) = result.payload.items[0].all_workpieces
    assert wp.source_segment.pristine_geometry.rect() == pytest.approx(
        expected, abs=1e-6
    )

from pathlib import Path

import pytest
from raygeo.geo import Matrix

from swiftcut.core.group import Group
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.layout.outline import item_world_polygons
from swiftcut.image.dxf.importer import DxfImporter
from swiftcut.image.svg.importer import SvgImporter

ARC_DXF = Path(__file__).parent.parent / "image" / "dxf" / "acdbarc.dxf"


def _import(importer_cls, path):
    """The one workpiece a file imports to."""
    result = importer_cls(path.read_bytes(), path).get_doc_items(
        PassthroughSpec()
    )
    assert result and result.payload
    (item,) = result.payload.items
    workpieces = item.get_descendants(of_type=WorkPiece) or [item]
    (workpiece,) = workpieces
    return workpiece


def _svg(path, d):
    """An SVG of one path, on a 40 mm square page."""
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40mm" '
        'height="40mm" viewBox="0 0 40 40"><path fill="none" '
        f'stroke="black" stroke-width="0.1" d="{d}"/></svg>'
    )
    return path


def _bounds(polygon):
    xs = [x for x, _y in polygon]
    ys = [y for _x, y in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def test_closed_geometry_gives_its_outer_outline_in_world(tmp_path):
    # A 40 mm square with a 20 mm square hole.
    ring = _svg(tmp_path / "ring.svg", "M0 0H40V40H0Z M10 10H30V30H10Z")
    workpiece = _import(SvgImporter, ring)
    x, y = workpiece.pos
    outline = workpiece.get_world_geometry().rect()
    workpiece.pos = (x + 500, y + 300)

    (polygon,) = item_world_polygons(workpiece)

    assert _bounds(polygon) == pytest.approx(
        (
            outline[0] + 500,
            outline[1] + 300,
            outline[2] + 500,
            outline[3] + 300,
        )
    )


def test_workpiece_without_geometry_gives_its_rotated_frame():
    workpiece = WorkPiece(name="Raster")
    workpiece.set_size(40, 20)
    workpiece.pos = (100, 100)
    workpiece.angle = 90

    (polygon,) = item_world_polygons(workpiece)

    # Turned about its centre (120, 110): 20 wide, 40 tall.
    assert _bounds(polygon) == pytest.approx((110, 90, 130, 130))


def test_open_geometry_gives_its_frame():
    workpiece = _import(DxfImporter, ARC_DXF)
    x, y, w, h = workpiece.bbox

    (polygon,) = item_world_polygons(workpiece)

    assert len(polygon) == 4
    assert _bounds(polygon) == pytest.approx((x, y, x + w, y + h))


def test_an_open_line_beside_a_closed_outline_gives_the_frame(tmp_path):
    # The line has no inside, so only the frame keeps it clear.
    mixed = _svg(tmp_path / "mixed.svg", "M0 0H20V20H0Z M30 0L40 10")
    workpiece = _import(SvgImporter, mixed)
    x, y, w, h = workpiece.bbox

    (polygon,) = item_world_polygons(workpiece)

    assert _bounds(polygon) == pytest.approx((x, y, x + w, y + h))
    assert w > 40


def test_group_gives_the_outlines_of_its_workpieces():
    group = Group()
    for x in (0, 50):
        workpiece = WorkPiece(name="Part")
        workpiece.set_size(10, 10)
        workpiece.pos = (x, 0)
        group.add_child(workpiece)
    group.matrix = Matrix.translation(200, 100)

    polygons = item_world_polygons(group)

    assert [_bounds(p) for p in polygons] == pytest.approx(
        [(200, 100, 210, 110), (250, 100, 260, 110)]
    )

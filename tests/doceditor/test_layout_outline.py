import math
from pathlib import Path

import numpy as np
import pytest
from raygeo.geo import Geometry, Matrix

from swiftcut.core.group import Group
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.layout.outline import (
    MIN_EDGE_MM,
    OUTLINE_TOLERANCE_MM,
    item_world_polygons,
    item_world_polygons_and_edges,
)
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


def test_straight_edges_come_with_the_outlines(tmp_path):
    # A 40 mm square with a 20 mm square hole: the hole has no edges.
    ring = _svg(tmp_path / "ring.svg", "M0 0H40V40H0Z M10 10H30V30H10Z")
    workpiece = _import(SvgImporter, ring)

    polygons, edges = item_world_polygons_and_edges(workpiece, 0.02)

    assert polygons == item_world_polygons(workpiece, 0.02)
    (polygon,) = polygons
    x0, y0, x1, y1 = _bounds(polygon)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    assert [math.dist(*edge) for edge in edges] == pytest.approx([40] * 4)
    for edge in edges:
        for point in edge:
            assert any(point == pytest.approx(c) for c in corners)


def test_a_curve_flattened_into_short_lines_gives_no_edges(tmp_path):
    # The SVG loader flattens a circle's Beziers into 4 mm chords.
    k = 0.5523 * 19
    circle = _svg(
        tmp_path / "circle.svg",
        f"M39 20 C39 {20 + k} {20 + k} 39 20 39 "
        f"C{20 - k} 39 1 {20 + k} 1 20 C1 {20 - k} {20 - k} 1 20 1 "
        f"C{20 + k} 1 39 {20 - k} 39 20 Z",
    )
    workpiece = _import(SvgImporter, circle)

    polygons, edges = item_world_polygons_and_edges(workpiece)

    assert polygons == item_world_polygons(workpiece)
    assert edges == []
    assert MIN_EDGE_MM < 17


def test_a_frame_outline_gives_no_edges():
    workpiece = WorkPiece(name="Raster")
    workpiece.set_size(40, 20)

    polygons, edges = item_world_polygons_and_edges(workpiece)

    assert polygons == item_world_polygons(workpiece)
    assert edges == []


# Bezier circles: the control point distance along the tangent, over
# the radius.
_KAPPA = 0.5522847498


def _quarters(radius):
    """The four Beziers of a circle about the origin, as point tuples."""
    k = _KAPPA * radius
    ends = [(radius, 0), (0, radius), (-radius, 0), (0, -radius)]
    return [
        (
            (x0, y0),
            (x0 - k * y0 / radius, y0 + k * x0 / radius),
            (x1 + k * y1 / radius, y1 - k * x1 / radius),
            (x1, y1),
        )
        for (x0, y0), (x1, y1) in zip(ends, ends[1:] + ends[:1])
    ]


def _circle(radius, beziers):
    """A circle of the radius about the origin: two arcs or four Beziers."""
    geometry = Geometry()
    geometry.move_to(radius, 0)
    if not beziers:
        geometry.arc_to(-radius, 0, -radius, 0, clockwise=False)
        geometry.arc_to(radius, 0, radius, 0, clockwise=False)
        return geometry
    for _start, c1, c2, end in _quarters(radius):
        geometry.bezier_to(*end, *c1, *c2)
    return geometry


def _reach(radius, beziers, angles):
    """
    How far the curve lies from the origin at each angle: the radius
    for arcs; for Beziers, from 4096 points along each.
    """
    if not beziers:
        return np.full(len(angles), float(radius))
    t = np.linspace(0, 1, 4096)[:, None]
    points = np.concatenate(
        [
            (1 - t) ** 3 * np.array(p0)
            + 3 * (1 - t) ** 2 * t * np.array(c1)
            + 3 * (1 - t) * t**2 * np.array(c2)
            + t**3 * np.array(p1)
            for p0, c1, c2, p1 in _quarters(radius)
        ]
    )
    around = np.arctan2(points[:, 1], points[:, 0])
    order = np.argsort(around)
    return np.interp(
        angles,
        around[order],
        np.hypot(*points.T)[order],
        period=2 * math.pi,
    )


@pytest.mark.parametrize("beziers", [False, True], ids=["arcs", "beziers"])
@pytest.mark.parametrize("radius", [0.5, 1, 2, 5, 20, 100, 500])
def test_outline_polygons_lie_well_within_the_merge_tolerance(radius, beziers):
    """
    Gap-0 Auto Layout relies on this: polygons at OUTLINE_TOLERANCE_MM
    lie much closer to arcs and Beziers than that, so touching curves
    overlap far less than the Merge Lines tolerance (see
    NestLayoutStrategy). If raygeo ever polygonizes more coarsely, this
    fails, and that claim must be looked at again.
    """
    (polygon,) = _circle(radius, beziers).to_polygons(OUTLINE_TOLERANCE_MM)

    # From each chord's middle out to the curve.
    points = np.asarray(polygon)
    middles = (points + np.roll(points, -1, axis=0)) / 2
    angles = np.arctan2(middles[:, 1], middles[:, 0])
    gaps = _reach(radius, beziers, angles) - np.hypot(*middles.T)
    # Half Merge Lines' default tolerance, 0.01 mm.
    assert gaps.max() <= 0.005

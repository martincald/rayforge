"""
World outlines of document items, as plain point lists for the
placement engine (swiftcut.shared.placement).
"""

from __future__ import annotations

import math

from raygeo.geo import Geometry, Line
from raygeo.geo.types import Point

from ...core.item import DocItem
from ...core.workpiece import WorkPiece

#: Curves become polygons within this deviation, in mm. A gap measured
#: between two such polygons can be up to twice this smaller than the
#: true gap.
OUTLINE_TOLERANCE_MM = 0.05
#: Straight edges shorter than this, in mm, are not laid flush. Curves
#: often come as lines: the SVG loader flattens the Beziers of a 100 mm
#: circle into 4 mm chords, and a 72-sided polygon that size has
#: 4.4 mm sides. Those are a curve's chords, and taking them as sides
#: to share would cost the layout much for little.
MIN_EDGE_MM = 5.0

_UNIT_SQUARE = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def item_world_polygons(
    item: DocItem, tolerance: float = OUTLINE_TOLERANCE_MM
) -> list[list[Point]]:
    """
    The outer outlines of a workpiece, or of the workpieces in a group,
    in world mm.

    A workpiece whose geometry is all closed contours gives their
    outermost ones. Any other (a raster without geometry, open lines,
    which have no inside to keep clear) gives its world frame
    rectangle.
    """
    return [
        polygon
        for workpiece in _workpieces(item)
        for polygon in _workpiece_polygons(workpiece, tolerance)
    ]


def item_world_polygons_and_edges(
    item: DocItem, tolerance: float = OUTLINE_TOLERANCE_MM
) -> tuple[list[list[Point]], list[tuple[Point, Point]]]:
    """
    item_world_polygons, and the straight edges of those outlines,
    from one pass over each workpiece's geometry.

    The edges are the Line segments of the outer contours, at least
    MIN_EDGE_MM long, in world mm, as (start, end) pairs. A workpiece
    that outlines as its frame rectangle gives none.
    """
    polygons, edges = [], []
    for workpiece in _workpieces(item):
        outer = _outer(workpiece, tolerance)
        if outer is None:
            polygons.extend(_frame(workpiece))
            continue
        geometry, found = outer
        polygons.extend(found)
        start = None
        for command in geometry.iter_typed_commands():
            end = command.end[:2]
            if (
                isinstance(command, Line)
                and start is not None
                and math.dist(start, end) >= MIN_EDGE_MM
            ):
                edges.append((start, end))
            start = end
    return polygons, edges


def _workpieces(item: DocItem) -> list[WorkPiece]:
    """The item if it is a workpiece, else the workpieces in it."""
    if isinstance(item, WorkPiece):
        return [item]
    return item.get_descendants(of_type=WorkPiece)


def _workpiece_polygons(
    workpiece: WorkPiece, tolerance: float
) -> list[list[Point]]:
    """The outer outlines of one workpiece, or its frame rectangle."""
    outer = _outer(workpiece, tolerance)
    return _frame(workpiece) if outer is None else outer[1]


def _frame(workpiece: WorkPiece) -> list[list[Point]]:
    """A workpiece's world frame rectangle, as its one outline."""
    transform = workpiece.get_world_transform()
    return [[transform.transform_point(p) for p in _UNIT_SQUARE]]


def _outer(
    workpiece: WorkPiece, tolerance: float
) -> tuple[Geometry, list[list[Point]]] | None:
    """
    The outer contours of a workpiece whose geometry is all closed
    contours, in world mm, and their polygons; None for any other.
    """
    geometry = workpiece.get_world_geometry()
    if geometry is not None and all(
        contour.is_closed() for contour in geometry.split_into_contours()
    ):
        outer = geometry.filter_to_external_contours()
        polygons = outer.to_polygons(tolerance)
        if polygons and all(len(polygon) >= 3 for polygon in polygons):
            return outer, polygons
    return None

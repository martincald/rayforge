"""
World outlines of document items, as plain point lists for the
placement engine (swiftcut.shared.placement).
"""

from __future__ import annotations

from raygeo.geo.types import Point

from ...core.item import DocItem
from ...core.workpiece import WorkPiece

#: Curves become polygons within this deviation, in mm. A gap measured
#: between two such polygons can be up to twice this smaller than the
#: true gap.
OUTLINE_TOLERANCE_MM = 0.05

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
    if isinstance(item, WorkPiece):
        workpieces = [item]
    else:
        workpieces = item.get_descendants(of_type=WorkPiece)
    return [
        polygon
        for workpiece in workpieces
        for polygon in _workpiece_polygons(workpiece, tolerance)
    ]


def _workpiece_polygons(
    workpiece: WorkPiece, tolerance: float
) -> list[list[Point]]:
    """The outer outlines of one workpiece, or its frame rectangle."""
    geometry = workpiece.get_world_geometry()
    if geometry is not None and all(
        contour.is_closed() for contour in geometry.split_into_contours()
    ):
        polygons = geometry.filter_to_external_contours().to_polygons(
            tolerance
        )
        if polygons and all(len(polygon) >= 3 for polygon in polygons):
            return polygons
    transform = workpiece.get_world_transform()
    return [[transform.transform_point(p) for p in _UNIT_SQUARE]]

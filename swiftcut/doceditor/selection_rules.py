"""
What the selection commands pick (Select Inside, Select Similar, Select
All on a layer, the lasso), as rules over document items. An item's
place is the center of its world box; the canvas applies the result.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from raygeo.geo import Geometry
from raygeo.geo.types import Point

from ..core.group import Group
from ..core.item import DocItem
from ..core.layer import Layer
from ..core.workpiece import WorkPiece
from .layout.outline import OUTLINE_TOLERANCE_MM

if TYPE_CHECKING:
    from ..core.doc import Doc

#: Select Similar by size picks the items whose box area differs from
#: the reference's by at most this fraction of it.
SIZE_TOLERANCE = 0.25

_UNIT_SQUARE = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def candidates(doc: Doc) -> list[DocItem]:
    """
    The items a selection command can pick: the workpieces and groups
    directly on a visible layer. A hidden layer's items are inert.
    """
    return [
        item
        for layer in doc.layers
        if layer.visible
        for item in layer.children
        if isinstance(item, (WorkPiece, Group))
    ]


def world_bbox(item: DocItem) -> tuple[float, float, float, float]:
    """The item's world box, as (min_x, min_y, max_x, max_y)."""
    transform = item.get_world_transform()
    corners = [transform.transform_point(p) for p in _UNIT_SQUARE]
    xs = [x for x, _y in corners]
    ys = [y for _x, y in corners]
    return min(xs), min(ys), max(xs), max(ys)


def world_center(item: DocItem) -> Point:
    """The center of the item's world box."""
    min_x, min_y, max_x, max_y = world_bbox(item)
    return (min_x + max_x) / 2, (min_y + max_y) / 2


def point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    """
    Whether the point lies inside the polygon, by the even-odd rule: a
    ray from the point crosses the polygon's edges an odd number of
    times.
    """
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    x1, y1 = polygon[-1]
    for x2, y2 in polygon:
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
        x1, y1 = x2, y2
    return inside


def _workpieces(item: DocItem) -> list[WorkPiece]:
    """The item if it is a workpiece, else the workpieces in it."""
    if isinstance(item, WorkPiece):
        return [item]
    return item.get_descendants(of_type=WorkPiece)


def has_closed_contour(item: DocItem) -> bool:
    """Whether the item, or a workpiece in it, has a closed contour."""
    for workpiece in _workpieces(item):
        boundaries = workpiece.boundaries
        if boundaries is not None and any(
            contour.is_closed() for contour in boundaries.split_into_contours()
        ):
            return True
    return False


def _outer_outlines(workpiece: WorkPiece) -> list[list[Point]]:
    """
    The outermost of the workpiece's closed contours, as world polygons.
    Open contours have no inside and are left out.
    """
    geometry = workpiece.get_world_geometry()
    if geometry is None:
        return []
    closed = Geometry()
    for contour in geometry.split_into_contours():
        if contour.is_closed():
            closed.extend(contour)
    if closed.is_empty():
        return []
    return closed.filter_to_external_contours().to_polygons(
        OUTLINE_TOLERANCE_MM
    )


def select_inside(
    references: Sequence[DocItem], items: Sequence[DocItem]
) -> list[DocItem]:
    """
    The items whose box center lies inside an outer closed contour of a
    reference (a workpiece, or one in a reference group). A hole does
    not leave its contents out: artwork in a plate's hole belongs to
    the plate. The references themselves are left out.
    """
    outlines = [
        outline
        for reference in references
        for workpiece in _workpieces(reference)
        for outline in _outer_outlines(workpiece)
    ]
    excluded = set(references)
    picked = []
    for item in items:
        if item in excluded:
            continue
        center = world_center(item)
        if any(point_in_polygon(center, outline) for outline in outlines):
            picked.append(item)
    return picked


def source_color(item: DocItem) -> str | None:
    """
    The source color of a workpiece, or of a group's first workpiece;
    None when unknown.
    """
    workpieces = _workpieces(item)
    return workpieces[0].source_color if workpieces else None


def source_layer_key(item: DocItem) -> tuple[str, str | None] | None:
    """
    The source layer of a workpiece, or of a group's first workpiece,
    with the source asset it came from (layer names like "0" repeat
    across files); None when unknown.
    """
    workpieces = _workpieces(item)
    if not workpieces or workpieces[0].source_layer is None:
        return None
    workpiece = workpieces[0]
    segment = workpiece.source_segment
    asset_uid = segment.source_asset_uid if segment else None
    return workpiece.source_layer, asset_uid


def select_similar_color(
    reference: DocItem, items: Sequence[DocItem]
) -> list[DocItem]:
    """The items with the reference's source color."""
    color = source_color(reference)
    if color is None:
        return []
    return [item for item in items if source_color(item) == color]


def select_similar_source_layer(
    reference: DocItem, items: Sequence[DocItem]
) -> list[DocItem]:
    """The items from the reference's source layer, in the same file."""
    key = source_layer_key(reference)
    if key is None:
        return []
    return [item for item in items if source_layer_key(item) == key]


def _area(item: DocItem) -> float:
    min_x, min_y, max_x, max_y = world_bbox(item)
    return (max_x - min_x) * (max_y - min_y)


def select_similar_size(
    reference: DocItem, items: Sequence[DocItem]
) -> list[DocItem]:
    """
    The items whose box area is within SIZE_TOLERANCE of the
    reference's.
    """
    reference_area = _area(reference)
    return [
        item
        for item in items
        if abs(_area(item) - reference_area) <= SIZE_TOLERANCE * reference_area
    ]


def select_all_on_layer(
    reference: DocItem, items: Sequence[DocItem]
) -> list[DocItem]:
    """The items on the reference's layer."""
    layer = reference.get_ancestor_by_type(Layer)
    return [
        item for item in items if item.get_ancestor_by_type(Layer) is layer
    ]

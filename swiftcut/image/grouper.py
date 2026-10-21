"""
Groups a flat set of imported paths into pieces, for files that carry
no structure of their own (a DXF of loose paths, a traced logo).

A closed path inside no other closed path is a piece's outline. The
piece holds every path inside that outline: the outline and the
closed paths directly inside it in the outline's own layer and color
are its boundary (outline and holes, which are cut); the rest is
interior detail (artwork). Paths inside no outline gather into pieces
by proximity.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

import numpy as np
from raygeo.geo.shape.polygon import get_polygon_area, is_point_inside_polygon
from raygeo.geo.types import Point, Polygon, Rect

from .import_tree import PathNode

_FLATNESS = 0.005
_GAP_RATIO = 0.02
_MIN_GAP_MM = 1.0
_CHUNK = 256


@dataclass
class Piece:
    """
    One piece of a drawing: its boundary (the outline and its holes,
    which are cut) and its interior detail (artwork), each in input
    order.
    """

    boundary: list[PathNode] = field(default_factory=list)
    interior: list[PathNode] = field(default_factory=list)


def group_pieces(
    paths: Sequence[PathNode],
    unit_to_mm: float = 1.0,
    drawing_bbox: Rect | None = None,
) -> list[Piece]:
    """
    Groups the paths into pieces, in the drawing order of each piece's
    first path. Every path lands in exactly one piece.

    drawing_bbox is the drawing's (x, y, width, height) in native
    units; it defaults to the paths' union box. It sets the proximity
    gap for paths inside no outline: 2% of its larger side, at least
    1 mm (unit_to_mm converts native units to millimetres).
    """
    if not paths:
        return []
    boxes = np.array([p.geometry.rect() for p in paths], dtype=float)
    span = _span(boxes, drawing_bbox)
    eps = 1e-9 * span
    outlines = [_outline(p) if p.closed else [] for p in paths]
    closed = np.array([i for i, o in enumerate(outlines) if o], dtype=int)
    sizes = np.array([_size(o) for o in outlines])
    container = np.full(len(paths), -1)
    pairs = _container_pairs(closed, boxes, sizes, eps)
    points = {i: outlines[i][0][0] for i in closed.tolist()}
    _smallest_holders(pairs, points, outlines, sizes, container)
    owner = _owners(closed, container, sizes)
    _hold_open_paths(paths, owner, boxes, outlines, sizes, eps)
    loose = np.flatnonzero(owner < 0)
    gap = max(_GAP_RATIO * span, _MIN_GAP_MM / unit_to_mm)
    owner[loose] = len(paths) + np.array(_clusters(boxes[loose], gap))
    return _pieces(paths, owner, container)


def _span(boxes: np.ndarray, drawing_bbox: Rect | None) -> float:
    """The larger side of the drawing box, or of the paths' union."""
    if drawing_bbox is not None:
        return float(max(drawing_bbox[2], drawing_bbox[3]))
    lo = boxes[:, :2].min(axis=0)
    hi = boxes[:, 2:].max(axis=0)
    return float(max(hi - lo))


def _outline(path: PathNode) -> list[Polygon]:
    """A closed path's contours as polygons, flattened to its size."""
    x0, y0, x1, y1 = path.geometry.rect()
    tolerance = _FLATNESS * max(x1 - x0, y1 - y0) or _FLATNESS
    return path.geometry.to_polygons(tolerance)


def _size(outline: list[Polygon]) -> float:
    """The area of an outline's largest contour."""
    return max(
        (abs(get_polygon_area(p)) for p in outline if len(p) >= 3),
        default=0.0,
    )


def _holds(outline: list[Polygon], point: Point) -> bool:
    """Whether the point lies inside any contour of the outline."""
    return any(
        is_point_inside_polygon(point, p) for p in outline if len(p) >= 3
    )


def _within(
    inner: np.ndarray, outer: np.ndarray, eps: float
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """
    The pairs (i, j) where box inner[i] lies within box outer[j],
    boxes as (x0, y0, x1, y1) rows, in chunks of rows to bound memory.
    """
    for start in range(0, len(inner), _CHUNK):
        a = inner[start : start + _CHUNK, None, :]
        hit = (
            (outer[:, 0] <= a[..., 0] + eps)
            & (outer[:, 1] <= a[..., 1] + eps)
            & (outer[:, 2] >= a[..., 2] - eps)
            & (outer[:, 3] >= a[..., 3] - eps)
        )
        i, j = np.nonzero(hit)
        yield i + start, j


def _container_pairs(
    closed: np.ndarray, boxes: np.ndarray, sizes: np.ndarray, eps: float
) -> Iterator[tuple[int, int]]:
    """
    The pairs (i, j) of closed paths where j may contain i: i's box
    lies within j's and j is larger. The box test keeps an outline
    whose box centre falls in a hole from becoming that hole's child.
    """
    for i, j in _within(boxes[closed], boxes[closed], eps):
        inner, outer = closed[i], closed[j]
        keep = sizes[outer] > sizes[inner]
        yield from zip(inner[keep].tolist(), outer[keep].tolist())


def _point_pairs(
    points: dict[int, Point],
    roots: np.ndarray,
    boxes: np.ndarray,
    eps: float,
) -> Iterator[tuple[int, int]]:
    """The pairs (i, j) where outline j's box holds path i's point."""
    order = np.array(list(points), dtype=int)
    corners = np.array(
        [(*points[i], *points[i]) for i in order.tolist()], dtype=float
    ).reshape(-1, 4)
    for i, j in _within(corners, boxes[roots], eps):
        yield from zip(order[i].tolist(), roots[j].tolist())


def _smallest_holders(
    pairs: Iterator[tuple[int, int]],
    points: dict[int, Point],
    outlines: list[list[Polygon]],
    sizes: np.ndarray,
    holder: np.ndarray,
) -> None:
    """
    For each candidate pair (i, j), makes j the holder of path i when
    j's outline holds i's point and j is smaller than i's holder yet.
    A closed path's point is its first vertex: it lies on the path, so
    the test is exact for paths that do not cross.
    """
    for i, j in pairs:
        best = holder[i]
        if best >= 0 and sizes[best] <= sizes[j]:
            continue
        if _holds(outlines[j], points[i]):
            holder[i] = j


def _owners(
    closed: np.ndarray, container: np.ndarray, sizes: np.ndarray
) -> np.ndarray:
    """
    For each closed path, the outline of its piece: its outermost
    container, or itself when nothing contains it; -1 for the rest.
    """
    owner = np.full(len(container), -1)
    for i in closed[np.argsort(-sizes[closed], kind="stable")].tolist():
        parent = container[i]
        owner[i] = i if parent < 0 else owner[parent]
    return owner


def _hold_open_paths(
    paths: Sequence[PathNode],
    owner: np.ndarray,
    boxes: np.ndarray,
    outlines: list[list[Polygon]],
    sizes: np.ndarray,
    eps: float,
) -> None:
    """
    Gives each path without an owner (the open ones) to the smallest
    outline holding its midpoint, or, failing that, its first vertex.
    """
    roots = np.flatnonzero(owner == np.arange(len(owner)))
    probes = {i: _probes(paths[i]) for i in np.flatnonzero(owner < 0).tolist()}
    for k in range(2):
        points = {
            i: probe[k]
            for i, probe in probes.items()
            if owner[i] < 0 and len(probe) > k
        }
        pairs = _point_pairs(points, roots, boxes, eps)
        _smallest_holders(pairs, points, outlines, sizes, owner)


def _probes(path: PathNode) -> tuple[Point, ...]:
    """A path's midpoint (halfway along it) and first vertex."""
    geometry = path.geometry
    half = geometry.distance() / 2
    found = geometry.get_positions_at_distances([half, 0.0])
    return tuple(point for _segment, _t, point in found)


def _clusters(boxes: np.ndarray, gap: float) -> list[int]:
    """
    A cluster label per box: boxes closer than the gap share one,
    transitively.
    """
    parent = list(range(len(boxes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for start in range(0, len(boxes), _CHUNK):
        a = boxes[start : start + _CHUNK, None, :]
        dx = np.maximum(boxes[:, 0] - a[..., 2], a[..., 0] - boxes[:, 2])
        dy = np.maximum(boxes[:, 1] - a[..., 3], a[..., 1] - boxes[:, 3])
        near = np.hypot(np.maximum(dx, 0.0), np.maximum(dy, 0.0)) < gap
        i, j = np.nonzero(near)
        for p, q in zip((i + start).tolist(), j.tolist()):
            parent[find(p)] = find(q)
    return [find(i) for i in range(len(boxes))]


def _pieces(
    paths: Sequence[PathNode], owner: np.ndarray, container: np.ndarray
) -> list[Piece]:
    """
    The pieces by owner, in drawing order of their first path. In an
    outline's piece, the boundary is the outline and its direct
    children in the outline's layer and color; everything else is
    interior. A loose cluster is all boundary.
    """
    pieces: dict[int, Piece] = {}
    for i, path in enumerate(paths):
        key = int(owner[i])
        piece = pieces.setdefault(key, Piece())
        if _is_boundary(paths, i, key, container):
            piece.boundary.append(path)
        else:
            piece.interior.append(path)
    return list(pieces.values())


def _is_boundary(
    paths: Sequence[PathNode], i: int, key: int, container: np.ndarray
) -> bool:
    """
    Whether path i is boundary in the piece of owner key: a loose
    cluster's path, the outline itself, or a direct child of the
    outline in its source layer and color.
    """
    if key >= len(paths) or key == i:
        return True
    outline, path = paths[key], paths[i]
    return (
        container[i] == key
        and path.source_layer == outline.source_layer
        and path.color == outline.color
    )

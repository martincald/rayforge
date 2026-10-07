"""
Placement: where a new piece goes among the pieces already on the bed.

The search tries grid positions around a target, nearest first, takes
the first one where the piece keeps a clearance from every obstacle
and stays inside the bed, then slides the piece toward the target
until it touches. Pure numpy and raygeo on plain point lists, so it
can run in a worker process.

Outlines are outer outlines of three or more points, in world mm
(origin bottom-left, Y up), as open or closed rings. Every outline
counts as filled, so a piece never goes inside another piece's
outline; one without area, such as a line, is not seen. Outlines are
taken as exact: the tolerance they were polygonized with is the
caller's to allow for.
"""

import math
from collections.abc import Sequence
from typing import NamedTuple

import numpy as np
from raygeo.geo.shape.polygon import (
    JoinStyle,
    do_polygons_intersect,
    get_polygon_convex_hull,
    is_polygon_clockwise,
    is_polygon_convex,
    offset_polygon,
    translate_polygon,
)

Point = tuple[float, float]
Polygon = Sequence[Point]
Rect = tuple[float, float, float, float]

#: The grid step is a quarter of the piece's smaller side, but no
#: less than this, in mm.
MIN_STEP_MM = 2.0
#: At most this many grid positions get an exact test per call. The
#: 40-piece benchmark needs at most 52; a bed-sized comb of 900
#: vertices, where nothing fits, takes about 0.5 ms per test.
MAX_TESTS = 1000
# Round joins sag between their vertices by about 0.2 % of the offset;
# growing by 1 % more keeps the true gap at or above the clearance.
_ROUND_JOIN_GROWTH = 1.01
# The slide toward the target stops this close to contact, in mm.
_SLIDE_TOLERANCE_MM = 0.01
# How many of the piece's vertices are tested for lying inside an
# obstacle, which proves an overlap without the exact test.
_SAMPLES = 8
# Float slack in mm, so a piece scaled to the bed's size still fits.
_EPSILON_MM = 1e-6


class Placement(NamedTuple):
    """The move that places the piece, and whether it fits there."""

    dx: float
    dy: float
    fits: bool


def find_position(
    piece: Sequence[Polygon],
    obstacles: Sequence[Polygon],
    bed: Rect,
    target: Point | None = None,
    clearance: float = 1.0,
    max_tests: int = MAX_TESTS,
) -> Placement:
    """
    Where to move a piece so it sits closest to the target without
    overlapping anything.

    Candidates lie on a grid anchored at the target, a quarter of the
    piece's smaller side apart (MIN_STEP_MM at least), plus the
    positions flush with the bed edges. They are tried nearest first;
    ties go to the lower, then the left one. A position is free when
    the piece's outlines keep `clearance` from every obstacle and its
    bounding box stays inside the bed. The first free position then
    slides toward the target until it touches: along the line to it,
    then along x, then along y. Most positions are decided without an
    exact outline test; after `max_tests` exact tests the nearest
    position known to be free that way is taken, if there is one.

    Args:
        piece: Outer outlines of the piece, moved as one.
        obstacles: Outer outlines already on the bed.
        bed: The bed as (x, y, width, height).
        target: Where the centre of the piece's bounding box should
            go; the bed centre if None.
        clearance: Minimum gap between outlines, in mm.
        max_tests: The most grid positions tested exactly (the slides
            add at most a bisection's worth each).

    Returns:
        The move (dx, dy) and fits=True. If no position is free (or
        none is found within `max_tests`), the move to the target,
        kept inside the bed (centred on an axis where the piece is
        larger than the bed), and fits=False.
    """
    raw = [np.asarray(p, dtype=float) for p in piece]
    x0, y0 = np.min([p.min(axis=0) for p in raw], axis=0)
    x1, y1 = np.max([p.max(axis=0) for p in raw], axis=0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bx, by, bw, bh = bed
    tx, ty = target if target is not None else (bx + bw / 2, by + bh / 2)

    # The range of the piece's centre that keeps it inside the bed.
    lo_x, hi_x = bx + (x1 - x0) / 2, bx + bw - (x1 - x0) / 2
    lo_y, hi_y = by + (y1 - y0) / 2, by + bh - (y1 - y0) / 2
    goal = (_clamp(tx, lo_x, hi_x), _clamp(ty, lo_y, hi_y))
    if lo_x > hi_x + _EPSILON_MM or lo_y > hi_y + _EPSILON_MM:
        return Placement(float(goal[0] - cx), float(goal[1] - cy), False)

    step = max(min(x1 - x0, y1 - y0) / 4, MIN_STEP_MM)
    off_x = _offsets(tx, lo_x, hi_x, step)
    off_y = _offsets(ty, lo_y, hi_y, step)
    xs, ys = tx + off_x, ty + off_y
    search = _Search(raw, (cx, cy), obstacles, clearance)
    blocked, unknown = search.classify(xs, ys)

    # Exact tests only for the undecided positions nearer than the
    # nearest one known to be free.
    dist = off_y[:, None] ** 2 + off_x[None, :] ** 2
    clear = ~blocked & ~unknown
    todo = ~blocked
    if clear.any():
        todo &= dist <= dist[clear].min()
    # Past max_tests, only the positions known to be free are left.
    rows, cols = np.nonzero(todo)
    tests = 0
    for k in np.lexsort((off_x[cols], off_y[rows], dist[rows, cols])):
        row, col = rows[k], cols[k]
        if clear[row, col]:
            break
        if tests < max_tests:
            tests += 1
            if search.is_free(xs[col], ys[row]):
                break
    else:
        return Placement(float(goal[0] - cx), float(goal[1] - cy), False)

    x, y = search.slide((xs[col], ys[row]), goal)
    x, y = search.slide((x, y), (goal[0], y))
    x, y = search.slide((x, y), (x, goal[1]))
    return Placement(float(x - cx), float(y - cy), True)


class _Search:
    """The piece grown by the clearance, and the outlines it must miss."""

    def __init__(
        self,
        raw: list[np.ndarray],
        centre: Point,
        obstacles: Sequence[Polygon],
        clearance: float,
    ):
        self.piece = [_points(p) for p in raw]
        self.centre = centre
        grow = clearance * _ROUND_JOIN_GROWTH
        self.grown = [
            g
            for p in self.piece
            for g in offset_polygon(p, grow, JoinStyle.ROUND)
        ]
        grown = np.concatenate(self.grown)
        self.grown_box = (*grown.min(axis=0), *grown.max(axis=0))
        self.grown_boxes = np.array(
            [(*np.min(g, axis=0), *np.max(g, axis=0)) for g in self.grown]
        )
        self.obstacles = [_points(o) for o in obstacles]
        self.boxes = np.array(
            [(*np.min(o, axis=0), *np.max(o, axis=0)) for o in self.obstacles]
        ).reshape(-1, 4)

    def classify(
        self, xs: np.ndarray, ys: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Sort the grid of piece centres (xs, ys) into blocked and
        unknown masks without exact tests; the rest is free.

        Outside the Minkowski sum of an obstacle's hull and the grown
        piece's hull, the two cannot meet. Inside it they surely do
        when both are convex, or when a piece vertex lies inside the
        obstacle.
        """
        blocked = np.zeros((len(ys), len(xs)), dtype=bool)
        unknown = np.zeros_like(blocked)
        centre = np.array(self.centre)
        reach = centre - _hull([v for g in self.grown for v in g])
        hull = _hull([v for p in self.piece for v in p]) - centre
        pick = np.linspace(0, len(hull), _SAMPLES, endpoint=False)
        samples = hull[np.unique(pick.astype(int))]
        convex = len(self.piece) == 1 and is_polygon_convex(self.piece[0])
        for obstacle in self.obstacles:
            outline = np.array(obstacle)
            nfp = _minkowski(_hull(obstacle), reach)
            rows = _span(ys, nfp[:, 1])
            cols = _span(xs, nfp[:, 0])
            if rows.start == rows.stop or cols.start == cols.stop:
                continue
            hit = _inside(nfp, xs[cols], ys[rows])
            if convex and is_polygon_convex(obstacle):
                blocked[rows, cols] |= hit
                continue
            sure = np.zeros_like(hit)
            for vertex in samples:
                sure |= _inside(outline - vertex, xs[cols], ys[rows])
            blocked[rows, cols] |= sure
            unknown[rows, cols] |= hit & ~sure
        return blocked, unknown & ~blocked

    def is_free(self, x: float, y: float) -> bool:
        """Whether the piece centred at (x, y) misses every obstacle."""
        dx, dy = x - self.centre[0], y - self.centre[1]
        gx0, gy0, gx1, gy1 = self.grown_box
        b = self.boxes
        near = np.flatnonzero(
            (b[:, 0] < gx1 + dx)
            & (b[:, 2] > gx0 + dx)
            & (b[:, 1] < gy1 + dy)
            & (b[:, 3] > gy0 + dy)
        )
        if not near.size:
            return True
        # Exact tests only for the outline pairs whose boxes overlap.
        g = self.grown_boxes[:, None, :] + (dx, dy, dx, dy)
        b = b[near]
        outlines, hits = np.nonzero(
            (b[:, 0] < g[..., 2])
            & (b[:, 2] > g[..., 0])
            & (b[:, 1] < g[..., 3])
            & (b[:, 3] > g[..., 1])
        )
        return not any(
            do_polygons_intersect(
                translate_polygon(self.grown[i], dx, dy),
                self.obstacles[near[j]],
            )
            for i, j in zip(outlines, hits)
        )

    def slide(self, start: Point, goal: Point) -> Point:
        """
        Move the piece from a free start toward the goal until it
        touches, by bisection on the segment between them.
        """
        if self.is_free(*goal):
            return goal
        (x0, y0), (x1, y1) = start, goal
        length = math.hypot(x1 - x0, y1 - y0)
        lo, hi = 0.0, 1.0
        while (hi - lo) * length > _SLIDE_TOLERANCE_MM:
            mid = (lo + hi) / 2
            if self.is_free(x0 + mid * (x1 - x0), y0 + mid * (y1 - y0)):
                lo = mid
            else:
                hi = mid
        return x0 + lo * (x1 - x0), y0 + lo * (y1 - y0)


def _points(polygon: Polygon) -> list[Point]:
    """A polygon as the list of float tuples raygeo takes fastest."""
    return [(float(x), float(y)) for x, y in polygon]


def _clamp(value: float, lo: float, hi: float) -> float:
    """The value limited to [lo, hi]; the middle if the range is empty."""
    if lo > hi:
        return (lo + hi) / 2
    return min(max(value, lo), hi)


def _offsets(target: float, lo: float, hi: float, step: float) -> np.ndarray:
    """
    Sorted grid offsets from the target on one axis: the multiples of
    step that land in [lo, hi], and the bounds themselves.
    """
    k = np.arange(math.ceil((lo - target) / step), (hi - target) // step + 1)
    offsets = np.clip(k * step, lo - target, hi - target)
    return np.unique(np.concatenate((offsets, (lo - target, hi - target))))


def _span(axis: np.ndarray, values: np.ndarray) -> slice:
    """The slice of a sorted axis that lies within the values' range."""
    return slice(
        int(np.searchsorted(axis, values.min())),
        int(np.searchsorted(axis, values.max(), side="right")),
    )


def _hull(points: list[Point]) -> np.ndarray:
    """The convex hull of the points, counter-clockwise."""
    hull = get_polygon_convex_hull(points)
    if is_polygon_clockwise(hull):
        hull = hull[::-1]
    return np.array(hull)


def _minkowski(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    The Minkowski sum of two counter-clockwise convex polygons: their
    edges merged by angle, from the sum of their lowest vertices.
    """
    starts, edges = [], []
    for polygon in (a, b):
        lowest = np.lexsort((polygon[:, 0], polygon[:, 1]))[0]
        polygon = np.roll(polygon, -lowest, axis=0)
        starts.append(polygon[0])
        edges.append(np.roll(polygon, -1, axis=0) - polygon)
    edge = np.concatenate(edges)
    angle = np.arctan2(edge[:, 1], edge[:, 0]) % (2 * np.pi)
    edge = edge[np.argsort(angle, kind="stable")]
    walk = np.cumsum(edge[:-1], axis=0)
    return starts[0] + starts[1] + np.vstack(((0.0, 0.0), walk))


def _inside(polygon: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """
    Which points of the grid xs by ys lie inside the polygon (even-odd
    rule), as a (len(ys), len(xs)) mask: one scanline per grid row.
    """
    a = polygon
    b = np.roll(polygon, -1, axis=0)
    rows, edges = np.nonzero(
        (a[:, 1] <= ys[:, None]) != (b[:, 1] <= ys[:, None])
    )
    ya, yb = a[edges, 1], b[edges, 1]
    xa, xb = a[edges, 0], b[edges, 0]
    x = xa + (ys[rows] - ya) / (yb - ya) * (xb - xa)
    # A crossing toggles every grid point to its right.
    width = len(xs) + 1
    cols = np.searchsorted(xs, x, side="right")
    toggles = np.bincount(rows * width + cols, minlength=len(ys) * width)
    toggles = toggles.reshape(len(ys), width)[:, :-1]
    return (np.cumsum(toggles, axis=1) & 1).astype(bool)

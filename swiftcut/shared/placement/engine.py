"""
Placement: where a new piece goes among the pieces already on the bed.

The search tries grid positions around a target, nearest first, takes
the first one where the piece keeps a clearance from every obstacle
and stays inside the bed, then slides the piece toward the target
until it touches. A caller may rank the positions by its own cost
instead (see find_position). Pure numpy and raygeo on plain point
lists, so it can run in a worker process.

Outlines are outer outlines of three or more points, in world mm
(origin bottom-left, Y up), as open or closed rings. Every outline
counts as filled, so a piece never goes inside another piece's
outline; one without area, such as a line, is not seen. Outlines are
taken as exact: the tolerance they were polygonized with is the
caller's to allow for.

Given straight edges (see Flush), a last phase moves the piece so its
straight edges lie exactly along nearby straight edges of others,
where touching outlines can then share one cut.
"""

import math
from collections.abc import Callable, Sequence
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
#: Costs of a position, given the arrays of its x and y (see
#: find_position).
Cost = Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, ...]]
#: A straight edge as its start and end points.
Edge = tuple[Point, Point]

#: The grid step is a quarter of the piece's smaller side, but no
#: less than this, in mm.
MIN_STEP_MM = 2.0
#: At most this many grid positions get an exact test per call. The
#: 40-piece benchmark needs at most 73; a bed-sized comb of 900
#: vertices, where nothing fits, takes about 0.5 ms per test.
MAX_TESTS = 1000
# Round joins sag between their vertices by about 0.2 % of the offset;
# growing by 1 % more keeps the true gap at or above the clearance.
_ROUND_JOIN_GROWTH = 1.01
# The slide toward the target stops this close to contact, in mm.
_SLIDE_TOLERANCE_MM = 0.01
# The pattern search for a lower cost (see find_position) starts at
# half the grid step and ends at this step, in mm.
_REFINE_MM = 0.05
# The directions it steps in: eight, 45 degrees apart.
_DIRECTIONS = [(math.cos(a), math.sin(a)) for a in np.arange(8) * math.pi / 4]
# How many of the piece's vertices are tested for lying inside an
# obstacle, which proves an overlap without the exact test.
_SAMPLES = 8
# Float slack in mm, so a piece scaled to the bed's size still fits.
_EPSILON_MM = 1e-6
# At most this many snap moves (see find_position) get an exact test
# per call. They are tried best first and most are free: the 40-piece
# benchmark at gap 0 needs at most 4, where a hundred slivers each
# blocking the next (test_placement) would take 203 with every line
# kept.
_SNAP_TESTS = 64
# Flush edges are paired (see _Pairs) only among the _FLUSH_EDGES
# longest of the piece and of the others near it, and only the
# _FLUSH_PAIRS nearest pairs are kept: a flattened curve has thousands
# of edges, each nearly parallel to tens of others, and uncapped a
# 2000-gon among four others takes 6.7 GB and 89 s (test_placement).
_FLUSH_EDGES = 256
_FLUSH_PAIRS = 2048
# Snap moves are made from the _SNAP_LINES nearest lines to lie flush
# along, a farther line being more often blocked by what lies nearer:
# at most 137 moves with their corners, each measured on the pairs
# above, so a call's arrays stay within some 300,000 cells.
_SNAP_LINES = 16


class Placement(NamedTuple):
    """The move that places the piece, and whether it fits there."""

    dx: float
    dy: float
    fits: bool


class Flush(NamedTuple):
    """Straight edges for the piece to lie flush along (see find_position)."""

    #: The piece's straight edges, where its outlines are.
    piece: Sequence[Edge]
    #: The straight edges it may lie flush along.
    others: Sequence[Edge]
    #: Edges this close are flush, in mm.
    tolerance: float


def find_position(
    piece: Sequence[Polygon],
    obstacles: Sequence[Polygon],
    bed: Rect,
    target: Point | None = None,
    clearance: float = 1.0,
    max_tests: int = MAX_TESTS,
    cost: Cost | None = None,
    flush: Flush | None = None,
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

    With a cost, the positions are tried lowest cost first instead,
    ties going nearest the target (past `max_tests`, the lowest cost
    one known to be free is taken). A slide is then kept only if it
    does not raise the cost, and a pattern search moves the piece on
    while that lowers the cost or, at the same cost, brings it nearer
    the target.

    With flush edges, a last phase lays the piece's straight edges
    along others. Each pair of a piece edge and another edge that are
    parallel within the tolerance over the piece edge's length, whose
    projections overlap by more than it, and whose offset (from the
    piece edge's middle to the other's line) is at most the grid step
    gives a move along the other's normal that puts the piece edge on
    its line; each two such moves with normals not parallel give the
    move that does both, into a corner. Only the nearest lines make
    moves, and moves past a grid step on either axis are dropped, so
    the phase stays small however many edges there are (see
    _FLUSH_EDGES and _SNAP_LINES). They are tried in order of the costs,
    then of how long the piece's edges lie flush along others (see
    shared_length), longest first, then of nearness to the target;
    the first where the piece is free and inside the bed wins if it
    comes before the position itself (at most _SNAP_TESTS are
    tested). A move into contact takes the piece into the pile, so it
    does not raise a pile's cost, and a position already flush within
    the tolerance moves only where that does better.

    Args:
        piece: Outer outlines of the piece, moved as one.
        obstacles: Outer outlines already on the bed.
        bed: The bed as (x, y, width, height).
        target: Where the centre of the piece's bounding box should
            go; the bed centre if None.
        clearance: Minimum gap between outlines, in mm.
        max_tests: The most grid positions tested exactly (the slides
            and the pattern search are not counted).
        cost: The costs of centring the piece's bounding box on
            (x, y), for arrays x and y that broadcast together,
            compared in order; None tries the positions nearest the
            target first.
        flush: The piece's straight edges, the edges it may lie flush
            along and how close is flush; None skips the last phase.

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

    # Exact tests only for the undecided positions that come no later
    # than the first one known to be free.
    dist = off_y[:, None] ** 2 + off_x[None, :] ** 2
    costs = []
    if cost is not None:
        costs = [
            np.broadcast_to(c, dist.shape)
            for c in cost(xs[None, :], ys[:, None])
        ]
    first = costs[0] if costs else dist
    clear = ~blocked & ~unknown
    todo = ~blocked
    if clear.any():
        todo &= first <= first[clear].min()
    # Past max_tests, only the positions known to be free are left.
    rows, cols = np.nonzero(todo)
    tests = 0
    keys = (off_x[cols], off_y[rows], dist[rows, cols])
    keys += tuple(c[rows, cols] for c in reversed(costs))
    for k in np.lexsort(keys):
        row, col = rows[k], cols[k]
        if clear[row, col]:
            break
        if tests < max_tests:
            tests += 1
            if search.is_free(xs[col], ys[row]):
                break
    else:
        return Placement(float(goal[0] - cx), float(goal[1] - cy), False)

    x, y = xs[col], ys[row]
    bounds = (lo_x, lo_y, hi_x, hi_y)
    if cost is None:
        x, y = search.slide((x, y), goal)
        x, y = search.slide((x, y), (goal[0], y))
        x, y = search.slide((x, y), (x, goal[1]))
    else:

        def key(x: float, y: float) -> tuple[float, ...]:
            """The position's costs, then its squared distance to target."""
            return (*map(float, cost(x, y)), (x - tx) ** 2 + (y - ty) ** 2)

        for along in range(3):
            # Along the line to the goal, then along x, then along y.
            end = (goal, (goal[0], y), (x, goal[1]))[along]
            moved = search.slide((x, y), end)
            if key(*moved) <= key(x, y):
                x, y = moved
        x, y = search.refine((x, y), key, step, bounds)
    if flush is not None:

        def keys(x: np.ndarray, y: np.ndarray, shared: np.ndarray) -> tuple:
            """
            The keys of positions whose straight edges lie flush along
            `shared` mm: their costs, the shared length, longest
            first, then their squared distance to the target.
            """
            costs = () if cost is None else cost(x, y)
            return (*costs, -shared, (x - tx) ** 2 + (y - ty) ** 2)

        x, y = _snap(search, (x, y), flush, keys, step, bounds)
    return Placement(float(x - cx), float(y - cy), True)


def shared_length(
    piece: Sequence[Edge], others: Sequence[Edge], tolerance: float
) -> float:
    """
    How long the piece's straight edges lie flush along the others:
    the sum, over every pair of a piece edge whose end points both lie
    within the tolerance of another edge's line and that other edge,
    of their overlap along it, where that is longer than the
    tolerance.
    """
    edges = _edges(piece)
    near = _near(edges, _edges(others), tolerance)
    pairs = _Pairs(edges, near, tolerance, 0.0)
    return float(pairs.shared(np.zeros((1, 2)))[0])


def _snap(
    search: "_Search",
    start: Point,
    flush: Flush,
    keys: Callable[..., tuple],
    step: float,
    bounds: tuple[float, float, float, float],
) -> Point:
    """
    The last phase of find_position: the best free snap move from a
    free start, within bounds (x0, y0, x1, y1) and _EPSILON_MM, if it
    comes before the start by keys(x, y, shared length); else the
    start.
    """
    x, y = start
    piece = _edges(flush.piece) + (x - search.centre[0], y - search.centre[1])
    tolerance = flush.tolerance
    # Every move stays within a step on each axis, so these are all
    # the edges the moved piece's edges can lie flush along.
    near = _near(piece, _edges(flush.others), step + tolerance)
    pairs = _Pairs(piece, near, tolerance, math.hypot(step, step))
    offset = (pairs.sa + pairs.sb) / 2
    pick = (
        (np.abs(pairs.sb - pairs.sa) <= tolerance)
        & (pairs.overlap(np.zeros((1, 2)))[0] > tolerance)
        & (np.abs(offset) <= step)
    )
    if not pick.any():
        return start
    normal, offset = pairs.normal[pick], offset[pick]
    # One move per line, the first pair's; the pairs are nearest
    # first, and so are the lines kept.
    _, first = np.unique(
        np.round(np.column_stack((normal, offset)), 9),
        axis=0,
        return_index=True,
    )
    first = np.sort(first)[:_SNAP_LINES]
    normal, offset = normal[first], offset[first]
    a, b = np.triu_indices(len(normal), 1)
    (ax, ay), (bx, by) = normal[a].T, normal[b].T
    det = ax * by - ay * bx
    with np.errstate(divide="ignore", invalid="ignore"):
        # The move m with m . normal = -offset for both lines.
        corners = np.column_stack(
            (
                (offset[b] * ay - offset[a] * by) / det,
                (offset[a] * bx - offset[b] * ax) / det,
            )
        )
    moves = np.concatenate(
        (np.zeros((1, 2)), -offset[:, None] * normal, corners)
    )
    moves = moves[np.all(np.abs(moves) <= step, axis=1)]
    xs, ys = x + moves[:, 0], y + moves[:, 1]
    shared = pairs.shared(moves)
    key = [np.broadcast_to(k, xs.shape) for k in keys(xs, ys, shared)]
    x0, y0, x1, y1 = bounds
    inside = (
        (xs >= x0 - _EPSILON_MM)
        & (xs <= x1 + _EPSILON_MM)
        & (ys >= y0 - _EPSILON_MM)
        & (ys <= y1 + _EPSILON_MM)
    )
    tests = 0
    # The start is the first move; a move tied with it comes after.
    for k in np.lexsort(key[::-1]):
        if k == 0 or tests == _SNAP_TESTS:
            break
        if inside[k]:
            tests += 1
            if search.is_free(xs[k], ys[k]):
                return xs[k], ys[k]
    return start


class _Pairs:
    """
    The pairs of a piece edge and another edge that can lie flush once
    the piece moves at most `reach` mm: parallel within twice the
    tolerance over the piece edge's length, its ends within reach of
    the tolerance off the other's line, and overlapping along it by
    more than the tolerance less reach. They are measured from the
    other edge's start along it and along its normal, nearest first
    (by the piece edge's middle), and only the _FLUSH_PAIRS nearest
    pairs of the _FLUSH_EDGES longest edges each side are kept.
    """

    def __init__(
        self,
        piece: np.ndarray,
        others: np.ndarray,
        tolerance: float,
        reach: float,
    ):
        piece = _longest(piece, _FLUSH_EDGES)
        others = _longest(others, _FLUSH_EDGES)
        start, end = others[:, 0], others[:, 1]
        length = np.hypot(*(end - start).T)
        along = (end - start) / length[:, None]
        normal = np.column_stack((-along[:, 1], along[:, 0]))
        a = ((piece[:, None, 0] - start) * normal).sum(-1)
        b = ((piece[:, None, 1] - start) * normal).sum(-1)
        ta = ((piece[:, None, 0] - start) * along).sum(-1)
        tb = ((piece[:, None, 1] - start) * along).sum(-1)
        overlap = np.minimum(np.maximum(ta, tb), length) - np.maximum(
            np.minimum(ta, tb), 0
        )
        i, j = np.nonzero(
            (np.abs(b - a) <= 2 * tolerance)
            & (np.abs(a) <= reach + tolerance)
            & (np.abs(b) <= reach + tolerance)
            & (overlap > tolerance - reach)
        )
        nearest = np.argsort(np.abs(a + b)[i, j], kind="stable")
        i, j = i[nearest[:_FLUSH_PAIRS]], j[nearest[:_FLUSH_PAIRS]]
        #: Where the piece edges' ends lie off the other edges' lines.
        self.sa, self.sb = a[i, j], b[i, j]
        #: Where they lie along the other edges.
        self.ta, self.tb = ta[i, j], tb[i, j]
        self.length = length[j]
        self.along, self.normal = along[j], normal[j]
        self.tolerance = tolerance

    def overlap(self, moves: np.ndarray) -> np.ndarray:
        """Each pair's overlap along the other edge, for each move."""
        t = moves @ self.along.T
        ta, tb = self.ta + t, self.tb + t
        return np.minimum(np.maximum(ta, tb), self.length) - np.maximum(
            np.minimum(ta, tb), 0
        )

    def shared(self, moves: np.ndarray) -> np.ndarray:
        """The piece's shared length (see shared_length) per move."""
        s = moves @ self.normal.T
        overlap = self.overlap(moves)
        flush = (
            (np.abs(self.sa + s) <= self.tolerance)
            & (np.abs(self.sb + s) <= self.tolerance)
            & (overlap > self.tolerance)
        )
        return np.where(flush, overlap, 0.0).sum(axis=1)


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

    def refine(
        self,
        start: Point,
        key: Callable[[float, float], tuple[float, ...]],
        step: float,
        bounds: tuple[float, float, float, float],
    ) -> Point:
        """
        Pattern search from a free start: step in eight directions to
        a free position of lower key within bounds (x0, y0, x1, y1),
        halving the step whenever there is none, down to _REFINE_MM.
        """
        x0, y0, x1, y1 = bounds
        x, y = start
        best = key(x, y)
        step /= 2
        while step >= _REFINE_MM:
            for ux, uy in _DIRECTIONS:
                nx, ny = x + ux * step, y + uy * step
                if not (x0 <= nx <= x1 and y0 <= ny <= y1):
                    continue
                k = key(nx, ny)
                if k < best and self.is_free(nx, ny):
                    x, y, best = nx, ny, k
                    break
            else:
                step /= 2
        return x, y


def _edges(edges: Sequence[Edge]) -> np.ndarray:
    """Edges as an (n, 2, 2) array of their start and end points."""
    return np.asarray(edges, dtype=float).reshape(-1, 2, 2)


def _longest(edges: np.ndarray, count: int) -> np.ndarray:
    """The count longest edges, or all if there are no more."""
    if len(edges) <= count:
        return edges
    length = np.hypot(*(edges[:, 1] - edges[:, 0]).T)
    return edges[np.argsort(-length, kind="stable")[:count]]


def _near(piece: np.ndarray, others: np.ndarray, reach: float) -> np.ndarray:
    """The others whose boxes come within reach of the piece edges' box."""
    if not len(piece):
        return others[:0]
    lo = piece.min(axis=(0, 1)) - reach
    hi = piece.max(axis=(0, 1)) + reach
    return others[
        np.all(others.max(axis=1) >= lo, axis=1)
        & np.all(others.min(axis=1) <= hi, axis=1)
    ]


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

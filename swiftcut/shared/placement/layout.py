"""
Layout: several pieces placed one after another into a tight pile,
each where the box around the pile grows least, turned by the quarter
turn that grows it least.

Pure numpy and raygeo on plain data, like the engine it calls, so it
can run in a worker process.
"""

import math
from collections.abc import Hashable, Iterator, Sequence
from typing import TYPE_CHECKING, NamedTuple

import numpy as np

from .engine import Point, Polygon, Rect, find_position

if TYPE_CHECKING:
    from ..tasker.progress import ProgressContext

#: The turns a piece is tried in, counter-clockwise in degrees.
ANGLES = (0.0, 90.0, 180.0, 270.0)
# Float slack in mm: a turn must land nearer than this to win over a
# smaller one.
_EPSILON_MM = 1e-6
# A turn whose frame and outlines lie this close to those of a turn
# already tried, in mm, is the same shape. Two polygonizations of one
# curve differ (outlines come within 0.05 mm of their curves), so equal
# points cannot be asked for.
_SAME_SHAPE_MM = 0.1
# How many points along a turn's outlines are checked against another.
_SAME_SHAPE_SAMPLES = 64
# How much the pile box's larger side, squared, weighs against its
# area (see _pile_costs): area alone stretches the pile into a strip.
# Every weight from 1.2 to 3 does about as well on the benchmarks;
# below 1.2 the results jump (docs/auto-layout-notes.md).
_SQUARE_WEIGHT = 2.0

#: A box as (x0, y0, x1, y1), in world mm.
Box = tuple[float, float, float, float]


class Piece(NamedTuple):
    """A piece to place, in world mm."""

    #: Names the piece in the result.
    id: Hashable
    #: Outer outlines, moved as one (see engine.find_position).
    outlines: Sequence[Polygon]
    #: The (x, y, width, height) box that must stay inside the boundary.
    frame: Rect


def arrange(
    proxy: "ProgressContext",
    pieces: Sequence[Piece],
    obstacles: Sequence[Polygon],
    boundary: Rect,
    target: Point,
    clearance: float = 1.0,
) -> dict[Hashable, tuple[float, float, float, bool]]:
    """
    Places the pieces one after another, largest outline area first
    (equal ones in the given order), each with find_position: its
    frame inside the boundary, its outlines `clearance` from the
    obstacles and from the pieces placed before it. The first frame
    goes as close to the target as it fits. Each later one goes where
    the box around the frames placed so far, the pile, grows least:
    by its area and its larger side (see _pile_costs), then by the
    frame's centre nearest the target. Each piece is tried as it is
    and turned 90, 180 and 270 degrees about its frame's centre,
    skipping turns that give an outline already tried; the turn that
    does best by the same order wins, ties going to the smaller turn.
    A piece that fits nowhere stays where it is, an obstacle for every
    other piece: one whose frame is larger than the boundary any way
    up is known from the start, and finding another starts the layout
    over (at most once per piece).

    Args:
        proxy: Takes one progress step per piece (going back when the
            layout starts over), and is asked before each piece
            whether to stop.
        pieces: The pieces to place.
        obstacles: Outer outlines that stay where they are.
        boundary: The (x, y, width, height) every frame stays inside.
        target: Where the pile is centred: the first frame's centre
            goes as close to it as it fits, and it breaks ties.
        clearance: Minimum gap between outlines, in mm.

    Returns:
        For each piece id, (angle, dx, dy, fits): turn the piece by
        angle degrees about the centre of its frame, then move it by
        (dx, dy). A piece that fits nowhere gets (0, 0, 0, False).
        Empty when the proxy says to stop.
    """
    proxy.set_total(len(pieces))
    by_size = sorted(pieces, key=lambda piece: -_area(piece.outlines))
    stay = [piece for piece in by_size if _too_large(piece.frame, boundary)]
    while True:
        placed: dict[Hashable, tuple[float, float, float, bool]] = {
            piece.id: (0.0, 0.0, 0.0, False) for piece in stay
        }
        fixed = list(obstacles)
        for piece in stay:
            fixed.extend(piece.outlines)
        pile: Box | None = None
        for piece in by_size:
            if piece.id in placed:
                continue
            if proxy.is_cancelled():
                return {}
            best = _best_turn(piece, fixed, boundary, target, clearance, pile)
            if best is None:
                stay.append(piece)
                break
            angle, dx, dy, outlines, box = best
            placed[piece.id] = (angle, dx, dy, True)
            fixed.extend((p + (dx, dy)).tolist() for p in outlines)
            pile = box if pile is None else _union(pile, box)
            proxy.set_progress(len(placed))
        else:
            return placed


def _too_large(frame: Rect, boundary: Rect) -> bool:
    """Whether the frame is larger than the boundary any way up."""
    sides, room = sorted(frame[2:]), sorted(boundary[2:])
    return any(side > r + _EPSILON_MM for side, r in zip(sides, room))


def _best_turn(
    piece: Piece,
    obstacles: Sequence[Polygon],
    boundary: Rect,
    target: Point,
    clearance: float,
    pile: Box | None,
) -> tuple[float, float, float, list[np.ndarray], Box] | None:
    """
    The turn of the piece that does best: by the pile's costs with its
    frame added (see _pile_costs; none for the first piece), then by
    its frame centre's distance to the target, ties going to the
    smaller turn. As (angle, dx, dy, turned outlines, frame box); None
    if no turn fits.
    """
    best = None
    for angle, outlines, frame in _turns(piece):
        dx, dy, fits = _place(
            outlines, frame, obstacles, boundary, target, clearance, pile
        )
        if not fits:
            continue
        x, y, w, h = frame
        box = (x + dx, y + dy, x + w + dx, y + h + dy)
        costs = () if pile is None else _pile_costs(pile, *box)
        distance = math.hypot(
            x + w / 2 + dx - target[0], y + h / 2 + dy - target[1]
        )
        score = (*map(float, costs), distance)
        if best is None or _before(score, best[0]):
            best = (score, angle, dx, dy, outlines, box)
    return None if best is None else best[1:]


def _before(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    """Whether a comes before b, compared in order, _EPSILON_MM apart."""
    for x, y in zip(a, b):
        if abs(x - y) > _EPSILON_MM:
            return x < y
    return False


def _turns(piece: Piece) -> Iterator[tuple[float, list[np.ndarray], Rect]]:
    """
    The piece's distinct turns about its frame's centre: the angle,
    the turned outlines and the turned frame.
    """
    x, y, w, h = piece.frame
    centre = np.array((x + w / 2, y + h / 2))
    shapes: list[tuple[np.ndarray, list[np.ndarray]]] = []
    for angle in ANGLES:
        # Quarter turns, so the matrix is exact.
        cos = round(math.cos(math.radians(angle)))
        sin = round(math.sin(math.radians(angle)))
        turn = np.array(((cos, -sin), (sin, cos)), dtype=float)
        outlines = [
            (np.asarray(p, dtype=float) - centre) @ turn.T + centre
            for p in piece.outlines
        ]
        size = np.array((h, w) if sin else (w, h))
        low = centre - size / 2
        # The shape is the frame's size and the outlines within it.
        shape = (size, [p - low for p in outlines])
        if any(_same_shape(shape, seen) for seen in shapes):
            continue
        shapes.append(shape)
        yield angle, outlines, (low[0], low[1], size[0], size[1])


def _same_shape(
    a: tuple[np.ndarray, list[np.ndarray]],
    b: tuple[np.ndarray, list[np.ndarray]],
) -> bool:
    """
    Whether two shapes, each a frame size and the outlines within it,
    lie within _SAME_SHAPE_MM of each other where sampled:
    _SAME_SHAPE_SAMPLES points spread along each set of outlines, to
    the nearest edge of the other.
    """
    (size_a, outlines_a), (size_b, outlines_b) = a, b
    if np.any(np.abs(size_a - size_b) > _SAME_SHAPE_MM):
        return False
    return (
        _distance(_samples(outlines_a), outlines_b) <= _SAME_SHAPE_MM
        and _distance(_samples(outlines_b), outlines_a) <= _SAME_SHAPE_MM
    )


def _edges(outlines: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """The outlines' edges as start points and vectors, closing each."""
    start = np.concatenate(outlines)
    edge = np.concatenate([np.roll(p, -1, axis=0) - p for p in outlines])
    return start, edge


def _samples(outlines: list[np.ndarray]) -> np.ndarray:
    """_SAME_SHAPE_SAMPLES points spread evenly along the outlines."""
    start, edge = _edges(outlines)
    length = np.hypot(edge[:, 0], edge[:, 1])
    ends = np.cumsum(length)
    at = (np.arange(_SAME_SHAPE_SAMPLES) + 0.5) * ends[-1]
    at /= _SAME_SHAPE_SAMPLES
    # The edge each sample falls on, which is never one of length 0.
    k = np.searchsorted(ends, at)
    t = (at - ends[k] + length[k]) / length[k]
    return start[k] + t[:, None] * edge[k]


def _distance(points: np.ndarray, outlines: list[np.ndarray]) -> float:
    """The largest distance from the points to the outlines' edges."""
    start, edge = _edges(outlines)
    # The nearest point of an edge of length 0 is its start.
    squared = np.maximum((edge * edge).sum(-1), 1e-12)
    p = points[:, None, :]
    t = ((p - start) * edge).sum(-1) / squared
    nearest = start + np.clip(t, 0, 1)[..., None] * edge
    return float(np.sqrt(((p - nearest) ** 2).sum(-1)).min(axis=1).max())


def _place(
    outlines: list[np.ndarray],
    frame: Rect,
    obstacles: Sequence[Polygon],
    boundary: Rect,
    target: Point,
    clearance: float,
    pile: Box | None,
) -> tuple[float, float, bool]:
    """
    find_position for a piece whose frame, not its outlines, is
    centred on the target and kept inside the boundary; with a pile,
    placed where the pile's costs with the frame added are lowest
    (see _pile_costs).
    """
    points = np.concatenate(outlines)
    (x0, y0), (x1, y1) = points.min(axis=0), points.max(axis=0)
    fx, fy, fw, fh = frame
    # The outlines' margins inside the frame move the target and the
    # boundary.
    left, right = x0 - fx, fx + fw - x1
    bottom, top = y0 - fy, fy + fh - y1
    bx, by, bw, bh = boundary
    tx, ty = target
    hw, hh = (x1 - x0) / 2, (y1 - y0) / 2

    def cost(x, y):
        # The frame's box when the outlines' box centres on (x, y).
        return _pile_costs(
            pile, x - hw - left, y - hh - bottom, x + hw + right, y + hh + top
        )

    return find_position(
        outlines,
        obstacles,
        (bx + left, by + bottom, bw - left - right, bh - bottom - top),
        (tx + (left - right) / 2, ty + (bottom - top) / 2),
        clearance,
        cost=None if pile is None else cost,
    )


def _pile_costs(pile: Box, x0, y0, x1, y1) -> tuple:
    """
    The cost the layout keeps lowest, as a 1-tuple: the area of the
    box around the pile and the box (x0, y0, x1, y1), plus
    _SQUARE_WEIGHT times its larger side squared. For numbers or
    arrays that broadcast together.
    """
    px0, py0, px1, py1 = pile
    w = np.maximum(px1, x1) - np.minimum(px0, x0)
    h = np.maximum(py1, y1) - np.minimum(py0, y0)
    return (w * h + _SQUARE_WEIGHT * np.maximum(w, h) ** 2,)


def _union(a: Box, b: Box) -> Box:
    """The box around two boxes."""
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _area(outlines: Sequence[Polygon]) -> float:
    """The area inside the outlines (shoelace formula)."""
    total = 0.0
    for outline in outlines:
        x, y = np.asarray(outline, dtype=float).T
        total += abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    return total / 2

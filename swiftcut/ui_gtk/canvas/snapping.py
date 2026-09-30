"""
Object snapping: a moving box's edges and centre line up with other
objects' edges and centres, and the bed's, each axis on its own.

Boxes are world-space rects (x, y, width, height). On each axis a box
offers three lines: its low edge, its centre and its high edge. The
edge midpoints and the centre point lie on those lines, so they add
no value of their own when the axes snap independently.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

#: How near a feature must come to a line to snap, in screen pixels.
SNAP_DISTANCE_PX = 8.0

Rect = tuple[float, float, float, float]
Point = tuple[float, float]


class SnapLine(NamedTuple):
    """
    A line a feature can snap to, on one axis: where it lies, and the
    source's extent along the other axis, which its guide spans.
    """

    value: float
    lo: float
    hi: float


class SnapMatch(NamedTuple):
    """The line a feature snaps to, and the move that lands it there."""

    offset: float
    line: SnapLine


def features(rect: Rect, axis: int) -> tuple[float, float, float]:
    """A rect's low edge, centre and high edge on axis 0 (x) or 1 (y)."""
    low, size = rect[axis], rect[axis + 2]
    return low, low + size / 2, low + size


def candidate_lines(
    rects: Sequence[Rect],
) -> tuple[list[SnapLine], list[SnapLine]]:
    """The x lines and the y lines the given rects offer."""
    lines: tuple[list[SnapLine], list[SnapLine]] = ([], [])
    for rect in rects:
        for axis in (0, 1):
            other = 1 - axis
            lo, hi = rect[other], rect[other] + rect[other + 2]
            lines[axis].extend(
                SnapLine(v, lo, hi) for v in features(rect, axis)
            )
    return lines


def nearest(
    values: Sequence[float], lines: Sequence[SnapLine], threshold: float
) -> SnapMatch | None:
    """
    The line nearest any of the values, if within threshold; the first
    such line wins a tie.
    """
    best: SnapMatch | None = None
    for value in values:
        for line in lines:
            offset = line.value - value
            if abs(offset) > threshold:
                continue
            if best is None or abs(offset) < abs(best.offset):
                best = SnapMatch(offset, line)
    return best


def nudge(
    values: Sequence[float],
    lines: Sequence[SnapLine],
    threshold: float,
    step: float,
) -> float:
    """
    The move for a nudge of step along one axis, snapped: the moved
    values land on the nearest line within threshold that lies ahead
    of where they started, so a nudge never stays put or goes back.
    """
    best: SnapMatch | None = None
    for value in values:
        ahead = [line for line in lines if (line.value - value) * step > 0]
        match = nearest([value + step], ahead, threshold)
        if match and (best is None or abs(match.offset) < abs(best.offset)):
            best = match
    return step + (best.offset if best else 0.0)


def guide(axis: int, line: SnapLine, rect: Rect) -> tuple[Point, Point]:
    """
    The guide for a snap on axis 0 (x) or 1 (y): a segment along the
    line, spanning the snapped rect and the source.
    """
    other = 1 - axis
    lo = min(line.lo, rect[other])
    hi = max(line.hi, rect[other] + rect[other + 2])
    if axis == 0:
        return (line.value, lo), (line.value, hi)
    return (lo, line.value), (hi, line.value)

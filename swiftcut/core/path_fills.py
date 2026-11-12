"""
How the source paths of a workpiece's geometry are filled: its
segment's path fills, one (contours, fill rule) pair per source path
in the geometry's contour order. contours is how many of the
geometry's contours, one after the other, the path has; the fill
rule is "nonzero" or "evenodd" for a path the file draws filled and
None for one it draws without a fill.

ContourIndex works them out for a geometry made of (some of) the
contours of known paths: the importer's geometry against the file's
paths, a split piece against the workpiece it was cut from.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

from raygeo.geo import Geometry
from raygeo.geo.types import Point, Rect

PathFills = list[tuple[int, str | None]]

# Contours whose first points and boxes agree to within this share of
# the size of everything indexed are the same contour.
_TOLERANCE = 1e-6


def paths_of(
    geometry: Geometry, path_fills: PathFills | None
) -> list[tuple[list[Geometry], str | None]] | None:
    """
    The geometry's contours by source path, each path's with its fill
    rule; None without path fills, or with path fills that do not
    count the geometry's contours.
    """
    if path_fills is None:
        return None
    contours = geometry.split_into_contours()
    if sum(count for count, _rule in path_fills) != len(contours):
        return None
    paths = []
    start = 0
    for count, rule in path_fills:
        paths.append((contours[start : start + count], rule))
        start += count
    return paths


class ContourIndex:
    """
    The contours of some source paths, to tell which path a contour
    is: the one with the same first point and box. A contour found is
    used up, so identical contours of different paths are told apart
    by their order.
    """

    def __init__(self, paths: Sequence[tuple[Sequence[Geometry], str | None]]):
        self._rules = [rule for _contours, rule in paths]
        self._entries: list[tuple[Point, Rect, int]] = [
            (_first_point(contour), contour.rect(), index)
            for index, (contours, _rule) in enumerate(paths)
            for contour in contours
        ]
        self._used = [False] * len(self._entries)
        self._tolerance = _TOLERANCE * _span(e[1] for e in self._entries)
        self._cells: defaultdict[tuple[int, int], list[int]] = defaultdict(
            list
        )
        for i, (point, _rect, _index) in enumerate(self._entries):
            self._cells[self._cell(point)].append(i)

    def path_fills(self, geometry: Geometry) -> PathFills | None:
        """
        The geometry's path fills, each contour taken as the indexed
        contour it matches; None if one matches none. A contour met
        again (the same path read twice) starts a path of its own.
        """
        runs: PathFills = []
        last = None
        for contour in geometry.split_into_contours():
            found = self._find(contour)
            if found is None:
                return None
            key = (self._entries[found][2], self._used[found])
            if key == last:
                runs[-1] = (runs[-1][0] + 1, runs[-1][1])
            else:
                runs.append((1, self._rules[key[0]]))
            self._used[found] = True
            last = key
        return runs

    def _cell(self, point: Point) -> tuple[int, int]:
        return (
            math.floor(point[0] / self._tolerance),
            math.floor(point[1] / self._tolerance),
        )

    def _find(self, contour: Geometry) -> int | None:
        """
        The first unused indexed contour that matches contour, else
        the first used one.
        """
        point, rect = _first_point(contour), contour.rect()
        cx, cy = self._cell(point)
        matches = sorted(
            i
            for nx in (cx - 1, cx, cx + 1)
            for ny in (cy - 1, cy, cy + 1)
            for i in self._cells.get((nx, ny), ())
            if self._same(self._entries[i], point, rect)
        )
        if not matches:
            return None
        return next((i for i in matches if not self._used[i]), matches[0])

    def _same(
        self, entry: tuple[Point, Rect, int], point: Point, rect: Rect
    ) -> bool:
        other_point, other_rect, _index = entry
        return all(
            abs(a - b) <= self._tolerance
            for a, b in zip(
                (*other_point, *other_rect), (*point, *rect), strict=True
            )
        )


def _first_point(contour: Geometry) -> Point:
    x, y, _z = contour.get_command_at(0).end
    return x, y


def _span(rects) -> float:
    """The larger side of the box around rects, never zero."""
    rects = list(rects)
    if not rects:
        return 1.0
    width = max(r[2] for r in rects) - min(r[0] for r in rects)
    height = max(r[3] for r in rects) - min(r[1] for r in rects)
    return max(width, height, 1e-6)

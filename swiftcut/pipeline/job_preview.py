"""
The job preview: the op stream a Start sends, as timed segments.

The preview is built from the job artifact's ops, the ones
MachineCmd._start_job checks out and the driver encodes, so what it
shows is the job in the order the head will run it. It reads them and
never filters, reorders or changes them.

Each moving command is one segment, timed by the same walk over the
same ops as the job's time estimate, so the preview's total is the
estimate the canvas shows.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from raygeo.ops import Ops
from raygeo.ops.types import CommandCategory, CommandType

if TYPE_CHECKING:
    from ..machine.models.machine import Machine

#: A segment's kind: how it is drawn.
TRAVEL = "travel"
CUT = "cut"
SCAN = "scan"

Point = tuple[float, float]

_CURVES = (
    CommandType.ARC_TO,
    CommandType.BEZIER_TO,
    CommandType.QUADRATIC_BEZIER_TO,
)

#: How far the preview's own clock may drift from the artifact's
#: estimate, as a fraction, before it is scaled onto the estimate.
ESTIMATE_TOLERANCE = 0.01


@dataclass(frozen=True)
class PreviewSegment:
    """One moving command of the job, as the preview draws it."""

    #: Its index in the job's ops.
    op_index: int
    kind: str
    #: World points, start first. A curve is its linearised polyline.
    points: tuple[Point, ...]
    #: When the head starts and finishes it, in seconds from Start.
    t0: float
    t1: float


class JobPreviewModel:
    """A job's moving commands in op order, timed from Start."""

    def __init__(self, segments: list[PreviewSegment], total_time: float):
        self.segments = segments
        self.total_time = total_time
        self._ends = [segment.t1 for segment in segments]

    @classmethod
    def from_ops(
        cls,
        ops: Ops,
        machine: Machine,
        estimate: float | None = None,
    ) -> JobPreviewModel:
        """
        The preview of a job's ops.

        Times come from ops.build_cumulative_time_index at the
        machine's cut and travel speeds and acceleration, the
        parameters the job's estimate is walked with. Should the
        result still differ from estimate (the artifact's
        time_estimate) by more than ESTIMATE_TOLERANCE, every time is
        scaled so the preview ends when the estimate says the job
        does.

        A travel is a MOVE_TO; a raster line is a SCAN_LINE; any other
        move cuts, unless the power in force for it is zero, which
        draws as a travel. Power follows the SET_POWER commands, as
        the encoder reads it, and is zero before the first one, as
        the ops' own state is.

        The time index runs the first move from the origin, but the
        job starts wherever the head is, so the first segment starts
        on its own endpoint: it draws nothing and keeps its time.
        """
        cumulative = ops.build_cumulative_time_index(
            float(machine.max_cut_speed),
            float(machine.max_travel_speed),
            float(machine.acceleration),
        )
        total = cumulative[-1] if cumulative else 0.0
        scale = 1.0
        if (
            estimate
            and total > 0
            and not math.isclose(total, estimate, rel_tol=ESTIMATE_TOLERANCE)
        ):
            scale = estimate / total

        segments: list[PreviewSegment] = []
        power = 0.0
        last: tuple[float, float, float] | None = None
        for i in range(len(ops)):
            command = ops.command_type(i)
            if command == CommandType.SET_POWER:
                power = ops.power(i)
                continue
            if ops.category(i) != CommandCategory.MOVING:
                continue
            end = ops.endpoint(i)
            start = last if last is not None else end
            if command in _CURVES:
                line = ops.linearize(i, start)
                points = [start[:2]] + [
                    line.endpoint(j)[:2] for j in range(len(line))
                ]
            else:
                points = [start[:2], end[:2]]
            if command == CommandType.MOVE_TO:
                kind = TRAVEL
            elif command == CommandType.SCAN_LINE:
                kind = SCAN
            else:
                kind = CUT if power > 0 else TRAVEL
            t0 = cumulative[i - 1] if i else 0.0
            segments.append(
                PreviewSegment(
                    i, kind, tuple(points), t0 * scale, cumulative[i] * scale
                )
            )
            last = end
        return cls(segments, total * scale)

    def index_at(self, t: float) -> int:
        """
        How many segments are finished at time t: the segment at that
        index, if there is one, is the one the head is on or waiting
        for.
        """
        return bisect.bisect_right(self._ends, t)

    def path_at(self, t: float) -> list[Point]:
        """
        The current segment's points, as far as the head has got at
        time t; its last point is the head. Empty past the end.
        """
        index = self.index_at(t)
        if index >= len(self.segments):
            return []
        segment = self.segments[index]
        span = segment.t1 - segment.t0
        fraction = (t - segment.t0) / span if span > 0 else 0.0
        return _along(segment.points, min(max(fraction, 0.0), 1.0))

    def point_at(self, t: float) -> Point | None:
        """Where the head is at time t; None for a job with no moves."""
        if not self.segments:
            return None
        path = self.path_at(t)
        return path[-1] if path else self.segments[-1].points[-1]


def _along(points: tuple[Point, ...], fraction: float) -> list[Point]:
    """The polyline's points up to a fraction of its length."""
    lengths = [math.dist(a, b) for a, b in pairwise(points)]
    remaining = fraction * sum(lengths)
    path = [points[0]]
    for (a, b), length in zip(pairwise(points), lengths, strict=True):
        if remaining <= 0:
            return path
        if remaining < length:
            share = remaining / length
            path.append(
                (a[0] + (b[0] - a[0]) * share, a[1] + (b[1] - a[1]) * share)
            )
            return path
        path.append(b)
        remaining -= length
    return path

"""
The job preview: the op stream a Start sends, as timed segments.

The preview is built from the job artifact's ops, the ones
MachineCmd._start_job checks out and the driver encodes, so what it
shows is the job in the order the head will run it. It reads them and
never filters, reorders or changes them.

Each moving command is one segment, timed by the same walk over the
same ops as the job's time estimate, so the preview's total is the
estimate the canvas shows. The times come at once; on a big job the
segments take longer (about a third of a second for 180,000 ops), so
the window builds them as they are needed, and in slices ahead.
"""

from __future__ import annotations

import bisect
import math
import time
from collections.abc import Iterator
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
    """
    A job's moving commands in op order, timed from Start.

    segments are the ones built so far: all of them, unless the model
    is from from_ops_lazily. count is how many there are in all.
    """

    def __init__(
        self,
        segments: list[PreviewSegment],
        total_time: float,
        rest: Iterator[PreviewSegment] | None = None,
        count: int | None = None,
    ):
        self.segments = segments
        self.total_time = total_time
        self._ends = [segment.t1 for segment in segments]
        # The segments still to build, in order.
        self._rest = rest
        self.count = len(segments) if count is None else count

    @classmethod
    def from_ops(
        cls,
        ops: Ops,
        machine: Machine,
        estimate: float | None = None,
    ) -> JobPreviewModel:
        """
        The preview of a job's ops, every segment built.

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
        on its own endpoint: it draws nothing and keeps its time, so
        the total stays the estimate. Nothing is drawn before it ends,
        at start_time, so the window starts playback there.
        """
        segments, total = _build(ops, machine, estimate)
        return cls(list(segments), total)

    @classmethod
    def from_ops_lazily(
        cls,
        ops: Ops,
        machine: Machine,
        estimate: float | None = None,
    ) -> JobPreviewModel:
        """
        The preview from_ops gives, its times and total at once and
        its segments as they are needed: index_at, path_at, point_at
        and start_time build up to the segment they answer with, and
        build builds ahead. It keeps its own copy of ops, so the
        caller may let go of them.
        """
        ops = ops.copy()
        segments, total = _build(ops, machine, estimate)
        # Every moving command: the cutting ones and the travels.
        count = ops.count_cutting() + ops.count_travel()
        return cls([], total, segments, count)

    @property
    def start_time(self) -> float:
        """
        When the first segment ends: the first moment anything is
        drawn. Before it the time index runs the head from the ops'
        origin to the job's first point, which the preview does not
        draw.
        """
        if not self.segments:
            self._grow()
        return self.segments[0].t1 if self.segments else 0.0

    def build(self, seconds: float) -> bool:
        """
        Builds the next segments, for up to seconds. False once a call
        finds none left to build.
        """
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            if not self._grow():
                return False
        return True

    def index_at(self, t: float) -> int:
        """
        How many segments are finished at time t: the segment at that
        index, if there is one, is the one the head is on or waiting
        for. Builds the segments up to that one.
        """
        # The ends only grow: once the last one built is past t, every
        # one still to build is too.
        while (not self._ends or self._ends[-1] <= t) and self._grow():
            pass
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
        path = self.path_at(t)
        if path:
            return path[-1]
        return self.segments[-1].points[-1] if self.segments else None

    def firing_at(self, t: float) -> bool:
        """
        Whether the laser is on at time t: the head is running a cut or
        a raster line. It is off on a travel (a zero-power cut among
        them), while the head waits, and before and after the job.
        """
        index = self.index_at(t)
        if index >= len(self.segments):
            return False
        segment = self.segments[index]
        return segment.kind != TRAVEL and segment.t0 <= t

    def _grow(self) -> bool:
        """Builds the next segment; False when there is none left."""
        if self._rest is None:
            return False
        segment = next(self._rest, None)
        if segment is None:
            self._rest = None
            return False
        self.segments.append(segment)
        self._ends.append(segment.t1)
        return True


def _build(
    ops: Ops, machine: Machine, estimate: float | None
) -> tuple[Iterator[PreviewSegment], float]:
    """The ops' segments, to be built in order, and the job's total."""
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
    return _segments(ops, cumulative, scale), total * scale


def _segments(
    ops: Ops, cumulative: list[float], scale: float
) -> Iterator[PreviewSegment]:
    """Each moving command of ops as a segment, in op order."""
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
        yield PreviewSegment(
            i, kind, tuple(points), t0 * scale, cumulative[i] * scale
        )
        last = end


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

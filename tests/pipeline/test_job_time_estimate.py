"""The job time estimate, measured against times you can work out.

The estimate is walked over the final post-optimization op stream:
every segment at the speed in force for it, travels at the rapid rate,
plus an acceleration penalty for every corner the head has to slow
through. These tests pin both halves of that.
"""

import pytest
from raygeo.ops import Ops

from rayforge.machine.models.machine import Machine

# Fast enough that the trapezoidal ramps cost nothing measurable, so
# the remaining time is pure distance over speed.
NO_ACCEL = 1e9

CUT_MM_MIN = 600.0  # 10 mm/s
RAPID_MM_MIN = 3000.0  # 50 mm/s


def _path(points, feed=CUT_MM_MIN, rapid=RAPID_MM_MIN) -> Ops:
    ops = Ops()
    ops.set_feed_rate(feed)
    ops.set_rapid_rate(rapid)
    ops.move_to(points[0][0], points[0][1], 0.0)
    for x, y in points[1:]:
        ops.line_to(x, y, 0.0)
    return ops


def _within(actual: float, expected: float, fraction: float = 0.05) -> bool:
    return abs(actual - expected) <= expected * fraction


class TestAnalyticTime:
    """With acceleration out of the way, time is distance over speed."""

    def test_straight_cut_matches_distance_over_speed(self):
        ops = _path([(0.0, 0.0), (100.0, 0.0)])

        estimate = ops.estimate_time(CUT_MM_MIN, RAPID_MM_MIN, NO_ACCEL)

        assert _within(estimate, 100.0 / 10.0)

    def test_travel_runs_at_the_rapid_rate(self):
        ops = Ops()
        ops.set_feed_rate(CUT_MM_MIN)
        ops.set_rapid_rate(RAPID_MM_MIN)
        ops.move_to(0.0, 0.0, 0.0)
        ops.move_to(100.0, 0.0, 0.0)

        estimate = ops.estimate_time(CUT_MM_MIN, RAPID_MM_MIN, NO_ACCEL)

        assert _within(estimate, 100.0 / 50.0)

    def test_each_segment_uses_the_speed_in_force_for_it(self):
        """A speed change mid-path is honoured, not averaged."""
        ops = Ops()
        ops.set_rapid_rate(RAPID_MM_MIN)
        ops.set_feed_rate(600.0)  # 10 mm/s
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(50.0, 0.0, 0.0)
        ops.set_feed_rate(3000.0)  # 50 mm/s
        ops.line_to(100.0, 0.0, 0.0)

        estimate = ops.estimate_time(CUT_MM_MIN, RAPID_MM_MIN, NO_ACCEL)

        assert _within(estimate, 50.0 / 10.0 + 50.0 / 50.0)


class TestAccelerationPenalty:
    """Corners cost time even when the distance is identical."""

    def test_a_corner_is_slower_than_a_straight_line(self):
        acceleration = 3000.0
        straight = _path([(0.0, 0.0), (100.0, 0.0)])
        cornered = _path([(0.0, 0.0), (50.0, 0.0), (50.0, 50.0)])
        assert straight.distance() == cornered.distance()

        straight_time = straight.estimate_time(
            CUT_MM_MIN, RAPID_MM_MIN, acceleration
        )
        cornered_time = cornered.estimate_time(
            CUT_MM_MIN, RAPID_MM_MIN, acceleration
        )

        assert cornered_time > straight_time

    def test_more_corners_cost_more(self):
        acceleration = 3000.0
        one = _path([(0.0, 0.0), (50.0, 0.0), (50.0, 50.0)])
        many = _path(
            [(0.0, 0.0)]
            + [(x, 1.0 if x % 20 else 0.0) for x in range(10, 101, 10)]
        )

        assert many.estimate_time(
            CUT_MM_MIN, RAPID_MM_MIN, acceleration
        ) > one.estimate_time(CUT_MM_MIN, RAPID_MM_MIN, acceleration)

    def test_a_softer_machine_takes_longer(self):
        cornered = _path([(0.0, 0.0), (50.0, 0.0), (50.0, 50.0)])

        slow = cornered.estimate_time(CUT_MM_MIN, RAPID_MM_MIN, 500.0)
        quick = cornered.estimate_time(CUT_MM_MIN, RAPID_MM_MIN, 3000.0)

        assert slow > quick


class TestMachineParams:
    """The estimate is fed from the machine profile."""

    def test_the_estimate_uses_the_profile_acceleration(
        self, isolated_machine: Machine
    ):
        """The profile value is what reaches the estimator."""
        cornered = _path([(0.0, 0.0), (50.0, 0.0), (50.0, 50.0)])
        isolated_machine.set_acceleration(500)
        slow = cornered.estimate_time(
            float(isolated_machine.max_cut_speed),
            float(isolated_machine.max_travel_speed),
            float(isolated_machine.acceleration),
        )

        isolated_machine.set_acceleration(3000)
        quick = cornered.estimate_time(
            float(isolated_machine.max_cut_speed),
            float(isolated_machine.max_travel_speed),
            float(isolated_machine.acceleration),
        )

        assert slow > quick

    def test_acceleration_defaults_to_3000(self, isolated_machine: Machine):
        assert isolated_machine.acceleration == 3000


@pytest.mark.parametrize("acceleration", [500.0, 3000.0, NO_ACCEL])
def test_estimate_is_never_below_the_frictionless_time(acceleration):
    """Acceleration can only ever add time, never remove it."""
    ops = _path([(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 0.0)])
    floor = ops.distance() / 10.0

    estimate = ops.estimate_time(CUT_MM_MIN, RAPID_MM_MIN, acceleration)

    assert estimate >= floor * 0.999

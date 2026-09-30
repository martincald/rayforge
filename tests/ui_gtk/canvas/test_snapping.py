"""The object-snap core: the lines a box offers, the nearest line in
reach, a snapped nudge, and a snap's guide."""

import pytest

from swiftcut.ui_gtk.canvas.snapping import (
    SnapLine,
    candidate_lines,
    features,
    guide,
    nearest,
    nudge,
)


def test_a_box_offers_its_edges_and_centre_on_each_axis():
    assert features((10.0, 20.0, 30.0, 40.0), 0) == (10.0, 25.0, 40.0)
    assert features((10.0, 20.0, 30.0, 40.0), 1) == (20.0, 40.0, 60.0)


def test_each_line_carries_its_box_extent_on_the_other_axis():
    xs, ys = candidate_lines([(10.0, 20.0, 30.0, 40.0)])

    assert xs == [
        SnapLine(10.0, 20.0, 60.0),
        SnapLine(25.0, 20.0, 60.0),
        SnapLine(40.0, 20.0, 60.0),
    ]
    assert ys == [
        SnapLine(20.0, 10.0, 40.0),
        SnapLine(40.0, 10.0, 40.0),
        SnapLine(60.0, 10.0, 40.0),
    ]


def test_the_nearest_line_in_reach_wins():
    lines = [SnapLine(10.0, 0, 1), SnapLine(13.0, 0, 1)]

    match = nearest([11.8, 30.0], lines, 2.0)

    assert match is not None
    assert match.line.value == 13.0
    assert match.offset == pytest.approx(1.2)


def test_no_line_in_reach_is_no_match():
    assert nearest([10.0], [SnapLine(12.5, 0, 1)], 2.0) is None


def test_a_nudge_in_open_space_moves_by_its_step():
    assert nudge([10.0, 15.0, 20.0], [SnapLine(50.0, 0, 1)], 2.0, 1.0) == 1.0


def test_a_nudge_lands_on_a_line_in_reach_ahead():
    lines = [SnapLine(22.5, 0, 1)]
    behind = [SnapLine(21.0, 0, 1)]

    assert nudge([10.0, 15.0, 20.0], lines, 2.0, 1.0) == pytest.approx(2.5)
    assert nudge([30.0], behind, 2.0, -10.0) == pytest.approx(-9.0)


def test_a_nudge_never_stays_put_or_goes_back():
    # A line where the box starts, and one behind it, both in reach.
    lines = [SnapLine(10.0, 0, 1), SnapLine(9.5, 0, 1)]

    assert nudge([10.0], lines, 2.0, 1.0) == 1.0
    assert nudge([10.0], lines, 2.0, -1.0) == pytest.approx(-0.5)


def test_a_guide_spans_the_snapped_box_and_the_source():
    line = SnapLine(60.0, 40.0, 60.0)

    assert guide(0, line, (60.0, 10.0, 20.0, 10.0)) == (
        (60.0, 10.0),
        (60.0, 60.0),
    )
    assert guide(1, SnapLine(40.0, 60.0, 90.0), (10.0, 40.0, 20.0, 10.0)) == (
        (10.0, 40.0),
        (90.0, 40.0),
    )

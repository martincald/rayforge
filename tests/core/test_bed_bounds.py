import math

import pytest
from raygeo.geo import Matrix

from swiftcut.core.bed_bounds import bed_rect, clamp_offset, fits, inside

BED = (0.0, 0.0, 1400.0, 900.0)


def test_bed_rect_spans_the_axis_extents_from_the_origin(sync_machine):
    sync_machine.set_axis_extents(1400, 900)
    assert bed_rect(sync_machine) == BED


def test_bed_rect_ignores_work_margins(sync_machine):
    sync_machine.set_axis_extents(1400, 900)
    sync_machine.set_work_margins(10, 20, 30, 40)
    assert bed_rect(sync_machine) == BED


def test_a_box_the_size_of_the_bed_fits():
    assert fits((1400.0, 900.0), BED)
    assert fits((1400.0 + 1e-9, 900.0), BED)


def test_a_box_larger_in_either_direction_does_not_fit():
    assert not fits((1400.1, 100.0), BED)
    assert not fits((100.0, 900.1), BED)


@pytest.mark.parametrize(
    "box, offset",
    [
        # Inside, and touching each edge: no move.
        ((100.0, 200.0, 300.0, 100.0), (0.0, 0.0)),
        ((0.0, 0.0, 1400.0, 900.0), (0.0, 0.0)),
        # Past one edge: back onto it.
        ((-30.0, 200.0, 300.0, 100.0), (30.0, 0.0)),
        ((1200.0, 200.0, 300.0, 100.0), (-100.0, 0.0)),
        ((100.0, -5.0, 300.0, 100.0), (0.0, 5.0)),
        ((100.0, 850.0, 300.0, 100.0), (0.0, -50.0)),
        # Past a corner: onto both its edges.
        ((-30.0, -5.0, 300.0, 100.0), (30.0, 5.0)),
        ((1200.0, -5.0, 300.0, 100.0), (-100.0, 5.0)),
        ((-30.0, 850.0, 300.0, 100.0), (30.0, -50.0)),
        ((1200.0, 850.0, 300.0, 100.0), (-100.0, -50.0)),
        # Larger than the bed: low edge onto the bed's.
        ((-50.0, 100.0, 1500.0, 100.0), (50.0, 0.0)),
        ((100.0, 100.0, 1500.0, 950.0), (-100.0, -100.0)),
    ],
)
def test_clamp_offset_is_the_smallest_move_inside(box, offset):
    assert clamp_offset(box, BED) == pytest.approx(offset)


def test_float_noise_at_an_edge_is_not_moved():
    assert clamp_offset((-1e-9, 0.0, 1400.0 + 1e-9, 900.0), BED) == (
        0.0,
        0.0,
    )
    assert inside((-1e-9, 0.0, 1400.0 + 1e-9, 900.0), BED)


def test_a_frame_turned_45_degrees_is_held_by_its_rotated_box():
    # A 300 x 100 frame centred on (100, 100), turned 45 degrees: its
    # world box is 282.8 mm square, past the bottom-left corner.
    frame = Matrix.translation(-50.0, 50.0) @ Matrix.scale(300.0, 100.0)
    turned = Matrix.rotation(45.0, center=(100.0, 100.0)) @ frame
    box = turned.transform_rectangle((0.0, 0.0, 1.0, 1.0))
    side = 400.0 / math.sqrt(2)
    assert box == pytest.approx((100 - side / 2, 100 - side / 2, side, side))
    assert not inside(box, BED)

    dx, dy = clamp_offset(box, BED)

    assert (dx, dy) == pytest.approx((side / 2 - 100, side / 2 - 100))
    assert inside((box[0] + dx, box[1] + dy, side, side), BED)


@pytest.mark.parametrize(
    "box, expected",
    [
        ((0.0, 0.0, 1400.0, 900.0), True),
        ((100.0, 100.0, 10.0, 10.0), True),
        ((-0.1, 100.0, 10.0, 10.0), False),
        ((1390.1, 100.0, 10.0, 10.0), False),
        ((100.0, -0.1, 10.0, 10.0), False),
        ((100.0, 890.1, 10.0, 10.0), False),
        ((0.0, 0.0, 1400.1, 10.0), False),
    ],
)
def test_inside(box, expected):
    assert inside(box, BED) is expected

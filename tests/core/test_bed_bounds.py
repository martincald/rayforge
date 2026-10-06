from swiftcut.core.bed_bounds import bed_rect, fits

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

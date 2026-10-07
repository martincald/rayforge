"""
The Auto Layout benchmark documents and measures in layout_bench are
what layouts are judged by, so they are tested here.
"""

import pytest

from swiftcut.core.workpiece import WorkPiece
from tests.doceditor import layout_bench as bench


def square(x, y, size, angle=0.0):
    """A workpiece without geometry: its outline is its frame."""
    workpiece = WorkPiece(name="Square")
    workpiece.set_size(size, size)
    workpiece.pos = (x, y)
    workpiece.angle = angle
    return workpiece


def test_a_piece_inside_another_overlaps():
    # Far from each other's outline, but one lies inside the other:
    # the ring an unfilled outline draws is not the piece.
    big, small = square(0, 0, 100), square(45, 45, 10)

    assert bench.clashes([big, small]) == {"overlap": 1, "close": 0}


def test_crossing_outlines_overlap():
    assert bench.clashes([square(0, 0, 10), square(5, 5, 10)]) == {
        "overlap": 1,
        "close": 0,
    }


def test_a_gap_under_the_clearance_is_close():
    assert bench.clashes([square(0, 0, 10), square(10.9, 0, 10)]) == {
        "overlap": 0,
        "close": 1,
    }


def test_a_gap_of_the_clearance_is_clear():
    # Corner to corner too: the gap is to the nearest edge point.
    pieces = [square(0, 0, 10), square(-11, 0, 10), square(10.71, 10.71, 10)]

    assert bench.clashes(pieces) == {"overlap": 0, "close": 0}


def test_a_corner_near_the_middle_of_an_edge_is_close():
    # Far from the edge's vertices, which a vertex-to-vertex distance
    # would see.
    long, turned = square(0, 0, 100), square(45, 120, 10, angle=45)
    (outline,) = bench.true_outlines(turned)
    x, y = turned.pos
    turned.pos = (x, y + 100.5 - outline[:, 1].min())

    assert bench.clashes([long, turned]) == {"overlap": 0, "close": 1}


def test_fixed_items_count_only_against_laid_out_ones():
    laid_out = [square(0, 0, 10)]
    fixed = [square(5, 0, 10), square(200, 0, 10), square(205, 0, 10)]

    assert bench.clashes(laid_out, fixed) == {"overlap": 1, "close": 0}


def test_compactness_is_box_area_over_piece_area():
    pieces = [square(0, 0, 10), square(20, 0, 10)]

    assert bench.compactness(pieces) == pytest.approx(300 / 200)


def test_frames_outside_the_boundary():
    inner, edge, turned = (
        square(0, 0, 10),
        square(95, 0, 10),
        square(1, 1, 10, angle=45),
    )

    outside = bench.frames_outside([inner, edge, turned], (0, 0, 100, 100))

    # Turned 45 degrees about its centre, the frame reaches below 0.
    assert outside == [edge, turned]


@pytest.fixture
def bed(test_machine_and_config):
    machine, _config = test_machine_and_config
    machine.set_axis_extents(1400, 900)
    return machine


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(bench.BENCHMARKS))
async def test_benchmark_is_real_workpieces_with_true_outlines(
    doc_editor, task_mgr, bed, tmp_path, name
):
    pieces, (stock_w, stock_h) = bench.BENCHMARKS[name]

    workpieces = await bench.build(doc_editor, task_mgr, tmp_path, pieces)

    assert len(set(workpieces)) == len(pieces)
    assert set(workpieces) <= set(doc_editor.doc.all_workpieces)
    # Their true outlines, not the frame: an L's frame has twice its
    # area.
    for workpiece, piece in zip(workpieces, pieces):
        assert bench.outline_area(workpiece) == pytest.approx(
            piece.area, rel=1e-3
        )
    # The stock holds them about twice over.
    total = sum(piece.area for piece in pieces)
    assert 1.8 < stock_w * stock_h / total < 2.4
    stock = bench.add_stock(doc_editor, (stock_w, stock_h))
    assert stock.visible
    x0, y0 = 700 - stock_w / 2, 450 - stock_h / 2
    assert stock.get_world_geometry().rect() == pytest.approx(
        (x0, y0, x0 + stock_w, y0 + stock_h)
    )

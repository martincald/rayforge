"""
Auto Layout (Arrange > Auto Layout, Ctrl+Alt+A) on real imported
workpieces: their true outlines end 1 mm apart with their frames
inside the boundary, every other workpiece is kept clear of and left
where it is, and one undo puts everything back.
"""

import numpy as np
import pytest
from raygeo.geo import Matrix

from swiftcut.core.group import Group
from swiftcut.core.workpiece import WorkPiece
from tests.doceditor import layout_bench as bench

ELLIPSES = [piece for piece in bench.FORTY if piece.name.startswith("ell")]

#: Each document and the stock it is laid out on, about twice its area.
DOCUMENTS = {
    "circles": bench.BENCHMARKS["circles-20"],
    "ellipses": bench.Benchmark(ELLIPSES, (200.0, 130.0)),
    "mixed": bench.BENCHMARKS["mixed-18"],
    # Circles, ellipses, rectangles, and Ls, Us, a cross and a star.
    "forty": bench.BENCHMARKS["forty-40"],
}


@pytest.fixture
def bed(test_machine_and_config):
    """The ilab-614 bed: 1400 x 900 mm."""
    machine, _config = test_machine_and_config
    machine.set_axis_extents(1400, 900)
    return machine


def _notices(editor):
    """The notices the editor shows from now on."""
    notices = []
    editor.notification_requested.connect(
        lambda sender, **kwargs: notices.append(kwargs["message"]),
        weak=False,
    )
    return notices


async def _auto_layout(editor, task_mgr, items):
    """Runs the Auto Layout action on the items; waits for its result."""
    editor.layout.layout_pixel_perfect(items)
    await bench.settle(editor, task_mgr)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(DOCUMENTS))
async def test_true_outlines_end_1mm_apart_inside_the_stock(
    doc_editor, task_mgr, bed, tmp_path, name
):
    pieces, size = DOCUMENTS[name]
    workpieces = await bench.build(doc_editor, task_mgr, tmp_path, pieces)
    stock = bench.add_stock(doc_editor, size)
    notices = _notices(doc_editor)

    await _auto_layout(doc_editor, task_mgr, workpieces)

    assert bench.clashes(workpieces) == {"overlap": 0, "close": 0}
    assert bench.frames_outside(workpieces, bench.frame_box(stock)) == []
    assert notices == []


@pytest.mark.asyncio
async def test_other_workpieces_are_kept_clear_of_and_stay(
    doc_editor, task_mgr, bed, tmp_path
):
    workpieces = await bench.build(
        doc_editor, task_mgr, tmp_path, bench.MIXED[::3]
    )
    # Not selected: one over the bed centre, where the layout gathers
    # the pieces, and one in the top left corner.
    fixed = []
    for x, y, w, h in ((640, 410, 120, 80), (0, 780, 400, 120)):
        workpiece = WorkPiece(name="Fixed")
        workpiece.set_size(w, h)
        workpiece.pos = (x, y)
        doc_editor.doc.add_workpiece(workpiece)
        fixed.append(workpiece)
    before = [workpiece.matrix.copy() for workpiece in fixed]

    await _auto_layout(doc_editor, task_mgr, workpieces)

    assert bench.clashes(workpieces, fixed) == {"overlap": 0, "close": 0}
    assert bench.frames_outside(workpieces, bench.BED) == []
    assert [workpiece.matrix for workpiece in fixed] == before


@pytest.mark.asyncio
async def test_a_stock_off_the_bed_edge_lays_out_on_its_part_on_the_bed(
    doc_editor, task_mgr, bed, tmp_path
):
    pieces = [bench.circle(40), bench.ellipse(40, 20), bench.rectangle(30, 20)]
    workpieces = await bench.build(doc_editor, task_mgr, tmp_path, pieces)
    # Half of it hangs off the right edge of the bed.
    stock = bench.add_stock(doc_editor, (200, 100))
    stock.pos = (1300, 400)

    await _auto_layout(doc_editor, task_mgr, workpieces)

    on_bed = (1300, 400, 100, 100)
    assert bench.frames_outside(workpieces, on_bed) == []
    assert bench.clashes(workpieces) == {"overlap": 0, "close": 0}


@pytest.mark.asyncio
async def test_piece_that_fits_nowhere_stays_with_a_notice(
    doc_editor, task_mgr, bed, tmp_path
):
    pieces = [bench.rectangle(100, 50), bench.circle(20), bench.circle(15)]
    long, *rest = await bench.build(doc_editor, task_mgr, tmp_path, pieces)
    # Lower than the rectangle is either way, and away from it.
    stock = bench.add_stock(doc_editor, (120, 40))
    stock.pos = (100, 100)
    before = long.matrix.copy()
    notices = _notices(doc_editor)

    await _auto_layout(doc_editor, task_mgr, [long, *rest])

    assert long.matrix == before
    assert notices == [f"Could not fit the following items: {long.name}"]
    assert bench.clashes(rest, [long]) == {"overlap": 0, "close": 0}
    assert bench.frames_outside(rest, bench.frame_box(stock)) == []


@pytest.mark.asyncio
async def test_larger_pieces_are_kept_clear_of_one_that_fits_nowhere(
    doc_editor, task_mgr, bed, tmp_path
):
    circle, rod = await bench.build(
        doc_editor,
        task_mgr,
        tmp_path,
        [bench.circle(40), bench.rectangle(100, 5)],
    )
    # Too long for the stock either way, and across its centre, where
    # the circle, larger and so placed first, would go.
    stock = bench.add_stock(doc_editor, (70, 90))
    rod.pos = (650, 447.5)
    before = rod.matrix.copy()
    notices = _notices(doc_editor)

    await _auto_layout(doc_editor, task_mgr, [circle, rod])

    assert rod.matrix == before
    assert notices == [f"Could not fit the following items: {rod.name}"]
    assert bench.clashes([circle], [rod]) == {"overlap": 0, "close": 0}
    assert bench.frames_outside([circle], bench.frame_box(stock)) == []


@pytest.mark.asyncio
async def test_turned_and_mirrored_items_in_a_transformed_group(
    doc_editor, task_mgr, bed, tmp_path, monkeypatch
):
    from swiftcut.shared.placement import arrange

    calls = []

    def spy(proxy, pieces, *args, **kwargs):
        result = arrange(proxy, pieces, *args, **kwargs)
        calls.append((pieces, result))
        return result

    monkeypatch.setattr("swiftcut.doceditor.layout.nest.arrange", spy)
    turned, mirrored = await bench.build(
        doc_editor, task_mgr, tmp_path, [bench.l_shape(60, 40, 15)] * 2
    )
    # A group moved, turned and stretched: a move worked out in the
    # world must reach its children in the group's space.
    group = Group()
    doc_editor.doc.active_layer.add_child(group)
    parent = (
        Matrix.translation(300, 200)
        @ Matrix.rotation(30)
        @ Matrix.scale(1.5, 0.8)
    )
    group.matrix = parent
    centre = turned.get_world_transform().transform_point((0.5, 0.5))
    worlds = [
        Matrix.rotation(10, center=centre) @ turned.get_world_transform(),
        mirrored.get_world_transform()
        @ Matrix.translation(1, 0)
        @ Matrix.scale(-1, 1),
    ]
    for workpiece, world in zip((turned, mirrored), worlds):
        group.add_child(workpiece)
        workpiece.matrix = parent.invert() @ world
    frames = [bench.frame_box(turned), bench.frame_box(mirrored)]
    # Too narrow for either as it is: both must turn upright.
    stock = bench.add_stock(doc_editor, (60, 200))
    stock.pos = (1000, 300)

    await _auto_layout(doc_editor, task_mgr, [turned, mirrored])

    ((pieces, result),) = calls
    for workpiece, world, frame in zip((turned, mirrored), worlds, frames):
        (piece,) = [p for p in pieces if p.frame == pytest.approx(frame)]
        angle, dx, dy, fits = result[piece.id]
        assert fits and angle in (90, 270)
        x, y, w, h = frame
        expected = (
            Matrix.translation(dx, dy)
            @ Matrix.rotation(angle, center=(x + w / 2, y + h / 2))
            @ world
        )
        assert np.allclose(
            workpiece.get_world_transform().to_numpy(),
            expected.to_numpy(),
            atol=1e-9,
        )
    assert mirrored.get_world_transform().is_flipped()
    assert not turned.get_world_transform().is_flipped()
    assert group.matrix == parent
    assert bench.clashes([turned, mirrored]) == {"overlap": 0, "close": 0}
    assert (
        bench.frames_outside([turned, mirrored], bench.frame_box(stock)) == []
    )


@pytest.mark.asyncio
async def test_one_undo_restores_every_matrix(
    doc_editor, task_mgr, bed, tmp_path
):
    workpieces = await bench.build(
        doc_editor, task_mgr, tmp_path, bench.MIXED[::3]
    )
    before = [workpiece.matrix.copy() for workpiece in workpieces]
    history = doc_editor.history_manager
    entries = len(history.undo_stack)

    await _auto_layout(doc_editor, task_mgr, workpieces)

    assert len(history.undo_stack) == entries + 1
    assert [wp.matrix for wp in workpieces] != before
    history.undo()
    assert [wp.matrix for wp in workpieces] == before

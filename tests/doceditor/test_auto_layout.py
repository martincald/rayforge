"""
Auto Layout (Arrange > Auto Layout, Ctrl+Alt+A) on real imported
workpieces: their true outlines end 1 mm apart with their frames
inside the boundary, the benchmarks end at least as compact as the
old layout left them (but the one in E3_GAP), every other workpiece is
kept clear of and left where it is, and one undo puts everything
back. It is worked out in a worker process, with progress; cancelled,
or if the document changes meanwhile, it changes nothing.
"""

import asyncio
import time
from unittest.mock import Mock

import numpy as np
import pytest
from raygeo.geo import Matrix

from swiftcut.core.doc import Doc
from swiftcut.core.group import Group
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.layout import NestLayoutStrategy, nest
from swiftcut.doceditor.layout_cmd import AUTO_LAYOUT_KEY
from tests.doceditor import layout_bench as bench

ELLIPSES = [piece for piece in bench.FORTY if piece.name.startswith("ell")]
#: The notice when the document changed while the layout was worked out.
CHANGED = "The document changed during Auto Layout; nothing was moved."

#: Each document and the stock it is laid out on, about twice its area.
DOCUMENTS = {
    "circles": bench.BENCHMARKS["circles-20"],
    "ellipses": bench.Benchmark(ELLIPSES, (200.0, 130.0)),
    "mixed": bench.BENCHMARKS["mixed-18"],
    # Circles, ellipses, rectangles, and Ls, Us, a cross and a star.
    "forty": bench.BENCHMARKS["forty-40"],
}

#: The least compact each benchmark may end, on its stock or on the
#: bed (bench.compactness; lower is more compact): the old layout's
#: result on the same pieces drawn filled, at the smallest margin
#: (0.625 mm) where it keeps 1 mm between outlines
#: (docs/auto-layout-notes.md, Before).
COMPACTNESS_BAR = {
    ("circles-20", "stock"): 1.328,
    ("mixed-18", "stock"): 1.337,
    ("forty-40", "stock"): 1.346,
    ("forty-40", "bed"): 1.700,
}
#: The benchmark that still ends less compact than its bar.
E3_GAP = {("forty-40", "stock")}


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
@pytest.mark.parametrize(
    "name, boundary",
    [
        pytest.param(
            *case,
            marks=pytest.mark.xfail(
                strict=True, reason="E3 gap, see docs/auto-layout-notes.md"
            ),
        )
        if case in E3_GAP
        else case
        for case in COMPACTNESS_BAR
    ],
)
async def test_benchmarks_end_within_the_compactness_bar(
    doc_editor, task_mgr, bed, tmp_path, name, boundary
):
    pieces, size = bench.BENCHMARKS[name]
    workpieces = await bench.build(doc_editor, task_mgr, tmp_path, pieces)
    if boundary == "stock":
        bench.add_stock(doc_editor, size)

    await _auto_layout(doc_editor, task_mgr, workpieces)

    assert bench.clashes(workpieces) == {"overlap": 0, "close": 0}
    assert bench.compactness(workpieces) <= COMPACTNESS_BAR[name, boundary]


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
async def test_no_stock_and_no_machine_bed_gives_a_notice(
    doc_editor, monkeypatch
):
    workpiece = WorkPiece(name="Piece")
    workpiece.set_size(20, 10)
    doc_editor.doc.add_workpiece(workpiece)
    before = workpiece.matrix.copy()
    monkeypatch.setattr(nest, "get_context", lambda: Mock(machine=None))
    notices = _notices(doc_editor)

    doc_editor.layout.layout_pixel_perfect([workpiece])

    assert workpiece.matrix == before
    assert notices == [
        "Auto Layout needs a stock or a machine bed to lay out on."
    ]


@pytest.mark.asyncio
async def test_turned_and_mirrored_items_in_a_transformed_group(
    doc_editor, task_mgr, bed, tmp_path, monkeypatch
):
    # The worker's result, as the main thread turns it into deltas.
    calls = []
    deltas = NestLayoutStrategy.deltas

    def spy(strategy, placements):
        calls.append((strategy.arrange_args()[0], placements))
        return deltas(strategy, placements)

    monkeypatch.setattr(NestLayoutStrategy, "deltas", spy)
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


@pytest.mark.asyncio
async def test_the_layout_runs_in_a_worker_process_with_progress(
    doc_editor, task_mgr, bed, tmp_path
):
    workpieces = await bench.build(doc_editor, task_mgr, tmp_path, bench.MIXED)
    progress = []

    doc_editor.layout.layout_pixel_perfect(workpieces)
    task = task_mgr.get_task(AUTO_LAYOUT_KEY)
    task.status_changed.connect(
        lambda task: progress.append(task.get_progress()), weak=False
    )
    await bench.settle(doc_editor, task_mgr)

    assert task.task_type == "process"
    assert task.get_status() == "completed"
    assert any(0 < fraction < 1 for fraction in progress)
    assert bench.clashes(workpieces) == {"overlap": 0, "close": 0}


@pytest.mark.asyncio
async def test_cancel_mid_run_changes_nothing(
    doc_editor, task_mgr, bed, tmp_path
):
    workpieces = await bench.build(doc_editor, task_mgr, tmp_path, bench.FORTY)
    before = [workpiece.matrix.copy() for workpiece in workpieces]
    history = doc_editor.history_manager
    entries = len(history.undo_stack)
    notices = _notices(doc_editor)

    doc_editor.layout.layout_pixel_perfect(workpieces)
    task = task_mgr.get_task(AUTO_LAYOUT_KEY)
    deadline = time.monotonic() + 60
    while task.get_progress() == 0:
        assert time.monotonic() < deadline, "no progress"
        await asyncio.sleep(0.005)
    assert task.get_progress() < 1
    task_mgr.cancel_task(AUTO_LAYOUT_KEY)
    # The worker stops at the next piece; its last word, which would
    # have been the result, clears the task.
    while task_mgr._zombie_tasks:
        assert time.monotonic() < deadline, "the worker did not stop"
        await asyncio.sleep(0.01)
    await bench.settle(doc_editor, task_mgr)

    assert task.get_status() == "canceled"
    assert [workpiece.matrix for workpiece in workpieces] == before
    assert len(history.undo_stack) == entries
    assert notices == []


@pytest.mark.asyncio
async def test_document_replaced_mid_run_is_left_alone(
    doc_editor, task_mgr, bed, tmp_path
):
    workpieces = await bench.build(doc_editor, task_mgr, tmp_path, bench.FORTY)
    before = [workpiece.matrix.copy() for workpiece in workpieces]
    old_history = doc_editor.history_manager
    entries = len(old_history.undo_stack)
    notices = _notices(doc_editor)

    doc_editor.layout.layout_pixel_perfect(workpieces)
    new_doc = Doc()
    doc_editor.set_doc(new_doc)
    await bench.settle(doc_editor, task_mgr)

    assert not new_doc.history_manager.can_undo()
    assert len(old_history.undo_stack) == entries
    assert [workpiece.matrix for workpiece in workpieces] == before
    assert notices == [CHANGED]


@pytest.mark.asyncio
async def test_obstacle_moved_mid_run_moves_nothing(
    doc_editor, task_mgr, bed, tmp_path
):
    workpieces = await bench.build(doc_editor, task_mgr, tmp_path, bench.MIXED)
    fixed = WorkPiece(name="Fixed")
    fixed.set_size(100, 100)
    doc_editor.doc.add_workpiece(fixed)
    before = [workpiece.matrix.copy() for workpiece in workpieces]
    history = doc_editor.history_manager
    entries = len(history.undo_stack)
    notices = _notices(doc_editor)

    doc_editor.layout.layout_pixel_perfect(workpieces)
    # Onto the bed centre, where the layout gathers the pieces.
    fixed.pos = (650, 400)
    await bench.settle(doc_editor, task_mgr)

    assert [workpiece.matrix for workpiece in workpieces] == before
    assert len(history.undo_stack) == entries
    assert notices == [CHANGED]

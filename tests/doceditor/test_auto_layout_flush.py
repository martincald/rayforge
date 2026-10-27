"""
Auto Layout at gap 0 (Preferences > General > Layout): pieces pack
flush, within the Merge Lines tolerance of their layers' steps, so
Merge Lines cuts a shared edge once, and true curves overlap by no
more than it. With Merge Lines off, a notice offers to turn it on, in
one undo step. At a gap above 0 the layout is worked out as before,
the gap apart.
"""

import asyncio
import itertools
import math

import pytest

from swiftcut.doceditor.layout import NestLayoutStrategy
from swiftcut.doceditor.layout.outline import (
    OUTLINE_TOLERANCE_MM,
    item_world_polygons,
    item_world_polygons_and_edges,
)
from swiftcut.pipeline.artifact import JobArtifact
from swiftcut.shared.placement import arrange
from swiftcut.shared.tasker.context import ExecutionContext
from tests.doceditor import layout_bench as bench

#: The squares' side, in mm.
SIDE = 20.0
#: The notice when a Merge Lines on the laid-out layers is off.
OFF = "Merge Lines is off, so shared edges are cut twice."


@pytest.fixture(autouse=True)
def _zero_debounce(zero_debounce_delay):
    """Rebuild on the next main-loop turn instead of 200 ms later."""


@pytest.fixture
def step(doc_editor, test_machine_and_config, contour_step_class):
    """The active layer's only step: a Contour."""
    machine, _config = test_machine_and_config
    machine.set_axis_extents(400, 300)
    workflow = doc_editor.doc.active_layer.workflow
    assert workflow is not None
    workflow.set_steps([])
    step = contour_step_class.create(doc_editor.context, name="cut")
    workflow.add_step(step)
    return step


def _merge_lines(step):
    (settings,) = [
        d
        for d in step.per_step_transformers_dicts
        if d["name"] == "MergeLinesTransformer"
    ]
    return settings


def _notices(editor):
    """Every notice the editor shows from now on, with its arguments."""
    notices = []
    editor.notification_requested.connect(
        lambda sender, **kwargs: notices.append(kwargs), weak=False
    )
    return notices


async def _squares(editor, task_mgr, folder, count=4):
    pieces = [bench.rectangle(SIDE, SIDE)] * count
    return await bench.build(editor, task_mgr, folder, pieces)


async def _auto_layout(editor, task_mgr, items):
    editor.layout.layout_pixel_perfect(items)
    await bench.settle(editor, task_mgr)


async def _cut_length(editor) -> float:
    """The cut length of the job a Start would send."""
    pipeline = editor.pipeline
    handle = await asyncio.wait_for(
        pipeline.generate_job_artifact_async(), timeout=30
    )
    with pipeline.artifact_store.checkout_handle(handle) as artifact:
        assert isinstance(artifact, JobArtifact)
        return artifact.ops.cut_distance()


def _block(workpieces):
    """The box around the workpieces' outlines, as (width, height)."""
    outlines = [o for wp in workpieces for o in bench.true_outlines(wp)]
    xs, ys = zip(*(p for outline in outlines for p in outline))
    return max(xs) - min(xs), max(ys) - min(ys)


@pytest.mark.asyncio
async def test_squares_pack_flush_and_shared_edges_are_cut_once(
    doc_editor, task_mgr, step, tmp_path
):
    # Centreline: the offset (the head's kerf) moves no line, so the
    # squares' shared edges coincide.
    assert step.cut_side == "CENTERLINE"
    tolerance = _merge_lines(step)["tolerance"]
    workpieces = await _squares(doc_editor, task_mgr, tmp_path)
    notices = _notices(doc_editor)

    await _auto_layout(doc_editor, task_mgr, workpieces)

    assert _block(workpieces) == pytest.approx((2 * SIDE, 2 * SIDE))
    assert bench.clashes(workpieces)["overlap"] == 0
    # The block's outline and the cross inside it. Merge Lines trims
    # each of the four shared edges by up to its tolerance at each end.
    length = await _cut_length(doc_editor)
    assert length == pytest.approx(12 * SIDE, abs=8 * tolerance)
    assert notices == []


@pytest.mark.asyncio
async def test_unequal_rectangles_end_with_a_shared_edge_exactly(
    doc_editor, task_mgr, step, tmp_path
):
    # Equal squares meet exactly on the grid anyway; these do so only
    # by the snap (tests/shared/test_arrange.py).
    pieces = [bench.rectangle(30, 30), bench.rectangle(17, 23)]
    big, small = await bench.build(doc_editor, task_mgr, tmp_path, pieces)

    await _auto_layout(doc_editor, task_mgr, [big, small])

    (bx0, by0, bx1, by1), (sx0, sy0, sx1, sy1) = [
        wp.get_world_geometry().rect() for wp in (big, small)
    ]
    offsets = (bx0 - sx1, sx0 - bx1, by0 - sy1, sy0 - by1)
    assert min(abs(offset) for offset in offsets) <= 1e-9
    assert bench.clashes([big, small])["overlap"] == 0


@pytest.mark.asyncio
async def test_with_merge_lines_off_a_notice_offers_to_turn_it_on(
    doc_editor, task_mgr, step, tmp_path
):
    merge_lines = _merge_lines(step)
    merge_lines["enabled"] = False
    workpieces = await _squares(doc_editor, task_mgr, tmp_path)
    notices = _notices(doc_editor)
    history = doc_editor.history_manager

    await _auto_layout(doc_editor, task_mgr, workpieces)

    assert _block(workpieces) == pytest.approx((2 * SIDE, 2 * SIDE))
    assert await _cut_length(doc_editor) == pytest.approx(16 * SIDE)
    (notice,) = notices
    assert notice["message"] == OFF
    assert notice["action_label"] == "Enable"
    entries = len(history.undo_stack)

    notice["action_callback"]()

    assert merge_lines["enabled"] is True
    assert len(history.undo_stack) == entries + 1
    history.undo()
    assert merge_lines["enabled"] is False
    await bench.settle(doc_editor, task_mgr)


@pytest.mark.asyncio
async def test_gap_1_lays_out_as_before(
    doc_editor, task_mgr, step, test_machine_and_config, tmp_path
):
    _machine, config = test_machine_and_config
    config.set_layout_gap_mm(1.0)
    workpieces = await _squares(doc_editor, task_mgr, tmp_path, 2)

    pieces, obstacles, _boundary, _target, clearance, *rest = (
        NestLayoutStrategy(workpieces).arrange_args()
    )

    assert clearance == 1.0 + 2 * OUTLINE_TOLERANCE_MM
    assert rest == []
    assert obstacles == []
    for piece, workpiece in zip(pieces, workpieces):
        assert piece.outlines == item_world_polygons(workpiece)
        assert piece.edges == ()


@pytest.mark.asyncio
async def test_gap_0_lays_edges_flush_within_the_step_tolerance(
    doc_editor, task_mgr, step, test_machine_and_config, tmp_path
):
    _machine, config = test_machine_and_config
    assert config.layout_gap_mm == 0
    _merge_lines(step)["tolerance"] = 0.04
    pieces = [bench.rectangle(30, 20), bench.circle(30), bench.circle(20)]
    moving, curve, fixed = await bench.build(
        doc_editor, task_mgr, tmp_path, pieces
    )

    strategy = NestLayoutStrategy([moving, curve])
    (piece, round_piece), obstacles, _b, _t, clearance, edges, tolerance = (
        strategy.arrange_args()
    )

    assert (clearance, tolerance) == (0.0, 0.04)
    assert (piece.outlines, list(piece.edges)) == (
        item_world_polygons_and_edges(moving)
    )
    assert len(piece.edges) == 4
    assert (round_piece.edges, edges) == ((), [])
    # Curves polygonize as at gap 1, not finer for the tolerance.
    config.set_layout_gap_mm(1.0)
    at_gap_1 = NestLayoutStrategy([moving, curve]).arrange_args()
    assert round_piece.outlines == at_gap_1[0][1].outlines
    assert round_piece.outlines != item_world_polygons(curve, 0.02)
    assert obstacles == at_gap_1[1] == item_world_polygons(fixed)
    assert obstacles != item_world_polygons(fixed, 0.02)
    assert strategy.merge_lines_off == []


@pytest.mark.asyncio
async def test_gap_0_with_merge_lines_off_takes_its_tolerance(
    doc_editor, task_mgr, step, tmp_path
):
    merge_lines = _merge_lines(step)
    merge_lines["enabled"] = False
    merge_lines["tolerance"] = 0.04
    (square,) = await _squares(doc_editor, task_mgr, tmp_path, 1)

    strategy = NestLayoutStrategy([square])

    # What Enable would merge at.
    assert strategy.arrange_args()[-1] == 0.04
    assert strategy.merge_lines_off == [(step, merge_lines)]


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", ["none", "no tolerance"])
async def test_gap_0_without_a_merge_tolerance_lays_nothing_flush(
    doc_editor, task_mgr, step, tmp_path, settings
):
    if settings == "none":
        step.per_step_transformers_dicts.remove(_merge_lines(step))
    else:
        del _merge_lines(step)["tolerance"]
    (square,) = await _squares(doc_editor, task_mgr, tmp_path, 1)

    strategy = NestLayoutStrategy([square])

    # The outlines keep what the polygons may lie inside the curves.
    (piece,), _obstacles, _b, _t, clearance = strategy.arrange_args()
    assert clearance == 2 * OUTLINE_TOLERANCE_MM
    assert piece.edges == ()
    assert strategy.merge_lines_off == []


def _circle_gap(a, b) -> float:
    """
    The distance between the true circles two workpieces draw: from
    their geometry's centres, less their radii.
    """
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = [
        wp.get_world_geometry().rect() for wp in (a, b)
    ]
    distance = math.hypot(bx0 + bx1 - ax0 - ax1, by0 + by1 - ay0 - ay1) / 2
    return distance - (ax1 - ax0) / 2 - (bx1 - bx0) / 2


@pytest.mark.asyncio
@pytest.mark.parametrize("merge_lines", ["on", "none"])
async def test_true_curves_at_gap_0_overlap_by_the_tolerance_at_most(
    doc_editor, task_mgr, step, tmp_path, merge_lines
):
    tolerance = _merge_lines(step)["tolerance"]
    if merge_lines == "none":
        step.per_step_transformers_dicts.remove(_merge_lines(step))
        tolerance = 0.0
    pieces = [bench.circle(40), bench.circle(30)]
    circles = await bench.build(doc_editor, task_mgr, tmp_path, pieces)

    await _auto_layout(doc_editor, task_mgr, circles)

    gap = _circle_gap(*circles)
    assert -tolerance <= gap < 0.2


@pytest.mark.asyncio
async def test_gap_2_lays_out_as_before_2_mm_apart(
    doc_editor, task_mgr, step, test_machine_and_config, tmp_path
):
    _machine, config = test_machine_and_config
    config.set_layout_gap_mm(2.0)
    workpieces = await _squares(doc_editor, task_mgr, tmp_path)
    strategy = NestLayoutStrategy(workpieces)
    pieces, obstacles, boundary, target, *rest = strategy.arrange_args()
    # The old path: arrange at the old clearance for a 2 mm gap.
    old = arrange(
        ExecutionContext(),
        pieces,
        obstacles,
        boundary,
        target,
        2 + 2 * OUTLINE_TOLERANCE_MM,
    )
    expected = [
        delta @ item.matrix for item, delta in strategy.deltas(old).items()
    ]

    await _auto_layout(doc_editor, task_mgr, workpieces)

    assert rest == [2 + 2 * OUTLINE_TOLERANCE_MM]
    assert all(piece.edges == () for piece in pieces)
    assert [wp.matrix for wp in strategy.items] == expected
    outlines = [bench.true_outlines(wp)[0] for wp in workpieces]
    for a, b in itertools.combinations(outlines, 2):
        assert bench.gap(a, b, within=3) >= 2

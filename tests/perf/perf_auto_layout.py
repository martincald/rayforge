"""Auto Layout on the benchmark documents: time, compactness, clashes.

Builds each benchmark of tests/doceditor/layout_bench.py on the
ilab-614 bed (1400 x 900 mm) and runs the Auto Layout action on all of
its pieces through DocEditor.layout.layout_pixel_perfect, which the
Arrange menu, the toolbar and Ctrl+Alt+A call. test_layout prints one
RESULT line per benchmark: the wall time until the result is in the
document (its undo entry exists), the longest stall of this test's
event loop meanwhile (it stands in for the main loop: the task
manager's main-thread callbacks run on it), how many pieces moved, the
notices, compactness, the pairs that clash on true outlines, and the
frames outside the boundary. Those numbers are recorded in
docs/auto-layout-notes.md.

test_profile profiles the 40-piece layout with cProfile. It builds the
strategy as layout_pixel_perfect does and calls it directly, because
the action computes on the task manager's thread, which a profiler
started here does not see.

Not named test_*.py: it must not join the default suite. Run
explicitly::

    python -m pytest tests/perf/perf_auto_layout.py -q -s

The boundary is each benchmark's stock, centred on the bed. With
PERF_LAYOUT_BOUNDARY=bed there is no stock, so the boundary is the
whole bed::

    PERF_LAYOUT_BOUNDARY=bed python -m pytest \\
        tests/perf/perf_auto_layout.py -q -s -k profile

With PERF_LAYOUT_FILL=black the pieces are drawn filled instead of as
outlines: the same outlines, but a layout that works on rendered
pixels then sees solid shapes, not rings.
"""

import asyncio
import cProfile
import io
import os
import pstats
import time

import pytest

from swiftcut.doceditor.layout import NestLayoutStrategy
from tests.doceditor import layout_bench as bench

BOUNDARY = os.environ.get("PERF_LAYOUT_BOUNDARY", "stock")
FILL = os.environ.get("PERF_LAYOUT_FILL", "none")
TIMEOUT_S = 1200.0


@pytest.fixture
def bed(test_machine_and_config):
    machine, _config = test_machine_and_config
    machine.set_axis_extents(1400, 900)
    return machine


async def _document(editor, task_mgr, folder, name):
    """The benchmark's workpieces and the layout boundary (x, y, w, h)."""
    pieces, stock_size = bench.BENCHMARKS[name]
    workpieces = await bench.build(editor, task_mgr, folder, pieces, FILL)
    if BOUNDARY == "bed":
        return workpieces, bench.BED
    stock = bench.add_stock(editor, stock_size)
    await bench.settle(editor, task_mgr)
    x0, y0, x1, y1 = stock.get_world_geometry().rect()
    return workpieces, (x0, y0, x1 - x0, y1 - y0)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(bench.BENCHMARKS))
async def test_layout(doc_editor, task_mgr, bed, tmp_path, name):
    workpieces, boundary = await _document(
        doc_editor, task_mgr, tmp_path, name
    )
    notices = []
    doc_editor.notification_requested.connect(
        lambda sender, **kwargs: notices.append(kwargs["message"]),
        weak=False,
    )
    before = [wp.matrix.copy() for wp in workpieces]
    undo = doc_editor.history_manager.undo_stack
    entries = len(undo)

    start = last = time.perf_counter()
    stall = 0.0
    doc_editor.layout.layout_pixel_perfect(workpieces)
    while len(undo) == entries:
        assert last - start < TIMEOUT_S, "no layout"
        await asyncio.sleep(0.01)
        now = time.perf_counter()
        stall, last = max(stall, now - last - 0.01), now
    seconds = last - start
    await bench.settle(doc_editor, task_mgr)

    moved = sum(wp.matrix != m for wp, m in zip(workpieces, before))
    assert moved, "the layout changed nothing"
    clashes = bench.clashes(workpieces)
    print(
        f"\nRESULT {name} fill={FILL} boundary={BOUNDARY} "
        f"{boundary[2]:g}x{boundary[3]:g} time={seconds:.1f}s "
        f"stall={stall * 1000:.0f}ms moved={moved}/{len(workpieces)} "
        f"compactness={bench.compactness(workpieces):.3f} "
        f"overlap={clashes['overlap']} close={clashes['close']} "
        f"frames_outside="
        f"{len(bench.frames_outside(workpieces, boundary))} "
        f"notices={notices}"
    )


@pytest.mark.asyncio
async def test_profile(doc_editor, task_mgr, bed, tmp_path):
    workpieces, boundary = await _document(
        doc_editor, task_mgr, tmp_path, "forty-40"
    )
    # As DocEditor.layout.layout_pixel_perfect builds it.
    strategy = NestLayoutStrategy(items=workpieces)
    profile = cProfile.Profile()

    start = time.perf_counter()
    profile.enable()
    deltas = strategy.calculate_deltas()
    profile.disable()
    seconds = time.perf_counter() - start

    assert deltas
    out = io.StringIO()
    stats = pstats.Stats(profile, stream=out)
    stats.sort_stats("tottime").print_stats(12)
    stats.sort_stats("cumulative").print_stats(12)
    print(
        f"\nPROFILE forty-40 fill={FILL} boundary={BOUNDARY} "
        f"{boundary[2]:g}x{boundary[3]:g} time={seconds:.1f}s "
        f"moved={len(deltas)}/{len(workpieces)}\n{out.getvalue()}"
    )

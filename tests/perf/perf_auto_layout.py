"""Auto Layout on the benchmark documents: time, compactness, clashes.

Builds each benchmark of tests/doceditor/layout_bench.py on the
ilab-614 bed (1400 x 900 mm) and runs the Auto Layout action on all of
its pieces through DocEditor.layout.layout_pixel_perfect, which the
Arrange menu, the toolbar and Ctrl+Alt+A call. test_layout prints one
RESULT line per benchmark: the wall time until the result is in the
document (its undo entry exists; the worker pool starts cold, as on
the first layout after launch), the time of a second run once the
pool has started (warm), the longest stall of this test's event loop
in each (it stands in for the main loop: the task manager's
main-thread callbacks run on it), the main thread's own time reading
the document and applying the result, how many pieces moved, the
notices, compactness, the pairs that clash on true outlines, and the
frames outside the boundary. Those numbers are recorded in
docs/auto-layout-notes.md.

test_profile profiles the 40-piece layout with cProfile. It builds the
strategy as layout_pixel_perfect does and calls it directly, because
the action computes in a worker process, which a profiler started
here does not see; its time is the layout's own, in-process.

test_exact_tests prints how many positions the placement engine tests
exactly per call on each benchmark (what engine.MAX_TESTS caps), and
test_spatial_index compares the engine's numpy box index with raygeo's
SpatialGrid.

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
import math
import os
import pstats
import time

import numpy as np
import pytest
from raygeo.geo.algo.spatial_grid2d import SpatialGrid
from raygeo.geo.shape.polygon import get_circle_polygon

from swiftcut.doceditor.layout import NestLayoutStrategy
from swiftcut.doceditor.layout_cmd import LayoutCmd
from swiftcut.shared.placement import engine, layout
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


def _time_main_thread_work(monkeypatch):
    """
    Times what Auto Layout does on the main thread: reading the
    document (NestLayoutStrategy's constructor) and applying the
    result (LayoutCmd._apply_deltas). The dict keeps the last ones.
    """
    seconds = {}

    def timed(name, func):
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            seconds[name] = time.perf_counter() - start
            return result

        return wrapper

    monkeypatch.setattr(
        NestLayoutStrategy,
        "__init__",
        timed("read", NestLayoutStrategy.__init__),
    )
    monkeypatch.setattr(
        LayoutCmd, "_apply_deltas", timed("apply", LayoutCmd._apply_deltas)
    )
    return seconds


async def _run(editor, workpieces):
    """
    Runs the Auto Layout action; returns the seconds until its undo
    entry exists, and the longest stall of this test's event loop
    meanwhile.
    """
    undo = editor.history_manager.undo_stack
    entries = len(undo)
    start = last = time.perf_counter()
    stall = 0.0
    editor.layout.layout_pixel_perfect(workpieces)
    while len(undo) == entries:
        assert last - start < TIMEOUT_S, "no layout"
        await asyncio.sleep(0.01)
        now = time.perf_counter()
        stall, last = max(stall, now - last - 0.01), now
    return last - start, stall


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(bench.BENCHMARKS))
async def test_layout(doc_editor, task_mgr, bed, tmp_path, name, monkeypatch):
    workpieces, boundary = await _document(
        doc_editor, task_mgr, tmp_path, name
    )
    notices = []
    doc_editor.notification_requested.connect(
        lambda sender, **kwargs: notices.append(kwargs["message"]),
        weak=False,
    )
    before = [wp.matrix.copy() for wp in workpieces]
    main = _time_main_thread_work(monkeypatch)

    seconds, stall = await _run(doc_editor, workpieces)
    await bench.settle(doc_editor, task_mgr)
    own = dict(main)

    moved = sum(wp.matrix != m for wp, m in zip(workpieces, before))
    assert moved, "the layout changed nothing"
    clashes = bench.clashes(workpieces)
    # Again, with the worker pool started: undone first, so the same
    # layout runs on the same document.
    doc_editor.history_manager.undo()
    await bench.settle(doc_editor, task_mgr)
    warm, warm_stall = await _run(doc_editor, workpieces)
    await bench.settle(doc_editor, task_mgr)
    print(
        f"\nRESULT {name} fill={FILL} boundary={BOUNDARY} "
        f"{boundary[2]:g}x{boundary[3]:g} time={seconds:.1f}s "
        f"warm={warm:.1f}s stall={stall * 1000:.0f}ms "
        f"warm_stall={warm_stall * 1000:.0f}ms "
        f"main=read {own['read'] * 1000:.0f}+apply "
        f"{own['apply'] * 1000:.0f}ms moved={moved}/{len(workpieces)} "
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


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(bench.BENCHMARKS))
async def test_exact_tests(doc_editor, task_mgr, bed, tmp_path, name):
    """
    How many grid positions each find_position call tests exactly (not
    counting its slides), which engine.MAX_TESTS caps.
    """
    workpieces, _boundary = await _document(
        doc_editor, task_mgr, tmp_path, name
    )
    counts = []
    calls = [0]
    is_free, slide = engine._Search.is_free, engine._Search.slide
    find_position = layout.find_position

    def counted_is_free(search, x, y):
        calls[0] += 1
        return is_free(search, x, y)

    def uncounted_slide(search, start, goal):
        before = calls[0]
        result = slide(search, start, goal)
        calls[0] = before
        return result

    def counted_find_position(*args, **kwargs):
        calls[0] = 0
        result = find_position(*args, **kwargs)
        counts.append(calls[0])
        return result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(engine._Search, "is_free", counted_is_free)
        patch.setattr(engine._Search, "slide", uncounted_slide)
        patch.setattr(layout, "find_position", counted_find_position)
        NestLayoutStrategy(items=workpieces).calculate_deltas()

    counts.sort()
    print(
        f"\nTESTS {name} boundary={BOUNDARY} calls={len(counts)} "
        f"max={counts[-1]} p90={counts[int(0.9 * len(counts))]} "
        f"total={sum(counts)}"
    )


def _numpy_index(boxes, queries):
    """The engine's way: one compare over the flat box array."""
    for x0, y0, x1, y1 in queries:
        np.flatnonzero(
            (boxes[:, 0] < x1)
            & (boxes[:, 2] > x0)
            & (boxes[:, 1] < y1)
            & (boxes[:, 3] > y0)
        )


def _grid_index(boxes, queries, cell):
    """SpatialGrid, built here, then the same exact box test."""
    grid = SpatialGrid(cell)
    for k, box in enumerate(boxes.tolist()):
        grid.insert(k, box)
    for query in queries.tolist():
        near = np.array(grid.query(query), dtype=int)
        b = boxes[near]
        x0, y0, x1, y1 = query
        near[(b[:, 0] < x1) & (b[:, 2] > x0) & (b[:, 1] < y1) & (b[:, 3] > y0)]


def _best_ms(func, *args):
    """The fastest of 50 runs, in ms."""
    best = math.inf
    for _ in range(50):
        start = time.perf_counter()
        func(*args)
        best = min(best, time.perf_counter() - start)
    return best * 1000


def test_spatial_index():
    """
    The engine's near-obstacle query (the first step of
    _Search.is_free): its flat numpy box array against raygeo's
    SpatialGrid. Per find_position call the index is built once and
    queried once per exact test or slide step, about 100 times.
    """
    rng = np.random.default_rng(1)
    for n in (40, 500):
        obstacles = [
            get_circle_polygon(
                tuple(rng.uniform((0, 0), (1400, 900))),
                rng.uniform(5, 40),
                64,
            )
            for _ in range(n)
        ]
        boxes = np.array(
            [(*np.min(o, axis=0), *np.max(o, axis=0)) for o in obstacles]
        )
        centres = rng.uniform((0, 0), (1400, 900), (100, 2))
        queries = np.hstack((centres - 26, centres + 26))
        grid = ", ".join(
            f"cell {cell:g} mm "
            f"{_best_ms(_grid_index, boxes, queries, cell):.2f} ms"
            for cell in (25.0, 50.0, 100.0)
        )
        print(
            f"\nINDEX obstacles={n} queries={len(queries)}: "
            f"numpy {_best_ms(_numpy_index, boxes, queries):.2f} ms; "
            f"SpatialGrid {grid}"
        )

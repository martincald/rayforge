# Auto Layout: research notes and baseline

Package E replaces the Auto Layout behind Arrange > Auto Layout
(Simple), Ctrl+Alt+A. These notes say which ideas from existing
nesting tools it takes and why, and record how today's layout
(`PixelPerfectLayoutStrategy`, `swiftcut/doceditor/layout/auto.py`)
performs before it is replaced.

## The layout Package E builds

One deterministic greedy pass, no search over orders. The pieces are
the selected items (unchanged rule); every other workpiece is a fixed
obstacle. The boundary is the visible stock's bounding box, or else the
bed, and the target is its centre. Pieces go largest first by outline
area. For each piece, Package A's engine
(`swiftcut/shared/placement/engine.py`) is asked once per distinct
orientation (the current one plus 90, 180 and 270 degrees, mirroring
kept), and the orientation that lands closest to the target wins. The
engine tests grid positions nearest the target first, rules most out
with the Minkowski sum of convex hulls, checks the rest exactly on true
outlines with 1 mm clearance, and slides the winner toward the target.
E2 moves the loop into a worker process with progress and Cancel.

## Ideas from existing tools

| Tool | Idea | Used here? | Why |
|---|---|---|---|
| SVGnest, Deepnest | No-fit polygon (NFP) of each placed part against the new part, plus an inner-fit polygon for the bin | Partly | Package A's engine uses the NFP of convex hulls as a prefilter: exact for circles, ellipses and rectangles, conservative for concave shapes, whose candidates go to an exact outline test instead. Full concave NFPs need a convex decomposition that raygeo lacks. |
| SVGnest, Deepnest | Genetic algorithm over insertion order and rotation | No | SVGnest's README says it matches commercial tools after about 5 minutes; the budget here is 3 s for 40 pieces. One greedy pass, largest first, is deterministic and repeatable. |
| SVGnest, Deepnest | NFP cache keyed by part and rotation | Not now | Duplicate parts are common in laser jobs, so it could pay off. Measure first (E2): the engine builds one hull NFP per obstacle per call, which is cheap for convex hulls. |
| Deepnest | Merge common lines (shared cut edges) | No | Needs parts edge to edge with no gap and changes the cut path; the layout keeps 1 mm between parts. |
| Deepnest, SVGnest | Placement score `width*2+height` (or `*5`, "gravity") | No | Packs parts against one side (strip packing). Here the pieces gather around the boundary's centre. |
| libnest2d | First-fit NFP placer; objective = distance of the item's bbox centre to the bin centre; 4 rotations | Yes | The same objective as the lead decision (target = boundary centre, keep the rotation that lands closest). Its default `CONVEX_ONLY` NFP has the same limit as A's hull prefilter: concave pockets are not filled. |
| libnest2d | NLopt subplex search along the NFP edges | Partly | A's engine slides the first free grid position toward the target by bisection instead; no NLopt dependency. |
| nest2D, pynest2d | Python bindings to libnest2d | No | No osx-arm64 build: PyPI `python-libnest2d` 0.1.3 ships wheels for manylinux x86_64 and win_amd64 only, and conda-forge has no `pynest2d`. It would add a C++ build (Boost, NLopt, Clipper) to pixi and to the Windows env. LGPL. |
| rectpack | MaxRects / Skyline / Guillotine rectangle packing | No (placer), yes (sort) | It packs bounding boxes, which wastes the area around circles, ellipses and L shapes, has no clearance, and minimises the bin count rather than pulling to a point. Its AREA sort (largest first) is taken. |
| PrusaSlicer arrange | `GravityKernel`: fitness = -‖item centroid + move - sink‖², sink = bed centre | Yes | Exactly "closest to the centre". Re-implemented as the engine's distance-to-target order, not copied (PrusaSlicer is AGPL-3.0, from memory; the licence was not re-fetched). |
| PrusaSlicer arrange | Neighbours from a boost r*-tree | Measure (E2) | The engine keeps a flat numpy array of obstacle boxes as its index. E2 measures raygeo's `SpatialGrid` against it at 40 and 500 obstacles and keeps whichever is faster; no rtree or shapely dependency. |
| raygeo `algo.nest2d.place_parts` | Bundled NFP nester | No | Measured while mapping the code (raygeo 1.38.3): `spacing` has no effect (circles 0.0028 mm apart), one fixed angle per part, the result is a bottom strip, and one call cannot report progress or be cancelled. |

Sources: https://github.com/Jack000/SVGnest (README,
`svgnest.js`, `util/placementworker.js`);
https://github.com/Jack000/Deepnest and
https://github.com/deepnest-next/deepnest (`main/background.js`);
https://github.com/tamasmeszaros/libnest2d and
https://raw.githubusercontent.com/tamasmeszaros/libnest2d/master/include/libnest2d/placers/nfpplacer.hpp;
https://github.com/Ultimaker/pynest2d,
https://pypi.org/pypi/python-libnest2d/json,
https://api.anaconda.org/package/conda-forge/pynest2d;
https://github.com/secnot/rectpack;
https://raw.githubusercontent.com/prusa3d/PrusaSlicer/master/src/slic3r-biz-arrange/src/Slic3r/Biz/Arrange/Kernels/GravityKernel.cpp
(and `TMArrangeKernel.cpp`, `Packer.cpp` beside it).

## Before

Today's layout at base commit 1e7a01ea2, measured on an Apple M1
(8 GB, macOS 26.7) with Python 3.14.6, numpy 2.5.2, scipy 1.18.0 and
raygeo 1.38.3.

**Benchmarks** (`tests/doceditor/layout_bench.py`, reusable by the
later steps). Every piece is an SVG of an unfilled outline (as cut
files usually are), imported one after another through
`DocEditor.file.load_file_from_path` onto the ilab-614 bed
(1400 x 900 mm):

- circles-20: 20 circles, 10 to 80 mm across;
- mixed-18: six circles, six ellipses and six rectangles;
- forty-40: 10 circles, 10 ellipses, 14 rectangles, and six concave
  pieces (two L, two U, a cross, a five-point star).

The boundary is a stock centred on the bed with about twice the
pieces' area (250 x 200, 280 x 200 and 500 x 320 mm), so that the
current layout finishes in seconds; the full bed is measured
separately below.

**Measures** (`tests/perf/perf_auto_layout.py`). The Auto Layout action
(`DocEditor.layout.layout_pixel_perfect`, what the menu, the toolbar
and Ctrl+Alt+A call) runs on all pieces. *time* runs until its undo
entry exists, i.e. the result is in the document. *stall* is the
longest the test's event loop, which runs the task manager's
main-thread callbacks like the GTK main loop does in the app, went
without running meanwhile. *compactness* is the bounding box area of
the laid-out outlines over the sum of their areas; it is at least 1
for any layout without overlaps, and lower is better. *overlap* counts
the pairs of pieces whose true outlines (polygonized to 0.01 mm) cross
or nest; *close* the pairs that do not, but are less than 1 mm apart
(exact vertex-to-edge distance); *frames_outside* the pieces whose
frame leaves the boundary.

```
RESULT circles-20 fill=none boundary=stock 250x200 time=7.1s stall=32ms moved=20/20 compactness=0.929 overlap=19 close=0 frames_outside=0 notices=[]
RESULT mixed-18 fill=none boundary=stock 280x200 time=5.4s stall=10ms moved=18/18 compactness=0.998 overlap=20 close=0 frames_outside=0 notices=[]
RESULT forty-40 fill=none boundary=stock 500x320 time=34.9s stall=13ms moved=40/40 compactness=0.908 overlap=55 close=0 frames_outside=0 notices=[]
```

Every benchmark ends with overlapping pieces: 19, 20 and 55 pairs.
Compactness below 1 says the same thing: the pieces cover each other.
The main cause is the collision mask. It is rendered from the piece,
and an unfilled outline renders as a ring, so the inside of a large
circle counts as free space and small pieces land in it. Drawing the
same pieces filled (same outlines, solid masks;
`PERF_LAYOUT_FILL=black`) removes most of the overlaps:

```
RESULT circles-20 fill=black boundary=stock 250x200 time=10.2s stall=68ms moved=20/20 compactness=1.312 overlap=0 close=1 frames_outside=0 notices=[]
RESULT mixed-18 fill=black boundary=stock 280x200 time=5.0s stall=5ms moved=18/18 compactness=1.335 overlap=0 close=2 frames_outside=1 notices=[]
RESULT forty-40 fill=black boundary=stock 500x320 time=33.4s stall=15ms moved=40/40 compactness=1.341 overlap=8 close=3 frames_outside=1 notices=[]
```

The 8 pairs left in forty-40 and the close pairs were not analysed
pair by pair. The layout map attributes the first to masks that are
upside down (only shapes that are not vertically symmetric, here the
L, U and star pieces, can overlap from it) and the second to a
dilation that keeps 0.5 mm along the axes but about 0.35 mm on the
diagonal; it also found every piece shifted by an extra 0.5 mm, which
may be what puts one frame outside the stock. The time of the first
benchmark in a session varies: over seven runs circles-20, always
first, took 6.3 to 11.6 s, mixed-18 5.0 to 5.4 s and forty-40 33.4 to
35.6 s.

What the benchmarks do not exercise: other workpieces as obstacles
(they lay out every piece; today unselected pieces are ignored,
another source of overlaps), mirrored pieces (today's layout drops the
mirroring), groups, and Cancel (it does not stop the computation).

**Full bed.** Without a stock the canvas is the whole bed at 8 px/mm
(80.6 Mpx). forty-40 then takes seven and a half minutes:

```
RESULT forty-40 fill=none boundary=bed 1400x900 time=447.6s stall=250ms moved=40/40 compactness=1.699 overlap=9 close=0 frames_outside=0 notices=[]
```

With room to spare, fewer small pieces fall into rings, but 9 pairs
still overlap. Each piece takes the first free canvas position in row
order (`_find_first_fit`), so the result starts from a corner of the
bed, not its centre (read from the code, not measured). The longest
event-loop stall was 250 ms here and 5 to 68 ms on the stocks: the
computation runs on the task manager's own thread, so it can only
hold the loop through the GIL (inferred, not traced). E2 measures the
GTK main loop itself.

**Profile** of forty-40 with cProfile (py-spy is not installed in the
environment). The strategy is built as `layout_pixel_perfect` builds it
and called directly, because the action computes on the task manager's
thread, which a profiler in the test does not see. On the stock
(34.6 s, 160 placement attempts, one per piece and rotation, 0.21 s
each):

```
ncalls  tottime  cumtime  function
   320   11.745   11.745  scipy.fft pyduccfft.r2c
   160    9.223    9.223  scipy.fft pyduccfft.c2r
   160    3.961    3.961  ndarray.nonzero (in np.argwhere)
  1600    1.950    1.950  ndarray.astype
   160    1.821    1.822  numpy _wrapit (np.argwhere's transpose)
   160    1.090   23.725  scipy.signal _freq_domain_conv
   320    0.520    0.520  ndarray.round
   160    0.513   33.491  auto.py _find_first_fit
    40    0.447   33.942  auto.py _find_best_placement
```

On the full bed (442.5 s, 2.77 s per attempt):

```
ncalls  tottime  cumtime  function
   160  147.258  147.258  scipy.fft pyduccfft.c2r
   320  113.976  113.977  scipy.fft pyduccfft.r2c
   164   83.747   83.789  numpy _wrapit (np.argwhere's transpose)
   164   41.358   41.358  ndarray.nonzero (in np.argwhere)
  1627   16.715   16.715  ndarray.astype
   160    8.435  275.599  scipy.signal _freq_domain_conv
    40    4.800  441.200  auto.py _find_best_placement
   339    4.403    4.403  ndarray.round
   160    3.688  283.151  scipy.signal fftconvolve
   160    3.492  436.387  auto.py _find_first_fit
```

The cost is one FFT correlation of the whole canvas per piece and
rotation (59 % on the bed), plus `np.argwhere` listing every free
position only to take the first (28 %), and the float conversions and
rounding around them. It grows with the canvas area, not with the
number of pieces: an attempt on the bed costs 13 times one on the
500 x 320 mm stock.

**Commands** (run from the repository root; these runs used the
sandbox wrapper from the package instructions around the same
`python -m pytest` lines):

```
python -m pytest tests/perf/perf_auto_layout.py -q -s -k test_layout
PERF_LAYOUT_FILL=black python -m pytest tests/perf/perf_auto_layout.py -q -s -k test_layout
python -m pytest tests/perf/perf_auto_layout.py -q -s -k test_profile
PERF_LAYOUT_BOUNDARY=bed python -m pytest tests/perf/perf_auto_layout.py -q -s -k test_profile
PERF_LAYOUT_BOUNDARY=bed python -m pytest tests/perf/perf_auto_layout.py -q -s -k "test_layout and forty"
```

**The bar for E3.** No layout without overlaps can reach today's
compactness on outline pieces (0.93, 1.00, 0.91): those numbers come
from pieces lying on top of each other. The fair bar is today's layout
on filled pieces, where it sees solid shapes: 1.31 (circles-20), 1.34
(mixed-18) and 1.34 (forty-40), with zero overlaps required instead of
0, 0 and 8; and 1.70 for forty-40 on the full bed.

## After (E2: off the main loop)

Measured on the same Apple M1 as Before, with the E1 layout (true
outlines, Package A's engine) now computed in a worker process.

**What runs where.** Pressing Auto Layout reads the document on the
main thread (`NestLayoutStrategy`: outlines, frames, obstacles), then
`TaskManager.run_process` runs `swiftcut.shared.placement.arrange` in
the spawn worker pool under the task key `auto-layout`. The worker
reports one progress step per piece and checks for Cancel before each
piece (`ExecutionContextProxy.is_cancelled`, one call to the pool's
Manager per piece). The result comes back as plain data and is applied
on the main thread as one undo step. A progress row at the end of the
toolbar (label, bar, Cancel) is shown only while that task runs;
Cancel calls `TaskManager.cancel_task("auto-layout")`. A cancelled
layout changes no matrix and adds no undo entry, and the worker stops
at its next piece.

**The pool's first start.** The pool is created on the first
`run_process` call. Before this change, that call blocked its caller,
here the main thread. In a small script, `TaskManager._ensure_pool()`
(two spawn Managers and eight workers) took 170 to 217 ms over three
runs. In the main window, with the 40 pieces loaded, it held the main
loop for 413 and 456 ms: the frame-time test below, run with only this
change reverted. `run_process` now starts the pool on a helper thread
and submits from there. `cancel_task` copes with a task whose pool is
not up yet, and `shutdown` waits for a start in progress. Started as
`python -m swiftcut`, the app's workers do not re-run its
`__main__`: multiprocessing's spawn skips a package's `__main__`
module (`_fixup_main_from_name`). So a worker imports the pool code,
the initializer (`swiftcut.worker_init`), and what the task's function
and data need. In the tests the initializer comes from
`tests/conftest.py`, which imports more.

**Timings** (`tests/perf/perf_auto_layout.py`). *time* is a cold start:
the first layout of a fresh task manager, pool start included. *warm*
is a second run on the same document after undo. *main* is the main
thread's own work: reading the document and applying the result. The
E1 column is the E1 code computing on the task manager's thread,
measured in the same session.

| Boundary | Benchmark | E1 | E2 cold | E2 warm | Stall cold / warm | Main: read + apply |
|---|---|---|---|---|---|---|
| stock | circles-20 | 0.6 s | 1.4 s | 0.6 s | 28 / 21 ms | 21 + 1 ms |
| stock | mixed-18 | 0.5 s | 1.2 s | 0.5 s | 11 / 20 ms | 8 + 1 ms |
| stock | forty-40 | 1.2 s | 2.0 s | 1.2 s | 20 / 29 ms | 18 + 2 ms |
| bed | circles-20 | 0.6 s | 1.3 s | 0.7 s | 21 / 27 ms | 17 + 1 ms |
| bed | mixed-18 | 0.5 s | 1.2 s | 0.5 s | 17 / 18 ms | 12 + 1 ms |
| bed | forty-40 | 1.2 s | 2.0 s | 1.2 s | 36 / 25 ms | 29 + 1 ms |

All within the 3 s target. A warm run takes as long as E1's run on
the task manager's thread. The first run after launch costs about
0.8 s more: the pool starting and its first worker importing what it
needs (not broken down further).
The layout's own time in-process (`test_profile`, under cProfile) is
1.3 s for forty-40 on the stock and on the bed. `classify` (the hull
NFP prefilter) is still the largest part. The E1 check that skips
quarter turns giving the same shape (`layout._same_shape`) costs about
0.38 s. Compactness, clashes and frames are unchanged from E1 on every
row (1.649 / 1.491 / 1.491 on the stocks, 1.629 / 1.549 / 1.666 on the
bed, 0 overlap, 0 close, 0 frames outside); E3 owns compactness.

**The GTK main loop** (`tests/ui_gtk/doceditor/test_auto_layout_ui.py`).
The test opens the main window on the 1400 x 900 bed, imports
forty-40, and activates `win.layout-pixel-perfect` (Ctrl+Alt+A's
action). A 16 ms GLib timer records the longest gap from the press
until the undo entry exists, plus one tick. The cold pool start, the
document read and the apply are all inside that window; nothing is
excluded. The bar is 100 ms.

| Code | Runs | Longest gap | Result in the document after |
|---|---|---|---|
| E1 (task manager's thread) | 3 | 59, 84, 125 ms | 1.3 s |
| E2, pool started on the main thread (manager.py reverted) | 2 | 413, 456 ms | not recorded |
| E2 (worker process), cold pool | 6 | 60, 63, 66, 72, 76, 79 ms | 1.9 to 2.0 s (3 timed) |
| E2, cold pool, progress row disabled | 2 | 64, 66 ms | 1.85, 1.9 s |
| E2, pool started just before the press | 4 | 32, 39, 67, 69 ms | 1.4 to 2.6 s |

E1 passed this bar twice in three runs, so the test does not tell E1
from E2 reliably. It does catch a pool start on the main thread. In
E2 cold, the longest gap comes about 0.1 s after the press, while the
helper thread spawns the pool's processes. That the spawn holds the
main thread there is inferred from the timing, not traced. The
progress row is not the cause: the gap is the same with it disabled.
The cold runs leave 21 to 40 ms below the bar, and a review run once
went over it, so on a loaded machine the test can fail; the margin is
accepted as is, for the owner to judge.
With the pool started on a thread just before the press, its workers
were still starting up, so those runs vary; one took 2.6 s. The read
takes 18 to 30 ms of main-thread time and the apply 7 to 9 ms, with
the canvas drawing. The "manager.py reverted" row is the test itself
with `swiftcut/shared/tasker/manager.py` put back to E1's. The last
two rows, the timings of the cold rows, and three of the cold runs
come from a temporary variant of the test that also recorded when
each gap came. The last two runs of the last row also had the row
disabled.

**Spatial index.** `_Search.is_free` first looks for obstacles whose
boxes overlap the grown piece's box. It does this with one vectorized
compare over a flat numpy array of obstacle boxes. `test_spatial_index`
times that against raygeo's `SpatialGrid` (built once, then queried 100
times, about one find_position call's worth):

```
INDEX obstacles=40 queries=100: numpy 0.39 ms; SpatialGrid cell 25 mm 0.43 ms, cell 50 mm 0.42 ms, cell 100 mm 0.43 ms
INDEX obstacles=500 queries=100: numpy 0.48 ms; SpatialGrid cell 25 mm 0.75 ms, cell 50 mm 0.66 ms, cell 100 mm 0.69 ms
```

**Decision: keep numpy.** At 40 obstacles the two are within 0.15 ms
per 100 queries either way: this test has numpy ahead, and an earlier
scratch version of the same loop had the grid ahead. At 500 obstacles
the grid is 40 to 60 % slower in both. Either way, the query costs
under 1 ms of a find_position call, which averages about 16 ms on
forty-40 (1.2 s for 73 calls). The flat box array is the index, and
the bbox prefilter still runs before every polygon test. An index
would not help `classify`, the largest cost, either: its grid spans
the whole boundary, so every obstacle is relevant to it.

**Cap on exact tests.** `find_position(..., max_tests=MAX_TESTS)` with
`MAX_TESTS = 1000`. It counts the grid positions given an exact
outline test. The slides are not counted; each is a bisection of at
most about 18 steps. Once the cap is reached, the nearest position
known to be free without a test is taken (then slid as usual). If there
is none, the piece does not fit.

- Benchmarks (`test_exact_tests`): circles-20 and mixed-18 need no
  exact test, because convex pieces are decided by the hull prefilter.
  forty-40 needs at most 33 per call on the stock (276 in all) and 52
  on the bed (302 in all), so a cap of 1000 is about 20 times the
  largest seen and does not change any benchmark result.
- Worst case: a bed-sized comb (3 mm teeth, 3 mm gaps, 936 vertices)
  and a small L that fits nowhere. Uncapped, it took 8,050 exact tests
  and 3.8 s, and 9.2 s with 10 mm gaps (38,925 tests). Capped, each
  call takes 0.26 to 0.48 s.
- The cap also bounds the import placement (A3), which runs on the
  main thread: the same comb now costs at most about 0.5 s per import
  there.
- `tests/shared/test_placement.py` covers the cap and the fall-back.

**auto.py.** `PixelPerfectLayoutStrategy` (`doceditor/layout/auto.py`)
was deleted in E1, after the Before numbers above were recorded. E2
checked what else it alone used. Nothing in `swiftcut/` or `tests/`
is left unused: `geometry_to_cairo` and cairo have other users, and
scipy stays for the sketcher addon. The only remaining mentions are the
generated `.po`/`.pot` source comments, which change when the
catalogues are next regenerated, and the historical note in
`docs/PERF_AUDIT.md`. Both are left as they are.

**The document changing meanwhile.** The window stays usable while
the worker computes, so the document can change before the result
arrives. The result is applied only if the editor still has the same
document and no laid-out item, workpiece or stock in it moved, came or
went since it was read (`NestLayoutStrategy.changed` compares world
transforms, so pipeline updates do not count). Otherwise nothing
moves, no undo entry is added, and a notice says the document changed.
This covers a document opened meanwhile, an item deleted or moved, and
an obstacle moved onto the layout; `tests/doceditor/test_auto_layout.py`
tests the replaced document and the moved obstacle.

**Pieces that fit nowhere.** Such a piece stays where it is, and every
other piece is kept clear of it, also the larger ones placed before it
was found: a piece too large for the boundary any way up is known
before the layout starts, and finding another starts the layout over
with it fixed (at most once per piece).

A second Auto Layout started while one runs replaces it (same task
key): the first is cancelled and the second's result applies (read
from the code, not tested).

Not verified: the frozen .app and the Windows build, where spawning
the pool may cost more (NEEDS-OWNER).

**Commands** (from the repository root, inside the sandbox wrapper
from the package instructions):

```
python -m pytest tests/perf/perf_auto_layout.py -q -s -k test_layout
PERF_LAYOUT_BOUNDARY=bed python -m pytest tests/perf/perf_auto_layout.py -q -s -k test_layout
python -m pytest tests/perf/perf_auto_layout.py -q -s -k "test_profile or test_exact_tests or test_spatial_index"
PERF_LAYOUT_BOUNDARY=bed python -m pytest tests/perf/perf_auto_layout.py -q -s -k "test_profile or test_exact_tests"
python -m pytest -m ui tests/ui_gtk/doceditor/test_auto_layout_ui.py -q -s
```

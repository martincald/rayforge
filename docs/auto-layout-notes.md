# Auto Layout: notes

Package E replaced Arrange > Auto Layout (Simple), Ctrl+Alt+A. The old
layout (`PixelPerfectLayoutStrategy`, `doceditor/layout/auto.py`,
deleted in E1) collided rendered masks on a pixel canvas. The new one
(`doceditor/layout/nest.py`, `shared/placement/layout.py`) places true
outlines 1 mm apart with Package A's engine
(`shared/placement/engine.py`), in a worker process with progress and
Cancel. Measured on an Apple M1 (8 GB, macOS 26.7), Python 3.14.6,
numpy 2.5.2, scipy 1.18.0, raygeo 1.38.3.

## Ideas from existing tools

| Tool | Idea | Used here? | Why |
|---|---|---|---|
| SVGnest, Deepnest | No-fit polygon (NFP) of each placed part against the new part, plus an inner-fit polygon for the bin | Partly | The engine uses the NFP of convex hulls as a prefilter: exact for circles, ellipses and rectangles, conservative for concave shapes, which then get an exact outline test. Full concave NFPs need a convex decomposition that raygeo lacks. |
| SVGnest, Deepnest | Genetic algorithm over order and rotation | No | SVGnest's README says it matches commercial tools after about 5 minutes; the budget here is 3 s for 40 pieces. One greedy pass, largest first, is deterministic. |
| SVGnest, Deepnest | NFP cache keyed by part and rotation | No | One hull NFP per obstacle per call is cheap; no NFP line in the profile's top 5. |
| Deepnest | Merge common lines | No | Needs parts edge to edge; the layout keeps 1 mm between parts. |
| Deepnest, SVGnest | Score `width*2+height` ("gravity") | No | Strip packing against one side. Tried in E3 on a scratch copy: 1.289 / 1.309 / 1.332 on the stocks, but on the bed a 121 x 897 mm column along the left edge, off the centre, and 1.96 s in-process for forty-40. |
| libnest2d | First-fit NFP placer, 4 rotations, distance of the item's box centre to the bin centre | Partly | Rotations kept; the bin centre takes the first piece and breaks ties. Centre pull alone (E1, E2) gives a round pile that misses the bar (After). |
| libnest2d | NLopt search along the NFP edges | Partly | A bisection slide and a pattern search instead; no NLopt. |
| nest2D, pynest2d | Python bindings to libnest2d | No | No osx-arm64 build (PyPI `python-libnest2d` 0.1.3: manylinux x86_64 and win_amd64 only; no conda-forge `pynest2d`); adds a C++ build (Boost, NLopt, Clipper) to pixi and Windows. LGPL. |
| rectpack | MaxRects / Skyline / Guillotine | Sort only | Packs bounding boxes (wastes the area around round and L shapes), no clearance, minimises bins. Its largest-first sort is taken. |
| PrusaSlicer arrange | `GravityKernel`: fitness = -‖centroid + move - sink‖², sink = bed centre | Partly | As libnest2d: first piece and ties. Re-implemented, not copied (AGPL-3.0, from memory). |
| PrusaSlicer arrange | `TMArrangeKernel`: candidates scored by the pile's bounding box with the item added | Yes, adapted | E3's objective: the pile's box grows least, by its area and its larger side. That the kernel scores the pile's box is recalled from E0's reading, not re-fetched. |
| PrusaSlicer arrange | Neighbours from a boost r*-tree | No | raygeo's `SpatialGrid` measured against the flat numpy box array (After): no faster. |
| raygeo `algo.nest2d.place_parts` | Bundled NFP nester | No | `spacing` has no effect (circles 0.0028 mm apart), one fixed angle per part, a bottom strip, no progress or Cancel. |

Sources: https://github.com/Jack000/SVGnest (README, `svgnest.js`, `util/placementworker.js`); https://github.com/Jack000/Deepnest, https://github.com/deepnest-next/deepnest (`main/background.js`);
https://github.com/tamasmeszaros/libnest2d, https://raw.githubusercontent.com/tamasmeszaros/libnest2d/master/include/libnest2d/placers/nfpplacer.hpp;
https://github.com/Ultimaker/pynest2d, https://pypi.org/pypi/python-libnest2d/json, https://api.anaconda.org/package/conda-forge/pynest2d; https://github.com/secnot/rectpack;
https://raw.githubusercontent.com/prusa3d/PrusaSlicer/master/src/slic3r-biz-arrange/src/Slic3r/Biz/Arrange/Kernels/GravityKernel.cpp (and `TMArrangeKernel.cpp`, `Packer.cpp` beside it).

## Benchmarks and measures

`tests/doceditor/layout_bench.py`: unfilled SVG outlines imported onto
the ilab-614 bed (1400 x 900 mm). circles-20: 10 to 80 mm. mixed-18:
six each of circles, ellipses, rectangles. forty-40: 10 circles, 10
ellipses, 14 rectangles, two L, two U, a cross, a star. Stocks centred
on the bed, about twice the pieces' area (250 x 200, 280 x 200,
500 x 320 mm); "bed" means no stock. `tests/perf/perf_auto_layout.py`
runs the action; *time* until its undo entry exists. Cells:
*compactness* (outlines' bounding box area over their summed areas,
lower is better) / overlapping pairs / pairs under 1 mm / frames
outside, on true outlines (0.01 mm). *Nearest gap*: each piece's gap
to its nearest neighbour it does not overlap, min / median over the
pieces, mm.

## Before: the old layout

At 1e7a01ea2: masks at 8 px/mm dilated by `margin_mm` (0.5 in the
action), each piece at the first free canvas position in row order by
an FFT correlation. Unfilled outlines render as rings, so small pieces
land inside large ones; *filled* (`PERF_LAYOUT_FILL=black`) draws the
same outlines solid, as the old layout expects.

| Boundary | Benchmark | Outlines, 0.5 mm | Filled, 0.5 mm | Filled, 0.625 mm = fair bar | Filled, 1.0 mm |
|---|---|---|---|---|---|
| stock | circles-20 | 0.929 / 19 / 0 / 0, 7.1 s | 1.312 / 0 / 1 / 0, 8.6 s | **1.328** / 0 / 0 / 0 | 1.371 / 0 / 0 / 0, 11.8 s |
| stock | mixed-18 | 0.998 / 20 / 0 / 0, 5.4 s | 1.335 / 0 / 2 / 1, 6.4 s | **1.337** / 0 / 0 / 0 | 1.375 / 0 / 0 / 2, 6.3 s |
| stock | forty-40 | 0.908 / 55 / 0 / 0, 34.9 s | 1.341 / 8 / 3 / 1, 43.0 s | **1.346** / 8 / 0 / 1 | 1.414 / 7 / 0 / 0, 43.2 s |
| bed | forty-40 | 1.699 / 9 / 0 / 0, 447.6 s | 1.694 / 1 / 2 / 0, 449.8 s | **1.700** / 0 / 0 / 0 | 1.696 / 0 / 0 / 0, 464.0 s |

| Nearest gap, filled, stock | circles-20 | mixed-18 | forty-40 |
|---|---|---|---|
| Old, margin 0.5 mm | 0.936 / 1.132 | 0.997 / 1.105 | 0.881 / 1.150 |
| Old, margin 0.625 mm (bed forty-40: 1.284 / 1.450) | 1.116 / 1.302 | 1.174 / 1.294 | 1.057 / 1.389 |
| Old, margin 1.0 mm | 1.651 / 1.931 | 1.650 / 1.919 | 1.607 / 2.156 |
| New, unfilled (After; the same on the bed) | 1.111 / 1.112 | 1.111 / 1.112 | 1.111 / 1.112 |

**Why the bar is the 0.625 mm column** (the owner's rule: 1 mm
between outlines). The old layout grows the masks of the placed pieces
and of the one being placed by `int(margin_mm * 8)` px, so pieces end
about twice the margin apart. At 0.5 mm 1 to 3 pairs keep under 1 mm;
at 1.0 mm (the first bar chosen) every pair keeps 1.6 mm or more, so
that bar favoured the new layout. 0.625 mm (5 px) is the smallest
margin with no pair under 1 mm among those that do not overlap; its
median gaps still exceed the new layout's, so the bar leans slightly
toward it. forty-40's stock bar is harder than fair: the old layout
reaches it with 8 overlapping pairs.
Measured in a temporary worktree at b672de66f (E0: old `auto.py`, the
harness), `margin_mm` from an environment variable and a nearest-gap
print added, uncommitted, since removed; the 0.625 mm runs shared the
machine, so their times are left out.

**Profile** (cProfile, forty-40, top 5 by own time). Stock (34.6 s):
FFT `r2c` 11.7 s, FFT `c2r` 9.2 s, `ndarray.nonzero` in `np.argwhere`
4.0 s, `ndarray.astype` 2.0 s, `np.argwhere`'s transpose 1.8 s. Bed
(442.5 s): `c2r` 147 s, `r2c` 114 s, transpose 84 s, `nonzero` 41 s,
`astype` 17 s. A whole-canvas correlation per piece and rotation, then
every free position listed to take the first: cost grows with canvas
area. On the task manager's thread the event loop stalled up to 152 ms
(stocks) and 270 ms (bed).

## After

**What runs where.** The main thread reads the document, a spawn
worker runs `shared.placement.arrange` (progress and Cancel per
piece), and the main thread applies the result as one undo step if the
document did not change meanwhile. The pool starts on a helper thread
(on the main thread it held the main loop 413 and 456 ms).

**The objective (user-visible change).** Auto Layout now packs a
tight, nearly square pile centred on the stock or the bed instead of
the old layout's top-left strip. Largest first, the first piece goes
to the centre; each later piece, in each distinct quarter turn, goes
where the box around the frames placed so far costs least (its area
plus twice its larger side squared), then nearest the centre. A slide
toward the centre is kept only if the cost does not rise; a pattern
search (eight directions, half the grid step down to 0.05 mm) then
moves it while the cost falls or, at equal cost, it nears the centre.
Overlap test, clearance, cap and prefilter are unchanged. Opt-in: only
`arrange` passes `find_position(..., cost=...)`; import placement
(A2/A3) keeps the free position nearest the bed centre
(`tests/shared/test_placement.py` unchanged).

**Choosing it** (on pickled `arrange` arguments of the benchmarks,
which give the action's result exactly). The lead asked for the
smallest pile-box *area*; alone it stretches the pile into strips on
the bed (80 x 385, 127 x 830, 526 x 84 mm). The larger side squared
keeps it square. Weights 1.2 to 3 all meet the circles-20 and mixed-18
bars (1.307 to 1.316, 1.299 to 1.335) with forty-40 at 1.354 and the
same bed results; below 1.2 results jump (forty-40 1.261 at 0.9, 1.354
at 1.0; circles-20 1.375 from 0.6 to 1.1); 2 is away from the jumps.
No single objective tried also meets forty-40's stock bar. The better
of two does, but runs both: 2.9 s in-process, over 3 s cold; two
workers side by side were not tried. Also tried, none better:
perimeter then area, the larger side squared alone, largest first by
frame area or frame side. The last four rows' times are this round's.

| Objective (slide kept only if no worse) | circles-20 | mixed-18 | forty-40 | Bed: circles / mixed / forty (pile mm) | forty-40 in-process |
|---|---|---|---|---|---|
| Fair bar | 1.328 | 1.337 | 1.346 | - / - / 1.700 | 3 s cold target |
| Nearest the centre (E1, E2) | 1.649 | 1.491 | 1.491 | 1.629 / 1.549 / 1.666 | 1.3 s |
| Smallest area, pattern search | 1.389 | 1.341 | 1.369 | 1.439 (80x385) / 1.598 (526x84) / 1.414 (127x830) | 1.7 s |
| Smallest area, pattern search, 4 starts | 1.322 | 1.380 | 1.351 | 1.383 (81x366) / - / 1.415 (127x828) | 2.6 s |
| Larger side, then area, pattern search | 1.316 | 1.350 | 1.354 | 1.375 / 1.361 / 1.340 | 1.5 s |
| Area + 0.5 x larger side², pattern search | 1.347 | 1.299 | 1.339 | 1.345 / 1.396 / 1.339 | 1.5 s |
| Better of the two rows above | 1.316 | 1.299 | 1.339 | 1.345 / 1.361 / 1.339 | 2.9 s |
| **Area + 2 x larger side², pattern search (shipped)** | **1.316** | **1.304** | **1.354** | 1.375 (174x170) / 1.357 (196x192) / 1.340 (321x312) | 1.4 s |

**Results through the action** (`test_layout`, two runs each on stock
and bed, alone on the machine, the same compactness both times):

| Boundary | Benchmark | Fair bar | After | Cold | Warm | Main: read + apply |
|---|---|---|---|---|---|---|
| stock | circles-20 | 1.328 | 1.316 / 0 / 0 / 0 | 1.4-1.5 s | 0.7-0.8 s | 17-18 + 1 ms |
| stock | mixed-18 | 1.337 | 1.304 / 0 / 0 / 0 | 1.4 s | 0.6-0.7 s | 19-20 + 1 ms |
| stock | forty-40 | 1.346 | 1.354 / 0 / 0 / 0, **misses** | 2.2-2.3 s | 1.6-1.7 s | 19-22 + 1-2 ms |
| bed | circles-20 | - | 1.375 / 0 / 0 / 0 | 1.5-1.6 s | 0.8 s | 17-21 + 1 ms |
| bed | mixed-18 | - | 1.357 / 0 / 0 / 0 | 1.3 s | 0.6-0.7 s | 18 + 1 ms |
| bed | forty-40 | 1.700 | 1.340 / 0 / 0 / 0 | 2.2-2.3 s | 1.6 s | 23-24 + 1 ms |

**E3 gap.** Zero clashes and every frame inside everywhere; all meet
their bar but forty-40 on the stock, 0.008 over a bar the old layout
reached only with 8 overlapping pairs. *Cold*: a fresh task manager's
first layout, pool start (about 0.7 s) included; the event loop
stalled at most 32 ms. `test_auto_layout.py` asserts zero clashes and
the bar per benchmark (the miss `xfail(strict=True)`) and E1's zero
overlaps on 20 circles, mixed, ellipses and forty; `test_arrange.py`'s
pile test fails with the centre-pull objective.

**Profile** (forty-40 on the stock, in-process 1.6 s under cProfile,
top 5 by own time): raygeo `do_polygons_intersect` 0.29 s (5,741
calls), numpy reductions 0.18 s, raygeo `translate_polygon` 0.15 s,
`numpy.array` 0.12 s, the prefilter's `_inside` 0.11 s. `classify`
(the hull NFP prefilter) is the largest part cumulatively.

**Main loop** (`tests/ui_gtk/doceditor/test_auto_layout_ui.py`, main
window, forty-40 on the bed, Ctrl+Alt+A): a 16 ms GLib timer records
the longest gap from the press to one tick after the result is in.
The first layout, which starts the pool (cold), is measured only;
after undo the same layout on the started pool (warm) is asserted
under 100 ms. Five runs: **cold 47, 63, 71, 67, 68 ms; warm 34, 36,
33, 26, 37 ms.** Earlier cold runs reached 79 ms and once over 100 ms
while the helper thread spawns the pool (inferred, not traced).

**Spatial index.** `_Search.is_free` finds obstacles whose boxes meet
the grown piece's with one compare over a flat numpy array.
`test_spatial_index` (100 queries, best of 50): 40 obstacles, numpy
0.42 ms, `SpatialGrid` 0.44 to 0.47 ms (cells 25, 50, 100 mm); 500,
numpy 0.50 ms, grid 0.69 to 0.79 ms. **Kept numpy**: never slower, under
1 ms of a 22 ms find_position call; `classify` costs most.

**Cap.** `engine.MAX_TESTS = 1000` exact tests of grid positions per
find_position call (not slides or pattern search); past it the best
position known free without a test is taken, else the piece does not
fit. `test_exact_tests`: circles-20 and mixed-18 need none; forty-40 at
most 27 per call on the stock, 73 on the bed: the cap changes no
result. Worst case: a bed-sized comb (936 vertices) and an L fitting
nowhere took 8,050 tests and 3.8 s uncapped, 0.26 to 0.48 s capped. It
also bounds import placement (A3) on the main thread.

Not verified: the frozen .app and the Windows build, where spawning
the pool may cost more (NEEDS-OWNER).

## Commands

From the repository root, inside the package's sandbox wrapper:

```
python -m pytest tests/perf/perf_auto_layout.py -q -s -k test_layout
PERF_LAYOUT_BOUNDARY=bed python -m pytest tests/perf/perf_auto_layout.py -q -s -k test_layout
python -m pytest tests/perf/perf_auto_layout.py -q -s -k "test_profile or test_exact_tests or test_spatial_index"
PERF_LAYOUT_BOUNDARY=bed python -m pytest tests/perf/perf_auto_layout.py -q -s -k "test_profile or test_exact_tests"
python -m pytest tests/doceditor/test_auto_layout.py tests/shared/test_arrange.py -q
python -m pytest -m ui tests/ui_gtk/doceditor/test_auto_layout_ui.py -q -s
```

Before: the `test_layout` lines at b672de66f with `PERF_LAYOUT_FILL=black`
for the filled columns, and `margin_mm` 0.625 or 1.0 in `layout_cmd.py`.

# Performance audit on the target M1

The machine the app has to feel fast on is an 8 GB MacBook Air M1.
The first audit (docs/PERF_AUDIT.md) was measured on Windows; nothing
in it carries over. Every number here was measured on this M1, and the
**baseline** table is the tree at `d9bbafcd4` before any change in this
pass. Later sections append the "after" numbers, one commit per fix.

## Machine and method

| | |
| --- | --- |
| Machine | MacBook Air (MacBookAir10,1), Apple M1 (4P + 4E), 8 GB |
| Display | built-in Retina 2560 x 1600, scale factor 2, 60 Hz |
| OS | macOS 26.7 (25G229) |
| Python | 3.14.6 conda-forge, arm64, from the pixi env |
| GTK / libadwaita | 4.22.4 / 1.9.3, PyGObject 3.56.3, cairo 1.18.4 |
| numpy / scipy / libvips | 2.5.2 (NEON, OpenBLAS) / 1.18.0 / 8.18.5 (highway SIMD on) |
| Power | on battery (55 % at the start, 23 % at the end of the baseline), Low Power Mode off; an Air has no fan, so long runs can throttle |

Harness: `pixi run bench` (= `python scripts/perf/measure.py`), which
runs every step below and prints this table; `pixi run bench <steps>`
re-runs some of them (`arch cold importtime import encode layout canvas
preview idle soak bundle renderers report`). Results merge into
`build/perf/results.json`.

- **Three runs, median.** Every launch is a fresh process with a fresh
  copy of `tests/config` (NoDeviceDriver machines, so never the real
  laser, and the app rewrites its config dir on exit). The bench runs
  under `sandbox-exec` with outbound network denied except localhost.
- **Distributions** (frame times) are pooled over the three runs; p50
  and p95 are of the pooled frames. A frame is the frame clock's
  `before-paint` to `after-paint`: the tick callbacks (where the
  gesture is driven), layout, every widget's snapshot and the GSK
  render, i.e. the main thread's whole cost of the frame. 240 frames
  per gesture per run. "missed" counts frame intervals over 25 ms
  (more than 1.5 vsyncs at 60 Hz).
- **Cold start** is process spawn to the main window's `map` signal
  (`scripts/perf/mark_mapped.py`), and spawn to the splash window up
  (`swiftcut/splash.py` stamps `$PERF_SPLASH_MARK_FILE`). One launch is
  made and discarded before the three: after an edit the first launch
  recompiles bytecode.
- **Encode** is the send path (`tests/perf/perf_encode.py`):
  `pipeline.generate_job_artifact_async()` then `build_rd_bytes()`. Ops
  are timed cold (the document's first build; a second build is a cache
  hit, ~0.05 ms).
- **Idle** is 60 s after the app has opened `large.dxf`, settled and,
  for "connected", reported CONNECTED to the Ruida simulator
  (`tests/machine/driver/ruida/simulator_app.py` on 127.0.0.1, its own
  CPU excluded). CPU % and wakeups/s are of the app's process tree from
  `proc_pid_rusage` (`scripts/perf/procstat.py`: the counters Activity
  Monitor shows, no root needed); energy is `top`'s POWER column, which
  is Activity Monitor's Energy Impact.
- **Memory** is `phys_footprint`, Activity Monitor's Memory column.

### Substitutions

| Asked for | Why not | Used instead |
| --- | --- | --- |
| `py-spy` | needs root on macOS ("This program requires root on OSX"); no sudo in this session | `cProfile` in-process, `python -X importtime` for startup. NEEDS-OWNER for a `sudo py-spy record` |
| `powermetrics` | needs root | `proc_pid_rusage` wakeups + `top` POWER |
| Instruments Time Profiler (`xctrace`) | "tool 'xctrace' requires Xcode"; only the Command Line Tools are installed | cProfile of the snapshot path and a GSK renderer A/B to split Python from native time. NEEDS-OWNER with Xcode |
| Activity Monitor "Kind" column | GUI | Mach-O header scan of every binary (`pixi run bench arch`) and `sysctl.proc_translated` |

### Assets

`tests/perf/`: `small.svg` (200 segments), `large.dxf` (20 000
segments, `$INSUNITS` = mm), `raster.png` (3000 x 2000), and two
documents added in this pass by `tests/perf/make_docs.py`:
`forty.ryp`, the 40 pieces of the Auto Layout benchmark
(`tests/doceditor/layout_bench.FORTY`) on a grid on the ilab-614 bed
(1400 x 900 mm) under one contour step, and `two_layer.ryp`, an
engrave+cut job: `raster.png` engraved at 150 x 100 mm on one layer,
`small.svg` cut on a second.

## P0 - baseline (tree at `d9bbafcd4`, harness `8bcd7040e`)

Measured 2026-10-20 11:49-12:30 in a worktree of the harness commit
(no app change), the built bundle beside it.

| metric | median | note |
| --- | --- | --- |
| a) cold start, spawn -> window mapped | 3.83 s |  |
| a) cold start, spawn -> splash up | 0.49 s |  |
| b) import small.svg | 0.013 s | footprint 105 MB |
| b) import large.dxf | 0.261 s | footprint 120 MB |
| b) import raster.png:decode | 0.072 s | footprint 116 MB |
| b) import raster.png:trace | 0.588 s | footprint 134 MB |
| b) import forty.ryp | 0.042 s | footprint 130 MB |
| b) import two_layer.ryp | 0.006 s | footprint 128 MB |
| c) ops small.svg (cold) | 211 ms |  |
| c) Ruida encode small.svg | 1.0 ms | 240 ops, 1611 B |
| c) ops large.dxf (cold) | 424 ms |  |
| c) Ruida encode large.dxf | 80.5 ms | 21510 ops, 106001 B |
| c) ops raster.png (cold) | 209 ms |  |
| c) Ruida encode raster.png | 0.4 ms | 17 ops, 556 B |
| c) ops forty.ryp (cold) | 350 ms |  |
| c) Ruida encode forty.ryp | 54.4 ms | 439 ops, 120728 B |
| c) ops two_layer.ryp (cold) | 3425 ms |  |
| c) Ruida encode two_layer.ryp | 1656.7 ms | 181810 ops, 2333908 B |
| d) large.dxf pan | p50 10.7 / p95 13.9 ms | GLRenderer x2, 717 missed of 717 |
| d) large.dxf zoom | p50 15.1 / p95 18.1 ms | GLRenderer x2, 717 missed of 717 |
| d) large.dxf pan_zoomed | p50 14.1 / p95 17.6 ms | GLRenderer x2, 717 missed of 717 |
| d) forty.ryp+selected pan | p50 11.0 / p95 14.6 ms | GLRenderer x2, 717 missed of 717 |
| d) forty.ryp+selected zoom | p50 15.0 / p95 18.0 ms | GLRenderer x2, 717 missed of 717 |
| d) forty.ryp+selected pan_zoomed | p50 13.5 / p95 16.7 ms | GLRenderer x2, 717 missed of 717 |
| e) auto-layout 40 pieces | 2.21 s | warm 1.57 s, longest stall 23 ms |
| f) preview ready | 0.39 s |  |
| f) preview play | p50 15.1 / p95 17.3 ms | 717 missed of 717 |
| f) preview scrub | p50 54.2 / p95 94.8 ms | 717 missed of 717 |
| g) idle connected | 0.49 % CPU | 32 wakeups/s, energy 0.4 |
| g) idle disconnected | 0.01 % CPU | 1 wakeups/s, energy 0.0 |
| g) idle hidden | 0.46 % CPU | 32 wakeups/s, energy 0.4 |
| h) footprint over idle soak | 333 -> 334 MB | growth +1.5 MB |
| i) .app size | 386 MB | 2466 files |
| i) .app start -> window | 4.02 s |  |

Detail the table does not carry:

- **Cold start samples** 5.68 / 3.83 / 3.26 s (splash 0.54 / 0.49 /
  0.39 s), after the discarded warm-up launch. The spread is real: the
  first measured launch ran while the machine was swapping (6.9 of 8 GB
  swap in use at the start of the session).
- **Every canvas and preview frame missed vsync**: frame intervals are
  33-35 ms at p95, i.e. the window runs at 30 fps, not 60. A plain GTK
  window on this machine (scratch `frametest.py`) shows why: with a
  before-paint to after-paint time under about 5 ms the frame clock
  holds 60 Hz (16.7 ms), at 6 ms it alternates, and from 8 ms on it
  locks to 30 Hz (33.3 ms). macOS 26 moved the compositor deadline
  close to vsync, so a frame that finishes late slips a whole refresh
  (the Zed and Psychtoolbox reports below). **The real target on this
  M1 is therefore a frame under ~5 ms, not 8 ms: that is what doubles
  the frame rate.**
- The canvas widget is 1285 x 406 points at scale 2 (2570 x 812 device
  pixels) in the default window of the test config; frame max 22-26 ms.
- **Preview**: the two-layer job is 181 770 segments and 9 479 s of
  machine time; preview ready 0.39 s after the toggle (the job artifact
  is already built). Scrub p95 95 ms, max 104 ms: each backwards jump
  restrokes every finished segment.
- **Encode**: `two_layer.ryp` (a 150 x 100 mm engraving) is the slow
  path: 3.4 s to build ops, 1.66 s to encode 181 810 ops (2.3 MB .rd).
  cProfile of the encode: `_handle_scan_line` 2.35 s cumulative under
  profiling, through `_handle_line_to` (363 784 calls), `_grow`
  (363 540), `_emit_immediate_power` (363 584), `_collect_job_info`
  (1.1 s) and `commands_to_rd_bytes` (0.32 s).
- **Idle connected** is the Ruida status poll: 32 wakeups/s, 0.49 %
  CPU, energy 0.4. Disconnected the app is silent (0.6 wakeups/s,
  0.015 % CPU). Minimizing the window changes nothing (0.46 %, 32/s):
  the poll runs whether or not anyone sees it.
- **Soak**: phys_footprint 333 MB at the start, 315 MB after 6 min (macOS
  compressing idle pages), 334 MB after 10 min: no growth.
- **Bundle**: 386 MB, 2 466 files, DMG 181 MB. From the bundle the
  window maps in 4.02 s (3.92 / 4.95 / 4.02) and the splash in 0.96 s,
  against 3.83 s / 0.49 s from source.
- **Auto Layout** samples 2.41 / 2.21 / 2.20 s cold, 1.54-1.61 s warm;
  the longest main-loop stall 19-27 ms.

### Startup profile

Sampling the main thread every 2 ms to the window's map (scratch
`sample_launch.py`, a py-spy stand-in): 2.98 s, of which imports 2.0 s.
`python -X importtime` of the first-paint UI (median of 3), third-party
top-level packages imported before the window exists:

| ms | package | needed before first paint? |
| --- | --- | --- |
| 195 | ezdxf | no: DXF import/export only |
| 129 | pyvips | no: images, SVG render |
| 109 | numpy | yes (geometry, canvas) |
| 105 | cv2 | no: tracing, resampling |
| 99 + 71 + 45 | Foundation, CoreFoundation, objc | no: haptics, via AppKit |
| 98 | pypdf | no: PDF import |
| 77 | gi | yes |
| 77 | pymupdf | no: PDF import |

All of them arrive through two doors: the importer registry
(`swiftcut/image/__init__.py` imports every importer and renderer to
register it) and the module-level `Haptics()` (AppKit).

### Ranking (P2 works the top five, by distance from the P3 target)

| # | metric | baseline | target | gap |
| --- | --- | --- | --- | --- |
| 1 | canvas pan/zoom frame, large.dxf at 2x | p95 13.9-18.1 ms, 30 fps | p95 <= 8 ms (60 fps needs ~5) | 2-3x |
| 2 | cold start to window / splash | 3.83 s / 0.49 s | 1.5 s / 0.3 s | 2.6x / 1.6x |
| 3 | engrave job: ops + encode | 3.4 s + 1.66 s | (encode large.dxf <= 0.8 s is met: 0.08 s) | the slowest send |
| 4 | preview scrub | p95 95 ms | a frame | 6x a 16 ms frame |
| 5 | auto-layout 40 pieces | 2.21 s cold | <= 2 s | 10 % |

Met at baseline: import large.dxf 0.26 s (<= 0.8), encode large.dxf
0.08 s (<= 0.8), idle CPU 0.49 % (< 1 %), energy 0.4 at idle, no
footprint growth over 10 min.

## P1 - native arm64

- **No Rosetta anywhere.** `pixi run bench arch`: the interpreter is an
  arm64 Mach-O (`sysctl.proc_translated` = 0); of the 1 178 Mach-O
  files in the pixi env, 1 014 are arm64-only and 164 universal
  (arm64 + x86_64), none without arm64; all 301 in the bundle are
  arm64-only. The env is `osx-arm64` (pixi.toml platforms). An arm64
  process cannot load an x86_64-only library, so this scan is
  conclusive where Activity Monitor's Kind column would only show the
  main executable.
- **Libraries**: numpy 2.5.2 is built with NEON / NEON_FP16 baseline
  SIMD and OpenBLAS (conda-forge `libblas *_openblas`); libvips 8.18.5
  reports "SIMD support with libhwy: true" (Highway 1.4.0 in the env).
  Nothing to replace.
- **GSK renderer** (large.dxf, the same 3 x 240 frames per gesture):

  | GSK_RENDERER | renderer used | pan p50 / p95 | zoom p95 | pan at 4x p95 |
  | --- | --- | --- | --- | --- |
  | unset (default) | GLRenderer | 11.0 / 13.6 ms | 18.0 ms | 18.1 ms |
  | opengl | GLRenderer | 10.5 / 13.8 ms | 17.8 ms | 17.7 ms |
  | cairo | CairoRenderer | 11.9 / 16.9 ms | 23.4 ms | 24.7 ms |
  | vulkan | GLRenderer (fallback) | 10.4 / 13.8 ms | 18.1 ms | 17.9 ms |

  GL (GTK's "ngl") is the default on macOS and the fastest; the cairo
  renderer is 25-35 % slower at p95. Vulkan is listed by this GTK build
  (libvulkan is in the env) but there is no MoltenVK ICD, so GTK falls
  back to GL. GTK's own docs: Vulkan became the default only on Wayland
  (4.16); other platforms keep ngl. The renderer is not where the frame
  goes: every renderer misses vsync the same way, because the canvas
  draws through one full-widget cairo node, which GTK rasterizes on the
  CPU and uploads as a texture on every redraw, with no partial
  invalidation (GNOME Discourse, below).
- **HiDPI**: that cairo node is device-scale (2570 x 812 pixels for a
  1285 x 406 canvas), so a pan re-rasterizes 2.1 M pixels of grid,
  workpiece bitmaps and overlays per frame: the "4x pixel work" the
  brief warns about. The workpieces' ops composites, in contrast, are
  rendered at the *logical* pixels per mm and scaled up 2x with
  FILTER_NEAREST, so on Retina they are cheap but blocky.
- **multiprocessing** already uses `spawn` with a persistent worker
  pool (`shared/tasker/pool.py`), created on first use: only Auto
  Layout runs in it, so a session without a layout never starts it.
  It starts `os.cpu_count()` = 8 workers on an 8 GB Mac; the layout's
  cold time (2.21 s vs 1.57 s warm) is that pool's start.

Sources: [GTK 4.15/4.16 default renderer](https://www.phoronix.com/news/GTK-4.15-Vulkan-Default),
[GTK macOS docs](https://docs.gtk.org/gtk4/osx.html),
[NGL renderer and MoltenVK](https://blogs.gnome.org/chergert/2021/02/24/gtk-4-ngl-renderer/),
[cairo nodes are re-uploaded whole](https://discourse.gnome.org/t/trying-to-make-custom-widget-with-cairo-drawn-content-more-efficient/33787),
[30 fps display-link pacing on macOS 26](https://github.com/zed-industries/zed/pull/65472).

## P2 - fixes, one commit each

Ranked work from the P0 table, in the order done. Each commit body has
its own before/after.

| commit | fix | measured |
| --- | --- | --- |
| `dd368a100` | AppKit imported by the first haptic tap, not by `ui_gtk.haptics` at import | first-paint UI import 1.696 -> 1.444 s |
| `8635d448d` | ezdxf and pypdf imported where DXF/PDF files are read | 1.444 -> 1.196 s |
| `0f46dc8e4` | pyvips, OpenCV, vtracer, PyMuPDF deferred to first use (`shared/util/lazy_import.py`); the libvips SVG probe lazy | 1.196 -> 0.854 s |
| `9caa48249` | canvas pan/zoom frames composited from GPU tiles (`ui_gtk/canvas/view_tiles.py`); grid and content in one cairo node | pan p95 13.9 -> 5.2 ms, zoom 17.7 -> 4.3 ms, missed vsync 717 -> ~30 of 717 |
| `b9b8bb21c` | `.rd` swizzle with `bytes.translate` (encoder internal; byte-identical on all five jobs) | `build_rd_bytes` two_layer 1684 -> 1586 ms |
| `ab3a1a4f6` | job preview keeps copies of its finished image; a scrub starts from the last one | scrub p95 94.8 -> 41.9 ms |
| `779afde61` | `GSK_RENDERER=opengl` pinned on macOS (P1) | no change: it is the default; this pins it |
| `ea4675440` | what startup deferred loads on a thread 1 s after the window maps (`swiftcut/warm_up.py`) | first import of large.dxf 0.496 -> 0.268 s (gate run without -> with) |

Also, not perf: `a3f19595f` draws the macOS splash at Retina
resolution (the owner's report that it looked pixelated).

Tried and dropped, by measurement: rewriting the encoder's scan-line
loop with hoisted lookups and a batched bounds walk gave 1581 -> 1564
ms on two_layer (1 %, inside the noise) for a protected-path change,
so it was reverted; rebuilding the view tiles when a zoom out reveals
new ones made zoom p95 worse (4.3 -> 29 ms), also reverted before
commit.

## After - the gate

Measured on the same M1. The canvas, preview, layout, idle, soak and
bundle rows are the gate run of `pixi run bench` at `779afde61`
(2026-10-20 15:31-16:08; battery 37 % discharging at the start, on the
charger at the end); cold start, import and encode are the re-run at
`ea4675440` (16:08-16:22, battery 63-61 %), which has the warm-up the
gate run did not.

| metric | baseline | after | change | note |
| --- | --- | --- | --- | --- |
| a) cold start to window | 3.83 s | 1.96 s | -49 % |  |
| a) cold start to splash | 0.49 s | 0.48 s | -2 % |  |
| b) import small.svg | 0.013 s | 0.013 s | -0 % |  |
| b) import large.dxf | 0.261 s | 0.268 s | +3 % |  |
| b) import raster.png:decode | 0.072 s | 0.077 s | +6 % |  |
| b) import raster.png:trace | 0.588 s | 0.581 s | -1 % |  |
| b) import forty.ryp | 0.042 s | 0.008 s | -81 % |  |
| b) import two_layer.ryp | 0.006 s | 0.007 s | +8 % |  |
| c) ops small.svg (cold) | 211 ms | 242 ms | +14 % | see note 1 |
| c) Ruida encode small.svg | 1.0 ms | 2.3 ms | +131 % | see note 1 |
| c) ops large.dxf (cold) | 424 ms | 430 ms | +1 % |  |
| c) Ruida encode large.dxf | 80.5 ms | 75.4 ms | -6 % |  |
| c) ops raster.png (cold) | 209 ms | 230 ms | +10 % | see note 1 |
| c) Ruida encode raster.png | 0.4 ms | 0.5 ms | +28 % | see note 1 |
| c) ops forty.ryp (cold) | 350 ms | 402 ms | +15 % | see note 1 |
| c) Ruida encode forty.ryp | 54.4 ms | 49.0 ms | -10 % |  |
| c) ops two_layer.ryp (cold) | 3425 ms | 3388 ms | -1 % |  |
| c) Ruida encode two_layer.ryp | 1656.7 ms | 1555.2 ms | -6 % |  |
| d) large.dxf pan p95 | 13.9 ms | 6.6 ms | -53 % | p50 10.7 -> 3.7; missed vsync 717 -> 43 of 717 |
| d) large.dxf zoom p95 | 18.1 ms | 6.4 ms | -65 % | p50 15.1 -> 3.5; missed vsync 717 -> 43 of 717 |
| d) large.dxf pan_zoomed p95 | 17.6 ms | 11.2 ms | -36 % | p50 14.1 -> 3.7; missed vsync 717 -> 51 of 717 |
| d) forty.ryp+selected pan p95 | 14.6 ms | 10.1 ms | -31 % | p50 11.0 -> 4.0; missed vsync 717 -> 61 of 717 |
| d) forty.ryp+selected zoom p95 | 18.0 ms | 6.9 ms | -62 % | p50 15.0 -> 3.8; missed vsync 717 -> 52 of 717 |
| d) forty.ryp+selected pan_zoomed p95 | 16.7 ms | 11.9 ms | -29 % | p50 13.5 -> 4.0; missed vsync 717 -> 61 of 717 |
| e) auto-layout 40 pieces, cold | 2.21 s | 2.23 s | +1 % | warm 1.57 -> 1.48 s |
| f) preview ready | 0.39 s | 0.37 s | -6 % |  |
| f) preview play p95 | 17.3 ms | 14.5 ms | -16 % | p50 15.1 -> 12.4 |
| f) preview scrub p95 | 94.8 ms | 51.1 ms | -46 % | p50 54.2 -> 28.5 |
| g) idle connected | 0.49 % | 0.58 % | see note 2 | wakeups 32 -> 32/s, energy 0.4 -> 0.4 |
| g) idle disconnected | 0.01 % | 0.03 % | see note 2 | wakeups 1 -> 1/s, energy 0.0 -> 0.0 |
| g) idle hidden | 0.46 % | 0.35 % | see note 2 | wakeups 32 -> 31/s, energy 0.4 -> 0.3 |
| h) footprint, 10 min idle soak | 333 -> 334 MB | 251 -> 248 MB | -26 % | growth +1.5 -> -3.7 MB |
| i) .app size | 386 MB | 392 MB | see note 3 | 2466 -> 2760 files |
| i) .app start to window | 4.02 s | 1.89 s | -53 % |  |

**Note 1 - not regressions, checked back to back.** The ops and
small-job encode rows read worse than the morning baseline, but the
morning was a different machine state. Run alternately in the baseline
worktree and at HEAD, minutes apart: small.svg ops 233 / 234 / 227 ms
(baseline) against 228 / 226 / 239 ms (HEAD); raster.png 229 / 235 /
208 against 228 / 212 / 214 ms; small.svg encode 2.56 / 2.38 / 2.00
and 2.74 / 2.36 / 2.44 ms against 2.78 / 2.25 / 2.21 and 2.47 / 2.30 /
2.24 ms. The baseline tree is as slow as HEAD when measured now.

**Note 2 - idle, back to back.** Idle CPU on this Air moves with what
else macOS is doing: the gate's three connected runs were 1.14, 0.58
and 0.36 %. Run interleaved (baseline, HEAD, baseline, HEAD, one minute
each): connected 0.95 / 0.58 / 0.54 / 0.36 %, disconnected 0.48 /
0.035 / 0.019 / 0.037 %, with 31-33 wakeups/s and 0.5-1.7/s in every
run. No regression. The connected figure is the Ruida status poll (32
wakeups/s), which also runs with the window minimized (the "hidden"
row); its cadence is in the protected driver
(`RuidaDriver.STATUS_POLL_INTERVAL` 0.5 s, `LOOP_TICK_INTERVAL` 0.1 s)
and was not touched: NEEDS-OWNER.

**Note 3 - bundle.** The gate bundle has 294 more files than the
baseline one, all `__pycache__/*.pyc` under `builtin_addons`: the gate
worktree had run the test suite before the build, and the spec copies
the add-on directories whole. Without the bytecode caches both bundles
are 2 466 files, 385.8 and 386.1 MB. (The spec also ships the add-ons'
`tests/` directories; noted for a packaging pass.)

### Targets (P3)

| target | baseline | after | verdict |
| --- | --- | --- | --- |
| cold start to window <= 1.5 s | 3.83 s | 1.96 s (bundle 1.89 s) | **not met**: what is left is spread over GTK/libadwaita setup (~0.3 s), the add-ons and their registration hooks (~0.2 s), building the main window (~0.6 s, of which the layer panel's material picker loads the material library, ~0.1 s) and the first frame. No single item left is over 0.2 s; going further means building parts of the window after the first frame. |
| splash < 300 ms | 0.49 s | 0.48 s | **not met**: the splash is a child Python process that imports PyObjC; its interpreter start is the floor from source. |
| large.dxf pan/zoom p95 <= 8 ms at 2x | 13.9-18.1 ms | pan 6.6 ms, zoom 6.4 ms; pan at 4x 11.2 ms; 40 selected 6.9-11.9 ms | **met at fit**; **not met** panning zoomed in or with a selection, where frames draw new tiles more often. Medians are 3.7-4.0 ms everywhere. |
| import large.dxf <= 0.8 s | 0.26 s | 0.27 s | met |
| encode large.dxf <= 0.8 s | 0.08 s | 0.08 s | met |
| 40-piece auto-layout <= 2 s, UI responsive | 2.21 s cold, 1.57 s warm, stall 23 ms | 2.23 s cold, 1.48 s warm, stall 29 ms | **not met cold**: the first layout starts the worker pool (about 0.7 s); met warm; the UI stays responsive (longest stall under 30 ms). |
| idle CPU < 1 % | 0.49 % | 0.36-0.58 % | met |
| no RSS growth over 10 min | +1.5 MB | -3.7 MB | met; footprint 333 -> 251 MB |
| energy impact "Low" at idle | 0.4 | 0.3-0.4 | met |

### Gate record

| check | baseline (`d9bbafcd4`) | gate (`779afde61`) |
| --- | --- | --- |
| non-UI suite | 6855 passed, 1 failed | 6866 passed, 2 failed |
| UI suite (one process per file) | 1025 passed, 3 failed | 1033 passed, 3 failed |
| ruff check swiftcut tests scripts | 34 | 31 |
| pyright (pyproject include) | 310 errors | 329 at the gate commit; 310 at `797b96382` |
| `pixi run bench` | - | reproduces the table (also as `pixi run --frozen bench`) |

The failures: `test_bind_failure_on_a_fixed_local_port_is_visible`
(known, Windows port semantics) at both; the UI suite's three known
ones (`TestTrackpadContinuousZoom` x2,
`test_identity_zoom_no_pan_matches_documented_composition`) at both;
and at the gate `test_simulator_answers_over_loopback`, which binds
the fixed UDP port 51311 that macOS `syslogd` held during the gate
(seen in `netstat`); it fails identically at the baseline commit with
the port taken. No new failure.

**Gate: passed.** No metric regressed against the baseline tree
measured back to back (notes 1-3), and every test failure is a
baseline one.

NEEDS-OWNER: a feel test on the M1 (pan, zoom - a zoom shows scaled
tiles for about 150 ms before they sharpen -, the job preview, Auto
Layout); a real job to the laser after `b9b8bb21c` (the encoder's
swizzle; output byte-identical by test, not yet by laser);
`sudo py-spy record` of a start, `powermetrics` at idle and an
Instruments Time Profiler run with Xcode, none of which could run in
this session.

# Performance audit — baseline

Package P, step P1. **Measured before any optimisation lands**, on the
tree at the commit this file is committed with. Every number here is a
"before" number; the "after" table is appended by P4.

## Machine and method

| | |
| --- | --- |
| OS | Windows 11 Pro 10.0.26200 |
| Python | 3.14.7, MSYS2 mingw64 (`/c/msys64/mingw64/bin/python.exe`) |
| GTK | via PyGObject, MSYS2 mingw64 |
| Repo state | branch `fix/ruida-driver`, working tree clean of source edits |

Harness: `scripts/perf/measure.py` (cold start, import profile, asset
import, bundle) and `tests/perf/perf_encode.py` (ops + Ruida encode).
Assets are committed under `tests/perf/` and reproduced by
`tests/perf/make_assets.py`.

### Substitutions, and why

The brief names three tools that are not available here. The machine is
**offline**, so none could be installed; each substitution is recorded
rather than silently skipped.

| Asked for | Not available because | Used instead |
| --- | --- | --- |
| `py-spy record` of startup | not installed, offline | `python -X importtime`, aggregated by cumulative cost |
| `psutil` for RSS / CPU | not installed, offline | Win32 `GetProcessMemoryInfo` via `ctypes` |
| `ruff` at baseline | `.pixi/envs/` does not exist and installing needs network | `py_compile` + a 79-char line-length check against `.flake8` |

`ctypes` note, because it silently produces a wrong answer rather than
an error: `GetProcessMemoryInfo` **must** have `argtypes`/`restype` set.
Without them the `HANDLE` is passed as a 32-bit int on win64, the call
fails, and `WorkingSetSize` reads back as 0. The first run of this
harness reported `rss_after_mb: 0.0` for exactly that reason.

### What "cold start" can and cannot mean here

The splash is a **PyInstaller bootloader artefact** (`SwiftCut.spec:18`,
`Splash('swiftcut_splash.png', ...)`), raised by the C bootloader before
the Python interpreter exists. `_close_splash()` (`app.py:172-188`)
only does anything inside a bundle — `import pyi_splash` raises in a
source run and is swallowed. So **a source run has no splash phase at
all**, and "splash shown -> window mapped" is only measurable against
`dist/SwiftCut/SwiftCut.exe`.

The number below is therefore the honest source-run equivalent:
**process spawn -> main window mapped**. The far end is exact —
`app.py:337` connects `self.win.connect("map", self._on_window_mapped)`
and that handler runs once, on the first frame that reaches the screen.
`scripts/perf/mark_mapped.py` stamps `time.time()` from a `--uiscript`,
which the app also runs from the `map` handler (`app.py:351`).

### Protocol

- Cold start and asset import: **3 fresh processes**, median reported.
  A fresh process per run is deliberate — these are *cold* numbers,
  what a user pays for the first file of a session.
- Ops generation: **cold and cached reported separately.** The artifact
  is cached per unchanged document, so only the first call builds
  anything; a naive median over three runs reports two cache hits as if
  they were work (measured: `[232.8, 0.036, 0.013] ms`).
- The app **rewrites its config directory on exit**, so every launch
  gets a throwaway copy of `tests/config` (which selects
  `NoDeviceDriver`, keeping the measurement off the real laser).
  Pointing the app straight at `tests/config` silently edits tracked
  fixtures — observed, and corrected, during this audit.

---

## a) Cold start — spawn to window mapped

| | s |
| --- | --- |
| **median of 3** | **3.16** |
| samples | 4.30, 3.12, 3.16 |

Measured twice, an hour apart, at 3.21 s and 3.16 s - so the number is
stable to within ~2 %. The first sample of each run is an OS-cache-cold
outlier and is kept in the record rather than discarded; the median is
taken over all three as specified.

**Target ≤ 2.0 s p50 — NOT MET, 58 % over.**

## b) Asset import — cold, per fresh process

`swiftcut.image.import_file`, the public entry, which resolves the
importer by mime type and then by extension.

| asset | median s | RSS after, MB |
| --- | --- | --- |
| `small.svg` (200 seg) | 0.033 | 172.4 |
| `large.dxf` (20 000 seg) | 0.355 | 179.2 |
| `raster.png` decode-only | 0.117 | 183.4 |
| `raster.png` real trace | 0.629 | 192.9 |

**A raster is two metrics, never one.** `PngImporter` declares only
`BITMAP_TRACING`, so `_resolve_default_spec` (`base_importer.py:322-328`)
hands it `TraceSpec(threshold=1.0, auto_threshold=False)` — and
`trace_surface` short-circuits on exactly that value, returning the
image's bounding rectangle without ever calling vtracer
(`tracing.py:589`). Timing the default measures PNG decode and nothing
else. The gap is 5.7x (113 ms vs 642 ms), so reporting the default
alone would have recorded a number that looks excellent and means
nothing.

Note vtracer downscales this asset: *"Image is too large for vtracer
(3004x2004px). Downscaling to 1224x816px to prevent overflow."*

## c) Ops generation + Ruida encode

Production path, not a re-implementation — the same three calls a send
makes (`test_ruida_production_path.py:106-120`):
`pipeline.generate_job_artifact_async()` ->
`artifact_store.checkout_handle()` -> `build_rd_bytes()`.

| asset | ops cold ms | ops cached ms | encode ms | ops | .rd bytes |
| --- | --- | --- | --- | --- | --- |
| `small.svg` | 225.4 | 0.031 | 0.87 | 240 | 1 611 |
| `large.dxf` | 607.4 | 0.059 | **77.4** | 21 510 | 106 001 |
| `raster.png` | 240.5 | 0.019 | 0.21 | 17 | 556 |

The cached column is the artifact cache working as intended: an
unchanged document rebuilds in ~0.02 ms.

`raster.png` here went through the **default** spec, so its 17 ops are
the bounding rectangle, not a traced image — the same short-circuit as
(b). This row therefore measures the encoder's floor, not a raster job;
it is kept for that reason and labelled rather than presented as a
raster workload.

## g) Bundle

| | |
| --- | --- |
| `dist/SwiftCut` | 933 049 684 bytes (889.8 MB) |
| files | 4 994 |
| installer (`swiftcut-v*-installer.exe`) | 241.7 MB |

## Startup import profile (py-spy substitute)

Heaviest cumulative imports on a startup that quits at first paint.
Full tree in `build/perf/importtime.txt`.

| ms | module |
| --- | --- |
| 1 059 | `swiftcut.ui_gtk.mainwindow` |
| 836 | `swiftcut.ui_gtk.shared.model_preview` |
| 835 | `swiftcut.ui_gtk` (and the `canvas2d.elements` chain) |
| 803 | `swiftcut.doceditor.editor` |
| 783 | `swiftcut.doceditor.layout` |
| 509 | `scipy.signal._support_alternative_backends` |
| 475 | `scipy.signal._signal_api` |
| 426 | `gi.repository.Adw` |
| 269 | `swiftcut.image.dxf.exporter` |
| 266 | `scipy.ndimage` |
| 257 | `ezdxf` |

These are cumulative and overlapping — `mainwindow` is the root of most
of the rest — but two things stand out and are named here as
*candidates only*, to be confirmed or killed before any of them is
optimised: **scipy** (`signal` + `ndimage`, ~1.25 s of cumulative import)
and **`model_preview`** (836 ms, which is the trimesh/PyOpenGL path),
neither of which is needed to paint the first frame.

## Found while measuring: unitless DXF is read as metres, unbounded

This is not a performance finding in the "make it faster" sense — it
came out of P1 because it is what stopped P1 finishing, twice, and it
took the machine down with it. Recorded here because the measurement is
the evidence.

The first `large.dxf` did not set `$INSUNITS`, which is ezdxf's default
(`0`, "unitless"). Measured, with the same 6-star drawing spanning
70 x 10 mm:

| `$INSUNITS` | imported WorkPiece size |
| --- | --- |
| absent (ezdxf default) | **70 000 x 10 000 mm** |
| `4` (millimetres) | 70 x 10 mm |
| `1` (inches) | 1 778 x 254 mm |

So a unitless DXF is interpreted as metres and comes in **1000x
oversized**. Two distinct defects follow, and the second is the
dangerous one:

1. **The unit default.** A DXF with no `$INSUNITS` is common in the
   wild. Reading it as metres rather than millimetres, with no warning
   and no prompt, silently produces a part a thousand times too big.
2. **There is no clamp.** The 70 m part drove ops generation to
   **17.7 GB RSS** and it had not finished after 120 s; the background
   run before that was killed by the OS for exhausting memory. A
   workpiece two orders of magnitude larger than the machine bed
   (200 x 150 mm here) should be rejected, or clamped, long before it
   reaches allocation — instead the pipeline tries to honour it and the
   whole system goes down with it.

Reproduce with `tests/perf/perf_dxf_scaling.py`, which walks the size up
under a wall-clock and a peak-RSS budget and stops at the first size to
blow either, precisely so it characterises the limit without repeating
the out-of-memory kill.

With `$INSUNITS = 4` set (now done in `make_assets.py`), the same
20 000-segment drawing imports as 598 x 118 mm and the whole path is
comfortable: 355 ms import, 607 ms ops, 77 ms encode.

## Metrics not yet measured

Recorded as gaps rather than quietly dropped:

- **d) canvas pan/zoom frame time (p50/p95)** — needs a uiscript that
  drives pan and zoom against `large.dxf` and records frame-clock
  callback durations.
- **e) idle CPU % and wakeups/sec over 60 s, connected to the
  simulator** — the simulator has a runnable entry point
  (`tests/machine/driver/ruida/simulator_app.py`), but its **own** idle
  cost must be excluded: it runs two `GLib.timeout_add(10, ...)` polls
  (100 Hz each) plus a 20 Hz position update, ~220 wakeups/s in the
  simulator process alone.
- **f) RSS after 10 min idle (leak check)** — the per-asset RSS in (b)
  is measured; the 10-minute idle delta is not.

## Acceptance targets

| target | measured | verdict |
| --- | --- | --- |
| cold start p50 ≤ 2.0 s | 3.16 s | **NOT MET** |
| `large.dxf` pan/zoom p95 < 16 ms | not measured | pending |
| idle CPU < 2 % | not measured | pending |
| RSS growth ≤ 5 % over 10 min idle | not measured | pending |
| `large.dxf` encode < 1.5 s | **0.077 s** | **MET** (19x headroom) |
| bundle smaller than before | 889.8 MB baseline | n/a at baseline |

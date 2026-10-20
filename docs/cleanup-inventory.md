# Cleanup inventory (Goal 2, C0)

Taken 2026-10-20 at the tree after the performance pass (Goal 1,
docs/PERF_AUDIT_M1.md). Scope: `swiftcut/` (built-in addons included,
their tests and the locale tree excluded). Tools, all reproducible:
vulture 2.x, pylint `duplicate-code`, import-linter, an `ast` pass
for sizes and layering, and the Graphify graph (`graphify-out/`, built
at `d9bbafcd4`).

## Dead code

The rule for deleting: vulture at min confidence 80 **and** coverage
from the full suite (plus a scripted UI walk) **and** no inbound
reference in the Graphify graph. Disagreement keeps the code.

**vulture --min-confidence 80: 41 findings, none of them code.** All
41 are unused *parameters* that a signature requires: GObject
`notify::` handlers' `pspec` (8 in the laser and print-and-cut
addons, 17 across `ui_gtk`), the driver interface's `feed_rate` /
`max_travel` (`driver.py:712`, `dummy.py:247`,
`ruida_driver.py:1932`), pluggy hook specs in `core/hooks.py`
(`machine_manager`, `model_manager`, `service_registry`),
`layer_cmd.py`'s `from_layer` and `file_cmd.py:308`'s
`original_file_bytes`. Removing any of them breaks a caller's
signature. **No function, class, method or import reaches 80 %, so no
code meets the first of the three conditions: C1 deletes nothing.**

Kept but suspicious (for a later pass with the owner): vulture at 60 %
names 432 callables (14 classes, 36 functions, 355 methods, 27
properties) and 187 variables/attributes. 390 of the callables also
have no inbound `calls` / `references` / `uses` / `inherits` /
`imports_from` edge in the Graphify graph. Both tools are blind to the
same dynamic dispatch this codebase leans on: GTK signal handlers
connected by name and `do_*` virtual methods, pluggy hooks, blinker
receivers, actions resolved by string (`ActionManager`), uiscripts,
and the addon API. Coverage (the third vote) was not run for this
pass. Nothing here was deleted. To regenerate the list:

    vulture swiftcut --min-confidence 60 \
        --exclude "swiftcut/locale,*/tests/*"

and drop the names that have an inbound `calls`, `references`, `uses`,
`indirect_call`, `inherits`, `imports_from` or `re_exports` edge in
`graphify-out/graph.json`.

C1 is therefore empty: no code was deleted and no dependency became
unused.

## Duplication

`pylint --disable=all --enable=duplicate-code --min-similarity-lines=15
--ignore-imports=yes --ignore-signatures=yes --ignore-comments=yes
--ignore-docstrings=yes swiftcut`: **4 clusters**, all merged in C2:

| # | where | lines | shared helper |
| --- | --- | --- | --- |
| 1 | `image/jpg/importer.py` 125-181, `image/png/importer.py` 123-176: an image's ParsingResult | 56 / 53 | `NormalizationEngine.raster_parse_result` |
| 2 | `machine/models/head.py` 59-96, `machine/models/rotary_module.py` 76-113: rotation and scale of the 3D transform | 37 / 37 | `core.matrix.TransformMixin` |
| 3 | `machine/models/dialect/grbl_dynamic.py` 19-42, `grbl_raster.py` 22-45 (and `grbl.py`): Grbl machine-control fields | 23 / 23 | `dialect.grbl.grbl_common()` |
| 4 | `image/base_renderer.py` 154-181, `image/pdf/renderer.py` 35-59: the upscale-and-crop render spec | 27 / 24 | `image.base_renderer.crop_render_spec` |

Below the 15-line threshold, the single-site rules of CLAUDE.md
section 9, checked by grep (`(/|\*) *60` next to a speed):

- **Axis direction mapping: one site**, `jog_widget._jog_deltas`
  (its four callers use it; nothing maps directions on its own).
- **mm/min to mm/s: one site per value path, not one site.** The job
  encode path converts once (`RuidaEncoder._speed_to_um_s`); the jog
  and move paths convert in `ruida_driver.py:1457, 1852` (protected);
  Cut Scale converts in `jog_widget.py:870, 883` (protected); recipes
  (`core/recipe_manager.py:62`) and LightBurn files
  (`image/lightburn/importer.py:377`) convert their mm/s on the way in.
  Each path converts exactly once, which is what the rule asks.
- **Duplicated concept, kept:** the acceleration run-up `v^2 / 2a` is
  written three times: `machine/driver/driver.py:46`
  (`acceleration_run_up_mm`, used by the Ruida encoder's job bounds)
  and, with a safety factor of 2, in the post-processor addon's
  `overscan_transformer.py:61` and `lead_in_out_transformer.py:67`.
  The two addon copies feed ops generation, so merging them changes
  job output unless proven byte-identical: listed for a later pass
  with the golden tests, not merged here.

## Structure

Measured with an `ast` pass over `swiftcut/`:

- **Modules over 800 lines: 32.** Largest: `ui_gtk/mainwindow.py`
  2677, `machine/driver/ruida/ruida_driver.py` 2009 (protected),
  `machine/models/machine.py` 1850, `ui_gtk/canvas2d/surface.py` 1777,
  `ui_gtk/canvas/canvas.py` 1775, `addon_mgr/addon_manager.py` 1703,
  `core/workpiece.py` 1593, sketcher `core/sketch.py` 1585,
  `doceditor/file_cmd.py` 1456.
- **Classes over 30 methods: 36.** `MainWindow` 151, `Machine` 138,
  `RuidaClient` 104 and `RuidaDriver` 92 (both protected),
  `WorkSurface` 84, `CanvasElement` 69, `WorldSurface` 63, `JogWidget`
  62 (protected behaviour), `Canvas` 59, `Sketch` 59, `AddonManager` 55.
- **Functions over 80 lines: 161.**
- **UI importing drivers or transports: 12 imports in 6 modules.**
  Most are enums and labels (`DeviceState`, `TransportStatus`,
  `NoDeviceDriver` as a type check); the substantive ones are
  `ui_gtk/machine/device_settings_page.py` importing `RuidaDriver` and
  `ruida_usb_transport.list_usb_devices`, and
  `general_preferences_page.py` importing `get_driver_cls`.
- **Layering** (import-linter, `layers = ui_gtk > machine > pipeline >
  core`): broken in five directions, 55 import chains. `core` imports
  `machine` (`core.step` -> `machine.models.head/spindle/machine`,
  `core.config`, `core.recipe*`, `core.bed_bounds` ->
  `machine.models.machine`); `core` reaches `ui_gtk` through
  `core.workpiece -> context -> debug -> ui_gtk.about`; `pipeline`
  imports `machine` (`intent_builder -> machine.driver`,
  `encoder.rust_helpers -> machine.models.laser`); `machine.cmd`
  imports `doceditor.editor` and `ui_gtk`. The machine *models* are
  effectively core models today: the layering the brief asks for does
  not match how the code is cut.

## Backlog (C3, not done in this pass)

Each needs the suite and `pixi run bench` behind it and is larger than
this pass could verify:

1. `MainWindow` (151 methods): move the job-preview wiring, the
   machine-status wiring and the file actions out into collaborators
   it owns (`JobPreviewController`, `MachineStatusPresenter`,
   `FileActions`), each with the signals it already uses.
2. `Machine` (138): split the serialisable model from the
   runtime-state mirror (connection status, position) and from the
   driver factory.
3. `core` <-> `machine.models`: move `Machine`, `Head`, `Laser`,
   `Spindle`, `RotaryModule` (pure models) under `core`, or let
   `core.step` depend on a protocol instead of `machine.models.head`.
4. `context -> debug -> ui_gtk.about`: the debug dump imports a UI
   module for its version string; pass it in instead.
5. `machine.cmd -> doceditor.editor`: pass the document in.

The import-linter contract committed in C3 (`.importlinter`) states
the layers and ignores the 46 direct imports that today's 55 broken
chains run through (19 `pipeline -> machine`, 8 `doceditor ->
pipeline`, 7 `core -> machine`, 4 `context -> machine`, and 8 more
through `context`, `debug`, `doceditor` and `image`). It passes as it
stands, and a new upward import fails it (checked by adding one).

## C4 - final check (2026-10-20, at `476b28adc`)

| check | Goal 1 gate (`779afde61`) | final |
| --- | --- | --- |
| non-UI suite | 6866 passed, 2 failed | 6877 passed, 2 failed, 1 error |
| UI suite (one process per file) | 1033 passed, 3 failed | 1033 passed, 3 failed |
| ruff check swiftcut tests scripts | 31 | 31 (baseline 34) |
| pyright (pyproject include) | 329, then 310 | 309 (baseline 310); no new error in a touched module |
| lint-imports | - | 1 kept, 0 broken (46 ignored) |

The failures are the gate's: `test_bind_failure_on_a_fixed_local_port_is_visible`
and `test_simulator_answers_over_loopback` (macOS `syslogd` on its
fixed UDP port 51311; it passes in the reruns below, once the port is
free), and the UI suite's three known ones. The error is a teardown
check, "Task manager still has tasks at end of test", on
`tests/machine/test_machine_cmd.py::TestBedOverrunWarning::test_warns_when_the_job_runs_past_the_bed`:
it did not recur in 5 runs of the file or 3 runs of `tests/machine`
(2496 passed; only the Windows-port test failing), and was not seen at
baseline or gate. Recorded as an intermittent, not fixed.

`pixi run bench` against the Goal 1 result (canvas: the gate run;
cold start: the warm-up re-run), at the final tree:

| metric | Goal 1 | final | change |
| --- | --- | --- | --- |
| cold start to window | 1.96 s | 1.90 s (median of 6, interleaved A/B with the old 1x splash: 1.97-2.10 s) | -3 % |
| splash up | 0.48 s | 0.41 s | -15 % |
| large.dxf pan p95 | 6.6 ms | 5.9 ms | -10 % |
| large.dxf zoom p95 | 6.4 ms | 4.8 ms | -25 % |
| large.dxf pan at 4x p95 | 11.2 ms | 9.2 ms | -18 % |
| 40 selected pan p95 | 10.1 ms | 6.1 ms | -40 % |
| 40 selected zoom p95 | 6.9 ms | 5.5 ms | -20 % |
| 40 selected pan at 4x p95 | 11.9 ms | 10.7 ms | -10 % |
| import, every asset | | within -6 % to +2 % | |
| ops and encode, every asset | | within -14 % to +4 % | |

Nothing slowed by more than 5 %. (One earlier canvas run had 40
selected pan at 4x at 13.2 ms, +11 %; the re-run above is 10.7 ms. No
Goal 2 change runs on that path, and the frame-to-frame spread there
is the tile draws.)

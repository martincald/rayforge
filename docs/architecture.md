# Architecture

How `swiftcut/` is cut into packages, which way they may depend on each
other, and where that is true today. Written with the cleanup pass of
2026-10-20 (docs/cleanup-inventory.md); the layering contract it
describes is `.importlinter`, checked by `lint-imports`.

## Packages

| package | holds | depends on |
| --- | --- | --- |
| `core` | the document model: `Doc`, `Layer`, `WorkPiece`, `Step`, assets, recipes, materials, config | `shared`; and today `machine.models` (see below) |
| `image` | importers, renderers and exporters per file format, tracing | `core`, `shared` |
| `pipeline` | ops generation: intents, the artifact store, encoders, the job preview model | `core`, `image`, `shared`; and today `machine` |
| `machine` | machine models, drivers (Ruida, G-code, no-device), transports, the controller and `MachineCmd` | `core`, `pipeline`, `shared` |
| `doceditor` | editing commands with undo: file, layout, layers, steps, groups | `core`, `image`, `pipeline` |
| `ui_gtk` | the GTK 4 / libadwaita application: main window, canvas, panels, dialogs | everything above |
| `shared` | task manager and worker pool, units, placement engine, utilities | the standard library and third-party only, mostly |
| `context` | the application context: one lazily built instance of each manager | everything it builds |
| `builtin_addons` | laser steps, materials, post-processors, sketcher, print-and-cut, loaded through pluggy hooks | the packages above, through the addon API |

## Layering

The intended direction is

    core  <-  pipeline  <-  machine  <-  ui_gtk

(a package may import the ones to its left, never to its right).
It does not hold today. Measured with import-linter on 2026-10-20:

- `core` imports `machine.models` (`core.step` needs `Head`, `Spindle`
  and `Machine`; `core.config`, `core.recipe*` and `core.bed_bounds`
  need `Machine`). The machine models are, in practice, core models.
- `pipeline` imports `machine` (`intent_builder` uses the driver
  registry to pick the encoder; `encoder.rust_helpers` uses
  `machine.models.laser`).
- `core` reaches `pipeline`, `machine` and `ui_gtk` through `context`,
  which builds every manager, and through `debug`, which imports
  `ui_gtk.about` and `doceditor.editor`.
- `machine.cmd` imports `doceditor.editor`, which reaches `ui_gtk`.

`.importlinter` states the intended layers and lists under
`ignore_imports` the 46 direct imports that today's broken chains run
through: the contract passes, and any **new** upward import breaks it. The list is the backlog; removing an
entry means removing the import. docs/cleanup-inventory.md has the
plan for the largest ones (machine models into `core`; `context` and
`debug` no longer importing UI).

Run it with

    lint-imports

(import-linter is in the `test` feature of pixi.toml).

## Protected paths

`machine/driver/ruida/**`, the pipeline's job path (intent_builder's
aggregate assembly, `build_rd_bytes`, `send_job`, .rd export), the jog
panel's behaviour and the layer/step system are protected
(CLAUDE.md section 7): their public interfaces do not change, and an
internal change ships only with the fixture and golden-byte tests
proving the job output byte-identical.

## Drawing

The canvas (`ui_gtk/canvas`, `ui_gtk/canvas2d`) draws through cairo:
`Canvas.draw_frame` is the one place that draws a frame (grid, then
elements, then overlays, into one cairo node). Frames asked for by a
moved view only are composited from GPU textures instead
(`canvas/view_tiles.py`, docs/PERF_AUDIT_M1.md): anything that changes
what is drawn calls `Canvas.queue_draw`, and view changes go through
`WorldSurface._view_changed`.

## The Graphify graph

`graphify-out/` (gitignored) is the knowledge graph of the repository:
at `d9bbafcd4`, 39 379 nodes and 79 824 edges over 1 886 files, in
1 388 communities. The largest communities follow the packages above
(`Canvas`, `MainWindow`, `Pipeline`, `RuidaEncoder`, `Doc`). Query it
with `graphify query "<question>"`, `graphify path "<A>" "<B>"` and
`graphify explain "<concept>"`; `graphify update .` refreshes it after
a change.


# Removal inventory - 2026-09-04

Scope: turn this fork into a Ruida-only application for a single
Duplotech-1490 (Ilab) machine. Every verdict below cites
`docs/graphify-map-2026-09-04.md` (the map), which was built from
`graphify-out/graph.json` and confirmed against the real file tree.

Base commit: `e1541f21d`. Map commit: `6e553d512`.

**No deletion may begin before this file is committed.**

## Legend

- **REMOVE** - delete, owner-confirmed or gate-passing.
- **REMOVE (UI only)** - delete the user-facing surface, keep the core
  the Ruida job path imports.
- **KEEP** - stays, with the reason it cannot go.
- **BLOCKED** - removal would require editing a PROTECTED path; halted
  and reported per the protocol's stop conditions.

PROTECTED = `machine/driver/ruida/**`, the pipeline job path
(intent_builder aggregate assembly, build_rd_bytes, send_job, .rd
export), jog panel behaviour, mm/s units, Min/Max power, Start/Pause/
Stop, layer/step system, Swift Cut theme + layout tokens,
MOTION_AUDIT.md invariants.

---

## A1 - Owner-confirmed removals

### 1. Camera system - REMOVE

| Item | Verdict | Reason |
|---|---|---|
| `rayforge/camera/**` (models, controller, manager, calibration, v4l) | REMOVE | Self-contained vertical slice; nothing in the doc/pipeline/job path imports it. |
| `rayforge/ui_gtk/camera/**` (13 widgets + 7 wizard pages) | REMOVE | Reached only from machine settings page 10 and the camera wizard. |
| `rayforge/ui_gtk/canvas2d/elements/camera_image.py` + overlay wiring | REMOVE | Only consumer is `surface.py:1104-1145,1409-1431`. |
| `win.toggle_camera_view` action + `CanvasViewState.show_camera` | REMOVE | Toggle chain `actions.py:55,270`, `visibility_overlay.py:80-95`, `core/config.py:37`. |
| `Machine.cameras`, `DeviceProfile.cameras`, `migrate_camera_data` | REMOVE (staged last) | Sits on the machine deserialisation path (`machine.py:18-19,1797-1799`, `profile.py:11-12,470-473`). Needs a migration story for existing `cameras:` YAML keys. |
| `tests/camera/**` (5 files) | REMOVE | Zero inbound refs. |
| `scripts/screenshot/machine_settings_camera.py` + cli entries | REMOVE | Reaches into controller privates; no test covers it. |
| sketcher addon camera button (`studio.py:234-249`, `sketchcanvas.py:83,93-159`) | REMOVE | Imports `rayforge.camera.controller` directly; breaks otherwise. |
| snap `camera` plug (`snap/snapcraft.yaml:21`) | REMOVE | Camera-only. |
| **`cv2` / opencv dependency** | **KEEP** | NOT camera-only - also `image/tracing.py:7`, `image/util/srgb.py:9`. Only `cv2.aruco` (charuco.py) is exclusive. |

### 2. Update checker - REMOVE

| Item | Verdict | Reason |
|---|---|---|
| `rayforge/updater.py`, `tests/test_updater.py` | REMOVE | Entire production surface is 5 lines in `mainwindow.py:32,175-178,563`. |
| `GITHUB_RELEASES_API`, `DOWNLOAD_URL` (`const.py`) | REMOVE | Orphaned by the above; verified no other referents. |
| `config.check_for_app_updates` + its settings row | REMOVE | Only gate for the checker. |
| `is_newer_version` (`shared/util/versioning.py`) | KEEP | Still used by `addon_mgr`. |
| `aiohttp` | KEEP | Five other users incl. `machine/transport/http.py`. |

### 3. Telemetry / usage consent - REMOVE

| Item | Verdict | Reason |
|---|---|---|
| `rayforge/usage.py`, `ui_gtk/shared/usage_consent_dialog.py` | REMOVE | Umami POST + the only launch dialog. |
| `UMAMI_URL`, `UMAMI_WEBSITE_ID` (`config.py:76-77`) | REMOVE | Telemetry endpoint. |
| `usage_consent_date` + consent helpers (`core/config.py`) | REMOVE | Persisted consent state. |
| Privacy group (`general_preferences_page.py:338-370`) | REMOVE | Consent toggle. |
| ~14 direct `track_page_view` calls | REMOVE | doceditor/*_cmd.py, project_cmd.py, console.py, sketcher addon. |
| `TrackedPreferencesPage` / `PatchedDialogWindow` **classes** | KEEP, gut tracking only | ~24 preference pages and ~23 dialogs inherit them; the Adw focus fix is load-bearing and unrelated to telemetry. |
| **`StartupBehavior`** | **KEEP** | Not telemetry - it is the "reopen my last project" feature (`app.py:415-450`). Removing it changes launch behaviour for existing users. |

### 4. 3D preview / simulation - REMOVE

| Item | Verdict | Reason |
|---|---|---|
| `rayforge/ui_gtk/sim3d/**` (44 files) GL layer | REMOVE | The `3d` view-stack page and its renderers. |
| `rayforge/simulator/op_player.py`, `scene3d/**` | REMOVE | Playback serves nothing outside the 3D view - the 2D time estimate comes from `machine/cmd.py:206`, not OpPlayer. |
| `show_3d_view` + 7 view actions, menu section, toolbar button, `ViewModeCmd.toggle_3d_view` | REMOVE | Entry points listed in the map. |
| `PlaybackOverlay`, `cylinder_renderer.py` | REMOVE | 3D-only. |
| **`rayforge/simulator/machine_state.py`** | **KEEP (relocate)** | `machine/assembly.py:16` and `machine/kinematics.py:13` type against it; 3 machine tests construct it. |
| **`get_model_extent` / `_load_mesh_data`** (`model_renderer.py:58,128`) | **KEEP (relocate)** | Consumed by `head_preferences_page.py:24`, `rotary_module_page.py:24`, `settings/model_preview_widget.py:14-18` - machine settings, not the 3D view. |
| `PyOpenGL`, `trimesh` | KEEP | Still needed by the machine-settings model preview after relocation. |
| `TimeEstimateOverlay`, `VisibilityOverlay`, `ColorLutProvider` | KEEP | Shared with the 2D surface / theme service. |
| `pipeline/pipeline.py:386-408`, `artifact/job.py` `preview_ops` | KEEP (PROTECTED) | Becomes dead but lives under `pipeline/`; leave and note. |

---

## A2 - Expected removals (gate: zero PROTECTED inbound refs)

### 5. Non-Ruida drivers - REMOVE (gate PASSES)

| Item | Verdict | Reason |
|---|---|---|
| `driver/grbl/**`, `driver/marlin/**`, `driver/octoprint/**`, `smoothie.py` | REMOVE | Order forced by inheritance: telnet before serial; smoothie before grbl (`smoothie.py:26` imports `grbl_util`). |
| 12 driver test files + 5 model/device/UI tests that import them | REMOVE / fix | Enumerated in the map. |
| 25 non-Ruida `resources/devices/*/device.yaml` | REMOVE | Would silently degrade to NoDeviceDriver via the `get_driver_cls` fallback. |
| `lightburn_importer.py:27-36` `_DRIVER_MAP` + its tests | REMOVE / fix | Maps LightBurn to Grbl class names. |
| Orphaned transports: `websocket.py`, `http.py`, `grbl.py`, `telnet.py` | REMOVE | Sole consumers are the removed drivers. |
| `websockets` dependency | REMOVE | Becomes unreferenced. |
| **`driver/dummy.py` (NoDeviceDriver)** | **KEEP** | Protocol requires one no-device driver; 9 isinstance gates in UI + `get_driver_cls` fallback. |
| **`driver/driver.py`** | **KEEP** | Ruida inherits it; `ruida_encoder.py:23` imports `acceleration_run_up_mm`. |
| **`transport/serial.py`** | **KEEP** | `varset/adapter/combo.py:11` calls `SerialTransport.list_ports()`. |
| `pyserial`, `aiohttp` | KEEP | Still referenced after removal. |

### 6. GCode - REMOVE (UI only). DEFAULT WHEN UNCERTAIN applied.

The package's default rule fires: dialect machinery IS imported by the
Ruida job path, so the minimal core stays and only UI goes.

Boundary, documented as required: `ruida_driver.py:18` and
`ruida_encoder.py:18` import `pipeline.encoder.base`, which runs
`pipeline/encoder/__init__.py:3` (`from .gcode import GcodeEncoder`)
and pulls in the dialect package. Ruida stays off the G-code branch
only because `RuidaDriver.uses_gcode = False` (`ruida_driver.py:61`)
makes `machine.dialect` return `None`, so `intent_builder.py:815`
falls through to `PythonEncoder(RuidaEncoder)`.

| Item | Verdict | Reason |
|---|---|---|
| `gcode_settings_page.py`, `dialect_list.py`, `dialect_editor.py`, `template_selector.py` | REMOVE | Dialect-editing UI; already hidden for Ruida at `settings_dialog.py:300-317`; no test importers. |
| **`pipeline/encoder/**` (all of it, incl. `gcode.py`)** | **KEEP** | Under `pipeline/` - the grep gate forbids touching it, and `NoDeviceDriver` returns `GcodeEncoder` (`dummy.py:86-89`), which the protected `intent_builder.py:978-982` falls back to. |
| `machine/models/dialect/**`, `dialect_manager.py` | KEEP | `machine.py:33` imports `GcodeDialect` at runtime; `Machine.__init__` defaults `dialect_uid='grbl'`; `from_dict` migrates at `:1670-1672`. |
| **G-code Viewer bottom tab / `shared/gcodeedit/**`** | **KEEP** | It renders the Ruida job preview (`mainwindow.py:1348-1349`). Removing it removes a working Ruida feature. |
| **Console (`ui_gtk/machine/console.py`)** | **KEEP** | Imports nothing gcode; commands go to `machine.run_raw`, which `RuidaDriver` implements at `:689`. A raw-command terminal that works on Ruida. |
| `gcode_editor.py`, `hook_list.py`, `macro_list.py`, `hooks_macros_page.py` | KEEP | Titled "G-code Hooks" but macros run through `run_raw`; functional for Ruida. |

Trap recorded: `settings_dialog.py:237-238` grabs the sidebar row by
hard-coded index 3 (`get_row_at_index(3)`); removing an earlier row
silently re-points it.

### 7. Multi-machine management - REMOVE (UI only)

| Item | Verdict | Reason |
|---|---|---|
| `unified_wizard.py` + `machine/wizard_pages/**` (11 pages) | REMOVE | Add-machine wizard; closed graph with `test_unified_wizard.py`. |
| `machine_dropdown.py` | REMOVE | Machine picker; `update_eta()` (`mainwindow.py:724,747,755,769`) must be rehomed first or the job ETA dies. |
| `settings/machine_settings_page.py` | REMOVE | Machine list/delete page. |
| `profile_importer.py`, `lbdev_import_dialog.py` | REMOVE | Only caller is `profile_page.py`. |
| Driver selector combo (`settings_dialog.py` General page) | REMOVE | One driver only. |
| **`MachineManager`** | **KEEP (collapse to one)** | `Machine.controller` delegates to `get_controller()`; every jog / Start-Pause-Stop path needs it. Leave `set_active_machine` a no-op - `core/config.py:355` subscribes to `machine_removed` at construction. |
| **`Config.machine` / `context.machine`** | **KEEP** | 81 references across 14 modules. |
| Machine settings dialog (per-machine editing) | KEEP | Becomes the single profile editor (Package B4). |

### 8. Rotary - BLOCKED (stop condition)

The A2 gate FAILS. Removal requires editing PROTECTED files:
`rayforge/pipeline/intent_builder.py:77` imports `RotaryMode` /
`RotaryType`, and `:911` / `:1140` call
`machine.get_rotary_module_for_layer`; `rayforge/core/layer.py` carries
`rotary_enabled` / `rotary_diameter` / `rotary_module_uid`.

Verdict: do not remove. Halted and reported rather than improvised.
Removing only the two UI pages (`rotary_module_page.py`,
`wizard_pages/rotary_page.py`) would leave the model, serialisation,
kinematics and job-path branches intact but make rotary
unconfigurable - a half-removal that reads as a bug. Awaiting an
explicit owner decision.

### 9. Z-probe / autofocus - split verdict

| Item | Verdict | Reason |
|---|---|---|
| `grbl_probe.py`, `marlin_probe.py` | REMOVE | Go with their drivers (item 5) - they are firmware auto-detection for GRBL/Marlin. |
| `wizard_pages/probe_page.py` | REMOVE | Goes with the wizard (item 7). |
| **`Driver.run_probe_cycle` + `probe_status_changed` base decl** | **KEEP** | Dead in production (no UI caller anywhere), but the PROTECTED `ruida_driver.py:1577` overrides it. Reported as dead code, not removed. |

### 10. Device discovery (non-Ruida) - REMOVE

Serial-port enumeration and driver `probe()` are the only discovery
that exists; there is no network scan / mDNS / zeroconf anywhere in the
repo. Removed together with the drivers and the wizard.
`SerialTransport.list_ports()` stays (item 5).

### 11. Experimental addons - REMOVE (the two experimental ones only)

| Item | Verdict | Reason |
|---|---|---|
| `rayforge-addon-cnc` (43 .py), `rayforge-addon-tools` (10 .py) | REMOVE | Both `default_state: disabled` + `maturity: experimental`; zero inbound refs from core. |
| `ui_gtk/addon_manager/experimental_dialog.py` | REMOVE | The experimental-addons dialog named in the package. |
| **`rayforge-addon-laser` (laser_essentials)** | **KEEP** | Supplies `ContourStep`/`EngraveStep`, resolved BY NAME in `doceditor/step_cmd.py:168,193,194`, `core/recipe.py:26-29`, `image/assembler.py:218,220`. The PROTECTED `intent_builder.py:498,528` calls `step.build_compute_payload()`. |
| **`rayforge-addon-post` (post_processors)** | **KEEP** | `ContourStep` hard-asserts seven of its transformers. |
| `addon_mgr/**` core, `pluggy` | KEEP | The whole hook/registry architecture uses pluggy (6 users). |

Latent bug recorded, not fixed: `AddonManager.can_disable`
(`addon_manager.py:1558`) only checks addon-to-addon `requires`, so the
Settings > Addons toggle lets a user disable `laser_essentials`, after
which `step_cmd.py:168` silently returns and new layers get no step.

### 12. AI subsystem - REMOVE

| Item | Verdict | Reason |
|---|---|---|
| `rayforge/core/ai/**` (5 modules), `tests/core/ai/` | REMOVE | Closed set; nothing in pipeline, layer/step, machine model or any driver imports it. |
| `ai_lookup_page.py`, `provider_page.py`, `ai_settings_page.py` | REMOVE | Its only UI surfaces. |
| `rayforge-addon-ai-workpiece`, `scripts/screenshot/ai_workpiece_generator.py` | REMOVE | Sole addon consumer. |
| `context.py:11-12,60-61,197-217,406-407` | REMOVE | AI service properties. |
| `aiohttp` | KEEP | Five other users. |

---

## Explicit KEEP list (PROTECTED and load-bearing)

- `machine/driver/ruida/**` and all its tests - PROTECTED.
- `pipeline/**` in its entirety - PROTECTED; no package touches it.
- Jog panel: hold-jog + safety releases, Home, Go Scale, Cut Scale +
  confirmation, start-corner selector, X/Y readout - PROTECTED.
- mm/s units, Min/Max power, Start/Pause/Stop - PROTECTED.
- Layer/step system, `laser_essentials`, `post_processors` - PROTECTED
  and load-bearing.
- Swift Cut theme + layout tokens (`docs/design/`) - PROTECTED.
- `StartupBehavior`, `machine_state.py`, model-preview mesh helpers,
  `TimeEstimateOverlay`, `VisibilityOverlay`, `SerialTransport`,
  `NoDeviceDriver`, `Driver` base - see reasons above.

## Dependencies that removal does NOT free

`cv2`, `numpy`, `blinker`, `raygeo`, `PyYAML`, `pluggy`, `aiohttp`,
`pyserial`, `PyGObject`, `pycairo`, `semver`, `PyOpenGL`, `trimesh`.

Only `websockets` (with the GRBL network driver) and the snap `camera`
plug become droppable.

## Uncertainties recorded, not acted on

- `rayforge/machine/kinematic_mapping.py` - no non-test inbound
  reference found, but the mapping agent could not prove it dead.
  Verify before touching.
- `mainwindow.py:1146` passes `initial_page="hours"`, but no such
  sidebar page exists (the counters page is `maintenance`).
- `profile_importer.open_profile_zip` has zero callers.
- `machine/device/__init__.py` re-exports four unused names.

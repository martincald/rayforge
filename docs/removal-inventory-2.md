# Removal inventory 2 - 2026-10-08

Second removal pass (Package A). Scope: remove the Ruida driver's
maturity warning (A1), then purge settings, step options, formats and
leftovers that have no effect on a Ruida CO2 machine (A2), keeping
everything the Ruida path reads.

Base commit: `2cdb96c0d`. Every row was located with graphify
(`graphify query` / `explain` / `path` over `graphify-out/graph.json`)
and then confirmed by grep against the code at the base commit; line
numbers are the base commit's. `docs/design/audit/AUDIT.md` section L
(L1-L31) found most of these first and is cited as `AUDIT Ln`.

**No deletion may begin before this file is committed.**

## Legend

- **REMOVE** - delete the surface and the code only it reaches.
- **REMOVE(UI)** - delete the user-facing surface; keep the model field
  because the job path or the profile YAML reads it.
- **KEEP** - stays, with the reason.
- **FIX** - a leftover gate that is changed, not deleted.
- **DEFER** - real, but outside this pass (a fix, not a removal, or
  owned by another package).

PROTECTED = `machine/driver/ruida/**`, the pipeline job path
(intent_builder aggregate assembly, build_rd_bytes, send_job, .rd
export), jog panel behaviour, mm/s units, Min/Max power, Start/Pause/
Stop, layer/step system, Swift Cut theme + layout tokens,
MOTION_AUDIT.md invariants. The only protected line this pass changes
is `ruida_driver.py:171` (A1 allows it).

## A1 - Driver maturity

| # | Path | What | Ruida path reads it? | Verdict |
|---|---|---|---|---|
|1|machine/driver/ruida/ruida_driver.py:171 `maturity = DriverMaturity.KNOWN_BUGGY`|Ruida class attribute|Only the banner reads it|SET to DriverMaturity.STABLE (PROTECTED path, task A1 allows it, 1-line diff)|
|2|ui_gtk/machine/settings_dialog.py:5-9 imports, :26-33 `.maturity-warning` CSS, :73-88 banner widgets, :198-202 signal + first call, :213-226 `_on_machine_changed`/`_update_maturity_banner`, :268-270 `_on_destroy` (it only disconnects that handler)|"almost certainly buggy" banner|n/a (UI)|REMOVE|
|3|machine/driver/driver.py:86-100 DRIVER_MATURITY_LABELS; driver/__init__.py:5,38|label table|banner was its only consumer (grep)|REMOVE|
|4|driver.py:79-84 DriverMaturity, :231 Driver.maturity|enum + attribute|ruida_driver.py:29,171 import it|KEEP|
|5|addon_mgr/addon.py:26-48 AddonMaturity, addon_list.py:86|addon maturity|unrelated|KEEP|

No test references DriverMaturity or the banner (grep over tests/).

## A2.1 - Machine Settings pages and fields

| # | Path | What | Ruida path reads it? | Verdict |
|---|---|---|---|---|
|6|hooks_macros_page.py(29), hook_list.py(184), macro_list.py(148), gcode_editor.py(299, opened only by those two lists); settings_dialog.py:21,119-123,175-177|"Hooks & Macros" page|NO. RuidaDriver.run_raw is a logged no-op (ruida_driver.py:1044-1056). Hooks reach only `_build_macro_table` (pipeline/encoder/rust_helpers.py:142-160), which runs only on the Grbl branch (intent_builder.py:814-816 → `_grbl_encoder_spec` :840). graphify path RuidaEncoder→MacroTrigger has only an INFERRED 8-hop link through Config→Machine. The first pass's KEEP (§6) was factually wrong (AUDIT L2/L4)|REMOVE(UI)|
|7|Macros menu: main_menu.py:5,183-188,262-267; mainwindow.py:742-763 (`_update_macros_menu`, `on_execute_macro`), :1592,:1757; actions.py:417-420 `execute-macro`; machine/cmd.py:657-683 `execute_macro_by_uid`|macro execution|NO (run_raw no-op)|REMOVE|
|8|Machine.hookmacros/macros, models/macro.py, profile.py:16,451-455|model + YAML|read by rust_helpers.py:17,144-156 (pipeline/**, PROTECTED) and YAML load|KEEP|
|9|device_settings_page.py "Device Settings" read/apply group: main_group header read button :76-82, unsupported_banner :86-91, prompt_group :202-212, `_rebuild_settings_widgets` :366, `_on_settings_op_success` :595, `_on_setting_apply` :649, `_on_read_clicked` :666, warning rows|firmware-settings editor|NO. supports_settings=False (ruida_driver.py:168); get_setting_vars returns "No settings", write_setting does nothing (:1480-1484) (AUDIT L6)|REMOVE(UI, partial)|
|10|device_settings_page.py: Connection group :169-196, USB device, Diagnostics :218-260, port reset :248-252, legacy-import banner :99-108, Activate banner `_on_activate_clicked` :805|connection/USB/diagnostics|YES (driver_args connection/usb_serial)|KEEP (the Activate banner belongs to H)|
|11|head_preferences_page.py:101-104,212-262 add/remove head, Laser/Spindle buttons; Tool Number row :441-452|more than one head|tool_number IS read (ruida_encoder.py:575, ruida_driver.py:1499); its value stays 0 → laser 1|REMOVE(UI). Keep Head.tool_number and Machine.add_head/remove_head|
|12|head_preferences_page.py:873-1020 SpindleHeadDetailWidget|spindle/coolant UI|NO (Ruida `_handle_coolant` does nothing, ruida_encoder.py:538-546)|REMOVE(UI)|
|13|machine/models/spindle.py SpindleHead|model|core/step.py:22,690 imports it (layer/step, PROTECTED); graphify explain shows 45 edges|KEEP|
|14|head_preferences_page.py:264-393 HeadModelGroup "3D Model" (scale, rotation)|3D head model|NO; only machine.get_head_specs (machine.py:429-446)|REMOVE(UI). Keep Head.model_path/transform (YAML)|
|15|head_preferences_page.py:456-468 Laser Type combo|Diode/CO₂/Fiber|laser_type IS read (ruida_driver.py:461-464 supports_pwm)|REMOVE(UI). Model keeps "diode" (ilab-614.yaml:60) so output stays unchanged|
|16|head_preferences_page.py:553-609 PWM group (PWM Freq, Max PWM Freq, Pulse Width, Min/Max Pulse Width) + `_update_pwm_visibility` :804; laser_control_widget.py:101-117,219-223 Frequency/Pulse rows|PWM fields|Model fields read by get_pwm_params (ruida_driver.py:466-476). The encoder emits C6 60/C6 10 only when ops carry them (ruida_encoder.py:474-513); its docstring says the reference .rd has neither. Diode → supports_pwm False → never emitted today|REMOVE(UI). Keep LaserHead.pwm_* fields and the encoder|
|17|head_preferences_page.py:470-477 Max Power ("value in GCode")|S-max|NO; only rust_helpers.py:183 (G-code) and legacy conversion laser.py:232-248|REMOVE(UI). Keep the field|
|18|head_preferences_page.py:542-551 Focal Distance|Z offset|NO; only machine.py:439-441 (3D assembly)|REMOVE(UI)|
|19|head_preferences_page.py:479-490 Focus Power|focus-laser power|toggle-focus (mainwindow.py:1736-1741,2316-2319) sends C7 power-immediate (ruida_client.py:690-702,889-896); Print-and-Cut wizard.py:626-648|KEEP (NEEDS-OWNER: does C7 light the beam?)|
|20|head_preferences_page.py:492-540 Spot Size X/Y, Cut/Raster colour|optics + display|spot size feeds raster resolution and kerf (laser.py:55-80; Package D); colours read by laser_step.py:246, raster_step.py:137, colors.py:48|KEEP|
|21|rotary_module_page.py(801); settings_dialog.py:24,134-138,180-182|Rotary Module page|model/pipeline only (intent_builder.py:77,888-909 PROTECTED). ilab-614 has rotary_modules: []|REMOVE(UI)|
|22|layer_settings_dialog.py:99-142,200-260 "Rotary Attachment" group; layer_column.py:388-389 icon, :431-432 module subtitle|layer rotary UI|same as #21|REMOVE(UI). Keep Layer.rotary_* (core/layer.py PROTECTED), the surface.py:756-779,1287-1401 branches, editor.py:76-84,510-540 and project_cmd.py:88-96 (all inert when rotary is off)|
|23|capabilities_page.py(83); settings_dialog.py:16,152-156,189-191|read-only capability list|NO (display only; MachineCapability drives step filtering through machine.get_capabilities)|REMOVE(UI). Keep core/capability.py|
|24|general_preferences_page.py:17-21,151-182,216-229,307-354 Unit System group + G20/G21 preamble warning|G-code units|NO. Zero hits for unit_system/_to_machine_* in machine/driver/ruida/*; readers are rust_helpers.py:215 and driver.py:293-326 helpers with 0 callers (AUDIT L14)|REMOVE(UI). Keep Machine.unit_system|
|25|general_preferences_page.py:291-305 `_update_travel_speed_state` (dialect.can_g0_with_speed) + calls :191,:212|dialect remnant that greys out Max Travel Speed|max_travel_speed IS read (ruida_driver.py:1459-1467; intent_builder.py:719; cmd.py:220)|FIX: delete the gate, row stays sensitive (AUDIT L7)|
|26|advanced_preferences_page.py:40-48,120-122 Support Bézier Curves|curve output|DANGEROUS: the RuidaEncoder dispatch (ruida_encoder.py:280-318) has no BEZIER_TO/QUADRATIC_BEZIER_TO branch; intent_builder.py:893 linearises only when False. Turning it on would silently drop curves|REMOVE(UI), value stays False|
|27|advanced_preferences_page.py:86-95,127-128 Allow Single Axis Homing|homing UI flag|NO; nothing else reads single_axis_homing_enabled|REMOVE(UI)|
|28|advanced_preferences_page.py:97-109,130-131 Clear Alarm On Connect|auto-unlock|NO; Ruida clear_alarm only logs (ruida_driver.py:1486-1494)|REMOVE(UI)|
|29|advanced_preferences_page.py:30-64 Arcs + tolerance, :75-84 Home On Start|path/homing|YES (ARC_TO ruida_encoder.py:302; contour_step.py:114-116; mainwindow.py:580)|KEEP|
|30|hardware_page.py:108-120,290,348-349 Reverse Z row|Z direction|already hidden: RuidaDriver.can_jog(Z) is False (:1505-1515)|REMOVE(UI). Keep reverse_z_axis (intent_builder.py:897)|
|31|nogo_zones_page.py, maintenance_page.py, the rest of hardware_page|zones, hours, bed|YES (sanity/checker.py:65; machine_hours; Ruida reads axis_extents and reverse_x/y)|KEEP|

## A2.2 - Dock, toolbar and menus

| # | Path | What | Ruida path reads it? | Verdict |
|---|---|---|---|---|
|32|laser_control_widget.py:41 on/off toggle, :92 Power, :118 Duration, :37 Laser Head combo|manual pulse|NO; disabled with "Not supported on this controller" because Ruida keeps can_pulse() False (driver.py default)|REMOVE. KEEP Focus Z row :127-136 (D8 2E, 06f1e6b59)|
|33|toolbar.py:173-180 clear_alarm_button; main_menu.py:194; actions.py:431; mainwindow.py:1140-1146 (auto-clear), :1590,:1717-1730 (enable/CSS), :2280 on_clear_alarm_clicked; cmd.py:471-476|Clear Alarm|NO (no-op; no ALARM state is ever produced; AUDIT L8)|REMOVE. Keep the abstract Driver.clear_alarm/can_clear_alarm (Ruida overrides them)|
|34|main_menu.py:41 "Export G-code...", actions.py:38 Ctrl+E, :243 `export`; toolbar.py:59-62 export_button "Generate G-code"; mainwindow.py:2057-2066, :2139-2150, :1583,:1615-1625; file_dialogs.py:67-100; file_cmd.py:971-1016 FileCmd.export_gcode_to_path|G-code export|Writes the RuidaEncoder text dump as .gcode, which no controller can load (AUDIT L1)|REMOVE. Re-point the toolbar button + Ctrl+E at win.export-rd and leave the .rd path untouched. KEEP DocEditor.export_gcode_to_path (editor.py:389, pipeline e2e test helper, test_doceditor.py:68,181)|
|35|main_menu.py:180 "Frame"; actions.py:425; mainwindow.py:1586,1662-1667,2174-2190; cmd.py:233-300 `_run_frame_action`, :366-380 frame_job; machine.py:1244-1249 can_frame; head Framing group head_preferences_page.py:611-658|Frame action|Frame needs frame_power>0 (ilab-614 has 0); its corner pause uses DWELL, which RuidaEncoder drops|KEEP - OWNER CALL. Commit 0344d7a35 kept the menu entry on purpose and a test pins it, so it is not a leftover of a removed feature. Removal waits for the owner|
|36|console.py:112-142 entry box, :474-560 input/history/send; bottom_panel.py:120,344 `_on_command_submitted`|console command line|NO (run_raw no-op; AUDIT L3)|REMOVE input only. KEEP the log view (UILogFilter)|
|37|bottom_panel.py:442-445,465,811 zero_z_btn|Zero Z|NO; set_wcs_offset ignores z (ruida_driver.py:1866-1893)|REMOVE(UI)|
|38|WCS dropdown (bottom_panel.py:618-620 → controller.switch_active_wcs → run_raw)|reference point|broken, not dead (AUDIT L5)|DEFER (a fix, not a removal)|

## A2.3 - Step types and options

| # | Path | What | Ruida path reads it? | Verdict |
|---|---|---|---|---|
|39|multipass_group.py:42-50,62-75,83-90 "Z Step-Down per Pass"|Z per pass|NO (RuidaEncoder has no Z handling)|REMOVE(UI). Keep MultiPassTransformer.z_step_down (default 0)|
|40|raster_page.py:190-200,527 z_step_row (Multiple Depths)|Z per depth|NO|REMOVE(UI). Keep raster_step.z_step_down and DepthMode.MULTI_PASS (passes still run)|
|41|step_settings/pages/base.py:9,80-95 coolant section; rows/coolant_row.py(55); rows/__init__.py:4|coolant|NO (only shown for SpindleHead; encoder no-op)|REMOVE(UI). Keep Step.coolant_method (core/step.py PROTECTED) and file_cmd.py:73-87 (inert)|
|42|Steps Contour, Engrave, Frame step, Material Test, Shrinkwrap, Wavefront (laser_essentials/worker.py:22-29)|step types|YES; all emit MOVE/LINE/ARC/SCAN_LINE/SET_POWER, which the encoder handles|KEEP|
|43|air_assist_row, overscan_group (handles native overscan :85-101), tabs, pwm_row (hides itself, pwm_row.py:39)|options|YES / self-hiding|KEEP|

## A2.4 - Import and export formats

| # | Path | What | Ruida path reads it? | Verdict |
|---|---|---|---|---|
|44|Importers SVG, DXF, PDF, PNG, JPG, BMP, LightBurn .lbrn, Ruida .rd (image/__init__.py:175-207)|lab formats|n/a|KEEP|
|45|Export Object/Document SVG/DXF (file_cmd.py:1072-1185), sketch .rfs|geometry export|n/a|KEEP|
|46|machine/device/lightburn_importer.py(259) + device/manager.py:12,206-240 install_from_lbdev|.lbdev device-profile importer, ships a GRBL dialect|NO; no caller since the first pass (AUDIT L28)|REMOVE. Do not touch image/lightburn|

## A2.5 - Leftovers of removed features

| # | Path | What | Ruida path reads it? | Verdict |
|---|---|---|---|---|
|47|ui_gtk/shared/model_preview/** (~1,200 LOC), ui_gtk/settings/model_preview_widget.py(255), ui_gtk/shared/model_selection_dialog.py(129), resources/models/*.glb/*.FCStd|3D mesh preview|NO; only #14 and #21 reach it|REMOVE (keep resources/models/__init__.py, which model_manager.py:198-200 imports)|
|48|PyOpenGL, PyOpenGL-accelerate, trimesh (pixi.toml:32-33,56; requirements.txt:14-15,23)|3D dependencies|only #47 imports them|KEEP for now - NEEDS-OWNER. Dropping them needs a pixi.lock re-solve (network). The code that imports them goes with #47|
|49|core/config.py:39 show_models, :41 perspective_mode; actions.py:279-281; mainwindow.py:974-981,1042-1048; visibility_overlay.py:27,79-90|3D view toggles|NO (AUDIT L10/L11)|REMOVE|
|50|icons 3d-symbolic (pinned only by test_swift_cut_icons), 3d-rotation, camera-on/off (0 refs), model-symbolic (#49 only). play-arrow-symbolic has 3 refs|icons|n/a|REMOVE (play-arrow KEEP)|
|51|about.py:164-165 "aiohttp","websockets"|About deps rows|n/a (AUDIT L18/L25)|REMOVE rows. Keep the aiohttp package (DEFER)|
|52|docs/profiles/ilab-614.source.yaml:31 `cameras: []`|stale key|n/a (L19)|DEFER to Package H (it regenerates the bundled profiles)|
|53|machine/transport/serial.py(367), serial_server.py, core/varset serialportvar.py/baudratevar.py, ui_gtk/varset/adapter/combo.py:6-11,105-160, transport/__init__.py:3,9-16|generic serial|NO. Ruida USB uses pyserial directly (ruida_usb_transport.py:72-74)|REMOVE (keep pyserial and TransportStatus/UDP)|
|54|resources/devices/{monport-60w-co2,omtech-polar,thunder-laser-nova35}|third-party profiles|NO UI reaches them (L27)|REMOVE trees. KEEP DeviceProfileManager (context.py:290-302), pending H|
|55|mainwindow.py:1179 initial_page="hours"|stale page id|n/a (L30)|FIX → "maintenance"|
|56|driver.py:238,432-445 detect_unit_system/supports_unit_detection; driver.py:293-326 `_to_machine_*` helpers|GRBL unit plumbing|0 callers|REMOVE (not under ruida/)|
|57|Driver.run_probe_cycle/probe_status_changed/supports_probing|probe|ruida_driver.py:1931 override uses the base signal (PROTECTED)|KEEP|
|58|machine/models/dialect/**, dialect_manager.py, pipeline/encoder/gcode.py|G-code dialects|NoDeviceDriver → GcodeEncoder (dummy.py:86-89); the migrated "Default Machine" uses them; intent_builder.py:76,88|KEEP|
|59|kinematic_mapping.py, machine/assembly.py, kinematics.py, core/model.py|kinematics|pipeline.py:19 (PROTECTED); machine.py:24-27|KEEP|
|60|website/sidebars.js + camera/3d-preview/usage-tracking/firmware/gcode-dialects/machines pages (+6 locales)|published docs|n/a (L9/L31)|REMOVE, separate last commit|
|61|locale/*.po stale strings (L20); TrackedPreferencesPage key/path_prefix (L12); G-code wording (L16); one-page view stack (L23)|polish|n/a|DEFER|
|62|MachineManager.set_active_machine/remove_machine (L26); recipe Machine picker (L15)|multi-machine|n/a|KEEP: owned by Packages H and I|

## Gates

- `git diff --stat 2cdb96c0d -- swiftcut/machine/driver/ruida
  tests/machine/driver/ruida` shows only `ruida_driver.py` (1 line).
- `swiftcut/pipeline/**`, `core/step.py`, `core/layer.py`,
  `jog_widget.py` and `theme.py` are unchanged.
- Grep for every removed identifier returns nothing outside
  `website/`, `locale/` and this file.
- Suites match the baseline at `2cdb96c0d`: non-UI 5304 passed, 1
  known failure (`test_bind_failure_on_a_fixed_local_port_is_visible`);
  UI 674 passed, 3 known failures (2 x `TestTrackpadContinuousZoom`,
  `test_identity_zoom_no_pan_matches_documented_composition`).

## Recorded decisions

- PWM and laser type: the UI goes, the model fields and the encoder
  stay. ilab-614 stores `laser_type: diode`, so no C6 60/C6 10 is ever
  emitted and the bytes still match the reference `.rd`.
- Rotary: an old document saved with `rotary_enabled: true` can no
  longer be switched off from the UI (core/layer.py is protected). No
  lab document uses rotary and ilab-614 has `rotary_modules: []`.
- Export G-code: the toolbar button and Ctrl+E now open the `.rd`
  export. The `.rd` export code itself is unchanged.
- Importers: all kept (SVG, DXF, PDF, PNG, JPG, BMP, LightBurn, .rd).
  Only the `.lbdev` device-profile importer goes.

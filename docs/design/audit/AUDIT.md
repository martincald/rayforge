# UI consistency audit — after the Swift Cut reskin

Phase 1 of the consistency pass. **No fixes are made here.** Every
entry names what is inconsistent, the evidence for it, and the shared
rule that would settle it — so Phase 2 can write one rule per finding
instead of one patch per widget.

The reskin (`docs/design/swift-cut-tokens.md`) gave the app a colour,
radius and type *token* map and applied it to the surfaces it named.
It never defined a **layout** system, and that is what this audit
keeps finding: spacing, control sizes, label columns and caption
grammar were each decided per widget, by whoever wrote the widget.

---

## 0. How the captures were made

`scripts/screenshot/ui_audit.py`, run against an isolated config so
the result does not depend on a developer's own machine profile:

```
rm -rf /tmp/rf-audit-config && cp -r tests/config /tmp/rf-audit-config
python -m rayforge.app --config /tmp/rf-audit-config \
    --uiscript scripts/screenshot/ui_audit.py
```

128 PNGs in this directory: **32 targets × {light, dark} × {1280,
1920}** — the whole main window, the toolbar, all six dock tabs, all
twelve machine-settings pages, all eight app-settings pages, the step
settings dialog and four sheets. Dialogs are their own toplevels, so
"window width" for them is the size they are given: 900px at the
1280 pass, 1300px at the 1920 pass, which is what exposes their
reflow.

Like `swift_cut_review.py` it renders through GTK's own renderer
rather than `gnome-screenshot` or ImageMagick's `import` — neither
exists on Windows — so the frames carry no compositor, cursor or
window shadow.

Two capture bugs had to be fixed before the matrix meant anything,
and both are worth recording because they are app behaviour, not
script bugs:

* **`Adw.StyleManager` does not hold the scheme.** `MainWindow.
  apply_theme()` (`rayforge/ui_gtk/mainwindow.py:1553`) re-reads
  `config.theme` from a config-changed handler and resets the colour
  scheme. Opening any settings dialog fires it, so a forced-light run
  silently produced *dark* dialog captures. The script now sets
  `config.set_theme(...)` instead, so every re-application agrees.
* **A mapped window will not shrink.** Neither `set_size_request`
  (raises the minimum only) nor `set_default_size` (ignored once
  mapped) moves the window off its startup 2048px on this backend;
  only hiding and re-presenting applies a smaller size. Measured, not
  assumed — see `scripts/screenshot/ui_min_width.py`, which also
  confirms the window's *content* minimum is 1086px, so 1280 is a
  legitimate target width.

---

## 1. Spacing

**S1 — There is no spacing scale; there are three.**
Tallied across `rayforge/ui_gtk/**/*.py`:

| value | `set_margin_*` | `spacing=` / `set_*_spacing` |
| --- | --- | --- |
| 12 | 75 | 53 |
| 6 | 61 | 52 |
| **9** | **21** | — |
| 24 | 17 | 1 |
| 4 | 14 | 7 |
| **18** | **13** | — |
| **10** | **5** | — |
| 8 | 2 | 4 |
| 16 | — | 5 |
| **2, 3, 5, 50** | 10 | 6 |

12 and 6 dominate (GNOME's 6px scale), 4/8/16/24 appear as well (a
4px scale), and 9/10/18/2/3/5 belong to neither. The brief asks for a
4px scale; adopting it means 6→8 and 9→8, 18→16, 10→8, and killing
2/3/5 outright.

**S2 — The bottom panel is on the 9px scale, alone.**
`bottom_panel.py:97-98,109-112,127-130` set margin 9 on the G-code
viewer, the laser box and the controls box. Nothing else in the app
uses 9. Inside them, `_jog_laser_box` uses spacing 12 and the jog
grid uses 6 (`jog_widget.py:38-39`), so one panel spans three scales.

**S3 — Row heights inside one list vary by up to 40%.**
Measured off `machine-settings-general-light-1280.png`: within the
one "Speeds & Acceleration" group, Max Travel Speed 66px, Max Cut
Speed 66px, Acceleration 76px. In
`app-settings-general-light-1280.png`, the "Appearance" group runs
50 / 60 / 60px. In `step-settings-light-1280.png` five rows are 54px
and Offset is 76px. The height is whatever the subtitle's line-wrap
produces; nothing sets a floor or a rhythm.

**S4 — Edge-to-edge stretch with an empty middle.**
`dock-controls-light-1280.png`: in the Zero Axes row the label ends
at x≈636 and the first button starts at x≈740 — 100px of nothing. In
Current Position the gap is ~140px. The `Adw.PreferencesGroup` takes
the panel's full width and pushes the suffix box to the far edge; at
1920 (`dock-controls-light-1920.png`) the gap simply grows. This is
the seed observation, and it is structural: a max width or a
two-column grid is the fix, not per-row padding.

---

## 2. Alignment

**A1 — Controls do not share a right edge.**
`dock-controls-light-1280.png`: the icon rows (Current Position,
Start Corner, Zero Axes) end at x≈957, the spin rows (Jog Speed, Jog
Distance) at x≈977, and the WCS edit pencil at x≈960. Three edges
within six rows of one group. Same in
`machine-settings-general-light-1280.png`: pencil 856, chevron 864,
spin 870.

Cause: an `Adw.ActionRow` suffix is whatever widget was added, and a
`Gtk.SpinButton` carries its own end padding while a flat icon button
does not. Nothing normalises the suffix box.

**A2 — There is no label column.**
Every row lets its title/subtitle take the space the suffix does not
want, so the text column width changes from row to row and from panel
to panel. In `machine-settings-general-light-1280.png` the
Acceleration subtitle wraps at ~640px; in
`step-settings-light-1280.png` the Offset subtitle wraps at ~610px in
a dialog of the same 900px width. Nothing declares "the label column
is N".

**A3 — Icons are centred in their box, not optically.**
`bottom_panel.py` gives ten row buttons `set_size_request(40, -1)`
with no height, so each is as tall as the row it lands in — 34px in
Zero Axes, 40px in Start Corner. A glyph centred in a box of varying
height does not sit on a common baseline down the column; visible in
`dock-controls-light-1280.png` where the Zero Axes glyph row sits ~3px
higher relative to its row than the Start Corner row does.

---

## 3. Sizing

**S5 — Five different icon-button sizes, one per author.**

| context | size | source |
| --- | --- | --- |
| Toolbar | GTK default (~30×28 measured) | `toolbar.py` — nothing set |
| Dock rail | `min-width/height: 28px`, padding 2, margin 1 | `shared/dock_area.py:12-18` |
| Canvas overlay | `min-width/height: 28px`, padding 0 | `shared/visibility_overlay.py:14-18` |
| Panel rows | `set_size_request(40, -1)` ×10 | `doceditor/bottom_panel.py:334-493` |
| Jog grid | `set_size_request(60, 60)` | `machine/jog_widget.py:97` |

Two of these agree on 28 and disagree on padding. None of them is
derived from a token. The brief's rule — *one size per type per
density context* — needs the density contexts named first: toolbar,
panel row, jog grid, rail, overlay.

A sixth size, `min-width/height: 36px` with padding 4 and margin 2,
sits in `shared/icon_tab_widget.py`. It is **dead code** — nothing in
the tree imports it — so it is reported, not changed.

**S6 — Icon glyph sizes are set ad hoc where they are set at all.**
`get_icon()` (`ui_gtk/icons.py:45`) never sets a pixel size, so
almost every icon inherits GTK's 16px. The exceptions are hand-picked:
12 (`asset_browser.py:106`), 16 (`sanity_check_dialog.py:114`), 18
(`workflow_row.py:217`), 40 (`wizard_pages/controller_page.py:137`),
128 (`about.py:260`, `asset_browser.py:258`). Five sizes, no scale.

**S7 — Text buttons and icon buttons in the same row are unrelated
sizes.** In `dock-controls-light-1280.png` the Zero Axes row puts
X/Y/Z (text, 40px wide, ~34 tall) beside zero-here and crosshairs
(icon, 40px wide, ~34 tall) — those match — but the jog grid next to
it runs 60×60, and the toolbar above runs ~30×28. Across the panel a
user sees three button scales with no rule explaining which is which.

**S8 — Eight radii for six roles.**
Declared in Python CSS: 1, 3, 4, 6, 7, 8, 12 and 32px.
`docs/design/swift-cut-tokens.md` §1.4 defines five (5/6/7/8/9/10)
and `theme.py` implements only 7, 6 and 3. Everything else predates
the reskin and drifted:

* `shared/preferences_group.py:11-30` — 12px, where the token map
  says a card is 10px.
* `shared/expander.py:9,15,23,28` — 12px, same.
* `shared/visibility_overlay.py:11` — 6px, where a canvas overlay is
  9px.
* `shared/dock_area.py:16` — 4px, where a dock pip is 5px.
* `doceditor/workflow_row.py:44` — 1px.
* `shared/round_button.py:7` — 32px (intentional: a circle).

**S9 — The main window will not fit a 1280px laptop by accident, only
by 194px of luck.** Content minimum is 1086px with the dock open,
969px without (`scripts/screenshot/ui_min_width.py`). That is fine
today, but nothing holds it: `mainwindow.py:398` hard-codes
`right_pane_box.set_size_request(430, -1)` and the dock adds ~117px
of its own minimum. Worth a regression test rather than a fix.

---

## 4. Typography

**T1 — Two dimming vocabularies.** `dim-label` is used 42 times and
`caption` 10; both render secondary text, and which one a widget gets
is arbitrary. `title-4` (2), `caption-heading` (2) and libadwaita's
own row-subtitle styling add three more paths to the same result.

**T2 — The type scale in the token map was never implemented.**
`docs/design/swift-cut-tokens.md` §1.5 defines `.sc-title` for the
13px/600 title role. `theme.py` has no `.sc-title` rule and no widget
adds the class — grep returns nothing outside the document. The
"Title (semibold)" row of the scale does not exist in the app.

**T3 — Three position readouts, three formats, in one panel.**
All visible at once in `dock-controls-light-1280.png`:

| readout | format | space | style | placeholder |
| --- | --- | --- | --- | --- |
| WCS row subtitle (`bottom_panel.py:752`) | `X: 0.00 Y: 0.00 Z: 0.00` | WCS offsets | row subtitle | — |
| Current Position subtitle (`bottom_panel.py:787-798`) | `X: 12.34   Y: …` 2dp, colon, 3 spaces | WCS-relative | row subtitle | `---` |
| Jog readout (`jog_widget.py:693-700`) | `X 12.3  Y 12.3` 1dp, no colon | machine | `.numeric` mono | `—` (em dash) |

Different precision, different coordinate space, different
punctuation, different type role, and two different "unknown"
glyphs. The brief calls for consolidating to one; the audit's finding
is that the *format* has to be one thing before the widget can be.

**T4 — Captions restate their label.** Extracted from every
`SpinRow` subclass by AST (110 rows):

| row | title | subtitle |
| --- | --- | --- |
| `bottom_panel.py:434` | Jog Speed | **Speed** |
| `nogo_zones_page.py:263` | Width | **Width** |
| `nogo_zones_page.py:271` | Height | **Height** |
| `nogo_zones_page.py:295` | Cylinder Height | **Cylinder height** |
| `nogo_zones_page.py:287` | Radius | Cylinder radius |
| `camera/wizard/card_page.py:104` | Width | Card width |
| `camera/wizard/card_page.py:114` | Height | Card height |
| `general_preferences_page.py:143` | Max Travel Speed | Maximum rapid movement speed |
| `general_preferences_page.py:158` | Max Cut Speed | Maximum cutting speed |

**T5 — Units live in three places, and often in none.**
Three conventions are in use simultaneously:

1. *In the title* — `'Total angle (deg)'` (`array_dialog.py:422,488`),
   `'PWM Frequency (Hz)'` (`wizard_pages/head_page.py:102`),
   `'Cache budget (MB)'` (`general_preferences_page.py:262`),
   `'Max Power (S-value)'` (`wizard_pages/head_page.py:74`).
2. *In the subtitle* — `'Default PWM frequency in Hz'`
   (`head_preferences_page.py:542`), `'Pulse width in µs'`
   (`laser_control_widget.py:109`), `'Pause duration in seconds…'`
   (`maintenance_page.py:273`).
3. *Only in a tooltip* — every unit-aware row.
   `UnitSpinRow.update_unit_and_bounds()`
   (`shared/pref_rows/unit_spin_row.py:100-103`) sets
   `_("Value in {unit}")` as the spin button's tooltip and nowhere
   else, deliberately: *"The unit is shown via the tooltip rather
   than repeated in every subtitle or as a suffix."*

The consequence is visible in
`machine-settings-general-light-1280.png`: **Max Cut Speed 16.7** and
**Acceleration 1000** carry no visible unit at all, and in
`step-settings-light-1280.png` **Offset 0.05** and **Overcut 0.00**
carry none either. The one row that *does* state its unit —
`'Distance in machine units'` on Jog Distance
(`bottom_panel.py:444`) — states it uselessly, since "machine units"
names no unit.

The brief's rule (units in the field suffix *or* the caption,
consistently, never both) resolves this, but note it contradicts the
existing deliberate tooltip-only choice, so Phase 2 has to pick one
and change `UnitSpinRow` rather than 110 call sites.

**T6 — Placeholder glyphs disagree.** `---` (three hyphens,
`bottom_panel.py:798`) versus `—` (em dash, `jog_widget.py:697`) for
the same "unknown" state, four rows apart on screen.

---

## 5. Iconography

**I1 — No leftovers from an old icon set.** All 203 icons in
`rayforge/resources/icons/` end in `-symbolic.svg`; the only three
non-symbolic files are the app icon itself
(`org.rayforge.rayforge.svg`, `rayforge.icns`, `rayforge.icon`).
Nothing mixes an old set with the design set. This criterion is
clean.

**I2 — 28 icon-only buttons carry no tooltip.** Found by scanning for
a `get_icon()` child with no `set_tooltip_text` within the
surrounding statement block:

```
about.py:211,215,221,236,240        camera/alignment_widget.py:281
camera/camera_preferences_page.py:62 camera/point_bubble_widget.py:112-115
doceditor/material_library_list.py:74,79
doceditor/material_list.py:88,93     doceditor/recipes/recipe_list.py:55,60
doceditor/step_box.py:75,81          machine/dialect_list.py:56
machine/head_preferences_page.py:66  machine/laser_control_widget.py:302,306
machine/macro_list.py:46,51          settings/color_presets_page.py:208
settings/machine_settings_page.py:133,143
```

The recurring shape is the edit/delete pair on every list row —
`material_list`, `material_library_list`, `recipe_list`,
`macro_list`, `dialect_list`, `machine_settings_page`,
`color_presets_page`, `head_preferences_page` all build the same
uncommented pair by hand. One shared row-actions widget would fix
eight of these at once.

**I3 — Tint semantics are applied to two surfaces out of five.**
`theme.py` implements the §2.3 tint map for `.sc-toolbar` and
`.sc-jog`. The dock rail and canvas overlay still colour themselves
from the legacy `@theme_selected_bg_color`
(`dock_area.py:25-26`, `visibility_overlay.py`), so the deck's
"active pip is white on accent" and "overlay toggle is soft accent"
readings are approximations of a different colour.

---

## 6. Theme rules that do not reach their widget

Found while tracing the above; each is a rule that exists and does
nothing.

**X1 — `.sc-split` matches nothing.** `theme.py:128` styles
`.sc-toolbar > .sc-split > button`, but neither split widget adds the
class: `SplitMenuButton` (`shared/splitbutton.py:37`) and
`_HistoryButton` (`shared/undo_button.py:29`) add only `linked`.

The visible symptom in `toolbar-light-1280.png` is that undo, redo,
arrange and tabs read as a different family of button from every
plain toolbar button beside them. Painting the selector red in a
probe run showed *why*, and it is not what it looks like: those four
are **disabled** in an empty document, and the theme's
`:disabled { opacity: .4 }` arm does not cover `.sc-split` either, so
they keep libadwaita's insensitive grey fill while their neighbours
fade. Two gaps in one rule, not one.

**X2 — `.sc-rail` matches nothing.** `theme.py:189` styles
`.sc-dock .sc-rail`; no widget adds `sc-rail`. The dock rail is
`dock-area` / `dock-icon-strip` (`shared/dock_area.py:6-11`) and
paints itself with `@theme_bg_color`.

**X3 — Two colour-token vocabularies.** The reskin redefines the
libadwaita names (`window_bg_color`, `card_bg_color`, …) but not the
GTK3-era `@theme_*` names, which are still live in 14 files: 24 uses
of `@theme_selected_bg_color`, 8 of `@theme_fg_color`, 6 of
`@theme_bg_color`, plus `@theme_selected_fg_color` and
`@theme_base_color`. Those surfaces — the dock, the layer column, the
asset browser, the visibility and time-estimate overlays, the 3D
playback overlay, `round_button`, `key`, `icon_tab_widget`,
`expression_entry` — follow the *stock* theme, not Swift Cut. This is
the single largest reason the reskin looks applied in some places and
not others.

---

## 7. What Phase 2 has to define

Nothing above is fixable widget-by-widget without re-creating the
same drift. The layout system needs to state, once:

1. **A spacing scale** — 4px base, and the allowed steps. Replaces
   S1, S2.
2. **A row contract** — minimum row height, label column width or
   max width, and a single right edge for suffixes. Replaces S3, S4,
   A1, A2.
3. **Control sizes per density context** — toolbar / panel row / jog
   grid / rail / overlay, one icon-button size and one glyph size
   each. Replaces S5, S6, S7, A3.
4. **The radius map from the token doc, actually applied** — and the
   legacy 12/4/1px values removed. Replaces S8.
5. **Typography roles** — title / label / caption / mono numeric, one
   class each, and `dim-label` retired in favour of `caption`.
   Replaces T1, T2.
6. **A caption and unit rule** — captions never restate the label,
   units in exactly one place, and one placeholder glyph. Replaces
   T4, T5, T6, and requires a change in `UnitSpinRow`, not in its 110
   callers.
7. **One position-readout format**, then one readout widget.
   Replaces T3.
8. **A shared list-row actions widget** with tooltips built in.
   Replaces I2.
9. **`@theme_*` retired in favour of the Swift Cut tokens**, and the
   two dead selectors either wired up or deleted. Replaces I3, X1,
   X2, X3.

---

# Pass 2 — after the branding, removal and navigation work

Second consistency pass, run against docs/design/swift-cut-layout.md and
swift-cut-tokens.md after everything that landed since pass 1. Captures
are in docs/design/audit/pass2/ — 112 PNGs, every panel and dialog in
light and dark at 1280 and 1920.

Ids continue rather than restart: pass 1 owns S1-S9, A1-A3, T1-T6, I1-I3
and X1-X3, so pass 2 opens new class letters and never reuses one. L =
leftovers, E = empty/error states, K = keyboard and focus, D = disabled
semantics, H = dialogs and high-DPI, G = token gaps, B = text.
Performance findings are NOT here; they live in docs/PERF_AUDIT.md,
which is measured rather than inspected.

Every finding below was produced by a reader that had to cite file:line,
then re-checked by an independent adversarial verifier whose default
verdict was REFUTED. 202 candidates were raised; 22 were refuted and are
not listed. A finding that merely restates a still-open pass-1 item was
refuted as a duplicate, so nothing here is pass 1 wearing a new number.

**Coverage caveat, stated rather than buried.** The splash screen cannot be
captured by this harness at all: it is a PyInstaller bootloader artefact
(SwiftCut.spec:18) raised before the Python interpreter exists, and a
source run has no splash phase whatsoever. It is audited as a static
asset (swiftcut_splash.png, 480x320, single image, no dark variant) and
appears under H and G. The corner selector and Go Scale ARE captured —
both live inside dock-controls-*.


## Status

Updated as pass-2 fixes land. Anything not listed as FIXED or ESCALATED
is OPEN.

| id | status | note |
| --- | --- | --- |
| B-desktop-exec | FIXED | `Exec=rayforge` -> `swiftcut` in the desktop entry |
| B-metainfo-icon | FIXED | remote icon path moved off the deleted `rayforge/` package dir |
| B-toast-markup | FIXED | `Adw.Toast.set_use_markup(False)` at both sinks |
| B-version-sha | FIXED | build scripts no longer ship a bare commit SHA as the version |
| H-cutscale-default | FIXED | Cut Scale's Enter default is cancel, not cut |
| H-audit-stale-pages | FIXED | `ui_audit.py` no longer requests three removed pages; `SettingsWindow` warns on an unknown id |

**ESCALATED — dead functionality behind live controls.** These are not
polish. Each is a control the user can operate that does nothing, and
each sits on or behind a PROTECTED path (`machine/driver/ruida/**`), so
they are reported rather than changed:

| id | what is dead |
| --- | --- |
| L — macros | `RuidaDriver.run_raw` is a documented no-op, so every macro the user creates or runs is silently discarded |
| L — console | the machine console accepts typed commands and drops them, same `run_raw` no-op |
| L — clear alarm | the toolbar button, the menu item and "Clear Alarm On Connect" are all no-ops |
| L — WCS dropdown | selecting a reference point never switches it on the controller |
| L — G-code hooks | Layer/Workpiece Start/End hooks can never reach a Ruida job |
| L — Device page | Machine Settings > Device is reachable and always empty |

Fixing any of these means either implementing the feature on the driver
or removing its UI, and both are product decisions on a protected path.

## L — Leftovers from removed features

**L1 — BROKEN — "Export G-code…" owns Ctrl+E and the toolbar export button; the real .rd export is a secondary menu item with no accelerator**

main_menu.py:40 appends _("Export G-code...") -> "win.export";
main_menu.py:41-43 appends _("Export Ruida Job (.rd)...") ->
"win.export-rd". actions.py:38 binds `"win.export": f"{PRIMARY_ACCEL}e"`
(Ctrl+E) — win.export-rd appears nowhere in SHORTCUTS. toolbar.py:59-62
is the only export button on the toolbar:
`self.export_button.set_tooltip_text(_("Generate G-code"))` /
`set_action_name("win.export")`. mainwindow.py:1785-1792
on_export_clicked defaults the filename to `f"{stem}.gcode"` and calls
file_dialogs.show_export_gcode_dialog, which (file_dialogs.py:81-96)
titles the dialog _("Save G-code File"), names the filter _("G-code
files"), adds mime `text/x.gcode` and defaults to "output.gcode".
file_cmd.py:962-991 export_gcode_to_path writes `artifact.machine_code`
verbatim, and on Ruida that string is the RuidaEncoder's textual command
dump (ruida_encoder.py:199-200
`EncodedOutput(text="\n".join(text_lines))`) — not G-code, and not a
controller-loadable .rd. So the app's primary, accelerator-bound,
toolbar-mounted export produces a useless file on the only supported
machine.

Fix: Retire the `win.export` action surface (main_menu.py:40,
toolbar.py:59-62, actions.py:38, mainwindow.py:1785-1792 +
_on_save_dialog_response, file_dialogs.show_export_gcode_dialog) and
repoint the existing toolbar button, the Ctrl+E accelerator and the
File-menu entry at `win.export-rd`. This is a pure re-wiring of the
menu/accel/toolbar layer; the .rd export path itself
(on_export_rd_clicked -> export_rd_to_path) is untouched. No shared
token is missing — this is action wiring, not styling.

PROTECTED: The .rd export path is PROTECTED. The fix must not alter
on_export_rd_clicked / _on_export_rd_response / file.export_rd_to_path —
only which menu item, button and accelerator point at them.

**L2 — BROKEN — Every macro the user creates or runs is silently discarded: RuidaDriver.run_raw is a documented no-op**

ruida_driver.py:688-699 `async def run_raw(self, machine_code: str)` —
docstring "This method logs a warning and does nothing." It logs a
warning and calls `self.job_finished.send(self)`. cmd.py:653-658
execute_macro_by_uid expands the macro then
`machine.run_raw(gcode_to_run)`. mainwindow.py:651-662
_update_macros_menu builds a live "Macros" menu from
`config.machine.macros`; mainwindow.py:664-671 on_execute_macro
dispatches to execute_macro_by_uid. hooks_macros_page.py:24-28 adds the
"Macros" group described as _("Create and manage reusable G-code
snippets."), with full create/edit/delete UI in macro_list.py.
docs/removal-inventory-2026-09-04.md §6 KEEPs Console and the macro
pages with the reason "macros run through `run_raw`, which `RuidaDriver`
implements at `:689`" — that verdict is factually wrong: :689 is the no-
op.

Citation corrected on verification:
swiftcut/machine/driver/ruida/ruida_driver.py:689-701 (the finding said
688-699): `async def run_raw(self, machine_code: str) -> None:` … "This
method logs a warning and does nothing." …
`self.job_finished.send(self)`. cmd.py:656-659 (finding said 653-658).

Fix: Re-open the §6 KEEP with the corrected fact and remove the macro
surface: the Macros menu (mainwindow.py:651-671 +
menu_model.update_macros_menu), the "Macros" group
(hooks_macros_page.py:24-28), macro_list.py, and cmd.py's
execute_macro_by_uid. All of these are outside PROTECTED paths.

PROTECTED: ruida_driver.py:688 is under machine/driver/ruida/**
(PROTECTED) — report only; do not change run_raw. The fix is entirely on
the UI/command side.

**L3 — BROKEN — The Console command line accepts input and drops it — same run_raw no-op**

bottom_panel.py:294-301 `_on_command_submitted` does `await
machine.run_raw(command)` inside a fire-and-forget task;
machine.py:1067-1069 -> controller.py:388-393 -> ruida_driver.py:688-699
(no-op, logs "Ruida controllers do not support text-based machine
code"). The Console is a first-class dock tab (bottom_panel.py registers
it alongside controls/laser/layers/assets/gcode) with history, an input
entry and a submit path, so the user gets a working-looking terminal
that never sends a byte. docs/removal-inventory-2026-09-04.md §6 KEEPs
it as "A raw-command terminal that works on Ruida."

Citation corrected on verification:
swiftcut/ui_gtk/doceditor/bottom_panel.py:295-302 (the finding said
294-301). Console tab registration is at bottom_panel.py:82-87 and
:189-192, and the submit signal fires at
swiftcut/ui_gtk/machine/console.py:532.

Fix: Either drop the Console's input entry and keep it as the log viewer
it actually is (console.py already renders UI log records via
UILogFilter — that half works), or drop the tab. Removing just the entry
+ _on_command_submitted (bottom_panel.py:294-301) is the smaller change
and keeps the log pane.

PROTECTED: ruida_driver.py run_raw is PROTECTED — report only. The
console/bottom-panel change is outside PROTECTED paths, but
bottom_panel.py also hosts the jog widget and WCS controls (jog panel
behaviour is PROTECTED), so the edit must be scoped to the console rows.

**L4 — BROKEN — "G-code Hooks" (Layer/Workpiece Start/End) can never reach a Ruida job — the hooks are only read on the Grbl encoder branch**

hook_list.py:19 titles the group _("G-code Hooks"), :33-35 describes it
as "Add custom G-code to be executed at specific points in the job", and
builds an editable row per MacroTrigger (macro.py:10-16:
LAYER_START/LAYER_END/WORKPIECE_START/WORKPIECE_END). The ONLY consumer
of `machine.hookmacros` outside serialisation is rust_helpers.py:144-156
(build_encode_context). build_encode_context is called from exactly two
places: pipeline/encoder/gcode.py:24 (GcodeEncoder) and
intent_builder.py:840 inside `_grbl_encoder_spec`.
intent_builder.py:813-819 routes there only when `dialect is not None
and _is_grbl(dialect)`. For the shipped machine dialect is always None:
ruida_driver.py:61 `uses_gcode = False`, default_profile.py:74
`"dialect_uid": None`, and machine.py:1655-1663 keeps it None for a non-
gcode driver. Ruida therefore always falls through to
PythonEncoder(RuidaEncoder) at intent_builder.py:816-819, which never
looks at hookmacros.

Citation corrected on verification:
swiftcut/pipeline/encoder/rust_helpers.py:142-160 is
`_build_macro_table(machine)`, not `build_encode_context` — the finding
conflated the two. build_encode_context is at rust_helpers.py:206 and
pulls the table in at :220. Routing condition is
intent_builder.py:814-816 (finding said 813-819) and the Ruida fall-
through is :818-821 (finding said 816-819).

Fix: Remove hook_list.py and its use in hooks_macros_page.py:21-22. With
the Macros group also gone (previous finding) the whole "Hooks & Macros"
page and its sidebar row (settings_dialog.py:116-119, :170-172) go with
it, along with gcode_editor.py, which only these two lists open.

PROTECTED: intent_builder.py and pipeline/** are PROTECTED — cited as
evidence only, no change proposed there. hook_list.py /
hooks_macros_page.py / gcode_editor.py are plain UI.

**L5 — BROKEN — The reference-point (WCS) dropdown never switches the reference point on the controller — it sends a G-code G54 through the dead run_raw path**

bottom_panel.py:556-570 `_on_wcs_selection_changed` ->
`machine.switch_active_wcs(w)`. machine.py:1400-1407 ->
controller.py:575-596 `switch_active_wcs`, whose own docstring says
"Sends the G-code WCS command (e.g. G54)" and whose body is `await
self.driver.run_raw(wcs)` then `read_parser_state()`. run_raw is the
Ruida no-op (ruida_driver.py:688-699), so nothing is sent;
read_parser_state (ruida_driver.py:1579-1582) then returns the
controller's *actual, unchanged* mode via
`_client.get_ref_point_mode()`, so `confirmed != wcs` and
controller.py:594-597 logs "Device did not confirm WCS switch" and
leaves `_confirmed_active_wcs = None`. Meanwhile RuidaDriver DOES
implement the correct call — ruida_driver.py:1584-1592 `select_wcs` ->
`_client.select_ref_point(wcs)` — reached only via controller.py:479-491
`MachineController.select_wcs`, which has ZERO callers anywhere in
swiftcut/ or tests/. Worse, ruida_driver.py:527-537
`_poll_ref_point_mode` writes the controller's real mode back into
`machine.active_wcs`, so the combo visibly snaps back to the old value.

Citation corrected on verification: Line ranges drift by a line or
three: bottom_panel.py:556-569 (finding said 556-570);
controller.py:588-599 for the handshake and :596-599 for the warning
(finding said 588-596 / 594-597); ruida_driver.py:527-538 for
_poll_ref_point_mode (finding said 527-537); ruida_driver.py:1584-1593
for select_wcs (finding said 1584-1592). Substance unaffected.

Fix: Point the UI at the method that already works: have
`Machine.switch_active_wcs` delegate to `MachineController.select_wcs`
(controller.py:479-491) instead of `switch_active_wcs`, and delete the
G-code `run_raw(wcs)` + `read_parser_state()` handshake at
controller.py:588-596. Both edits are in controller.py/machine.py, not
in the Ruida driver.

PROTECTED: Adjacent to PROTECTED territory: bottom_panel.py also owns
the jog panel, and active_wcs feeds the Ruida encoder's REF0 anchor
(machine.py:1681-1690, MOTION_AUDIT.md:2151,2181). The change must be
confined to which controller method the dropdown calls; the REF0 default
and the encoder's JOB_REF_POINT must not move. Verify against
MOTION_AUDIT before touching.

**L6 — BROKEN — Machine Settings > Device is a dead page: no driver in the app supports device settings, so it renders one "not supported" banner and nothing else**

device_settings_page.py:210 `is_supported =
self.machine.driver.supports_settings`. The only two drivers left both
hard-code False: ruida_driver.py:59 `supports_settings = False` and
dummy.py:39 `supports_settings = False` (driver/__init__.py:21-25 shows
the registry is exactly Driver/NoDeviceDriver/RuidaDriver). With
is_supported False, `_update_ui_state` (:209-282) blanks the group title
and description (:218-224), hides header_box with the refresh button
(:225), hides both dismissible warning rows (:227-231), suppresses the
error row because `is_not_connected_state` requires is_supported
(:233-237), and hides prompt_group because show_prompt requires
is_supported (:262-269). All that survives is `unsupported_banner`
(:65-70): "The current driver does not support reading device settings."
RuidaDriver reinforces it — ruida_driver.py:1145 returns
`[VarSet(title=_("No settings"))]` and `write_setting` is `pass`. The
page and its sidebar row exist purely for the removed GRBL/Marlin `$$`
settings feature.

Citation corrected on verification: The unsupported banner is
device_settings_page.py:67-71, not :65-70. The wiring the fix targets is
settings_dialog.py:124 (`device_page =
DeviceSettingsPage(machine=self.machine)`) and :176
(`self._add_sidebar_row(_("Device"), "settings-symbolic", "device")`).

Fix: Delete device_settings_page.py and its wiring in
settings_dialog.py:121-125 (add_titled + show_toast connect) and :176
(_add_sidebar_row). The dialog's row->page mapping is by dict
(settings_dialog.py:244), not by index, so the inventory's recorded
`get_row_at_index(3)` trap no longer applies and removing a row is safe.
This is the archetypal "machine-settings page that renders empty for
Ruida" the lens is looking for.

PROTECTED: None. device_settings_page.py is UI only; supports_settings
lives in the PROTECTED ruida driver but is read, not written, by the
fix.

**L7 — BROKEN — Max Travel Speed is permanently greyed out with "Not supported by the driver", yet the value it locks still drives every laser step**

general_preferences_page.py:288-296 `_update_travel_speed_state`: `if
self.machine.dialect and self.machine.dialect.can_g0_with_speed:` ->
sensitive; `else:` -> `set_sensitive(False)` and subtitle _("Not
supported by the driver"). `can_g0_with_speed` is a G-code dialect flag
(dialect/base.py:65) and `machine.dialect` is always None for the
shipped Ruida machine (ruida_driver.py:61 uses_gcode=False;
default_profile.py:74 dialect_uid None), so the else branch is
unconditional — the row is dead on every launch. It is called at :185 at
the end of __init__ and again on every machine change (:213). But the
value is NOT inert: contour_step.py:265, frame_step.py:197,
raster_step.py:451, shrinkwrap_step.py:220, wavefront_step.py:177 and
material_test.py:267 each copy `machine.max_travel_speed` into the step,
so it shapes real Ruida jobs and the time estimate. The user is locked
out of a setting that still matters, with a message that names a driver
capability the app no longer has more than one of.

Citation corrected on verification: The call sites are
general_preferences_page.py:191 and :212 (the finding said :185 and
:213); :185 is `self._update_error_state()`. The method itself spans
:289-303 (finding said 288-296) and the row is defined at :110-115 with
the real subtitle at :112.

Fix: Drop `_update_travel_speed_state` and its two call sites
(general_preferences_page.py:185, :213) and leave the row permanently
sensitive with its real subtitle _("Maximum rapid movement speed") from
:112. The gate was a multi-dialect capability check; with one non-gcode
driver it can only ever say no.

PROTECTED: The value feeds the laser steps and thence the PROTECTED job
path. The fix must only change the row's sensitivity/subtitle — the
stored max_travel_speed semantics and mm/s units must not move.

**L8 — BROKEN — "Clear Alarm" toolbar button, menu item and "Clear Alarm On Connect" switch are all no-ops — Ruida models no alarm state**

ruida_driver.py:1150-1158 `clear_alarm`: "Nothing to clear: this driver
models no alarm state" — the body is a single logger.debug. It is
reachable from three places: toolbar.py:164-171 (a permanent toolbar
button with a clear-alarm-symbolic icon, action `win.machine-clear-
alarm`), main_menu.py:190 (_("Clear Alarm")), and actions.py:420.
mainwindow.py:1536-1541 enables it when `device_status ==
DeviceStatus.ALARM or (active_driver and active_driver.state.error)` and
adds the `suggested-action` CSS class when enabled — the error half IS
reachable, so on any driver error the button lights up as the
recommended action and does nothing. No `DeviceStatus.ALARM` is ever
produced under swiftcut/machine/driver/ruida/ (zero hits), so
status_widget.py:57's ALARM branch and mainwindow.py:971-979's auto-
clear are unreachable too. advanced_preferences_page.py:100-109 exposes
the switch "Clear Alarm On Connect" / "Automatically send an unlock
command if connected in an ALARM state" — "unlock command" is GRBL's
`$X` (still visible at lightburn_importer.py:61 and dialect/grbl.py:30).

Citation corrected on verification: actions.py:419-421 (the finding said
:420 — the _add_action spans three lines).
advanced_preferences_page.py:97-109 for the switch row (finding said
100-109; :97 is the `Adw.SwitchRow()`). mainwindow.py:1536-1550 for the
enable + suggested-action block (finding said 1536-1548) and :971-979
for the auto-clear-on-connect branch.

Fix: Remove the whole clear-alarm surface: toolbar.py:164-171,
main_menu.py:190, actions.py:420, mainwindow.py:1960-1964
(on_clear_alarm_clicked), mainwindow.py:964-980 (the auto-clear-on-
connect branch), the enable/CSS block at mainwindow.py:1536-1548, the
switch at advanced_preferences_page.py:100-109 with its handler at
:130-131, and Machine.clear_alarm_on_connect (machine.py:136,636-639)
once nothing reads it. Everything except ruida_driver.clear_alarm is
outside PROTECTED paths. Note the toolbar slot it frees sits next to
Start/Pause/Stop.

PROTECTED: The toolbar row also carries Start/Pause/Stop, which is
PROTECTED. Removing the clear-alarm button must not reorder or restyle
the transport buttons beside it. ruida_driver.py:1150 itself must not be
touched.

**L9 — INCONSISTENT — Live documentation site still ships nav entries and full pages for the camera, the 3D preview, telemetry and the update checker**

website/sidebars.js:39 lists 'machine/camera', :49 lists 'ui/3d-preview'
and :120 lists 'general-info/usage-tracking' - all three are live
sidebar nav entries. The backing pages exist:
website/docs/machine/camera.md, website/docs/ui/3d-preview.md,
website/docs/general-info/usage-tracking.md, plus full translations in
six locales each under website/i18n/{de,es,fr,pt-BR,uk,zh-
CN}/docusaurus-plugin-content-docs/current/.
website/docs/ui/settings.md:36 documents 'Rayforge can **Check for
updates** automatically on startup' and :43-48 a whole '### Privacy'
section for 'Report Anonymous Usage' linking to the usage-tracking page.
All four features are REMOVE rows: A1.1 (camera), A1.2 (update checker,
'config.check_for_app_updates + its settings row'), A1.3 (telemetry,
'Privacy group ... REMOVE'), A1.4 (3D preview). Supporting screenshots
are still checked in too: website/static/screenshots/machine-settings-
camera*.png (6 files), config-wizard-camera.png, main-3d.png,
main-3d-rotary.png. The site also builds in CI
(.github/workflows/website.yml).

Citation corrected on verification: website/docs/ui/settings.md:43-49 is
the '### Privacy' block (the finding said :43-48; the section runs
through the usage-tracking link on :49). Everything else verbatim as
cited.

Fix: Remove the three sidebar ids from website/sidebars.js and delete
the three doc pages plus their six locale copies each, then strip the
'Check for updates' paragraph and the '### Privacy' section from
website/docs/ui/settings.md. Do this as one sidebar-driven pass rather
than page-by-page: sidebars.js is the single list that decides what is
reachable, so pruning it first makes the orphaned files findable
mechanically.

**L10 — INCONSISTENT — `CanvasViewState.perspective_mode` is a 3D-view-only persisted config key with zero readers**

swiftcut/core/config.py:41 declares `perspective_mode: bool = False` on
CanvasViewState, whose own docstring at :33 still says 'Persistent view
toggle states for the 2D/3D canvases.' A repo-wide grep for
`perspective_mode` across swiftcut/ and tests/ returns exactly one hit -
that declaration. Nothing reads it, no action toggles it, no widget
renders it. It is nevertheless persisted on every save, because
`to_dict` (config.py:44-45) serialises every dataclass field:
tests/config/config.yaml:17 carries `perspective_mode: false` today.
Perspective vs orthographic projection was the 3D canvas's camera mode,
removed under A1.4 ('rayforge/ui_gtk/sim3d/** (44 files) GL layer |
REMOVE'); the surviving projection code is
swiftcut/ui_gtk/shared/model_preview/camera.py
(_get_ortho_matrix/_get_perspective_matrix), which is the machine-
settings mesh preview and reads no config.

Citation corrected on verification: tests/config/config.yaml:18 `
perspective_mode: false` (the finding said :17; :17 is
`pan_inertia_enabled: true`). `from_dict` spans
swiftcut/core/config.py:47-51 including the `@classmethod` decorator.

Fix: Delete the `perspective_mode` field from CanvasViewState and
correct the class docstring at config.py:33 to '2D canvas'.
`CanvasViewState.from_dict` (config.py:48-51) already filters unknown
keys against `fields(cls)`, so existing user config.yaml files carrying
`perspective_mode:` load cleanly with no migration - that filter is the
shared mechanism that makes retiring any canvas_view key a one-line
change.

**L11 — INCONSISTENT — The whole `show_models` toggle chain survives the 3D view: config field, GTK action, window handlers and an overlay button captioned 'Toggle 3D model visibility'**

Four live pieces of a removed feature: (1) swiftcut/core/config.py:39
`show_models: bool = True`; (2) swiftcut/ui_gtk/actions.py:274-278
registers the stateful `win.show_models` action; (3)
swiftcut/ui_gtk/mainwindow.py:825-832 `on_show_models_state_change` -
whose body only writes `config.canvas_view.show_models` and fires
`config.changed`, with no call to `self.surface.*` unlike its siblings
`on_toggle_travel_view_state_change` (:809 calls
`set_show_travel_moves`) and `on_show_nogo_zones_state_change` (:819
calls `set_show_nogo_zones`) - plus mainwindow.py:883-889 re-triggering
it at startup from `_sync_view_toggle_actions`; (4)
swiftcut/ui_gtk/shared/visibility_overlay.py:78-89 builds a toggle
button whose tooltip is literally `_("Toggle 3D model visibility")` and
whose child is `get_icon("model-symbolic")`, wired to `win.show_models`.
Nothing renders models: a repo-wide grep for `show_models` returns only
those four sites. The only VisibilityOverlay instantiation is
mainwindow.py:316-320, which does not pass `show_models`, so the button
never appears - the action, the handler, the persisted key and the icon
asset are all reachable-but-inert. A1.4 removes 'show_3d_view + 7 view
actions, menu section, toolbar button'.

Citation corrected on verification:
swiftcut/ui_gtk/shared/visibility_overlay.py:79-90 (`if show_models:` at
:79 through `self.append(self.models_button)` at :90 — the finding said
78-89). Sole instantiation is swiftcut/ui_gtk/mainwindow.py:317-321
`VisibilityOverlay(show_workpiece=True, show_tabs=True,
shortcuts=SHORTCUTS,)` — the finding said 316-320. Constructor default
`show_models=False` at visibility_overlay.py:27.

Fix: Retire the chain end to end in one pass - the `show_models` field,
the actions.py registration, both mainwindow handlers/sync blocks, the
`show_models` constructor parameter and its branch in VisibilityOverlay,
and the now-orphaned model-symbolic.svg. VisibilityOverlay is the shared
widget here: its constructor flags are the single place that decides
which toggles exist, so deleting the flag is what makes the rest
provably dead.

PROTECTED: VisibilityOverlay is on the inventory's explicit KEEP list
(A1.4: 'TimeEstimateOverlay, VisibilityOverlay, ColorLutProvider | KEEP
| Shared with the 2D surface / theme service'). Only the show_models
branch and parameter go; the workpiece/tabs/travel buttons the 2D
surface uses must not be touched.

**L12 — INCONSISTENT — `TrackedPreferencesPage` is a telemetry husk: its two remaining attributes are Umami page-path fields no code reads, still set by 17 pages**

swiftcut/ui_gtk/shared/preferences_page.py is six lines: `class
TrackedPreferencesPage(Adw.PreferencesPage): key = ""; path_prefix =
"/settings/"`. Both attributes are the analytics page-path pair from the
removed `track_page_view` calls - a grep for readers of `path_prefix` or
of a `.key` on a preferences page finds none anywhere in swiftcut/ or
tests/ (the `.key` hits that exist are all `Var.key` in core/varset).
Seventeen pages still declare them:
swiftcut/ui_gtk/machine/{advanced_preferences_page.py:13-14,
capabilities_page.py:15-16, device_settings_page.py:26-27,
general_preferences_page.py:25-26, hardware_page.py:13-14,
head_preferences_page.py:1020-1021, hooks_macros_page.py:10-11,
maintenance_page.py:311-312, nogo_zones_page.py:182-183,
rotary_module_page.py:227-228},
swiftcut/ui_gtk/settings/{addon_manager_page.py:18,
color_presets_page.py:359, general_preferences_page.py:43,
license_settings_page.py:17, material_manager_page.py:20,
recipe_manager_page.py:15}, plus
swiftcut/ui_gtk/doceditor/step_settings/pages/general.py:9-10 and
runtime assignments at doceditor/recipes/pages/post_processing.py:43,
step_settings/pages/base.py:51,
step_settings/pages/post_processing.py:42. Neither settings dialog reads
them: a grep for `key` in swiftcut/ui_gtk/settings/settings_dialog.py
and swiftcut/ui_gtk/machine/settings_dialog.py (excluding
keyval/keyboard) returns nothing. The A1.3 KEEP row reads
'TrackedPreferencesPage / PatchedDialogWindow classes | KEEP, gut
tracking only | ~24 preference pages and ~23 dialogs inherit them; the
Adw focus fix is load-bearing and unrelated to telemetry.' That stated
reason no longer covers TrackedPreferencesPage: the Adw focus fix lives
entirely in PatchedDialogWindow (patched_dialog_window.py:15-38), and
TrackedPreferencesPage now adds nothing to Adw.PreferencesPage but two
dead telemetry fields. It is also named in a public addon hookspec
(swiftcut/core/hooks.py:413), so third-party addon authors are being
pointed at it.

Citation corrected on verification:
swiftcut/ui_gtk/shared/preferences_page.py:4-6 (whole file);
swiftcut/ui_gtk/machine/general_preferences_page.py:25-26 `key =
"general"` / `path_prefix = "/machine-settings/"`;
swiftcut/ui_gtk/doceditor/step_settings/pages/base.py:50-51 (runtime
writes); swiftcut/core/hooks.py:413. Subclass count is 20 files, not the
'~24 pages' the inventory row estimated.

Fix: Gut the tracking as the KEEP row intended: delete `key` and
`path_prefix` from preferences_page.py and from all 17 declaring pages
plus the 3 runtime assignments. Keep the class itself as the shared base
the ~24 pages and the register_settings_pages hookspec depend on, but
rename it `PreferencesPage` (the module is already preferences_page.py)
so the name stops advertising telemetry to addon authors reading
hooks.py:413 - one shared base, one rename, no per-page behaviour
change.

PROTECTED: The class is the base type named in the public addon hookspec
(core/hooks.py:413) and inherited by the machine settings pages, so a
rename must land with an alias or in the same commit as all subclasses.
The attribute deletion alone is behaviour-neutral and can go first.

**L13 — INCONSISTENT — Machine Settings opens with a permanent "almost certainly buggy" banner — the driver-maturity system has only one driver left to rank**

settings_dialog.py:211-224 `_update_maturity_banner` reads
`get_driver_cls(self.machine.driver_name).maturity` and shows
DRIVER_MATURITY_LABELS[maturity] in a warning banner pinned under the
header bar (:69-83, styled by the `.maturity-warning` CSS at :26-30).
ruida_driver.py:62 sets `maturity = DriverMaturity.KNOWN_BUGGY`, whose
label (driver.py:97-100) reads "This driver is experimental and almost
certainly buggy. It may not work reliably. Use it at your own risk."
Since default_profile.py:75 hard-codes `"driver": "RuidaDriver"` and
driver/__init__.py:21-25 registers nothing else selectable, this banner
is on screen every single time the user opens Machine Settings.
DriverMaturity (driver.py:79-100) exists to rank drivers against each
other — with one driver it is a permanent scare message about the
product's only supported hardware.

Citation corrected on verification: settings_dialog.py:214-224 (not
:211-224) `def _update_maturity_banner(self)` — :211-212 is
`_on_machine_changed`. Banner widget is :71-86 (not :69-83). Signal
wiring is :197 `self.machine.changed.connect(self._on_machine_changed)`
and :200 `self._update_maturity_banner()`. The fix's ":189-192 and
:201-224" is wrong and dangerous: :191-192 is
`self.sidebar_list.connect("row-selected", self._on_row_selected)` and
:202-209 is the initial-page/first-row selection — deleting either
breaks page navigation. Always-visible proof chain:
default_profile.py:75 `"driver": "RuidaDriver"` -> machine.py:1641
`ma.driver_name = ma_data.get("driver")` -> ruida_driver.py:62 `maturity
= DriverMaturity.KNOWN_BUGGY` -> driver.py:96-99 non-empty label.

Fix: Remove the maturity banner from the dialog:
settings_dialog.py:26-30 (CSS), :69-83 (widget), :189-192 and :201-224
(the signal wiring and _update_maturity_banner), plus the
DRIVER_MATURITY_LABELS/DriverMaturity import at :5-9. That deletes the
surface without touching the PROTECTED `maturity` attribute. If the
warning is genuinely wanted it should be a one-time first-run notice,
not a banner on every open.

PROTECTED: ruida_driver.py:62 is PROTECTED — do not change the maturity
value itself. The fix is confined to settings_dialog.py, and must not
disturb the Swift Cut theme/layout tokens the dialog uses
(SPACE_CONTROL/SPACE_GROUP).

**L14 — INCONSISTENT — Machine "Unit System" (Metric/Imperial) is a G-code-emission control whose driver-side plumbing has zero callers left**

general_preferences_page.py:148-157 describes the group as _("The unit
system used when emitting G-code and communicating with the device.")
and :162-173 offers a live Metric/Imperial ComboRow. The three Driver
helpers this setting existed to feed — `_to_machine_length`
(driver.py:293), `_to_machine_speed` (driver.py:307) and
`_from_machine_length` (driver.py:319) — have ZERO callers anywhere in
swiftcut/; they went with the GRBL/Marlin/Smoothie drivers. The only
surviving consumers are rust_helpers.py:215 (`"unit_scale":
machine.unit_system.scale_from_mm`), which is on the Grbl-only encoder
branch Ruida never takes, and rotary_module_page.py:527/666, where it
silently multiplies the "Travel per Rotation" spin row (defined at
:388-393 with no unit in its label) — so flipping to Imperial
reinterprets that row without relabelling it and without changing
anything the Ruida encoder emits. The group's own warning row is dead
too: `_update_unit_warning` (:315-355) returns early when `dialect is
None` (:319-322), which is always, so the G20/G21 preamble mismatch row
at :175-181 can never become visible.

Citation corrected on verification: general_preferences_page.py:152-159
(not :148-157) is the group+description; :164-173 the ComboRow.
`_update_unit_warning` is :313-352 (not :315-355) with the early return
at :318-321 (not :319-322). One claim is too narrow: rust_helpers.py:215
`"unit_scale": machine.unit_system.scale_from_mm` is inside
`build_encode_context`, which has TWO callers — intent_builder.py:840
`_grbl_encoder_spec` (the Grbl-only branch, as the finding says) AND
pipeline/encoder/gcode.py:24 `GcodeEncoder.encode`, which
`NoDeviceDriver.create_encoder` (dummy.py:86-89) returns. That second
path is still unreachable for the shipped machine because dummy.py:88
asserts `machine.dialect is not None`, which is None here — so the
conclusion survives, but "the Grbl-only encoder branch" is not the whole
story.

Fix: Remove the Unit System group (general_preferences_page.py:147-181),
its handler `on_unit_system_changed` (:305-312),
`_sync_unit_system_widgets` (:216-229) and `_update_unit_warning`
(:314-355), and drop the `scale_from_mm` multiply at
rotary_module_page.py:527/666 so Travel per Rotation is plain mm like
every other length row on that page. Machine.unit_system can stay as a
persisted field (machine.py:145) until a follow-up. The missing token
here is a unit suffix on the Travel per Rotation label — every other row
on that page uses LengthSpinRow, which carries its own unit; this one is
a bare SpinRow.

PROTECTED: mm/s units are PROTECTED. This must not touch
SpeedSpinRow/LengthSpinRow or any speed/power display — only the
machine-side Metric/Imperial selector and the one rotary row that
silently scales off it.

**L15 — INCONSISTENT — Recipe editor still offers a "Machine" applicability picker, but only one machine can ever exist**

applicability.py:56-73 `_build_machine_row` builds an Adw.ComboRow
titled _("Machine") from `get_context().machine_mgr.get_machines()`,
prefixed with _("Any"); edit_recipe_dialog.py:333 persists the choice as
`target_machine_id`; recipe_list.py:71-76 renders the machine name (or
_("Unknown Machine")) into every recipe subtitle. But no UI can create a
second machine: `MachineManager.add_machine` (manager.py:168) is reached
only from `create_default_machine` (manager.py:209-212, the ILAB_614
bootstrap) and from `DeviceProfile.create_machine` (profile.py:392),
which itself has zero callers now that the add-machine wizard, machine-
list page and lbdev import dialog are gone. So the combo is always
exactly ["Any", "ilab-614"] — two labels for one outcome — and
core/recipe.py:175-176's target_machine_id filter can never exclude
anything.

Citation corrected on verification: applicability.py:49 is
`self._build_machine_row(group)` (the fix says :50, which is
`self._build_step_types_row(group)`). `DeviceProfile.create_machine`
starts at profile.py:387, not :385. Two overstatements worth recording:
(1) `create_machine` is not caller-free —
tests/machine/device/test_device_profile.py:690,710,740,770 and
tests/machine/models/test_machine_profile.py:114,252 and
test_profile_driver_assignment.py:23 all call it; it is production code
that only tests exercise. (2) "only one machine can ever exist" is
stronger than the evidence: MachineManager.__init__ (manager.py:20-28)
ends in `self.load()`, which reads every YAML in MACHINE_DIR, and
context.py:199-200 / :345-346 only bootstrap the default `if not
self._machine_mgr.machines` — a config dir carried over from a multi-
machine build can still hold several. The defensible claim is that no
surviving UI can add or remove one.

Fix: Remove `_build_machine_row` and its call at applicability.py:50,
the `get_machine_id()` result wired at edit_recipe_dialog.py:333, and
the machine segment of the recipe subtitle at recipe_list.py:71-76.
Leave `Recipe.target_machine_id` on the model so existing recipe files
keep deserialising (core/recipe.py:371).

PROTECTED: None. The layer/step system is PROTECTED but recipes are a
separate applicability layer; step_registry and step types are untouched
by this change.

**L16 — INCONSISTENT — G-code wording survives on three controls that are actually Ruida-native**

(a) head_preferences_page.py:439 and :895 both subtitle the tool-number
row _("G-code tool number (e.g., T0, T1)"), but on Ruida that field is
the laser index: ruida_encoder.py:569-575 `self.active_laser =
laser_head.tool_number + 1` and ruida_driver.py:1163 `laser_num =
head.tool_number + 1`. There is no T-word in a Ruida stream. (b)
bottom_panel.py:181-184 registers the dock tab as `name="gcode"`,
`icon_name="gcode-symbolic"`, `label=_("G-code Viewer")` — docs/removal-
inventory-2026-09-04.md §6 KEEPs the widget precisely because "It
renders the Ruida job preview (mainwindow.py:1348-1349)", i.e. the KEEP
is for the function, not the name. (c) file_dialogs.py:83-96 titles the
export sheet _("Save G-code File") with a _("G-code files") filter and
`text/x.gcode` mime.

Citation corrected on verification: The dialog function is
`show_export_gcode_dialog` (file_dialogs.py:67), not a "save" one, and
it is live: its only caller is mainwindow.py:1790. The fix's rename-
impact list is incomplete: the stack name "gcode" is read at
mainwindow.py:724 `if name == "gcode":` AND :1210, :1229, :1254
(`self.bottom_panel.is_item_visible("gcode")`), plus bottom_panel.py:218
and scripts/screenshot/ui_audit.py:66 DOCK_TABS — six sites, not the
four the fix names.

Fix: String-and-label pass, no behaviour change: retitle the tool-number
subtitle to name the laser index (both copies at
head_preferences_page.py:439,895 — they are duplicated, so fix them
together), and rename the dock tab label to something like "Job
Preview". (c) disappears with the export-action finding above. The dock
tab's stack `name="gcode"` is referenced by mainwindow.py:724 and
bottom_panel.py:218 and by scripts/screenshot/ui_audit.py's DOCK_TABS,
so rename the label only or update all four together.

PROTECTED: None for the text. The gcode-symbolic icon is part of the
Swift Cut icon set — if the tab is renamed, reuse an existing token icon
rather than adding a new asset.

**L17 — MINOR — Deleted camera packages still exist as empty directories and still import successfully as namespace packages**

`find` shows five directories with zero files of any kind (not even
__pycache__): swiftcut/camera, swiftcut/camera/calibration,
swiftcut/camera/models, swiftcut/ui_gtk/camera,
swiftcut/ui_gtk/camera/wizard. Because `swiftcut` is a regular package
whose `__path__` is searched by FileFinder, a child directory without
`__init__.py` resolves as an implicit namespace package. Verified with
the project interpreter: `importlib.util.find_spec` returns a spec with
`origin is None` (NAMESPACE-PKG) for all five of swiftcut.camera,
swiftcut.ui_gtk.camera, swiftcut.camera.models,
swiftcut.camera.calibration, swiftcut.ui_gtk.camera.wizard - while
swiftcut.simulator and swiftcut.ui_gtk.sim3d correctly report absent. So
`import swiftcut.camera` still SUCCEEDS and only `from swiftcut.camera
import X` fails, which turns a clean ImportError into a confusing
AttributeError for anything that probes the module. Removal inventory
A1.1 marks `rayforge/camera/**` and `rayforge/ui_gtk/camera/**` REMOVE.
They are untracked by git (git ls-files shows no swiftcut/camera
entries) so they are stale working-tree directories that any fresh clone
will not have - the tree this app is built and run from does.

Fix: rmdir the five directories. They hold no files, so nothing is lost;
this is finishing the A1.1 deletion, not a new decision.

**L18 — MINOR — About > System Info still advertises `websockets`, which is no longer a dependency, so the dialog renders a 'not found' row**

swiftcut/ui_gtk/about.py:159-167 iterates `["ezdxf", "pypdf", "PyYAML",
"pyserial", "aiohttp", "websockets"]` under the 'File Formats &
Communication' heading and appends `_get_version(pkg)` for each.
`_get_version` (about.py:21-26) returns `_not_found_str` on
PackageNotFoundError. `websockets` appears in none of requirements.txt,
pyproject.toml, debian/control, debian/requirements-bundle.txt,
debian/rules or snap/snapcraft.yaml - it was dropped per removal
inventory A2.5 ('`websockets` | REMOVE | Becomes unreferenced') and the
inventory's closing line 'Only `websockets` (with the GRBL network
driver) and the snap `camera` plug become droppable'. So every user
opening About sees a dependency the app does not ship, reported as
missing.

Citation corrected on verification: swiftcut/ui_gtk/about.py:166
`"websockets",` inside the `comm_deps` loop at :159-169; `_get_version`
at :21-26 returns `_not_found_str` (defined :18 as `_("Not found")`).
Only occurrence of 'websockets' in the entire tree outside dist/.

Fix: Drop `"websockets"` (and `"aiohttp"`, see the separate finding)
from the `comm_deps` package list at about.py:160-167. The list is a
hand-maintained literal with no single source of truth - the durable fix
is to build it from the installed distribution's own requires metadata
(`importlib.metadata.requires`) so retiring a dependency cannot leave a
phantom row behind again.

**L19 — MINOR — The bundled default machine profile still writes `cameras: []`, contradicting its own round-trip docstring**

swiftcut/machine/models/default_profile.py:60 has `"cameras": [],`
inside ILAB_614_PROFILE, the dict
`MachineManager.create_default_machine` uses to seed a fresh install
(per the module docstring at :1-13). That docstring asserts the dict
'uses the same `machine:`-wrapper shape that
`Machine.to_dict`/`Machine.from_dict` read and write, so it is loaded
exactly like any other saved machine file' - which is now false for this
key. `Machine.from_dict` (machine.py:1638ff) reads only named keys and
never touches `cameras`, and
tests/machine/models/test_machine.py:453-477
(`test_from_dict_ignores_legacy_cameras_key`) asserts exactly that:
`assert not hasattr(machine, "cameras")` and `assert "cameras" not in
machine.to_dict()["machine"]`. So the shipped default profile writes a
key the model can never emit. The same line survives in the source-of-
truth copy at docs/profiles/ilab-614.source.yaml:31.

Citation corrected on verification:
swiftcut/machine/models/default_profile.py:60 — `        "cameras":
[],`; docs/profiles/ilab-614.source.yaml:31 — `  cameras: []`;
swiftcut/machine/models/machine.py:1633 `def from_dict(` (no `cameras`
read anywhere in the body); tests/machine/models/test_machine.py:474,477
— `assert not hasattr(machine, "cameras")` / `assert "cameras" not in
machine.to_dict()["machine"]`. Effect is cosmetic residue, not a load
failure.

Fix: Drop the `"cameras": []` entry from ILAB_614_PROFILE and the
`cameras: []` line from docs/profiles/ilab-614.source.yaml.
`Machine.to_dict` is the single schema authority the docstring already
points at - the durable guard is a test that round-trips
ILAB_614_PROFILE through from_dict/to_dict and asserts key equality,
which would have caught this and will catch the next stale key.

**L20 — MINOR — Translation catalogues still ship 162 camera / 3D-playback / updater / usage-consent strings sourced from deleted files**

swiftcut/locale/rayforge.pot: a parse of its 1899 msgid blocks finds 162
whose `#:` source references point at files that no longer exist. The
referenced paths include rayforge/updater.py (blocks at lines
21,25,29,34,38,42), rayforge/ui_gtk/shared/usage_consent_dialog.py
(:2462), rayforge/ui_gtk/sim3d/playback_overlay.py,
rayforge/ui_gtk/machine/wizard_pages/camera_page.py and eighteen
rayforge/ui_gtk/camera/** modules (alignment_dialog, alignment_widget,
camera_preferences_page, capture_surface, image_settings_dialog,
image_settings_widget, lens_calibration_dialog, lens_calibration_widget,
point_bubble_widget, properties_widget, selection_dialog and seven
wizard/ pages). Sample msgids still present and translated: 'New version
available.' (:39), 'Check for updates' (:2424), 'Report Anonymous Usage'
(:2454), '3D view is not available due to missing dependencies.'
(:2653), 'Select a machine to open the 3D view.' (:2657), 'Camera
Wizard' (:2844), 'Camera calibration' (:1444). The compiled catalogues
ship with the app:
swiftcut/locale/{de,en,es,fr,pt,uk,zh_CN}/LC_MESSAGES/rayforge.{po,mo} -
7 languages x 2 files each.

Citation corrected on verification: swiftcut/locale/rayforge.pot: 1899
msgid blocks, of which 534 have no surviving source file (149 in the
camera/3D/updater/usage subset), not 162. Stale-source leaders:
swiftcut/machine/driver/grbl/grbl_util.py x115,
swiftcut/ui_gtk/machine/wizard_pages/hardware_page.py x54,
swiftcut/ui_gtk/machine/wizard_pages/review_page.py x39. Mechanism:
scripts/update_translations.sh (xgettext over swiftcut/, msgmerge,
msgfmt) exists and is simply stale.

Fix: Do not hand-edit the catalogues. Re-run the project's xgettext
extraction over the current swiftcut/ tree to regenerate rayforge.pot,
then `msgmerge` each of the seven .po files and recompile the .mo -
obsolete entries drop out mechanically and translated strings for
surviving msgids are preserved. That extraction step is the shared
mechanism; it is evidently stale (the pot still uses `rayforge/` source
paths from before the package rename), so re-running it also repairs
every path reference at once.

**L21 — MINOR — Camera and 3D-playback icon assets are now referenced by nothing**

A per-asset reference scan over swiftcut/, tests/ and scripts/ finds no
code referencing swiftcut/resources/icons/camera-on-symbolic.svg or
camera-off-symbolic.svg. Their former consumers are all deleted - `git
grep` against the pre-removal tree
(18d6d9f097f1ad83e644099bf909abeb578c41ac^) shows camera-on-symbolic
used by rayforge/ui_gtk/camera/camera_preferences_page.py,
rayforge/ui_gtk/machine/settings_dialog.py,
rayforge/builtin_addons/rayforge-addon-
sketcher/sketcher/ui_gtk/studio.py and
rayforge/ui_gtk/shared/visibility_overlay.py, and camera-off-symbolic by
studio.py and visibility_overlay.py. Same for the 3D playback transport:
skip-previous-symbolic.svg and skip-forward-symbolic.svg are
unreferenced today, and `git show
18d6d9f^:rayforge/ui_gtk/sim3d/playback_overlay.py` lines 105 and 113
are their only historical users
(`self._step_back_button.set_child(get_icon("skip-previous-symbolic"))`
/ `_step_fwd_button ... "skip-forward-symbolic"`). PlaybackOverlay is an
A1.4 REMOVE row; the camera icons fall under A1.1.

Fix: Delete the four SVGs. They are tracked in git (unlike the empty
camera directories) so they are genuinely shipped weight. Note the wider
gap this exposes: swiftcut/resources/icons has no manifest, so nothing
links an asset to its consumer - the reference scan that found these is
the shared check worth adding as a test alongside
tests/ui_gtk/test_swift_cut_icons.py, asserting the reverse direction
(every shipped icon is referenced) rather than only the forward one.

**L22 — MINOR — The icon test still pins `3d-symbolic` as a required toolbar icon, which is the asset's only remaining referent**

tests/ui_gtk/test_swift_cut_icons.py:64 lists `"3d-symbolic"` inside
`TOOLBAR_ICONS` (:56-70), which feeds `ALL_ICONS` (:86-92) and both
`test_icon_resolves_to_a_file` and
`test_icon_is_symbolic_so_gtk_recolours_it`. The 3D toolbar button was
removed under A1.4 ('show_3d_view + 7 view actions, menu section,
toolbar button ... REMOVE'). Confirmed: grepping `3d-symbolic` across
swiftcut/, tests/ and scripts/ returns this test line and nothing else -
no widget builds it. So the test now asserts that a removed feature's
icon must remain on disk, and is what keeps
swiftcut/resources/icons/3d-symbolic.svg alive. The file's own docstring
says its purpose is 'that every name the map uses still resolves to a
file, so a rename cannot quietly fall back to the system theme' - the
map no longer uses this name.

Fix: Drop `"3d-symbolic"` from TOOLBAR_ICONS and delete 3d-symbolic.svg.
The list is the shared toolbar-icon contract; keeping a retired name in
it inverts the test's stated purpose from 'guard the icons we use' into
'preserve icons we do not'.

**L23 — MINOR — The main view stack is a one-page Gtk.Stack with a slide transition and a change handler that can never fire**

swiftcut/ui_gtk/mainwindow.py:303 comments 'Create the view stack for 2D
and 3D views'; :304-309 builds a Gtk.Stack and sets
`Gtk.StackTransitionType.SLIDE_LEFT_RIGHT`. Exactly one child is ever
added: :326 `self.view_stack.add_named(self.surface_overlay, "2d")` -
the '3d' page went with A1.4. :462-463 still connects `notify::visible-
child-name` to `_on_view_stack_changed` (:753-755), which calls
`self._update_actions_and_ui()`. With a single child the visible-child-
name never changes, so the handler is unreachable and the slide
transition never plays; the Stack is an inert wrapper around one widget.

Fix: Collapse the stack: make `self.surface_overlay` the direct child of
`self._canvas_overlay` (:312), and drop the transition setup, the
`notify::visible-child-name` connection and `_on_view_stack_changed`.
Move the two layout calls the Stack currently carries -
`set_margin_start(SPACE_GROUP)` (:308) and `set_hexpand(True)` (:309) -
onto surface_overlay so the canvas gutter token is preserved unchanged.

PROTECTED: SPACE_GROUP on :308 is a Swift Cut layout token
(docs/design/swift-cut-layout.md) setting the canvas's left gutter; it
must move to the new child verbatim, not be dropped, or the canvas
shifts.

**L24 — MINOR — Docstrings and design notes across eight files still describe the camera, the 3D canvas and OpPlayer as if they exist**

Each of these names a removed subsystem in prose a maintainer will act
on. swiftcut/doceditor/editor.py:212 'The OpPlayer overrides this per
playback position when a job exists.' - OpPlayer was removed (A1.4,
'rayforge/simulator/op_player.py ... REMOVE').
swiftcut/machine/kinematic_mapping.py:67 'Single source of truth shared
by ``OpPlayer``, ``SnapshotBuilder``, and the 3D canvas' and :245 'the
single entry point for both the UI path (3D canvas / OpPlayer via
``job_compute.py``)' - none of the three named consumers exist.
swiftcut/context.py:335 and tests/conftest.py:337 both describe lite
context as 'MachineManager and Config without cameras, materials,
recipes, or addons'. swiftcut/ui_gtk/mainwindow.py:1224 'refresh of all
data previews, like the simulator and G-code view' - only the G-code
view remains. swiftcut/ui_gtk/theme.py:105 lists 'the canvas and 3D
overlays' among colour-alias consumers and :313 justifies a CSS rule by
'a bare `.sc-overlay button` rule would crush the 3D playback speed
button ("1x") into a 32px square' - the playback overlay is gone, so
that rule's stated reason is void. docs/design/swift-cut-
tokens.md:306-307 tells whoever picks up the kerf animation that 'The
machinery is already in the tree - `simulator/op_player.py` has
`seek_to_fraction()` and `render_state()`', and :325-327 instructs them
to seed 'An `OpPlayer` from the running job's ops' - a follow-up brief
pointing at a deleted module.

Citation corrected on verification: Additional instance the finding
omits: swiftcut/pipeline/artifact/job.py:49 — 'playback (scene compiler,
OpPlayer). Not suitable for G-code' — inside the PROTECTED pipeline
tree.

Fix: Comment-only edits, no behaviour change. The one that matters most
is docs/design/swift-cut-tokens.md §6, because it is a live instruction
to a future implementer: add a note that op_player.py was removed with
the 3D view, so the kerf overlay now needs its own progress-to-position
mapping rather than a resurrected OpPlayer. For theme.py:313, keep the
CSS rule (it still governs every .sc-overlay button) but restate the
justification without the deleted playback button.

PROTECTED: swiftcut/ui_gtk/theme.py and docs/design/swift-cut-tokens.md
are both PROTECTED (Swift Cut theme + layout tokens). Only prose changes
here - no selector, token value or rule may be altered, and the .sc-
overlay/.sc-icon-button sizing rules must stay byte-identical.

**L25 — MINOR — KEEP row obsolete: `aiohttp` is kept for `machine/transport/http.py`, which no longer exists, and no swiftcut module imports it**

Removal inventory A1.2 keeps aiohttp with the reason 'Five other users
incl. `machine/transport/http.py`' (A1.3 and A2.12 repeat it), and lists
it among 'Dependencies that removal does NOT free'. That reason is now
false on both counts. A2.5 removed http.py ('Orphaned transports:
websocket.py, http.py, grbl.py, telnet.py | REMOVE'), and a repo-wide
grep for `aiohttp` in .py files - excluding .git, dist (gitignored) and
graphify-out - returns only scripts/media/update_supporters.py:9,39,62
(a maintainer script for the About-dialog supporters list, not shipped
code) and the string literal `"aiohttp"` at
swiftcut/ui_gtk/about.py:165. Zero imports anywhere under swiftcut/. It
is still a hard runtime dependency: requirements.txt:2 `aiohttp==3.14.3`
and debian/control:29 `python3-aiohttp`.

Citation corrected on verification: Third pin omitted by the finding:
pixi.toml:42 — `aiohttp = "==3.14.3"`. Also note about.py:165's
comm_deps list still names `"websockets"` alongside aiohttp even though
websockets is no longer in requirements.txt at all.

Fix: Re-decide the row rather than assume it: aiohttp's only remaining
need is the maintainer-only scripts/media/update_supporters.py, so move
it out of requirements.txt and debian/control into whatever dev/tooling
extra that script uses, and drop it from the About dialog's comm_deps
list at about.py:165. Same shared fix as the websockets finding -
deriving that list from distribution metadata instead of a hand-kept
literal is what keeps About honest as dependencies come and go.

**L26 — MINOR — The multi-machine lifecycle was never collapsed: set_active_machine, remove_machine and the "Activate Machine" handler are all unreachable**

`MachineManager.set_active_machine` (manager.py:127-163) — a full
disconnect/switch/reconnect routine — has ZERO callers in swiftcut/ or
tests/. `MachineManager.remove_machine` (manager.py:176-200) likewise
has zero callers, which makes core/config.py:313
(`machine_removed.connect`) and its handler at :318-328, including the
"If there are other machines available, select the first one" fallback,
unreachable. device_settings_page.py:389-393 `_on_activate_clicked`
("Handler for the 'Activate Machine' button", calling
`config.set_machine`) is never connected to any widget — grep for
`_on_activate_clicked` returns only its definition.
device_settings_page.py:329-333 still renders _("Cannot connect: Used by
'{machine}'") for ResourceBusyError, a two-machines-share-a-port
message. docs/removal-inventory-2026-09-04.md §7 promised "KEEP
(collapse to one) ... Leave `set_active_machine` a no-op" — the collapse
did not happen.

Citation corrected on verification: core/config.py:309 is
`self.machine_mgr.machine_removed.connect(self._on_machine_removed)`
(the finding says :313) and the handler is :314-328 (not :318-328), with
the "If there are other machines available, select the first one"
fallback at :321-328. One claim is wrong as scoped: `remove_machine` is
NOT caller-free — tests/machine/models/test_machine_manager.py:101 calls
`manager.remove_machine(machine.id)` (and :61 asserts `hasattr(manager,
"machine_removed")`), so deleting it per the fix breaks that test.
`set_active_machine` is genuinely zero-caller in swiftcut/ and tests/,
as claimed. manager.py:127-163 and :176-200 and
device_settings_page.py:329-333 / :389-393 are all exact.

Fix: Finish §7: delete set_active_machine and remove_machine from
MachineManager, drop the machine_removed subscription and
_on_machine_removed from core/config.py:313,318-328, and drop
_on_activate_clicked with the rest of device_settings_page.py (see the
Device-page finding). Keep MachineManager itself, get_controller and
create_default_machine — Machine.controller delegates through them on
every jog and Start/Pause/Stop path.

PROTECTED: Jog and Start/Pause/Stop reach the driver through
MachineManager.get_controller (manager.py:76-98). That method and the
controllers dict must stay exactly as they are; only the
add/remove/switch lifecycle goes.

**L27 — MINOR — Three device profiles ship in the package but no UI can reach them; the manager that loads them has no consumer**

swiftcut/resources/devices/ contains monport-60w-co2, omtech-polar and
thunder-laser-nova35. All three are clean on the A2.5 risk — each
device.yaml line 6 reads `driver: RuidaDriver`, so none would degrade to
NoDeviceDriver via the get_driver_cls fallback
(driver/__init__.py:28-29). But they are unreachable:
`DeviceProfile.create_machine` (profile.py:385-...) has zero callers,
and `device_profile_mgr` appears nowhere in swiftcut/ except
context.py:63,289-301, which constructs DeviceProfileManager and calls
`.discover(context=self)` — startup file I/O for data nothing renders.
The profile-picking UI that consumed them (unified_wizard,
wizard_pages/, settings/machine_settings_page.py, profile_importer.py,
lbdev_import_dialog.py) is correctly gone, and
swiftcut/ui_gtk/machine/wizard_pages/ is left behind as an empty
directory.

Citation corrected on verification: `DeviceProfile.create_machine`
begins at profile.py:387, not :385 (:392
`context.machine_mgr.add_machine(m)` is exact). Two corrections to the
characterization: (1) it is NOT "startup file I/O" — context.py:291
guards with `if self._device_profile_mgr is None:` and logs "Lazy
loading device profile manager", and since no code in swiftcut/ ever
reads `context.device_profile_mgr`, `.discover()` never runs at all; the
property and the discovery call are entirely dead, which strengthens
rather than weakens the finding. (2) The YAML trees are not orphaned
from tests: tests/machine/models/test_machine_profile.py:236 iterates
`BUILTIN_DEVICES_DIR` (config.py:75) and :251 loads `BUILTIN_DEVICES_DIR
/ "omtech-polar"`, as does
tests/machine/models/test_profile_driver_assignment.py:22 — the fix's
"drop the three resources/devices/* trees" breaks both.

Fix: Drop the three resources/devices/* trees, the DeviceProfileManager
property and discover() call at context.py:289-301, and the now-orphaned
empty swiftcut/ui_gtk/machine/wizard_pages/ directory. If the profiles
are wanted as future presets, keep the YAML but stop discovering it at
startup. Nothing user-visible changes either way — that is why this is
MINOR rather than a surface finding.

PROTECTED: None. profile.py:366-399 also carries the `driver_uses_gcode`
branching that machine deserialisation relies on; only the discovery
entry point and the resource trees should go, not DeviceProfile itself.

**L28 — MINOR — The orphaned LightBurn .lbdev device-profile importer still ships a full GRBL dialect template**

lightburn_importer.py:44-70 defines `_DEFAULT_GRBL_DIALECT` — laser_on
"M4 S{power:.0f}", laser_off "M5", travel_move "G0...", home_all "$H",
clear_alarm "$X", move_to "$J=G90 G21 F{speed}...", set_wcs_offset "G10
L2 P{p_num}...", probe_cycle "G38.2..." — and :195-199 attaches it
unconditionally to every imported profile as
`dialect_config=_DEFAULT_GRBL_DIALECT`. Its only entry point,
`DeviceProfileManager.install_from_lbdev` (manager.py:206) and
`convert_to_profile` (lightburn_importer.py:181), has zero callers now
that lbdev_import_dialog.py is gone. The `_DRIVER_MAP` at :27-35 WAS
correctly narrowed per §5 — every entry is None except "Ruida":
"RuidaDriver" — so the A2.5 remediation landed; only the dead GRBL
template and the dead import path remain. Note this is the device-
profile importer, distinct from the live .lbrn project importer at
swiftcut/image/lightburn/, which is in use (image/__init__.py:23).

Citation corrected on verification: `_DEFAULT_GRBL_DIALECT` spans :44-72
(the dict closes at :72; the finding says :44-70) and `_DRIVER_MAP`
spans :27-36 (the finding says :27-35, which is the inventory's own
range minus the closing brace). The "zero callers" claim is production-
only and materially incomplete:
tests/machine/device/test_lbdev_importer.py exercises both entry points
heavily — `convert_to_profile` at
:193,214,222,230,239,249,259,267,279,288,296,304,312,416,433,440 and
`mgr.install_from_lbdev` at :323,351,359,365,371,378,386,456. The fix's
"Remove lightburn_importer.py and manager.py:206-240" deletes code under
live test coverage; the narrower alternative it offers (drop
`_DEFAULT_GRBL_DIALECT` and the `dialect_config` argument at :198) is
the safe form, and even that will move test assertions.

Fix: Remove lightburn_importer.py and manager.py:206-240
install_from_lbdev, or at minimum delete _DEFAULT_GRBL_DIALECT and the
dialect_config argument at :198 so the package stops shipping a GRBL
command table. Do not touch swiftcut/image/lightburn/ — that is the
working .lbrn importer.

PROTECTED: None.

**L29 — MINOR — Serial transport, SerialPortVar and BaudrateVar are orphaned — the inventory's KEEP reason for transport/serial.py is now circular**

docs/removal-inventory-2026-09-04.md §5 KEEPs transport/serial.py
because "varset/adapter/combo.py:11 calls SerialTransport.list_ports()".
But nothing produces the var types that adapter serves: grepping
SerialPortVar and BaudrateVar across swiftcut/ returns only their
definitions (core/varset/serialportvar.py:12,
core/varset/baudratevar.py:30), the __init__ re-exports, and the adapter
registrations at ui_gtk/varset/adapter/combo.py:6-8,105-111. The only
driver that declares setup vars is RuidaDriver, whose get_setup_vars
(ruida_driver.py:210-237) is HostnameVar + two PortVars over UDP
(ruida_driver.py:22,271-275 use UdpTransport). So SerialTransport,
transport/serial_server.py and the pyserial dependency are unreferenced
by any driver, contrary to the inventory's "Dependencies that removal
does NOT free" list.

Citation corrected on verification: combo.py registers TWO adapters, not
one: `@register_adapter(BaudrateVar)` at :105 (class body :105-111, as
cited) and `@register_adapter(SerialPortVar)` at :123, whose body calls
`SerialTransport.list_ports()` at :130 and :148 — the finding cites only
:6-8,105-111 and misses :123-148, which is the actual site the
inventory's KEEP reason points at. Removal is wider than the fix states:
transport/__init__.py:3 imports SerialTransport unconditionally and :9
imports SerialServerTransport on non-win32 (with `SerialServerTransport
= None` at :11), and both modules are under live test coverage —
tests/machine/transport/test_serial_transport.py (SerialTransport
constructed at :249,282,302,334,344,365 plus permission tests :171-225)
and tests/machine/transport/test_serial_server_transport.py:154. Note
also that docs/removal-inventory-2026-09-04.md explicitly lists
`pyserial` under "Dependencies that removal does NOT free", so dropping
it contradicts a recorded verdict and needs that doc amended first,
exactly as the finding's own fix says.

Fix: Correct the §5 KEEP note, then remove transport/serial.py,
transport/serial_server.py, SerialPortVar, BaudrateVar and their two
adapter registrations in combo.py, and drop pyserial from
requirements.txt. Verify nothing else imports `machine.transport.serial`
first — TransportStatus (transport/__init__.py) is separate and is used
by the Ruida driver.

PROTECTED: ruida_driver.py imports TransportStatus and UdpTransport from
machine/transport — those must survive. Only serial.py and
serial_server.py go.

**L30 — MINOR — The screenshot audit tooling still captures three removed pages, silently producing mislabelled General-page PNGs**

scripts/screenshot/ui_audit.py:68-80 MACHINE_PAGES still lists "gcode",
but MachineSettingsDialog has no such page (settings_dialog.py:100-150
registers general/hardware/advanced/hooks-macros/device/heads/rotary-
module/nogo-zones/maintenance/capabilities). settings_dialog.py:200-208
loops for a matching row and, finding none, falls out with NO row
selected and the stack still on General — so `machine-settings-
gcode-<theme>-<width>.png` is a silent duplicate of the General page.
Same failure for ui_audit.py:84 "machines" and :88 "ai":
SettingsWindow.PAGE_INDICES (settings/settings_dialog.py:26-33) contains
only general/materials/recipes/color_presets/addons/licenses, and
:100-102 does `PAGE_INDICES.get(self._initial_page, 0)` — both fall back
to index 0, General. scripts/screenshot/cli.py:34 maps "machine-
settings:laser" to machine_settings_laser.py, whose PAGE = "laser" (:16)
while the dialog's page name is "heads" — a third silent General
capture. cli.py TARGETS (:17-37) has no target for the real `device` or
`capabilities` pages. AUDIT.md:29 says the first pass covered "twelve
machine-settings pages", so pass 1 inherited these blind spots.
Separately, mainwindow.py:1004-1013 `_open_machine_hours_dialog` passes
`initial_page="hours"` — no such page exists either, so the "View
Counters" notification action opens the dialog on General with nothing
selected (recorded as an open uncertainty in docs/removal-
inventory-2026-09-04.md, still unfixed).

Citation corrected on verification: settings_dialog.py:203-209 (not
:200-208) is the unmatched-name loop; the ten pages are registered at
:101-153 (not :100-150); SettingsWindow.PAGE_INDICES is :27-34 (not
:26-33) with the `.get(..., 0)` fallback at :102. The "hours" sub-claim
is NOT new: docs/removal-inventory-2026-09-04.md, "Uncertainties
recorded, not acted on", already states `mainwindow.py:1146 passes
initial_page="hours", but no such sidebar page exists (the counters page
is maintenance)` — the finding is right that it is still unfixed, and
the inventory's own line number is now stale (the call is at
mainwindow.py:1012). The screenshot-tooling half (ui_audit.py
"gcode"/"machines"/"ai", machine_settings_laser PAGE="laser", missing
device/capabilities targets) is genuinely new and is the load-bearing
part of this finding.

Fix: Drop "gcode" from ui_audit.py MACHINE_PAGES and "machines"/"ai"
from APP_PAGES; add "device" and "capabilities" to cli.py TARGETS;
change machine_settings_laser.py PAGE to "heads" (renaming the script
and its cli.py key to match); and fix mainwindow.py:1012 to
`initial_page="maintenance"`. Then make the mismatch loud rather than
silent: settings_dialog.py:200-208 and
settings/settings_dialog.py:100-102 should log a warning when the
requested page name is unknown instead of quietly landing on General.

PROTECTED: None. Do not run these scripts to verify — a screenshot
capture run is executing concurrently.

**L31 — MINOR — Published website docs still advertise GRBL/Marlin/Smoothieware/OctoPrint drivers, the removed G-code settings page and multi-machine management**

website/docs/reference/firmware.md:2 frontmatter: 'description:
"Supported firmware in Rayforge — GRBL, Marlin, Smoothieware, and
compatible controllers."'; :11 "designed primarily for **GRBL-based
controllers** but also supports Marlin, Smoothieware, and other firmware
types"; :15-24 a compatibility matrix naming drivers that no longer
exist in the package — GRBL Serial, GRBL Telnet, SmoothieDriver
(Telnet), Marlin Serial, OctoPrint — against a driver registry that is
now exactly Driver/NoDeviceDriver/RuidaDriver
(driver/__init__.py:21-25). website/docs/reference/gcode-dialects.md and
website/docs/machine/gcode.md document the dialect editor and G-code
machine-settings page removed under §6; website/docs/application-
settings/machines.md documents the machine-list page removed under §7.
website/sidebars.js:18,31 still publishes 'application-
settings/machines' and 'machine/gcode' in the live sidebar. Other lenses
own the neighbouring stale pages (machine/camera.md, ui/3d-preview.md,
application-settings/ai-provider.md, general-info/usage-tracking.md, all
still in sidebars.js).

Citation corrected on verification: website/sidebars.js line numbers are
off by two on the second entry: :18 `'application-settings/machines',`
and :33 `'machine/gcode',` (the finding says :18,31 — :31 is not one of
these). The fix also omits the two sidebar entries for the other files
it proposes deleting: :137 `'reference/gcode-dialects',` and :138
`'reference/firmware',`. For the "other lenses own the neighbouring
pages" note, those are at :22 'application-settings/ai-provider', :39
'machine/camera', :49 'ui/3d-preview', :120 'general-info/usage-
tracking' (and :119 'general-info/gcode-basics', which the finding does
not mention).

Fix: Delete reference/firmware.md, reference/gcode-dialects.md,
machine/gcode.md and application-settings/machines.md and their
sidebars.js entries, in the same pass that handles the camera/3D/AI
pages so the sidebar is edited once. The app's Help menu
(main_menu.py:205-210) does not link to the site, so this is a
published-docs surface rather than an in-app one — hence MINOR — but it
is the most discoverable remaining claim that the product drives GRBL
and Marlin hardware.

PROTECTED: None. docs/design/ (the Swift Cut theme and layout token
docs) is PROTECTED but is a different tree from website/docs/.


## E — Empty and error states

**E1 — BROKEN — Empty Macros / Recipes / Counters / Color Rules / Addons lists all render the literal string "No parameters"**

`PreferencesGroupWithButton.set_items()`
(swiftcut/ui_gtk/shared/preferences_group.py:85-92) appends its OWN
placeholder row
`Gtk.ListBoxRow(child=Gtk.Label(label=self._empty_placeholder))` when
the item list is empty. `_empty_placeholder` defaults to `_("No
parameters")` (preferences_group.py:50). Five subclasses set a correct
string via `self.list_box.set_placeholder(...)` instead of passing the
ctor arg — and a GtkListBox placeholder is only shown when the box has
ZERO rows, so the row `set_items` appends permanently suppresses it:
macro_list.py:104-111 ("No macros configured") + :118
`self.set_items(sorted_macros)`; recipes/recipe_list.py:116-122 ("No
recipes found.") + :132; maintenance_page.py:180-186 ("No counters
configured") + :198; settings/color_presets_page.py:250-256 ("No color
rules found.") + :266; addon_manager/addon_list.py:208-214 ("No addons
installed.") + :270. Screenshot-confirmed in the pass-1 capture set:
docs/design/audit/machine-settings-hooks-macros-light-1280.png shows the
Macros card reading exactly "No parameters" above the "+ Add New Macro"
button. Only nogo_zones_page.py:92-98, head_preferences_page.py:126-132
and rotary_module_page.py:131-137 escape it, and only because they
bypass `set_items` and drive `list_box` by hand; material_list.py:122
and material_library_list.py:124 escape it by passing
`empty_placeholder=`.

Citation corrected on verification: preferences_group.py:85-92 is the
placeholder branch, but `set_items` itself begins at :75 (`def
set_items(self, items: Iterable):`). Subclass placeholder blocks start
one line earlier than cited in three cases: recipe_list.py:115 (not
116), maintenance_page.py:179 (not 180), color_presets_page.py:249 (not
250), addon_list.py:207 (not 208).

Fix: One shared fix in `PreferencesGroupWithButton.set_items`: stop
appending a placeholder row and let the GtkListBox placeholder do its
job (each of the five subclasses already supplies a correct one), or
make `empty_placeholder` a required ctor argument so the "No parameters"
default can never leak. The same shared widget is where a real empty
state belongs — icon + title + one-line explanation, with the existing
bottom "Add …" button as the action — which is the missing token: there
is no shared empty-state widget or empty-state class in the token map at
all.

**E2 — BROKEN — Laser unreachable: every transport carries an error message to the UI and every consumer discards it**

All transports emit `status_changed(status=TransportStatus.ERROR,
message=str(e))` — udp.py:61,73,146, udp_server.py:21,70,
serial.py:207,301, serial_server.py:91,146 — and the Ruida driver emits
the specific `_("No response from controller")` on connect timeout
(ruida_driver.py:392-394) and `str(e)` on loop failure
(ruida_driver.py:468). `RuidaDriver._update_connection_status`
(ruida_driver.py:1662-1667) and
`MachineController._on_driver_connection_status_changed`
(controller.py:251-264) faithfully forward `message` up to
`Machine.connection_status_changed`. Every UI consumer then drops it:
`ConnectionStatusWidget._on_connection_status_changed`
(connection_status_widget.py:103-109) accepts `message: str | None` and
calls `self._update_display(status)` without it, rendering only the one-
word `TRANSPORT_STATUS_LABELS[ERROR]` = `_("Error")` (transport.py:24);
`device_settings_page.py:174-178` and `jog_widget.py:735-743` take
`**kwargs` and ignore it; `laser_control_widget.py:152-154` likewise. So
"connection refused / no response from controller" reaches the user as,
at best, the single word "Error" — and since ConnectionStatusWidget is
never mounted (see the leftovers finding), in practice as nothing.

Citation corrected on verification: laser_control_widget.py:152-154 is
the `.connect()` call, not the handler - the handler that ignores
`message` is laser_control_widget.py:221 `def
_on_connection_status_changed(self, sender, **kwargs):`. The finding
also omits a fifth consumer that drops it: mainwindow.py:964-969 `def
_on_connection_status_changed(self, machine: Machine, status:
TransportStatus, message: str | None = None):` whose body only auto-
clears alarms and calls `_update_actions_and_ui()`. One nuance worth
recording: the closest thing to a user-visible surface is
device_settings_page.py `_update_ui_state` which sets the generic
`error_row.set_title(_("Machine Not Connected")); set_subtitle(_("The
machine is not connected."))` - still not the transport message, and
only inside the machine-settings dialog. mainwindow.py uses conn_status
only at :1425, :1468, :1500, :1533, :1561 to gate sensitivity, never to
display text.

Fix: The message payload already exists end to end; the fix is a
consumer, not a producer. Route `connection_status_changed(status=ERROR,
message=…)` into the shared error-state widget with title "Cannot reach
the laser", the transport `message` as the one-line explanation, and a
Retry action. No change inside swiftcut/machine/driver/ruida/** is
needed — it already supplies the text.

PROTECTED: swiftcut/machine/driver/ruida/** is the source of the message
(ruida_driver.py:392-394, :468, :1662-1667). Reported only; the fix is
entirely on the UI consumer side and requires no edit to the driver.

**E3 — BROKEN — driver.state.error is set in exactly one place, so the toolbar's only machine-error surface never fires for a connection failure or a mid-run job failure**

`grep -rn "state.error\s*=|DeviceError(" swiftcut/machine/` returns
three hits, all in swiftcut/machine/driver/driver.py: :363 (`= None`),
:368-372 (`= DeviceError(-999, str(e), …)`) inside `Driver.setup()` on
`DriverSetupError`, and :377 (`= None` in cleanup). Nothing else in the
tree ever assigns it. The main window's only machine-error surface is
gated on exactly that field: `mainwindow.py:1454-1462` shows
`toolbar.machine_warning_box` only `if active_driver and
active_driver.state.error`. Consequently a connection loss
(TransportStatus.ERROR), a timeout, an alarm, or a job that dies mid-run
leaves the toolbar warning hidden. The sole cue for `DeviceStatus.ALARM`
is the Clear Alarm icon button gaining the `suggested-action` CSS class
(mainwindow.py:1536-1550) — a colour change on one 28px glyph, with no
title, no reason and no text anywhere.

Citation corrected on verification: One consumer the finding does not
mention, which does not change the verdict:
general_preferences_page.py:244-249 also renders
`driver.state.error.title` into the settings-page banner via
`_("<b>Error:</b> {error}")`. That is inside the machine-settings
dialog, not the main window, so the claim that the toolbar warning box
is the main window's only machine-error surface still holds.

Fix: Feed the same shared error-state surface from three sources instead
of one: `driver.state.error` (setup), `connection_status ==
TransportStatus.ERROR` with its message, and `device_state.status ==
DeviceStatus.ALARM`. One widget, three inputs — rather than one hidden
box, one icon tint and one dead widget.

PROTECTED: Start/Pause/Stop and the alarm path are protected. This is a
report on what the UI renders; the proposal adds a display surface and
changes no motion, interlock or job behaviour.

**E4 — BROKEN — Import of an unsupported file type is a log-only no-op — the user picks a file and nothing happens**

swiftcut/ui_gtk/doceditor/import_handler.py:118-121: `else:  #
UNSUPPORTED` → `logger.warning(f"Unsupported file type: {mime_type} for
{file_path}")` and nothing else. Identical silent branch at :168-169 for
the drag-drop / positioned path. The enclosing `except (OSError,
ValueError, KeyError): logger.exception("Error opening file")` at
:123-124 is also silent. `start_reimport` has two more: :286-287
("Cannot reimport: missing _importer_class metadata" → `return`) and
:290-293 (importer not registered → `return`). Five silent returns in
one 327-line file. Contrast the one place the app does this well:
`ImportDialog`'s `warning_banner` (import_dialog.py:121-132) — a title
plus a real `button_label=_("Switch to Trace Mode")` action.

Citation corrected on verification: The fix paragraph cites
`drag_drop_cmd.py:626-632` without a directory; the file is
swiftcut/ui_gtk/canvas2d/drag_drop_cmd.py and the relevant method is
`_show_clipboard_error` at :623-632, which already does show
`Adw.Toast.new(_("Failed to import image from clipboard"))`. It is cited
as a site to unify, not as a silent one, so the finding is not
contradicted by it.

Fix: Every one of those five `return`s should raise the shared error
state (or at minimum a titled toast with the file name and the reason).
The reusable piece is a single `show_import_failure(win, file_path,
reason)` helper so all five sites and the clipboard path
(drag_drop_cmd.py:626-632) share one presentation.

**E5 — BROKEN — ImportDialog closes itself silently when the file cannot be read or parsed, and OSError is not caught at all**

swiftcut/ui_gtk/doceditor/import_dialog.py:384-386: `except
(AttributeError, KeyError, TypeError): logger.exception(f"Failed to read
import file {self.file_path}"); self.close()`. The dialog presents and
then vanishes with no message — the user sees a flash. The `try` block
it guards begins at :334 with `self._file_bytes =
self.file_path.read_bytes()`, which raises `OSError`, a type the handler
does not list, so an unreadable/permission-denied file propagates out of
the GTK callback entirely. Separately, when the scan does return
structured errors they are rendered as
`self.error_banner.set_title("\n".join(self._manifest.errors))`
(:351-353) — raw parser strings, newline-joined, into an `Adw.Banner`
title, which is a single ellipsized line with no button.

Citation corrected on verification: The claim that OSError "propagates
out of the GTK callback entirely" is only true on some paths.
`_load_initial_data()` is called from `__init__` at
import_dialog.py:291, so it runs inside the ImportDialog constructor at
import_handler.py:36. On the file-chooser path that constructor call
sits inside `_on_file_selected`'s `try:` (import_handler.py:98-121),
whose `except (OSError, ValueError, KeyError)` at :123-124 DOES swallow
it - silently, which still supports the finding, but as a silent swallow
rather than an escape. It genuinely escapes uncaught only on the drag-
drop/positioned path (`import_file_at_position`,
import_handler.py:137-169, no try/except) and `start_reimport` (:310, no
try/except, though that path reads `source_asset.original_data` rather
than `read_bytes()`).

Fix: Replace `self.close()` with the shared error state inside the
dialog (icon, "Could not read this file", the reason, a Close action),
add `OSError` to the caught tuple, and render `_manifest.errors` as a
list in that state rather than a newline-joined Banner title.

**E6 — BROKEN — Send with a failed or empty job artifact is a silent no-op while the Send button stays enabled**

`MachineCmd._start_job` (swiftcut/machine/cmd.py:324-328): `if not
handle: logger.warning(f"{job_name.capitalize()} job has no
operations."); return` — no notification. `_execute_monitored_job`
(cmd.py:149-153): `if ops.is_empty(): logger.warning("Job has no
operations. Skipping execution."); … job_finished.send(...); return` —
also silent, and it fires job_finished so the UI resets as if the job
ran. The Send action is gated on `doc.has_result()`
(mainwindow.py:1501), and `Doc.has_result` (core/doc.py:453-461) only
asks "is there a workpiece and at least one visible step" — it has no
knowledge of whether the pipeline actually produced ops, so it stays
True after an encode failure. The pre-flight sanity check also swallows
the failure: `mainwindow.py:1766-1769` `if error or not handle:
proceed_callback(); return`. Net effect: press Send, sanity check
silently passes, `_start_job` silently returns, nothing moves and
nothing is said.

Citation corrected on verification: The pre-flight sanity-check citation
is off by two: the branch is at mainwindow.py:1768-1770, inside `def
_on_artifact_ready(handle, error):` (:1767) - `if error or not handle:`
/ `proceed_callback()` / `return`. (mainwindow.py:1766 is a blank line.)
Also worth flagging for the fix, not the finding: cmd.py `_start_job` /
`send_job` is the PROTECTED pipeline job path, so adding the
notification at :324-328 means editing a protected file even though the
branch condition itself is untouched.

Fix: Both silent `return`s already sit next to a `logger.warning` with
the exact text a user needs; send the same reason through
`notification_requested` / the shared error state instead of only to the
log. No behaviour change to the send path itself — the job still does
not run, the user is merely told why.

PROTECTED: swiftcut/machine/cmd.py `send_job` / `_start_job` is the
protected pipeline job path. Reported only: the finding is the absent
UI, and the proposal adds a message on an already-taken early-return
branch without altering when that branch is taken.

**E7 — BROKEN — Empty G-code preview dock is a blank white rectangle with no message**

`GcodeViewer.clear()` (swiftcut/shared/gcodeedit/viewer.py:119-126) sets
the editor text to `""` and calls `_update_status_bar()`, which for
`_line_count == 0` sets the status label to `""` (viewer.py:74-77) — so
nothing at all is drawn. `MainWindow._update_gcode_preview` calls
`clear()` whenever `gcode_string is None` (mainwindow.py:757-762), which
happens for: no machine configured (`refresh_previews`,
mainwindow.py:1234-1237), a job that produced no artifact
(`_on_previews_ready`, mainwindow.py:1198-1201), and the gcode tab not
being the visible one (mainwindow.py:1216-1217). Confirmed visually in
the pass-1 capture docs/design/audit/dock-gcode-light-1280.png: the
entire panel is empty white. Three different causes, one identical
blank.

Citation corrected on verification: Line spans are each ~1 line short:
the clear-and-return in `_update_gcode_preview` is mainwindow.py:757-763
(cited 757-762, the `return` is on :763); `_on_previews_ready`'s handle-
is-None branch is :1198-1202 (cited 1198-1201); `refresh_previews`'s no-
machine branch is :1234-1238 (cited 1234-1237, the `return` is on
:1238). Content at each is as described.

Fix: Give GcodeViewer an empty state fed by a reason enum from the
caller — "Select a machine to preview G-code", "Add a workpiece and a
processing step", "This job could not be generated" — rendered through
the shared empty-state widget so the three causes are distinguishable.

**E8 — INCONSISTENT — The app has exactly one Adw.StatusPage; there is no shared empty-state or error-state widget, and no token for one**

`grep -rn "StatusPage" --include=*.py swiftcut/` returns exactly one hit
in the whole tree, including builtin_addons:
swiftcut/ui_gtk/addon_manager/addon_dialog.py:100-104 ("Connection
Failed" / "Could not reach the registry."). Every other empty or error
state in the app is one of: a bare dim `Gtk.Label`
(preferences_group.py:86, workflow_row.py:204-208,
recipes/pages/post_processing.py:142-151,
step_settings/pages/post_processing.py:99, addon_dialog.py:161-164,
gcode_editor.py:221, image_metadata_dialog.py:55); a completely empty
container (layer_column.py:311-332, shared/gcodeedit/viewer.py:119-126);
or nothing at all. docs/design/swift-cut-tokens.md and
docs/design/swift-cut-layout.md define no empty-state or error-state
class, which is why every author invented their own. Not a pass-1
finding: AUDIT.md covers S1-S9/A1-A3/T1-T6/I1-I3/X1-X3 (spacing,
alignment, sizing, type, icons, theme selectors) and never inventories
empty or error states.

Citation corrected on verification: Two path/detail corrections. (1)
"shared/gcodeedit/viewer.py:119-126" is
swiftcut/shared/gcodeedit/viewer.py (NOT under ui_gtk/), and :119-126 is
`def clear(self)` which blanks the editor — an empty container, as
claimed. (2) addon_dialog.py:161-164 is `Gtk.Label(label=_("No addons
found in registry."), margin_top=SPACE_PAGE)` with NO `dim-label` class,
so "a bare dim Gtk.Label" is bare but not dim there. Also,
docs/design/swift-cut-layout.md:142-148 does mention "an empty-state
placeholder" as an example of dim-label usage — it defines no empty-
state class, so the finding's claim survives, but "never mentions" would
not.

Fix: Add one shared `SwiftCutStatusPage` (thin wrapper over
`Adw.StatusPage`) plus the `.sc-empty` / `.sc-error` classes to the
token map, with a fixed contract: icon, title, one-line description,
optional action button. Then route every site listed above through it.
The missing token is the empty/error-state role itself — the token doc
has colour, radius and type roles but no state role.

**E9 — INCONSISTENT — Job encode failure never reaches the UI: the only consumer of job_generation_finished ignores both task_status and error**

`IntentController._emit_job_encode_failed`
(swiftcut/pipeline/intent_controller.py:471-477) sends
`job_generation_finished(handle=None, task_status="failed",
error=str(node.error))`, and `Pipeline._on_job_encoded`
(pipeline.py:350-365) faithfully re-emits it with both fields. The
single UI subscriber is `mainwindow.py:483-484` →
`_on_job_generation_finished_for_preview(self, sender, **kwargs)`
(mainwindow.py:1251-1256), whose entire body is `if
self.bottom_panel.is_item_visible("gcode"): self.refresh_previews()` —
`task_status` and `error` are swallowed by `**kwargs`. The stored
`Pipeline._job_error` is read only inside pipeline.py:472-473, to build
a `RuntimeError` for a later export attempt. Also in this path: non-
CACHE_BUDGET node failures are log-only with no signal at all
(intent_controller.py:518-520).

Citation corrected on verification: (1) `_emit_job_encode_failed` is at
intent_controller.py:472-477, not :471-477 (:471 is blank). (2) The
claim "non-CACHE_BUDGET node failures are log-only with no signal at all
(intent_controller.py:518-520)" mis-cites: the log-only `else:` branch
is at :515-517 (`else:` / `# Internal errors (cache type mismatch, etc.)
- log.` / `logger.error("Node %s failed: %s", node.key, node.error)`).
Lines :518-525 are the opposite - `if node.key == job_encode_key():`
followed by `schedule_on_main_thread(self._emit_job_encode_failed,
str(node.error))`, i.e. the branch that DOES signal. (3) The title
"never reaches the UI" is false for the Send path:
`generate_job_artifact_async` (pipeline.py:504-516) does
`future.set_exception(error)`, the error being `_encode_error` =
`RuntimeError(f"Job encoding failed: {error}")` (pipeline.py:34-35)
raised from `when_done` at :473, which surfaces in cmd.py:339-346 as a
toast `_("{job_name} failed: {error}")`. The silence is real only on the
automatic/preview path, which is what the signal serves.

Fix: Have `_on_job_generation_finished_for_preview` read
`task_status`/`error` and, on "failed", show the shared error state
(title "This job could not be generated", the error as the explanation,
"Recalculate (F5)" as the action) instead of only refreshing a preview
that will render blank.

PROTECTED: intent_builder aggregate assembly / the pipeline job path is
protected. Reported only; the proposed change is confined to the
mainwindow signal handler and reads fields the pipeline already emits.

**E10 — INCONSISTENT — Failure messages are raw str(exception) interpolated into transient, untitled toasts — several of them untranslated**

`MainWindow._on_editor_notification` (mainwindow.py:1123-1149) turns
every `notification_requested` into a bare `Adw.Toast.new(message)` — no
title, no icon, no severity, default timeout unless `persistent=True`.
The messages fed to it interpolate exceptions directly:
file_cmd.py:1000-1004 `_("Export failed: {error}").format(error=e)`,
:1114-1117 `_("Failed to export object: {error}")`, :1168-1171
`_("Failed to export document: {error}")`, :1196-1199 `_("Save failed:
{error}")`, :1274-1277 `_("Load failed: {error}")`, and cmd.py:342-347
`_("{job_name} failed: {error}").format(job_name=job_name.capitalize(),
error=e)`. Two are not translated at all: `Pipeline._on_pipeline_error`
(pipeline.py:290-299) builds `message = f"Pipeline error:
{error_kind.value}"` and the CACHE_BUDGET string with plain
f-string/literals, no `_()`, and ships them straight to a toast via
editor.py:584-586. `cmd.py:345` also feeds the untranslated literals
"sending"/"framing" through `.capitalize()` into a translated template,
so no locale can render that sentence correctly. The exception text
itself is frequently untranslated English from pipeline.py:480-485 ("The
document has no visible steps with workpieces to assemble.") and
pipeline.py:34-35 ("Job encoding failed: …").

Citation corrected on verification: Minor line-span drift, all confirmed
nearby: file_cmd.py export-failed block is :999-1005 (cited 1000-1004),
export-object :1114-1120 (cited 1114-1117), export-document :1166-1174
(cited 1168-1171), save :1196-1200 (cited 1196-1199), load :1272-1278
(cited 1274-1277); cmd.py's notification is :341-346 (cited 342-347)
with `.capitalize()` on :345 as cited. The Copy-Error exemplar is
device_settings_page.py:75-84 (error_row at :75, `copy_button` with
`_("Copy Error Details")` at :79-84), not :73-80. Note for the fix, not
the finding: cmd.py and pipeline.py are on the PROTECTED job path, so
changing those message strings means editing protected files.

Fix: Give `notification_requested` a severity field and have
`_on_editor_notification` map error-severity notifications onto the
shared error surface (title + explanation + action) rather than a
5-second untitled toast; and stop interpolating `str(e)` — carry a
translated reason plus a "Details" affordance, the way
device_settings_page.py:73-80 already does with its Copy-Error button.

PROTECTED: cmd.py:342-347 sits on the protected send/frame job path.
Reported only; the change proposed is to the presentation layer
(mainwindow toast handler) and the message text, not to job control
flow.

**E11 — INCONSISTENT — A misconfigured machine (precheck failure) has no main-window surface, and its only surface is a raw exception in a markup-enabled Banner with no action**

`MachineController.rebuild_driver` stores
`self.machine.set_precheck_error(str(e))` on `DriverPrecheckError`
(swiftcut/machine/models/controller.py:193-199) — a raw exception
string. The only reader in the whole UI is
`general_preferences_page.py:235-256`, which formats it as
`_("<b>Configuration required:</b> {error}")` into `self.error_banner`,
an `Adw.Banner` created with `set_use_markup(True)`
(general_preferences_page.py:43-46) and **no** `button_label` — so it is
a dead-end message, and any `<` or `&` in the exception text is parsed
as markup. `mainwindow._update_actions_and_ui` never reads
`precheck_error` (it tests only `active_driver.state.error`,
mainwindow.py:1454), so a machine that failed precheck looks completely
normal in the main window: Send is simply disabled with the tooltip
"Send to machine" (mainwindow.py:1513-1514).

Fix: Escape the interpolated text, give the Banner a `button_label` that
opens the driver settings, and add `machine.precheck_error` to the
condition at mainwindow.py:1454 so the toolbar warning box — whose
default label is literally `_("Machine not fully configured")` — finally
has the case it was written for.

**E12 — INCONSISTENT — The toolbar machine warning is a click-gesture Gtk.Box, and the tooltip that says it is clickable is overwritten the moment it appears**

swiftcut/ui_gtk/toolbar.py:184-200 builds `machine_warning_box` as a
plain `Gtk.Box` with a `Gtk.GestureClick` — not a `Gtk.Button` — so it
has no button role, no keyboard focus and no press/hover affordance,
despite being the app's only clickable error surface (it opens machine
settings, mainwindow.py:1637-1641). Its constructor sets the
discoverability tooltip `_("Machine driver is missing required settings.
Click to edit.")` (toolbar.py:191-193) and the label `_("Machine not
fully configured")` (toolbar.py:187) — but `set_machine_warning`
(toolbar.py:323-330) replaces BOTH (`warning_label.set_label(f"{title}
({code})")`, `set_tooltip_text(error_description)`) and
`mainwindow.py:1455-1460` always calls it immediately before
`set_visible(True)`. So the constructed label and the "Click to edit"
hint are dead strings that no user can ever see, and the error's
description lives only in a tooltip.

Fix: Make it a real `Gtk.Button` with the error icon + short title as
its child and the description as visible text or an inline expander,
keeping a stable "Open machine settings" tooltip; that is also the shape
the shared error-state token should specify for inline (toolbar-density)
errors.

**E13 — INCONSISTENT — An empty layer's workpiece list is a blank rectangle — the most-seen empty state in the app has no treatment at all**

`LayerColumn._rebuild_workpiece_list`
(swiftcut/ui_gtk/doceditor/layer_column.py:311-332) clears the ListBox
and then only iterates `self.layer.get_content_items()`; when that is
empty the loop body never runs and the `Gtk.ListBox` is left with zero
children. There is no `set_placeholder` call anywhere in
layer_column.py. A new document starts with three empty layers
(`Doc.__init__`, swiftcut/core/doc.py:47-51), so this is what every user
sees on launch, three times over. Confirmed visually in
docs/design/audit/dock-layers-light-1280.png: three columns, each an
empty panel below its header. In the same dock a third convention
appears — `workflow_row.py:203-208` renders an empty step list as a bare
`dim-label` + `sc-caption` "No Operations" — so the Layers dock alone
shows blank-container, bare-caption, and (in the Assets tab) icon-plus-
buttons, three different answers to the same question.

Fix: One shared compact empty state for in-panel lists (small icon, one
line, and the existing adjacent add affordance as the action), applied
to `LayerColumn._rebuild_workpiece_list`, `workflow_row.py:203-208` and
the asset browser so the Layers/Assets dock speaks with one voice.

PROTECTED: The layer/step system is protected. This is a presentation-
only addition inside the layer column's own list rebuild; it changes no
layer or step semantics.

**E14 — INCONSISTENT — The asset browser's empty state is the app's only icon-plus-action empty state, and it is hand-rolled with no title and no explanation**

swiftcut/ui_gtk/doceditor/asset_browser.py:254-289 builds
`_create_empty_state()` by hand: a 128px `sketch-edit-symbolic` icon at
`opacity: 0.15` (CSS at asset_browser.py:72-80) and two buttons "Add
Stock" / "Add Sketch" — with **no title and no description line**. Its
CSS classes `.asset-browser-empty*` are local to that file and derive
from no token. It is the only empty state in the app with an action, and
it is not `Adw.StatusPage` (see the token-gap finding — the single
StatusPage in the tree is in addon_dialog.py:100).

Citation corrected on verification: CSS block is asset_browser.py:72-81,
not 72-80: `.asset-browser-empty { padding: 24px; }` (72-74), `.asset-
browser-empty-icon { opacity: 0.15; }` (75-77), `.asset-browser-empty-
buttons button { padding: 12px 24px; font-size: 1.1em; }` (78-81).

Fix: Reparent it onto the shared empty-state widget and add the two
missing parts of the contract (title: "No assets yet"; one-line
explanation), deleting the three one-off `.asset-browser-empty*` CSS
rules. This site is the natural template for the shared widget — it is
already closest to right.

**E15 — INCONSISTENT — With no machine configured, the Controls / Laser / Console docks render fully populated panels with everything greyed and one explanatory tooltip between them**

`BottomPanel.set_machine`
(swiftcut/ui_gtk/doceditor/bottom_panel.py:536-554) guards the
forwarding with `if self.machine and self.machine_cmd:` — so passing
`None` never reaches `jog_widget.set_machine` or
`laser_control.set_machine`, leaving them bound to whatever they last
held. Nothing renders a "no machine" state.
`LaserControlWidget._update_sensitivity`
(laser_control_widget.py:228-236) just marks six rows insensitive with
no tooltip. `bottom_panel.update_position_menu_sensitivity`
(bottom_panel.py:590-604) disables the four move buttons with no
tooltip. Exactly one control in the set explains itself: `zero_here_btn`
gets `_("Machine must be connected to set Zero Here")`
(bottom_panel.py:766-773). The Console dock disables `console_input`
(console.py:562-568) — and it is a `Gtk.TextView` (console.py:126),
which has no placeholder-text property at all, so it is a blank grey
box; the guard behind it (console.py:517-525) is a
`logger.error("Machine not connected")` with no UI. The empty console
terminal is likewise an empty `Gtk.TextView` (console.py:64) with no
placeholder.

Citation corrected on verification: console.py `_update_sensitivity`
begins at :560 (`def _update_sensitivity(self):`), not :562;
`self.console_input.set_sensitive(sensitive)` is at :568 as claimed.
bottom_panel.py zero_here tooltip string is at :769 inside the 764-773
block, not 766-773.

Fix: One rule for machine-dependent panels: when `config.machine is
None` or the driver is `NoDeviceDriver`, swap the panel content for the
shared empty state ("No machine connected" + "Add a machine in Settings"
+ a button that opens machine settings), instead of showing a dead copy
of the live panel. The reusable piece is a single `MachineRequiredStack`
wrapper that bottom_panel, laser and console all mount into.

PROTECTED: Jog panel behaviour, Min/Max power and mm/s units are
protected. Reported as-is; the proposal wraps the panels rather than
changing any jog, power or unit behaviour, and the jog widget itself
would keep its existing sensitivity logic.

**E16 — MINOR — ConnectionStatusWidget and MachineStatusWidget are dead code — the main window has no connection or device-status indicator at all**

`grep -rn "ConnectionStatusWidget|MachineStatusWidget|connection_status_
widget|status_widget" --include=*.py .` returns only the two class
definitions themselves:
swiftcut/ui_gtk/machine/connection_status_widget.py:67 and
swiftcut/ui_gtk/machine/status_widget.py:83. No import, no
instantiation, no test. Both are fully written (icon-per-status mapping,
"No driver" / "Disconnected" labels, machine binding) and never mounted.
The main window's header bar carries only `Adw.WindowTitle(title,
subtitle=__version__)` (mainwindow.py:190-193) and a menubar
(mainwindow.py:180); toolbar.py contains no status readout.
docs/removal-inventory-2026-09-04.md is silent on both files — it is not
listed as a KEEP (contrast `Driver.run_probe_cycle`, line 162, which IS
explicitly recorded as "dead in production … reported as dead code, not
removed"), and not listed as a REMOVE. Note the pass-1 capture
docs/design/audit/main-window-light-1280.png still shows a header
machine chooser reading "My Laser Cutter / No driver" — that widget no
longer exists in the tree (the same frame also shows the updater toast
that the removal inventory line 52 removed), so the capture predates the
current state and must not be cited as current evidence.

Citation corrected on verification: The fix's closing claim — "no
surface in the app reports the machine's connection state" — is false.
swiftcut/ui_gtk/machine/device_settings_page.py:239-246: `# The error
row now also shows connection status.` /
`self.error_row.set_visible(has_op_error or is_not_connected_state)` /
`self.error_row.set_title(_("Machine Not Connected"))` /
`set_subtitle(_("The machine is not connected."))`, driven by
connection_status_changed at :136-137/:175-178. jog_widget.py:735-737
and laser_control_widget.py:230/248 also react to it (as sensitivity
gating). The accurate statement is the title's: the MAIN WINDOW has no
connection or device-status indicator — the state is only visible inside
Machine Settings -> Device. Also, the updater removal is docs/removal-
inventory-2026-09-04.md:51 (`rayforge/updater.py`,
`tests/test_updater.py` | REMOVE), not :52 (which is the orphaned
`GITHUB_RELEASES_API`/`DOWNLOAD_URL` consts).

Fix: Decide once and record it in the removal inventory: either mount a
single status indicator in the header bar (one widget, driven by
`Machine.connection_status_changed` + `state_changed`, using the shared
status/error token from the token-gap finding), or delete both files as
leftovers. Today it is neither, so no surface in the app reports the
machine's connection state.

**E17 — MINOR — The one properly designed disconnect state — the Device settings page — restates its own title and offers no action**

swiftcut/ui_gtk/machine/device_settings_page.py:239-247 is the app's
best error surface: an `Adw.ActionRow` with an `error-symbolic` prefix,
`error` CSS class, a Copy-Error-Details button and a Dismiss button
(built at :73-91), showing `_("Machine Not Connected")` with subtitle
`_("The machine is not connected.")`. The subtitle adds no information
over the title — no reason, no last error, and no Connect/Retry button,
even though the transport already supplies a reason (see the discarded-
message finding). The sibling `unsupported_banner` (:65-71) and the
prompt row (:121-131) are likewise text-only. This page also proves the
pattern is affordable — nothing else in the app reuses it.

Citation corrected on verification: Line offsets are ~2 low. The error
row is built at device_settings_page.py:74-92 (`# Error row with copy
and close buttons` at 74, `self.error_row =
Adw.ActionRow(use_markup=True, activatable=False)` at 75,
`self.main_group.add(self.error_row)` at 92), not :73-91. The
unsupported banner is at :66-72 (`self.unsupported_banner = Adw.Banner(`
at 67), not :65-71. The cited :239-247 and the prompt row at :121-131
are accurate.

Fix: Promote this row's structure (icon + title + explanation + copy +
dismiss) into the shared error-state widget, replace the tautological
subtitle with the transport's `message`, and add a Connect action. Then
every other disconnect surface in the app can point at one
implementation instead of none.

**E18 — MINOR — The app's only Adw.StatusPage — "Connection Failed" — has no retry action**

swiftcut/ui_gtk/addon_manager/addon_dialog.py:99-104 sets icon `error-
symbolic`, title `_("Connection Failed")`, description `_("Could not
reach the registry.")` and adds it to the stack; `_fetch_registry`'s
`_done` callback (addon_dialog.py:119-125) switches to it when `data is
None`. `Adw.StatusPage.set_child()` is never called, so the page is a
dead end — the only way to retry is to close and reopen the dialog. The
sibling empty case in the same file is worse: addon_dialog.py:161-164
appends a bare `Gtk.Label(_("No addons found in registry."),
margin_top=SPACE_PAGE)` directly into the ListBox, with no `dim-label`,
no centring and no `set_placeholder`, unlike addon_list.py:208-214 four
files away.

Citation corrected on verification: The contrasting good case is
addon_list.py:207-214 (`placeholder = Gtk.Label(` at 207,
`placeholder.add_css_class("dim-label")` at 213,
`self.list_box.set_placeholder(placeholder)` at 214), not :208-214.

Fix: Add a Retry button as the StatusPage child wired to
`_fetch_registry`, and route the empty-registry case through the same
shared empty-state widget instead of a raw label append.

**E19 — MINOR — Clipboard import failure is a reason-free toast; the surrounding file has no shared failure presentation**

swiftcut/ui_gtk/canvas2d/drag_drop_cmd.py:622-632 catches every
exception from the clipboard import and calls `_show_clipboard_error()`,
which adds `Adw.Toast.new(_("Failed to import image from clipboard"))`
(drag_drop_cmd.py:626-632) — no reason, no retry, no icon, and the
exception is only in the log. The success case beside it
(drag_drop_cmd.py:594-597) uses the same untitled toast shape, so
success and failure are visually indistinguishable apart from the words.

Citation corrected on verification:
swiftcut/ui_gtk/canvas2d/drag_drop_cmd.py:599-601 — `        except
Exception:` / `            logger.exception("Failed to import from
clipboard")` / `            self._show_clipboard_error()`.
swiftcut/ui_gtk/canvas2d/drag_drop_cmd.py:623,630-632 — `    def
_show_clipboard_error(self):` ... `
self.main_window.toast_overlay.add_toast(` / `
Adw.Toast.new(_("Failed to import image from clipboard"))` / `
)`.

Fix: Route it through the same `show_import_failure(win, source,
reason)` helper proposed for import_handler.py so clipboard, file-
chooser and drag-drop import failures share one presentation and one
severity treatment.

**E20 — MINOR — No first-run / empty-document state: an empty canvas is indistinguishable from a loaded one that is scrolled away**

A `Doc` always exists (`MainWindow` builds `WorkSurface` with
`config.machine` at mainwindow.py:253-259) and always starts with three
empty layers (core/doc.py:47-51), so "no document open" never happens —
but "document with nothing in it" is the launch state and gets no
treatment. `doc.has_workpiece()` is read only for action enablement and
tooltips (mainwindow.py:1446-1447, :1601, :1604); nothing renders
guidance. The only import affordance on the canvas is the drag-hover
overlay `Gtk.Label(_("Drop files to import"))`
(canvas2d/drag_drop_cmd.py:295-316), which exists only while a drag is
in flight and is a bare label with a local `.drop-overlay` class.

Citation corrected on verification: The citation 'mainwindow.py:253-259'
does not support 'a Doc always exists' — :253-258 is `self.surface =
WorkSurface(editor=self.doc_editor, parent_window=self,
machine=config.machine, cam_visible=True,)` and :259 is
`self.surface.set_hexpand(True)`. The supporting evidence for the
always-nonempty-Doc claim is core/doc.py:47-51 alone. Also
`_find_parent_overlay` is *called* at drag_drop_cmd.py:312, not defined
at :311-316.

Fix: Render the shared empty state as a canvas overlay while
`doc.has_workpiece()` is False — icon, "Nothing to cut yet", one line,
and an Import button reusing `win.machine`-independent
`import_handler.start_interactive_import`. It reuses the overlay parent
the drop label already finds (`_find_parent_overlay`,
drag_drop_cmd.py:311-316).


## K — Keyboard, focus and shortcuts

**K1 — BROKEN — The Start button's focus ring is invisible in both themes: the ring colour and the button fill are the same token**

theme.py:200-204 fills the primary button with the accent: `.sc-toolbar
> button.suggested-action, .sc-jog button.suggested-action { background-
color: @sc_accent; border-color: @sc_accent; color: #FFFFFF; }`.
theme.py:216-219 then draws the focus ring in the SAME token, inset:
`.sc-toolbar > button:focus-visible, .sc-jog button:focus-visible {
outline: 2px solid @sc_accent; outline-offset: -1px; }`. A negative
outline-offset puts the 2px ring inside the border box, i.e. on top of
the button's own `@sc_accent` fill — ring vs fill is #2F7BFF on #2F7BFF,
a contrast ratio of 1.00:1. `@sc_accent` is defined once in
`_SHARED_TOKENS` (theme.py:72) and is identical in light and dark
(docs/design/swift-cut-tokens.md:58 lists `sc_accent` as `#2F7BFF` /
`#2F7BFF`), so the ring is invisible in BOTH themes. This hits the jog
panel's Start button (`self.start_btn.add_css_class("suggested-
action")`, jog_widget.py:226) and the toolbar's clear-alarm button while
an alarm is latched (mainwindow.py:1543-1545). The Stop button is
unaffected — theme.py:210-214 deliberately keeps `background-color:
@sc_button_bg` for `.sc-jog button.destructive-action`, so its ring
still shows.

Citation corrected on verification: Block boundaries only; all quoted
text is accurate. theme.py:200-205 is the suggested-action block (`.sc-
toolbar > button.suggested-action,` on 200, `.sc-jog button.suggested-
action {` on 201, declarations 202-204, `}` on 205) — the finding's
"200-204" omits the closing brace. theme.py:216-220 is the focus block
(selectors 216-217, `outline: 2px solid @sc_accent;` on 218, `outline-
offset: -1px;` on 219, `}` on 220). mainwindow.py: the guard `if
clear_alarm_sensitive:` is line 1543 and the call spans 1544-1546
(`self.toolbar.clear_alarm_button.add_css_class(` / `"suggested-action"`
on 1545 / `)` on 1546) — cite 1543-1546. Exact and unchanged:
jog_widget.py:226 `self.start_btn.add_css_class("suggested-action")`;
theme.py:72 `@define-color sc_accent #2F7BFF;`; theme.py:210-214
destructive-action keeping `@sc_button_bg`; docs/design/swift-cut-
tokens.md:58 `| sc_accent | #2F7BFF | #2F7BFF |`; docs/design/swift-cut-
tokens.md:25 `| blue-brand | #2F7BFF | Selection, focus, the single
primary action |`. Additional supporting evidence the finding did not
cite: `grep -n "focus\|outline" swiftcut/ui_gtk/theme.py` returns only
lines 67, 192, 216, 217, 218, 219 in the whole file, proving 216-219 is
the sole focus rule and no exception exists; `grep -in "focus"
docs/design/audit/AUDIT.md` returns nothing, proving no pass-1 overlap;
theme.py:408-412 installs the provider at
`Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION`; toolbar.py:36 and
jog_widget.py:100 add the `.sc-toolbar` / `.sc-jog` classes the
selectors depend on.

Fix: A missing token, not a one-off: the token map (docs/design/swift-
cut-tokens.md:44-61) has no focus-ring colour — theme.py:216-218 borrows
`@sc_accent`, which the map already assigns to "Selection, focus, the
single primary action" (tokens doc:25), three roles that collide exactly
here. Add one `sc_focus_ring` token defined per theme so it never equals
the surface it is drawn on, and drive theme.py:216-219 from it. The
accompanying rule change is to stop insetting the ring over an accent
fill — `outline-offset: 1px` (outside the border box, over
`@sc_panel_bg`/`@sc_window_bg`) makes one ring definition work on every
fill instead of needing a `.suggested-action:focus-visible` exception.

PROTECTED: PROTECTED — the Swift Cut theme + layout tokens, and the
Start button. Adding a token is additive, but changing `outline-offset`
on `.sc-jog button` alters the jog panel's rendered geometry.

**K2 — BROKEN — Asset browser suppresses the focus outline on every card, so keyboard navigation through the grid shows nothing**

asset_browser.py:40-47 sets, unconditionally and not scoped to any
state, `.asset-flowbox > flowboxchild { padding: 0; margin: 0;
background: none; border: none; outline: none; box-shadow: none; ... }`.
`outline` is how GTK4 draws `:focus-visible` on a `flowboxchild`, and
`box-shadow` covers the older path, so both indicators are removed for
every card. There is no substitute: the FlowBox is created with
`set_selection_mode(Gtk.SelectionMode.NONE)` (asset_browser.py:202), so
GTK never applies `:selected`, and the `.selected` CSS class the code
adds by hand (asset_browser.py:418-420) tracks the app's own selection,
not the focus cursor. Keyboard is a real path here —
`set_activate_on_single_click(False)` (asset_browser.py:205) means a
pointer needs a double-click while Enter/Space on the focused child
activates it, and a key controller is attached to the FlowBox at
asset_browser.py:208-210. So arrowing through the asset grid moves an
invisible cursor. Note the two other `outline: none` sites in the app
are NOT this bug and should not be lumped in: layer_column.py:75-78 and
shared/draglist.py:26-29 both scope it to `> row:drop(active)`, a drag-
hover state, leaving the focus ring intact.

Citation corrected on verification: The finding's aside undercounts by
one. It says "the two other `outline: none` sites in the app are NOT
this bug" — there are three others, and the third is not scoped either:

- swiftcut/ui_gtk/doceditor/layer_column.py:75-78 — `.layer-workpiece-
list > row:drop(active) { background-color: transparent; outline: none;
}` — correctly characterized by the finding as drag-hover-scoped; focus
ring intact.
- swiftcut/ui_gtk/shared/draglist.py:26-29 — `.material-
list>row:drop(active) { outline: none; box-shadow: none; }` — likewise
correctly characterized.
- swiftcut/ui_gtk/shared/slider.py:34 — `.slider-value-entry { outline:
none; }` — MISSED by the finding. Unscoped, same shape as the bug being
reported, on a text entry. Not part of this finding's claim, but the
parent may want it triaged separately rather than assumed clean on this
finding's say-so.

All other citations verified verbatim, including the ones the finding
gave for the comparison sites and for theme.py:216-219 (`.sc-toolbar >
button:focus-visible, .sc-jog button:focus-visible { outline: 2px solid
@sc_accent; outline-offset: -1px; }` — note this rule covers only
toolbar and jog buttons, so it does not restore a ring on
`flowboxchild`).

One supporting detail the finding did not state, which strengthens it:
`_on_key_pressed` (asset_browser.py:498-502) handles only
`Gdk.KEY_Delete` and acts on `self._selected_uids`. So a keyboard user
arrowing to a card and pressing Delete deletes the pointer-selected
assets, not the focused one — the invisible focus cursor and the visible
selection are fully decoupled.

Fix: Scope the suppression to the states it was written for instead of
all of them — the intent (per the surrounding rules) is to strip
libadwaita's card chrome so `.asset-card` can draw its own, which needs
`background`/`border`/`box-shadow` gone but not `outline`. Dropping
`outline: none` from asset_browser.py:45 restores the platform ring for
free. If a Swift Cut ring is wanted instead, it is the same
`sc_focus_ring` token proposed for the theme.py:216-219 rule — this
widget is one of the surfaces AUDIT.md:346-358 (X3) already lists as
following the stock theme rather than Swift Cut, so it needs the token
either way.

**K3 — INCONSISTENT — Start, Pause, Stop and Export .rd have no keyboard accelerator at all — the four highest-consequence actions are pointer-only**

`SHORTCUTS` (swiftcut/ui_gtk/actions.py:31-84) is the complete
accelerator registry: `ActionManager.register_shortcuts`
(actions.py:644-653) iterates `SHORTCUTS.items()` and nothing else, and
the only other registration paths are `App.set_accels_for_action` for
`app.quit` / `app.preferences` (swiftcut/app.py:262-265) and
`action_registry.get_all_with_shortcuts()` (actions.py:673-680), which
today yields exactly two entries — `layout-pixel-perfect` `<Ctrl><Alt>a`
(actions.py:461) and the sketcher's `<Primary><Shift>n`
(builtin_addons/rayforge-addon-
sketcher/sketcher/ui_gtk/__init__.py:191). The actions exist and are
wired: `machine-send` (actions.py:417), `machine-cancel`
(actions.py:418), `machine-hold` (actions.py:425), `export-rd`
(actions.py:244). None of those four strings appears in `SHORTCUTS`.
Their only reach is pointer: toolbar.py:146-161 (send/hold/cancel
buttons), main_menu.py:187-189 and main_menu.py:42 (`Export Ruida Job
(.rd)...`). MOTION_AUDIT.md:310-312 independently states this and it is
still true: "machine-cancel has no keyboard accelerator (only
main_menu.py:201 and toolbar.py:169 plus the jog widget's stop button),
so it needs a touchscreen/second pointer to press STOP while an arrow is
held." Compounding it, the jog panel's own Start/Pause/Stop bypass the
actions entirely — jog_widget.py:227/231/236 use `connect("clicked",
...)` into `machine_cmd.run_send_job` / `set_hold(machine, True)` /
`cancel_job` rather than `set_action_name`, so they can never inherit an
accelerator, and `_on_pause_clicked` (jog_widget.py:903-906) passes
`True` unconditionally, meaning the jog panel offers no resume at all.
Contrast: every File and Edit action, plus `zoom_to_fit`, `zoom_in`,
`recalculate` and `about` (F1), does have one.

Citation corrected on verification: Line-number corrections (all minor,
none change the substance): SHORTCUTS spans actions.py:31-85, not 31-84
— line 84 is "win.about": "F1" and the closing brace is line 85.
machine-hold spans actions.py:424-428, not 425 — line 424 is
`self._add_stateful_action(`, 425 is the "machine-hold" string, 426 the
handler, 427 `GLib.Variant.new_boolean(False)`; the comment at 423 reads
"# Stateful action for the hold/pause button", which is the strongest
support for the finding's own warning that hold is a toggle. The toolbar
block is toolbar.py:146-163, not 146-161 (send 146-149, hold 151-158,
cancel 160-163). _on_pause_clicked is jog_widget.py:904-907, not
903-906: "def _on_pause_clicked(self, button):" is line 904 and the body
is `if self.machine and self.machine_cmd:
self.machine_cmd.set_hold(self.machine, True)`. The button-wiring lines
227/231/236 are exact. MOTION_AUDIT.md:310 is exact ("machine-cancel has
no keyboard accelerator (only main_menu.py:201 and"). NEW EVIDENCE the
finding missed, which bears on severity:
website/docs/reference/shortcuts.md ships a "Machine Control" table
listing only Ctrl+L, Ctrl+< and F1, followed by an explicit admonition —
":::note Machine Operations / Machine control operations (Home, Frame,
Send, etc.) currently don't have default shortcuts but can be accessed
via toolbar buttons or menus. :::". The absence is therefore a
documented, acknowledged state rather than an oversight, though the doc
records it without justifying it. ALSO NEW:
swiftcut/ui_gtk/shared/visibility_overlay.py:133 parses a
ShortcutTrigger but only inside _format_tooltip to append an accelerator
label to a tooltip — it is not a registration path, so it does not
rescue the four actions; I verified this so it is not mistaken for one
later. Finally, tests/ui_gtk/machine/test_jog_widget_hold.py covers
press-and-hold JOGGING only, not the Pause button, so it offers no
evidence that the one-way set_hold(True) is intentional.

Fix: The shared fix is four entries in the one `SHORTCUTS` dict
(actions.py:31-84) — that dict IS the shared token class for
accelerators, and `register_shortcuts` already fans it out to the window
controller with no per-widget work. Then make the jog panel's three
buttons `set_action_name("win.machine-send"/"-hold"/"-cancel")` instead
of raw `clicked` handlers, so the panel and the toolbar share one
action, one sensitivity rule and one accelerator. Do NOT invent bindings
here: the choice of keys for a laser Start/Stop is a safety decision,
and `machine-hold` is stateful (toggle) while the jog Pause button is
not, so the two paths must be reconciled first.

PROTECTED: PROTECTED — Start/Pause/Stop, jog panel behaviour, and the
.rd export path. Report only; adding an accelerator to `machine-send`
changes what a keystroke can start on real hardware, and rewiring the
jog buttons to the stateful `machine-hold` action changes jog panel
behaviour.

**K4 — INCONSISTENT — No main-toolbar tooltip names its accelerator, although the codebase already has a helper that does exactly that**

Eight toolbar controls have a registered accelerator and a tooltip that
never mentions it: Open `win.open` = `<Primary>o` (toolbar.py:40 tooltip
`"Open Project"`), Save `<Primary>s` (toolbar.py:45 `"Save"`), Save As
`<Primary><Shift>s` (toolbar.py:50 `"Save As..."`), Import `<Primary>i`
(toolbar.py:55 `"Import image"`), Export `<Primary>e` (toolbar.py:60
`"Generate G-code"`), Undo `<Primary>z` (toolbar.py:69 `"Undo"`), Redo
`<Primary>y` (toolbar.py:74 `"Redo"`), Toggle bottom panel `<Primary>l`
(toolbar.py:98 `"Toggle bottom panel"`) — accels all from SHORTCUTS,
actions.py:33-56. Meanwhile `VisibilityOverlay._format_tooltip`
(swiftcut/ui_gtk/shared/visibility_overlay.py:130-140) already
implements the correct pattern —
`Gtk.ShortcutTrigger.parse_string(shortcut_str).to_label(display)`
appended as `f"{text} ({label})"` — and the canvas overlay toggles use
it (visibility_overlay.py:107-115, 122-127). So the app renders "Toggle
travel move visibility (Ctrl+Shift+T)" on the canvas and a bare "Save"
two inches above it. The one toolbar tooltip that does carry a modifier
hint spells it by hand: `_("Recalculate (Shift+Click to force)")`
(toolbar.py:82), which is a mouse hint, not the registered `F5` /
`<Shift>F5` accelerator (actions.py:57-58).

Citation corrected on verification: Corrections to two supporting refs
in swiftcut/ui_gtk/shared/visibility_overlay.py (substance unchanged):

1. The finding cites the two overlay toggles that DO show accels as
"visibility_overlay.py:107-115, 122-127". The actual blocks are :105-116
(travel) and :118-128 (no-go); the _format_tooltip calls are at :109-114
and :122-126:
   109  self.travel_button.set_tooltip_text(
   110      self._format_tooltip(
   111          _("Toggle travel move visibility"),
   112          "win.toggle_travel_view",
   113      )
   114  )
   With actions.py:56 "win.toggle_travel_view":
f"{PRIMARY_ACCEL}<Shift>t", this renders "Toggle travel move visibility
(Ctrl+Shift+T)".

2. The finding cites the two accel-less actions as
"visibility_overlay.py:103/126". The correct anchors are :99
("win.show_grid", inside the _format_tooltip call; set_action_name at
:102) and :124 ("win.show_nogo_zones"; set_action_name at :127). The
claim itself is correct — neither win.show_grid nor win.show_nogo_zones
(nor win.show_models) appears in SHORTCUTS (actions.py:31-88), so the
graceful-degradation requirement on the proposed shared helper is real.

Additional confirming evidence the finding did not cite:
- swiftcut/ui_gtk/mainwindow.py:316-319 —
VisibilityOverlay(show_workpiece=True, show_tabs=True,
shortcuts=SHORTCUTS); this is the only construction site in the repo, so
the accel-bearing overlay tooltips are live. Note show_grid/show_models
default to False here, so the grid button is never built in the shipping
window — the degradation path matters only for win.show_nogo_zones
today.
- swiftcut/ui_gtk/actions.py:644-653 register_shortcuts() populates a
Gtk.ShortcutController with Gtk.NamedAction, which rules out any
automatic GTK tooltip-accel decoration.
- Scope note on the fix: as worded ("every set_tooltip_text in
toolbar.py") it would also wrap the machine controls (Send :147, Pause
:155, Stop/Cancel :160, Home :135, Frame :141, Clear alarm :168, Toggle
focus :178). None of those action names are in SHORTCUTS, so the helper
returns the bare text and their behaviour and rendered text are
unchanged — but the change should be scoped to the eight controls that
actually have an accel.

Fix: Shared-helper fix, and the helper is already written — lift
`VisibilityOverlay._format_tooltip` (visibility_overlay.py:130-140) out
of that private class into `swiftcut/ui_gtk/shared/keyboard.py`, next to
`PRIMARY_ACCEL`, as a module-level `accel_tooltip(text, action_name)`
that reads the `SHORTCUTS` dict directly instead of taking it as a
constructor argument. Then every `set_tooltip_text(_("..."))` in
toolbar.py becomes `set_tooltip_text(accel_tooltip(_("..."),
"win.save"))`, and `VisibilityOverlay` drops its copy. The helper
already degrades correctly for actions with no accelerator (it returns
the bare text), which matters because `win.show_grid` and
`win.show_nogo_zones` — the two actions visibility_overlay.py:103/126
passes it — are not in `SHORTCUTS`.

**K5 — INCONSISTENT — Pass-1 finding X1 was fixed everywhere except the focus-ring arm: split buttons in the toolbar get a different focus ring from their neighbours**

AUDIT.md:327-339 (X1) reported that `.sc-split` matched nothing. That is
now FIXED — `SplitMenuButton` adds the class at shared/splitbutton.py:43
and `_HistoryButton` at shared/undo_button.py:31, each with a comment
citing the fix, and theme.py extended three of its four arms to reach
them: base bezel `.sc-split > button, .sc-split > menubutton > button`
(theme.py:143-144), hover (theme.py:175-176), disabled
(theme.py:186-187). The focus arm was not extended. theme.py:216-217
still reads only `.sc-toolbar > button:focus-visible, .sc-jog
button:focus-visible`. `.sc-toolbar > button` is a direct-child selector
and the split widgets' real buttons are grandchildren (`Gtk.Box.sc-
split` > `Gtk.Button`, splitbutton.py:52-54, undo_button.py:35-37), so
Undo, Redo, Arrange and Add Tabs — four of the toolbar's controls,
sitting directly beside Open/Save/Import/Export — fall back to
libadwaita's default focus ring while their neighbours get the 2px inset
`@sc_accent` one. This is the same visual failure X1 described ("one
toolbar read as two button families"), surviving in the one state pass 1
did not screenshot.

Citation corrected on verification: Two citations are off by one;
substance unaffected.

- Claimed "hover (theme.py:175-176)". Actual hover arms are
theme.py:174-175:
    172  .sc-toolbar > button:hover,
    173  .sc-toolbar > togglebutton:hover,
    174  .sc-split > button:hover,
    175  .sc-split > menubutton > button:hover,
    176  .sc-jog button:hover {
- Claimed "undo_button.py:35-37" for the real button. Line 35 is the
comment `# 1. The main action button`; the widget is
undo_button.py:36-38:
    36  self.main_button = Gtk.Button(child=get_icon(icon_name))
    37  self.main_button.set_tooltip_text(tooltip)
    38  self.append(self.main_button)
  (its menu button is 41-45, not cited)

Accurate as cited: theme.py:143-144, theme.py:186-187, theme.py:216-217,
splitbutton.py:43, splitbutton.py:52-54, undo_button.py:31,
AUDIT.md:327-339.

Selector-block ranges in the FIX text each overshoot by one line (they
include the opening-brace line) and the lists are five selectors, not
four. Correct ranges: base 141-145, hover 172-176, disabled 184-188,
focus 216-217.

The exact unextended rule, swiftcut/ui_gtk/theme.py:216-220:
    .sc-toolbar > button:focus-visible,
    .sc-jog button:focus-visible {
        outline: 2px solid @sc_accent;
        outline-offset: -1px;
    }

Supporting citations the finding did not make:
- swiftcut/ui_gtk/toolbar.py:36 `self.add_css_class("sc-toolbar")`;
split widgets appended at 71, 76, 111, 128; plain buttons at 42, 47, 52,
57, 62.
- swiftcut/ui_gtk/theme.py:97 `@define-color accent_color
@sc_accent_text;` vs theme.py:72 `@define-color sc_accent #2F7BFF;` -
this is why the fallback ring is a different colour.
- docs/design/swift-cut-tokens.md:25 `| blue-brand | #2F7BFF |
Selection, focus, the single primary action |`
- docs/design/swift-cut-layout.md:238 `| .sc-split | split menu buttons
| **new** - same, the rule existed and matched nothing |`

Fix: One-line class-list extension, not a new rule: add `.sc-split >
button:focus-visible` and `.sc-split > menubutton > button:focus-
visible` to the existing selector list at theme.py:216-217, so all four
arms (base / hover / disabled / focus) cover the same set of nodes.
Better still, define the four selectors once as the documented `.sc-
toolbar-button` class group in docs/design/swift-cut-tokens.md, since
the same four-selector list is now hand-repeated at theme.py:141-146,
172-177, 184-189 and 216-217 — the fourth copy is exactly where the
omission happened.

PROTECTED: PROTECTED — the Swift Cut theme + layout tokens.

**K6 — INCONSISTENT — The slider value entry is frameless AND has its focus outline removed, so an editable numeric field shows no focus state anywhere in the app**

`create_slider_row` (shared/slider.py:38-97) builds the editable readout
as `entry = Gtk.Entry(); entry.set_has_frame(False)` (slider.py:59-62)
and then applies `.slider-value-entry { outline: none; }`
(slider.py:33-34, attached at slider.py:63 and injected globally via
`apply_css(_SLIDER_VALUE_ENTRY_CSS)` at slider.py:64). Frameless removes
the resting border; `outline: none` removes the focus ring GTK4 would
otherwise draw in its place. The result is a Tab stop that is both
editable and completely unmarked when focused — and it commits on blur
(`Gtk.EventControllerFocus` "leave" -> `commit_entry`, slider.py:89-91),
so a user who tabs into it without seeing it and types can change a
value and commit it by tabbing away. This is a shared widget: it backs
the fixed/min/max power rows in
laser_essentials/widgets/material_test_grid_page.py:187,203,215,330 and
raster_page.py:69,136,152, the smoothing amount in
post_processors/widgets/smooth_group.py:38, and every varset slider row
(varset/adapter/slider.py:50).

Citation corrected on verification: swiftcut/ui_gtk/shared/slider.py:34
`.slider-value-entry { outline: none; }` (finding cited 33-34/33-35);
:62 `entry.set_has_frame(False)`; :63-64 `entry.add_css_class("slider-
value-entry")` / `apply_css(_SLIDER_VALUE_ENTRY_CSS)`; :89-91
`focus_ctrl = Gtk.EventControllerFocus()` / `focus_ctrl.connect("leave",
lambda c: commit_entry(entry))`.

Fix: Fix once in the shared widget: remove the `outline: none` from
`_SLIDER_VALUE_ENTRY_CSS` (slider.py:33-35) so the platform focus ring
returns, and keep `set_has_frame(False)` for the resting look —
frameless-at-rest, ringed-on-focus is the standard shape and needs no
per-caller change. The rule is one line of app-global CSS applied from a
helper, so no call site is touched. If the ring should match the reskin
rather than libadwaita, it is the same missing `sc_focus_ring` token as
the theme.py:216-219 finding — one token serves all three sites.

PROTECTED: PROTECTED (adjacent) — Min/Max power. The change is to the
focus indicator only; the entry's value, units and commit behaviour
(slider.py:66-91) must not move.

**K7 — INCONSISTENT — Arrow keys in the jog panel mean two different things depending on connection state: focus navigation when disconnected, machine motion when connected**

`JogWidget._on_key_pressed` (machine/jog_widget.py:918-951) binds
Up/Down/Left/Right to jog moves and returns `True` for each
(jog_widget.py:931-942), and returns `True` again for every auto-repeat
of a held key (jog_widget.py:926-927). Its controller is attached to the
widget with the default BUBBLE phase (jog_widget.py:251-254 — no
`set_propagation_phase` call, unlike the per-button click gestures at
jog_widget.py:281 which explicitly opt into CAPTURE). Those same four
keys are GTK's directional focus-navigation keys inside the 3x3
`Gtk.Grid` the panel is built from. The handler gates on connection: `if
not self.machine or not self.machine.is_connected(): return False`
(jog_widget.py:921-922). So with a machine connected the arrows are
claimed for motion and never navigate the grid; with no machine they
fall through and navigate. Same widget, same key, two behaviours, and
nothing in the UI signals which mode is live — the arrow buttons'
tooltips ("Move North", jog_widget.py:135, etc.) name the motion but not
the key. Separately, and NOT a finding: the 3x3 grid is attached row-
major, not column-major — jog_widget.py:133,137,145 (row 0: NW, N, NE),
152,158,164 (row 1: W, Home, E), 173,177,185 (row 2: SW, S, SE) — so Tab
traversal is reading-order and correct.

Citation corrected on verification: Two corrections, both narrowing
rather than overturning the finding.

1. TOOLTIP CLAIM IS PARTLY WRONG. The finding states the arrow buttons'
tooltips "name the motion but not the key," citing jog_widget.py:135.
Half the cluster already names the key:
   - jog_widget.py:135  create_button("arrow-north-symbolic", _("Move
North"))          -- no key hint
   - jog_widget.py:149  create_button("arrow-west-symbolic", _("Move
West (Left)"))     -- KEY HINT PRESENT
   - jog_widget.py:161  create_button("arrow-east-symbolic", _("Move
East (Right)"))    -- KEY HINT PRESENT
   - jog_widget.py:175  create_button("arrow-south-symbolic", _("Move
South"))          -- no key hint
   - jog_widget.py:240  create_button("arrow-z-up-symbolic", _("Increase
Z-Distance"))  -- no hint, though bound to Page_Up at 943-944
   - jog_widget.py:245  create_button("arrow-z-down-symbolic",
_("Decrease Z-Distance"))-- no hint, though bound to Page_Down at
946-947
   Accurate statement: 2 of the 4 arrow keys and 0 of the 2 Page keys
disclose their accelerator, so the panel is internally inconsistent
about accelerator disclosure and the "(Left)"/"(Right)" suffix is the
precedent the fix should follow.

2. SCOPE IS WIDER THAN "the 3x3 Gtk.Grid." _jog_grid is 3 columns x 5
rows (rows 0-2 the directional 3x3, row 3 the Go Scale / Cut Scale box
at :209, row 4 the position readout at :222). There is a SECOND grid,
_action_grid (jog_widget.py:65-66), holding Start/Pause/Stop/Z+/Z- at
:228,232,237,243,249. Both are parented directly to the JogWidget
(`self._jog_grid.set_parent(self)` at :57,
`self._action_grid.set_parent(self)` at :66), and the key controller
sits on the JogWidget itself at :251-254. So the arrow-key swallow
covers the Start/Pause/Stop column too: with a machine connected, a
keyboard user on the Start button pressing Down does not move focus to
Pause -- it jogs the head South. That amplifies the finding; it does not
weaken it.

Supporting citations verified verbatim:
  jog_widget.py:99    self.set_focusable(True)
  jog_widget.py:921-922  if not self.machine or not
self.machine.is_connected(): return False
  jog_widget.py:926-927  if keyval in self._pressed_keyvals: return True
  jog_widget.py:251-254  key_controller = Gtk.EventControllerKey() ...
self.add_controller(key_controller)   [no set_propagation_phase]
  jog_widget.py:281
gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
  visibility_overlay.py:130-140  def _format_tooltip(self, text,
action_name): ... return f"{text} ({label})"
  removal-inventory-2026-09-04.md:201-203  jog panel KEEP entry, cursor-
key jogging not listed

Fix: Do not rebind. The shared fix is disclosure, not behaviour: the jog
buttons' tooltips are built through one helper,
`create_button(icon_name, tooltip, label=None)` (jog_widget.py:102-124),
so the accelerator hint can be added in exactly one place — give
`create_button` an optional `key` argument and render it the way
`VisibilityOverlay._format_tooltip`
(shared/visibility_overlay.py:130-140) already does, so "Move North"
reads "Move North (Up)". That reuses the same helper this lens proposes
lifting into `shared/keyboard.py` for the toolbar.

PROTECTED: PROTECTED — jog panel behaviour and the motion invariants in
MOTION_AUDIT.md (see MOT-03/MOT-04, MOTION_AUDIT.md:295-330, and the
auto-repeat churn at MOTION_AUDIT.md:1455-1470, which already covers
this handler). Report only; changing which keys the handler claims
changes when the head moves.

**K8 — MINOR — JogWidget is itself a focus stop with no focus style, so Tab into the jog panel lands somewhere invisible before reaching any button**

`JogWidget.__init__` calls `self.set_focusable(True)`
(machine/jog_widget.py:99) on the container — it is a `Gtk.Widget`
subclass parenting two grids (jog_widget.py:57-58, 65-66), needed so the
widget-level `Gtk.EventControllerKey` (jog_widget.py:251-254) receives
arrow keys when no button holds focus. But the only focus style in the
theme for this subtree is `.sc-jog button:focus-visible` (theme.py:217)
— there is no `.sc-jog:focus-visible` rule, and the widget draws nothing
of its own (`do_size_allocate`, jog_widget.py:322-345, only positions
the two grids). So the container's focused state is unrendered.
`set_focusable(True)` on a container with focusable children makes it a
Tab stop in its own right ahead of them, which puts a blank stop at the
head of the panel.

Citation corrected on verification: Two precision fixes, neither of
which changes the conclusion:

(a) Line range for the parented grids. The finding cites
"jog_widget.py:57-58, 65-66"; the actual `set_parent` calls are
jog_widget.py:58 (`self._jog_grid.set_parent(self)`) and
jog_widget.py:67 (`self._action_grid.set_parent(self)`) — line 65 is
blank and 66 is `self._action_grid = Gtk.Grid()`. Correct range:
jog_widget.py:57-58 and 66-67.

(b) Why the focused state is unrendered. The finding attributes it to
`do_size_allocate` (jog_widget.py:321-345, which is correctly cited —
the method spans exactly 321 to 345, `set_machine` begins at 346 — and
does only allocate the two grids). That is a non-sequitur: `grep -n "def
do_"` shows the class overrides only `do_get_request_mode` (:307),
`do_measure` (:310) and `do_size_allocate` (:321) — there is NO
`do_snapshot` override, so GTK4's default widget snapshot runs and would
paint a CSS background/border/outline for this widget if one were
declared. The real and only cause is the missing selector: theme.py
styles `.sc-jog button:focus-visible` (theme.py:217, in the block at
216-219) and never `.sc-jog` itself. This actually strengthens the
proposed fix — a pure CSS arm will render with no Python change.

Fix: Same missing token as the other focus findings: a `sc_focus_ring`
token plus a `.sc-jog:focus-visible` arm alongside the existing `.sc-jog
button:focus-visible` at theme.py:216-219 gives the container a visible
state without touching Python. The alternative — dropping
`set_focusable(True)` — is not available: the key controller at
jog_widget.py:251 depends on it.

PROTECTED: PROTECTED — jog panel behaviour. A CSS-only ring is safe;
removing `set_focusable` would break keyboard jogging.

**K9 — MINOR — The shipped keyboard-shortcut reference documents accelerators that do not exist and gets six others wrong**

website/docs/reference/shortcuts.md is the user-facing reference and
disagrees with `SHORTCUTS` (actions.py:31-84) in three ways. (a)
Documents accelerators with no registration anywhere: `F12` 3D View,
`F11` Simulation Mode, `Ctrl+Alt+C` Toggle Camera (shortcuts.md:56-62) —
the stateful view actions actually registered are `show_workpieces`,
`toggle_travel_view`, `show_nogo_zones`, `show_grid`, `show_models`,
`toggle_bottom_panel`, `toggle_right_panel`, `toggle_pan_inertia`
(actions.py:254-303); there is no camera, 3D or simulate action, and
none of those three strings appears in `SHORTCUTS`. (b) Six alignment
entries drop the primary modifier: the doc lists
`Shift+Left/Right/Up/Down/Home/End` (shortcuts.md:103-110) where the
code registers `<Primary><Shift>Left` … `<Primary><Shift>End`
(actions.py:71-76) — and bare `<Shift>h` / `<Shift>v` are separately
bound to flip (actions.py:77-78), so the doc's version would collide.
(c) Omits the zoom accelerators entirely: `<Primary>0` fit, `<Primary>1`
100%, `plus`/`minus` (actions.py:59-62) appear nowhere; the doc's only
zoom rows are mouse (shortcuts.md:158-159). The file also still names
the product "Rayforge" throughout (shortcuts.md:2,6,29) after the
swiftcut rename (commit 1e0b2c53f).

Citation corrected on verification: swiftcut/ui_gtk/actions.py:72-77 are
the align-* entries (finding said 71-76); spread-h/spread-v are at 78-79
and `"win.flip-horizontal": "<Shift>h"` / `"win.flip-vertical":
"<Shift>v"` at 80-81 (finding said 77-78). SHORTCUTS spans 31-85.
website/docs/reference/shortcuts.md:102-107 is the alignment table
(finding said 103-110); the Rayforge strings are at :2, :7, :28.

Fix: The shared fix is to stop maintaining the table by hand:
`SHORTCUTS` (actions.py:31-84) is already a single flat dict of action-
name to accelerator, and `ActionInfo.label` (action_registry.py:26) plus
the menu labels in main_menu.py carry the human names, so the reference
page can be generated from them the same way
`VisibilityOverlay._format_tooltip` derives its display string
(`Gtk.ShortcutTrigger.to_label`, visibility_overlay.py:135-139). Short
of generation, a test asserting every row of the doc resolves to a key
in `SHORTCUTS` would have caught all nine discrepancies.

**K10 — MINOR — The focus ring falls just below the 3:1 non-text contrast threshold against the dark-theme button fill**

theme.py:216-219 draws the ring as `outline: 2px solid @sc_accent;
outline-offset: -1px`. The negative offset places the ring inside the
border box, so the background it must separate from is the button's own
fill, `@sc_button_bg`. In the dark theme that token is `rgba(255, 255,
255, 0.10)` (theme.py:54, and docs/design/swift-cut-tokens.md lists the
pair), composited over `@sc_panel_bg` `#232325` (theme.py:51) which
`.sc-dock` paints (theme.py:224-226) — giving an effective #393A3B.
Against `@sc_accent` #2F7BFF (theme.py:72) that is a contrast ratio of
2.96:1, just under the 3:1 WCAG 1.4.11 floor for non-text indicators.
The light theme is fine: `@sc_button_bg` is `#FFFFFF` (theme.py:32),
3.89:1. Ring-against-surface is comfortable in both (#2F7BFF on
`sc_window_bg` #F5F5F7 = 3.57:1; on #1C1C1E = 4.37:1) — it is only the
inset placement over the dark button fill that fails, and the margin is
thin enough (2.96 vs 3.00) that this is a token-definition matter, not a
visible break.

Citation corrected on verification: Dark composite is #39393B, not
#393A3B (0.10*255 + 0.90*0x23 = 57 for both R and G). `.sc-dock {
background-color: @sc_panel_bg; }` is theme.py:223-225, not 224-226.

Fix: Same missing token as the other focus findings, and this is the
case that fixes all of them at once: define `sc_focus_ring` per theme in
docs/design/swift-cut-tokens.md and theme.py's
`_LIGHT_TOKENS`/`_DARK_TOKENS` blocks (theme.py:25-47) rather than
reusing `@sc_accent` from `_SHARED_TOKENS` (theme.py:71-76) — a lighter
blue in dark clears 3:1 against #393A3B, and the same token then also
solves the invisible ring on `.suggested-action`. Alternatively
`outline-offset: 1px` moves every ring outside the border box onto
`@sc_panel_bg`, where #2F7BFF already measures 4.37:1 dark and 3.57:1
light, and no new token is needed.

PROTECTED: PROTECTED — the Swift Cut theme + layout tokens. Adding a
token is additive; changing `outline-offset` alters rendered geometry on
jog and toolbar buttons.


## D — Disabled semantics

**D1 — BROKEN — The jog widget never re-evaluates sensitivity when a job starts or ends, so every jog control stays live for the whole run**

swiftcut/ui_gtk/machine/jog_widget.py:730-733
`_on_machine_state_changed` — the only handler wired to
`machine.state_changed` (connected at jog_widget.py:373) — calls
`self._update_limit_status()` and `self._update_position()` and NOT
`_update_button_sensitivity()`. The only caller paths to
`_update_button_sensitivity` are `set_machine` (:378),
`_on_machine_changed` (:387-388) and `_on_connection_status_changed`
(:745), none of which fire on a DeviceStatus IDLE->RUN transition.
Nothing in jog_widget.py connects to `machine_cmd.job_started` (that
signal is defined at swiftcut/machine/cmd.py:40 and is consumed only in
swiftcut/ui_gtk/mainwindow.py:153). Even if the condition existed it
would never be recomputed: `_update_button_sensitivity` (:413-460)
computes only `connected = self.machine is not None and
self.machine.is_connected()`, and `_can_run_scale` (:806-810) checks
only `is_connected()` and `machine_cmd.has_job_ops`. Result: the eight
jog arrows, Z+/Z-, Home All, Go Scale and Cut Scale are all fully
sensitive while the machine is executing a job. Compare
swiftcut/ui_gtk/mainwindow.py:1465-1478, which does compute
`is_job_or_task_active` and uses it to disable Home, Frame, macros and
focus.

Citation corrected on verification:
swiftcut/ui_gtk/machine/jog_widget.py:730-733 — `def
_on_machine_state_changed(self, machine, state):` / `"""Handle machine
state changes to update limit status."""` /
`self._update_limit_status()` / `self._update_position()`. Connected at
:373
`self.machine.state_changed.connect(self._on_machine_state_changed)`.
Callers of `_update_button_sensitivity`: :260 (__init__ tail), :379
(set_machine, def at :346), :388 (_on_machine_changed, def at :387),
:745 (_on_connection_status_changed, def at :735) — none fires on an
IDLE->RUN transition. swiftcut/ui_gtk/machine/jog_widget.py:421
`connected = self.machine is not None and self.machine.is_connected()`
is the sole gate; :449-453 `self.home_all_btn.set_sensitive(connected)`
/ `# Job controls - always enabled when connected` / start, pause, stop.
swiftcut/ui_gtk/machine/jog_widget.py:806-810 `_can_run_scale` checks
`is_connected()` and `machine_cmd.has_job_ops` only.
swiftcut/machine/cmd.py:41 `self.job_started = Signal()` (finding said
:40); sole consumer swiftcut/ui_gtk/mainwindow.py:153. Gate that does
exist: swiftcut/ui_gtk/mainwindow.py:1467-1476 `machine_processing =
(conn_status == TransportStatus.CONNECTED and device_status !=
DeviceStatus.IDLE)` then `is_job_or_task_active = (machine_processing or
task_mgr.has_tasks() or self.machine_cmd.is_job_running)`, applied to
machine-home at :1478-1480. MISSING FROM THE ORIGINAL FINDING (raises
its value): the Ruida driver already refuses interactive motion during a
job at swiftcut/machine/driver/ruida/ruida_driver.py:1427 (`jog`: `if
self._jog_busy or self._job_running: return`), :1203 (`jog_key_down`)
and :882 (`trace_frame`/Go Scale), so the arrows and Go Scale are silent
no-ops, not live motion — but `RuidaDriver.home` (:728) has NO such
guard (grep for `_job_running` returns only 135, 586, 605, 882, 1203,
1427), and swiftcut/ui_gtk/machine/jog_widget.py:894-897
`_on_home_all_clicked` calls `self.machine_cmd.home(self.machine)`
directly -> swiftcut/machine/cmd.py:703-705 `add_coroutine(lambda ctx:
machine.home(axis))`, so the jog panel's Home All reaches the controller
mid-job while the toolbar's identical command is disabled.

Fix: The window already owns the one correct definition of "a job is
running" (mainwindow.py:1465-1474). Publish it as a single shared gate
(machine_cmd.job_started/job_finished already exist as the signal pair)
and have the jog widget consume it in `_update_button_sensitivity`,
rather than each panel deriving its own notion of busy. Minimum first
step, which changes no behaviour: call `_update_button_sensitivity()`
from `_on_machine_state_changed` so the existing conditions are at least
re-evaluated on a status change.

PROTECTED: Jog panel behaviour and Start/Pause/Stop are PROTECTED.
Reported, not proposed as an edit.

**D2 — BROKEN — Home and Frame stay enabled while the machine is disconnected**

swiftcut/ui_gtk/mainwindow.py:1477-1479: `am.get_action("machine-
home").set_enabled(not is_job_or_task_active)` — connection is not part
of the condition. `is_job_or_task_active` (:1470-1474) is
`machine_processing or task_mgr.has_tasks() or
machine_cmd.is_job_running`, and `machine_processing` (:1465-1469) is
itself `conn_status == TransportStatus.CONNECTED and device_status !=
DeviceStatus.IDLE`, so a disconnected machine makes it False and Home
enabled. Frame is the same: :1483-1487 `can_frame =
active_machine.can_frame() and doc.has_result() and not
is_job_or_task_active`, and `Machine.can_frame`
(swiftcut/machine/models/machine.py:1264-1269) is a pure configuration
check (`any(h.frame_power_percent …)`) with nothing to do with the
transport. The handlers do not compensate: `on_home_clicked`
(mainwindow.py:1880-1891) returns only `if not config.machine`, then
calls `machine_cmd.home(...)` -> cmd.py:703-705 -> `machine.home()`
(machine.py:1053-1055) -> `self.controller.home(...)`. Every other
machine action in the same block does check the transport (`machine-
send` :1498, `machine-cancel` :1533, `execute-macro` :1569, `zero-here`
:1578-1582).

Citation corrected on verification:
swiftcut/ui_gtk/mainwindow.py:1478-1480 (finding said 1477-1479):
`am.get_action("machine-home").set_enabled(\n    not
is_job_or_task_active\n)`. | :1467-1470 (said 1465-1469):
`machine_processing = (\n    conn_status == TransportStatus.CONNECTED\n
and device_status != DeviceStatus.IDLE\n)`. | :1472-1476 (said
1470-1474): `is_job_or_task_active = (\n    machine_processing\n    or
task_mgr.has_tasks()\n    or self.machine_cmd.is_job_running\n)`. |
:1482-1487 (as cited): `can_frame = (\n    active_machine.can_frame()\n
and doc.has_result()\n    and not is_job_or_task_active\n)` then
`am.get_action("machine-frame").set_enabled(can_frame)`. | machine-
send's transport term is at :1500 (`and conn_status ==
TransportStatus.CONNECTED`), with `set_enabled` at :1505 — the finding
cited :1498, which is the `NoDeviceDriver` line. | machine-cancel
:1533-1534, execute-macro :1569-1570, zero-here :1578-1583 all verified
as cited. | swiftcut/machine/models/machine.py:1264-1269 `def
can_frame(self): return any(h.frame_power_percent for h in self.heads if
isinstance(h, LaserHead))` — verified, no transport term. |
machine.py:1053-1055 `async def home` -> `await
self.controller.home(axes)` and cmd.py:703-705 — verified as cited. |
mainwindow.py:1880-1891 on_home_clicked — verified as cited. |
ADDITIONAL evidence not in the original finding:
swiftcut/ui_gtk/machine/jog_widget.py:449
`self.home_all_btn.set_sensitive(connected)` (with `connected =
self.machine is not None and self.machine.is_connected()` at :422)
versus jog_widget.py:894-897 `self.machine_cmd.home(self.machine)` — the
same command, connection-gated in the jog panel and ungated in the
toolbar. | swiftcut/machine/driver/ruida/ruida_driver.py:728-729 `async
def home(self, axes: Axis | None = None) -> None:` / `    assert
self._client`, with `self._client = None` at :113 and :353 — the
disconnected click asserts rather than no-ops. |
swiftcut/ui_gtk/toolbar.py:136 and :143 bind the toolbar Home/Frame
buttons to `win.machine-home` / `win.machine-frame`, and
swiftcut/ui_gtk/main_menu.py:175-176 expose the same two actions in the
menu, so both surfaces inherit the missing gate.

Fix: Fold `connected` into the shared machine-action gate rather than
repeating it per action: every control in this block needs (connected,
not busy, plus its own extra condition), and Home and Frame are the two
that dropped the first term. One `machine_gate(connected, busy)` base
reused by all eight actions makes the omission impossible.

**D3 — BROKEN — The laser dock's fire toggle has no job-running guard, while the toolbar's focus toggle does**

swiftcut/ui_gtk/machine/laser_control_widget.py:228-236
`_update_sensitivity`: `self._toggle_btn.set_sensitive(connected and
has_heads)`. The toolbar control for the same operation is gated at
swiftcut/ui_gtk/mainwindow.py:1553-1559: `can_focus = head is not None
and head.focus_power_percent > 0 and not is_job_or_task_active`. Both
paths reach `machine_cmd.set_focus_power`
(laser_control_widget.py:249-250 in `_turn_on`, and
swiftcut/machine/cmd.py:682-701), so the laser can be fired from the
dock during a running job while the toolbar button for it is greyed. The
toggle's tooltip is the static `_("Toggle laser on/off")` set at
laser_control_widget.py:46 and never rewritten (the only later tooltip-
free state change is the css class swap at :304). The four rows above it
(:231-235) are gated on `has_heads` only, so they stay editable while
disconnected — a different condition again in the same method.

Citation corrected on verification: Two line slips, both minor; the
substance is exact.

1) The `_turn_on` call is at laser_control_widget.py:251-252, not
249-250:
   251  percent = self._power_adj.get_value() / 100.0
   252  self.machine_cmd.set_focus_power(head, percent, self.machine)
   (lines 248-249 are the `if not self.machine.is_connected(): return`
early-out).
   The off path is :274 `self.machine_cmd.set_focus_power(head, 0,
self.machine)`.

2) cmd.py `set_focus_power` spans 682-700 (`def` at :682, body ends :700
with
   `lambda ctx: machine.set_focus_power(head, percent)`); :701 is blank.

3) "The four rows above it (:231-235)" — :231-235 is five rows
   (head_row, power_row, frequency_row, pulse_width_row, duration_row),
all
   `set_sensitive(has_heads)`. Four is right only if head_row is
excluded.

Verified verbatim and unchanged: laser_control_widget.py:236
`self._toggle_btn.set_sensitive(connected and has_heads)`;
mainwindow.py:1554-1559
`can_focus = (head is not None and head.focus_power_percent > 0 and not
is_job_or_task_active)`; laser_control_widget.py:46 static tooltip;
:304/:308 css swap.

Additional corroboration the finding did not cite, which strengthens it:
no layer
below the UI rejects the command during a job. mainwindow.py:1472-1476
defines
is_job_or_task_active; cmd.py:696-700 only null-checks the machine;
machine.py:1300-1310 and controller.py:425-448 only null-check
driver/head; and
ruida_driver.py:1166-1167 `set_focus_power` -> :1160-1164 `set_power` ->
`set_power_immediate` carries NO `_job_running`/`_jog_busy` check,
unlike the jog,
step-jog and trace paths at ruida_driver.py:882, :1203 and :1427. The
MOTION_AUDIT.md
invariant at :4577 ("a job holds it for its whole upload and run") is
scoped to
"jog, step jog and trace alike" and does not cover the power path.
bottom_panel.py:110-123 adds no parent-level gating.

Scope caveat on the FIX (not a refutation): the minimal fix - adding the
job-active
gate to the dock toggle in `_update_sensitivity` and calling it on job-
state change -
is UI-only and touches no protected path. The FIX's wider framing ("one
gate shared
by the toolbar toggle and the dock toggle ... Send, Pause, focus") would
reach the
Send and Pause gating at mainwindow.py:1494-1531, and Start/Pause/Stop
is PROTECTED,
so the shared-gate refactor must not be applied to those two without
approval.

Fix: The focus/fire command needs one gate shared by the toolbar toggle
and the dock toggle, with the reason attached — this is the third
instance of the same drift (Send, Pause, focus), which is the argument
for the shared gate rather than three separate patches.

PROTECTED: Firing the laser is a motion/interlock concern —
MOTION_AUDIT.md invariants should be consulted before changing when the
toggle is live. Reported only.

**D4 — INCONSISTENT — Arrow-key and Page Up/Down jogging bypasses the per-axis capability gate that disables the matching buttons**

swiftcut/ui_gtk/machine/jog_widget.py:918-948 `_on_key_pressed` guards
only on `if not self.machine or not self.machine.is_connected(): return
False` (:920-921), then routes straight to `_on_y_plus_clicked` /
`_on_x_minus_clicked` / `_on_z_plus_clicked` etc., which call
`_perform_visual_jog` (:760-765) -> `_perform_jog` (:747-758) ->
`machine_cmd.jog(...)`. The buttons those keys mirror are gated on far
more: jog_widget.py:427-447 disables each direction unless
`self._can_jog_direction(direction)` (defined :405-411, requiring
`machine.can_jog(axis)` for every axis the direction drives). So on a
machine without a Z axis, `z_plus_btn` is insensitive
(jog_widget.py:442-444) while Page_Up still issues the jog (:940-942).
The same holds for any rotated/limited axis mapping. The keyboard path
also has no job-running guard, per the previous finding.

Citation corrected on verification: Page_Up/Page_Down branch is
jog_widget.py:943-948, not :940-942 (940-942 is the `Gdk.KEY_Right` ->
`_on_x_plus_clicked` branch): "943: elif keyval == Gdk.KEY_Page_Up: /
944: self._on_z_plus_clicked(None)  # Up / 945: return True / 946: elif
keyval == Gdk.KEY_Page_Down: / 947: self._on_z_minus_clicked(None)  #
Down / 948: return True". `_on_key_pressed` spans :918-951 (finding said
918-948). `_perform_visual_jog` is :760-764, not :760-765. z-button gate
is jog_widget.py:442-447 (both z_plus_btn and z_minus_btn), not
:442-444. Add the missing root citation that makes the case concrete:
swiftcut/machine/driver/ruida/ruida_driver.py:1169-1179 `def
can_jog(self, axis=None)` -> "Z is not implemented here, so it is not
advertised... a Z delta used to be converted and then dropped, which
left the panel offering a button that did nothing but pin the busy
interlock." / `return not bool(axis & Axis.Z)`. Correct the implied
consequence: swiftcut/machine/driver/ruida/ruida_driver.py:1430-1431 `if
not (dx_um or dy_um): return` sits before `self._jog_busy = True`
(:1442), so the keyboard-issued Z jog is discarded without pinning the
interlock. The surviving effect is task displacement via
swiftcut/machine/cmd.py:430-432
`self._editor.task_manager.add_coroutine(lambda ctx: machine.jog(deltas,
speed), key="jog")`.

Fix: Route the key handler through the same predicate as the buttons:
the direction lookup should ask `_can_jog_direction(direction)` before
`_perform_visual_jog`, so one predicate governs both input paths. This
is a shared-predicate fix, not a per-key one.

PROTECTED: Jog panel behaviour is PROTECTED (docs/removal-
inventory-2026-09-04.md:202-203 lists hold-jog and safety releases as
protected). Report only.

**D5 — INCONSISTENT — The Export Ruida Job (.rd) action is never disabled for any reason; the failure is shown after the file chooser instead**

`export-rd` is registered at swiftcut/ui_gtk/actions.py:244
(`self._add_action("export-rd", self.win.on_export_rd_clicked)`) and
appears in the menu at swiftcut/ui_gtk/main_menu.py:41-43. A search for
every `set_enabled` call on a named action in the tree returns no hit
for `export-rd`: it is one of the actions that never has its sensitivity
touched. Its sibling `export` (G-code) is fully gated —
swiftcut/ui_gtk/mainwindow.py:1407 (`set_enabled(False)` with no
machine) and :1428-1435 `can_export = doc.has_result() and not
task_mgr.has_tasks() and not pipeline.is_data_stale` — and carries four
distinct reason tooltips at :1418-1420 and :1436-1452. So with no
machine configured, "Export G-code…" is grey with the tooltip "Select a
machine to enable G-code export" while "Export Ruida Job (.rd)…" is
live; the user picks a filename and only then gets a toast, from
swiftcut/doceditor/file_cmd.py:1033-1034 `raise ValueError("No machine
is configured.")` surfaced at file_cmd.py:1051-1057 as "Export failed:
…". The same holds for an empty document and for a stale pipeline.

Citation corrected on verification: Three line citations were off by a
couple of lines; the corrected ones are:

- swiftcut/doceditor/file_cmd.py:1034-1036 (finding said 1033-1034):
  1034                    machine = get_context().config.machine
  1035                    if machine is None:
  1036                        raise ValueError("No machine is
configured.")

- swiftcut/doceditor/file_cmd.py:1053-1059 (finding said 1051-1057):
  1053            except Exception as e:
  1054                logger.error(
  1055                    f"Ruida job export to {file_path} failed.",
exc_info=e
  1056                )
  1057                self._editor.notification_requested.send(
  1058                    self, message=_("Export failed:
{error}").format(error=e)
  1059                )

- swiftcut/ui_gtk/mainwindow.py:1430-1435 (finding said 1428-1435; 1428
is `is_dummy = isinstance(active_driver, NoDeviceDriver)`):
  1430            can_export = (
  1431                doc.has_result()
  1432                and not task_mgr.has_tasks()
  1433                and not self.doc_editor.pipeline.is_data_stale
  1434            )
  1435            am.get_action("export").set_enabled(can_export)

Exact as cited: actions.py:244, main_menu.py:41-43, mainwindow.py:1407,
mainwindow.py:1418-1420, mainwindow.py:1436-1452.

Supporting citation the finding did not include — the reason the file
chooser opens with no machine at all,
swiftcut/ui_gtk/mainwindow.py:1735-1738:
  1735        machine = config.machine
  1736        if not machine:
  1737            proceed_callback()
  1738            return
`on_export_rd_clicked` (mainwindow.py:1796-1805) routes through this
helper, so the no-machine case short-circuits straight to
`show_export_rd_dialog`.

Fix: `export-rd` should consume the same gate as `export` — the two
differ only in the writer, not in the preconditions (machine present,
has_result, not stale, no tasks). One `export_gate` computed once in
`_update_actions_and_ui` and applied to both actions removes the
divergence permanently.

PROTECTED: The .rd export path is PROTECTED. The gate is a sensitivity
change on the action only and must not alter build_rd_bytes / export_rd
itself; report and let the owner decide.

**D6 — INCONSISTENT — Send Job's tooltip explains one of its five disabled reasons; the other four leave it reading "Send to machine"**

swiftcut/ui_gtk/mainwindow.py:1496-1514. `send_sensitive` has six terms
(no NoDeviceDriver, no driver error, CONNECTED, `doc.has_result()`, `not
is_job_or_task_active`, `not is_data_stale`) but the tooltip branch
immediately below tests exactly one of them: `if
self.doc_editor.pipeline.is_data_stale:` -> "Pipeline needs
recalculation before sending. Press F5 to recalculate.", `else:` ->
`set_tooltip_text(_("Send to machine"))`. So a disconnected machine, a
driver in an error state, an empty document and a running job all
produce a grey Send button whose tooltip is the generic action label.
Contrast the export button five lines earlier (:1436-1452), which does
branch four ways.

Citation corrected on verification: Citation stands as given; adding
precision and one additional supporting site.

swiftcut/ui_gtk/mainwindow.py:1497-1514 (verbatim):
            send_sensitive = (
                not isinstance(active_driver, NoDeviceDriver)
                and (active_driver and not active_driver.state.error)
                and conn_status == TransportStatus.CONNECTED
                and doc.has_result()
                and not is_job_or_task_active
                and not self.doc_editor.pipeline.is_data_stale
            )
            am.get_action("machine-send").set_enabled(send_sensitive)
            if self.doc_editor.pipeline.is_data_stale:
                self.toolbar.send_button.set_tooltip_text(
                    _(
                        "Pipeline needs recalculation before sending. "
                        "Press F5 to recalculate."
                    )
                )
            else:
                self.toolbar.send_button.set_tooltip_text(_("Send to
machine"))

Contrast, swiftcut/ui_gtk/mainwindow.py:1436-1452 - export_tooltip
starts at _("Generate G-code") then branches four ways:
task_mgr.has_tasks() -> "Cannot export while other tasks are running";
is_data_stale -> "Pipeline needs recalculation before export. Press F5
to recalculate."; not doc.has_workpiece() -> "Add a workpiece to enable
export"; not doc.has_result() -> "Add or enable a processing step to
enable export".

ADDITIONAL SITE the original evidence omitted, which strengthens the
finding: swiftcut/ui_gtk/mainwindow.py:1406-1420, the no-active-machine
branch, calls am.get_action("machine-send").set_enabled(False) at :1411
and sets an explanatory export tooltip at :1418-1420 (_("Select a
machine to enable G-code export")) but never touches
self.toolbar.send_button. So with no machine selected, Send is disabled
while its tooltip is whatever was last written - the static _("Send to
machine") from swiftcut/ui_gtk/toolbar.py:147, or a stale "Pipeline
needs recalculation" string left over from a previous update. That makes
six uncovered disabled paths, not five.

The only three writers of this tooltip in the tree are
swiftcut/ui_gtk/toolbar.py:147 and swiftcut/ui_gtk/mainwindow.py:1507
and :1514; nothing else overrides it.

Fix: Compute the reason and the sensitivity in one expression (first
failing term wins, as the export tooltip already does) and write both
through one helper. The export block at :1436-1452 is the in-repo model
for the shape; the defect is that Send was written with the pattern
half-applied.

PROTECTED: Send Job is on the PROTECTED pipeline job path; this is a
tooltip-text change only, but it is on the same control, so flagging it.

**D7 — INCONSISTENT — Frame's tooltip is keyed to a different condition than Frame's sensitivity**

swiftcut/ui_gtk/mainwindow.py:1483-1494. Sensitivity: `can_frame =
active_machine.can_frame() and doc.has_result() and not
is_job_or_task_active`. Tooltip: `if not active_machine.can_frame(): …
"Configure frame power to enable" else: … "Cycle laser head around the
occupied area"`. The tooltip therefore only ever explains the first of
the three terms. With frame power configured but the document empty, or
with a job running, the button is grey and the tooltip is the
description of what the button does when it works.

Citation corrected on verification:
swiftcut/ui_gtk/mainwindow.py:1482-1495 (finding said 1483-1494):
can_frame at 1482-1486, `am.get_action("machine-
frame").set_enabled(can_frame)` at 1487, and the `if not
active_machine.can_frame():` tooltip branch at 1488-1495.

Fix: Same shared gate as the Send finding — reason and sensitivity
derived from one ordered list of conditions so a term can never be gated
on without being explained.

**D8 — INCONSISTENT — The no-machine branch disables ten controls but updates exactly one tooltip, leaving the others stale or generic**

swiftcut/ui_gtk/mainwindow.py:1406-1421: with `not active_machine`, ten
actions are disabled (`export`, `machine-settings`, `machine-home`,
`machine-frame`, `machine-send`, `machine-hold`, `machine-cancel`,
`machine-clear-alarm`, `execute-macro`, `zero-here`) and the only
tooltip written is
`self.toolbar.export_button.set_tooltip_text(_("Select a machine to
enable G-code export"))` at :1418-1420. The other buttons keep whatever
text they last had. Two distinct symptoms follow. (a) Never-updated:
`home_button` "Home the machine" (swiftcut/ui_gtk/toolbar.py:135),
`cancel_button` "Cancel running job" (:160), `clear_alarm_button` "Clear
machine alarm (unlock)" (:167-169), `focus_button` "Toggle focus laser"
(:178). (b) Stale: `send_button`, `frame_button` and `hold_button` are
only ever written inside the `else:` (machine present) arm at
:1489-1493, :1507-1514 and :1527-1531, so if the machine is removed
while the pipeline was stale the Send tooltip stays "Pipeline needs
recalculation before sending. Press F5 to recalculate." on a button that
is now disabled because there is no machine at all. This is the lens's
"tooltip does not update when the reason changes", demonstrated on the
same control in both directions.

Citation corrected on verification:
swiftcut/ui_gtk/mainwindow.py:1406-1421 — the not-active_machine arm;
only export_button gets a tooltip at :1418-1420. Additional facts the
finding did not cite that strengthen it: (a) mainwindow.py:1526-1531
sets the hold_button CHILD ICON as well as its tooltip only inside the
else arm, so after the last machine is removed mid-HOLD the button keeps
the play-arrow "Resume machine" icon and text while disabled; (b)
toggle-focus is NOT among the actions disabled at :1406-1416 at all —
the only place it is touched is :1554-1559 inside the else arm, so with
no machine it retains whatever sensitivity it last had, and
mainwindow.py:1991-1993 swaps focus_button's icon without ever touching
its tooltip. Runtime reachability of active_machine is None:
swiftcut/core/config.py:314-320, "self.config.set_machine(None)" in
_on_machine_removed, with re-selection guarded by "if
self.machine_mgr.machines:".

Fix: Both arms of the `if not active_machine:` branch must write the
same set of tooltips. The durable form is a single table of (action,
sensitive, reason) built once per update and applied in a loop, so a
branch cannot cover a subset. No new token is needed.

**D9 — INCONSISTENT — Every disabled reason is stored on a toolbar widget, so the same action in the main menu greys out with no explanation at all**

All reason text is written with `Gtk.Widget.set_tooltip_text` on toolbar
children — swiftcut/ui_gtk/mainwindow.py:1418, :1452, :1489, :1493,
:1507, :1514, :1528, :1531 — never on the `Gio.SimpleAction`. The same
actions are also presented as `Gio.MenuItem`s, which have no tooltip:
swiftcut/ui_gtk/main_menu.py:175-176 (Home, Frame), :187-190 (Send Job,
Pause / Resume Job, Cancel Job, Clear Alarm), :195 (Machine Settings),
:40 (Export G-code). The keyboard shortcuts route to the same actions
(swiftcut/ui_gtk/actions.py:31-83), so a user who presses Ctrl+E or
opens the menu gets a dead item and no explanation anywhere in the UI.
The condition is known — it is computed a few lines from where the
tooltip is set — and simply has no place to live that the menu can read.

Citation corrected on verification: Two overstatements in the original
write-up, both narrowing rather than breaking the finding.

(1) "no explanation anywhere in the UI" is too strong for
export/frame/send/hold. For those four the reason string does exist on-
screen, on the toolbar button (swiftcut/ui_gtk/mainwindow.py:1452,
:1489, :1507, :1528) — it is simply unreachable from the point of
interaction (menu item or accelerator). The accurate claim is that the
reason is bound to one presenter and no other surface can read it.

(2) The stronger, unstated half of the finding: for six of the ten
actions gated in `_update_actions_and_ui` there is no dynamic reason on
ANY surface, including the toolbar. `machine-home`
(mainwindow.py:1477-1479), `machine-cancel` (:1533-1534), `machine-
clear-alarm` (:1536-1541), `machine-settings` (:1466), `execute-macro`
and `zero-here` (:1417-1418 region, disabled at :1416-1417) all get
`set_enabled(...)` with no matching tooltip write. Their toolbar buttons
keep a static label set once at construction and never updated —
swiftcut/ui_gtk/toolbar.py:135
`self.home_button.set_tooltip_text(_("Home the machine"))`, :160
`self.cancel_button.set_tooltip_text(_("Cancel running job"))`, :167-169
`self.clear_alarm_button.set_tooltip_text(_("Clear machine alarm
(unlock)"))` — so when Home greys out because `is_job_or_task_active` is
true (mainwindow.py:1471-1479), the tooltip still reads "Home the
machine" and the real reason is discarded at the point it is computed.

(3) actions.py: the SHORTCUTS dict is lines 31-85, not 31-83. Only
`win.export` (Ctrl+E, :36) and `win.machine-settings` (Ctrl+less, :82)
among the cited actions have accelerators; machine-
home/frame/send/hold/cancel/clear-alarm have none, so the "presses
Ctrl+E" example is correct but the accelerator argument covers two of
the eight actions, not all of them.

Fix: There is no token for "why this action is unavailable". Add one: a
small reason registry keyed by action name that `_update_actions_and_ui`
writes to and every presenter reads — the toolbar renders it as a
tooltip, the menu renders it as the item's disabled subtitle (or the
label gains a suffix), and future surfaces get it for free. Today the
shared vocabulary stops at the action's boolean.

**D10 — INCONSISTENT — Ten jog buttons are disabled for two different reasons and their tooltips name neither**

swiftcut/ui_gtk/machine/jog_widget.py:427-449 disables the four cardinal
arrows, the four diagonals, Z+/Z- and Home All. Two independent reasons
are folded into one boolean: `connected` (:423) and
`self._can_jog_direction(direction)` (:405-411, per-axis
`machine.can_jog`). Every one of those buttons carries a tooltip set
once in `create_button` at :100-105 (`button.set_tooltip_text(tooltip)`)
with text like `_("Move North")` (:133), `_("Increase Z-Distance")`
(:238-240), and no code path ever rewrites them — the only later
`set_tooltip_text` calls in the file are on `position_label` (:728) and
`go_scale_btn` (:816, :823). So a user on a machine without a Z axis and
a user with the machine unplugged see the identical grey button with the
identical "Increase Z-Distance".

Citation corrected on verification:
swiftcut/ui_gtk/machine/jog_widget.py:422 — `connected = self.machine is
not None and self.machine.is_connected()` (finding said :423, off by
one).
swiftcut/ui_gtk/machine/jog_widget.py:405-411 — `def
_can_jog_direction(self, direction)` ... `return
all(self.machine.can_jog(axis) for axis in self._jog_deltas(direction))`
(as cited).
swiftcut/ui_gtk/machine/jog_widget.py:427-447 — the two reasons folded
per button: `east = connected and
self._can_jog_direction(JogDirection.EAST)` (427) through
`self.z_minus_btn.set_sensitive(connected and
self._can_jog_direction(JogDirection.DOWN))` (445-447). Line 449
`self.home_all_btn.set_sensitive(connected)` is a ONE-reason gate and
should be dropped from the set (finding cited 427-449).
swiftcut/ui_gtk/machine/jog_widget.py:102-124 — `def
create_button(icon_name, tooltip, label=None)`, with
`button.set_tooltip_text(tooltip)` at :105 (finding said the helper
starts at :100; it starts at :102).
swiftcut/ui_gtk/machine/jog_widget.py:135 — `self.north_btn =
create_button("arrow-north-symbolic", _("Move North"))` (finding said
:133; :133 is `self._jog_grid.attach(self.north_west_btn, 0, 0, 1, 1)`).
swiftcut/ui_gtk/machine/jog_widget.py:239-241 — `self.z_plus_btn =
create_button("arrow-z-up-symbolic", _("Increase Z-Distance"))`;
:245-247 for `_("Decrease Z-Distance")` (finding said :238-240).
swiftcut/ui_gtk/machine/jog_widget.py — complete set of
`set_tooltip_text` calls: 105, 728, 816, 823. Nothing rewrites an arrow
or Z tooltip; confirms the "no code path ever rewrites them" claim.
swiftcut/machine/driver/ruida/ruida_driver.py:1169-1179 — NEW supporting
evidence the reporter missed: `def can_jog(self, axis=None)` / docstring
"Z is not implemented here, so it is not advertised." / `return not
bool(axis & Axis.Z)`. Via machine.py:1071-1073 -> controller.py:618 this
makes Z+/Z- permanently insensitive on a CONNECTED Ruida while the
tooltip still reads "Increase Z-Distance".
Constraint on any fix (jog panel is PROTECTED): jog_widget.py:414-421
docstring — "Each button's value is computed once and written once.
Writing False and then the real value would reset every controller on
the button in between, which cancels a press the user is still holding."
A `set_gate` helper must keep exactly one `set_sensitive` write per
button per call.

Fix: `create_button` should take the enabled-tooltip and the widget
should be driven by a shared `set_gate(button, sensitive, reason)` that
swaps the text, exactly as `_update_scale_buttons` already does for the
running case. Ten buttons, one helper.

PROTECTED: Jog panel behaviour is PROTECTED; tooltip-only change
proposed, still flagged.

**D11 — INCONSISTENT — The dock's Zero X/Y/Z and Move To buttons have no job-running guard, while the identical win.zero-here action does**

swiftcut/ui_gtk/doceditor/bottom_panel.py:747-760: `is_active =
is_connected or is_dummy`, `can_zero = is_active and not is_mcs`,
applied to `zero_x_btn`, `zero_y_btn`, `zero_z_btn`, `zero_here_btn`.
And bottom_panel.py:589-604 `update_position_menu_sensitivity`:
`move_ll_btn`/`move_center_btn`/`move_ur_btn` get `has_bounds and
is_active`, `move_origin_btn` gets `is_active`. Neither expression
contains any notion of a job being in flight. The same operation exposed
as an action IS guarded: swiftcut/ui_gtk/mainwindow.py:1574-1583
`can_zero = (connected or is_dummy) and not is_g53 and not
is_job_or_task_active`. The move buttons call `machine_cmd.move_to`
(bottom_panel.py:_on_move_to_position ->
swiftcut/machine/cmd.py:707-713), i.e. they drive the head, mid-job,
from a panel that is not covered by the inspector lock (the lock at
mainwindow.py:679-687 applies to `_right_pane` only, and the WCS
controls live in the bottom panel).

Citation corrected on verification: Citation drift only on the first
block's start line (747 -> 748). Accurate evidence:
swiftcut/ui_gtk/doceditor/bottom_panel.py:748-750 `is_dummy =
isinstance(self.machine.driver, NoDeviceDriver)` / `is_connected =
self.machine.is_connected()` / `is_active = is_connected or is_dummy`;
:753 `can_zero = is_active and not is_mcs`; :756-759
`self.zero_x_btn.set_sensitive(can_zero)` / `zero_y_btn` / `zero_z_btn`
/ `zero_here_btn`. bottom_panel.py:590-604
update_position_menu_sensitivity: :601-603
`self.move_ll_btn.set_sensitive(has_bounds and is_active)` (also
move_center_btn, move_ur_btn), :604
`self.move_origin_btn.set_sensitive(is_active)`. Guarded counterpart:
swiftcut/ui_gtk/mainwindow.py:1578-1583 `can_zero = ((connected or
is_dummy) and not is_g53 and not is_job_or_task_active)` ->
`am.get_action("zero-here").set_enabled(can_zero)`, with
is_job_or_task_active defined at mainwindow.py:1472-1476 as
`machine_processing or task_mgr.has_tasks() or
self.machine_cmd.is_job_running`. Additional evidence the finding did
not cite: bottom_panel.py:401-402 `self.zero_here_btn.connect("clicked",
self._on_zero_axis_clicked, Axis.X | Axis.Y | Axis.Z)` versus
mainwindow.py:929 `axes_to_zero = Axis.X | Axis.Y | Axis.Z` in
on_zero_here_clicked - the dock button bypasses the guarded action
rather than sharing it. Inspector lock scope confirmed at
mainwindow.py:679-687 (`self._right_pane.set_sensitive(not locked)`).
Motion path confirmed: swiftcut/machine/cmd.py:707-713 move_to ->
swiftcut/machine/driver/ruida/ruida_driver.py:1102 move_to ->
_rapid_move_to (:1128-1134), no job interlock. Parallel precedent for
the same split: swiftcut/ui_gtk/machine/jog_widget.py:449
`self.home_all_btn.set_sensitive(connected)` versus
mainwindow.py:1478-1480 `am.get_action("machine-home").set_enabled(not
is_job_or_task_active)`.

Fix: Same shared machine gate as the toolbar actions: `is_active` in
bottom_panel is a locally reinvented, weaker copy of the window's
`connected and not is_job_or_task_active`. Replace the local derivation
with the shared one so the dock cannot drift from the action.

PROTECTED: Touches the machine motion path; MOTION_AUDIT.md invariants
should be checked before any change to when move_to can be issued.
Reported, not edited.

**D12 — INCONSISTENT — click_to_zero_btn is never passed to set_sensitive and stays live beside a disabled Zero Here**

`click_to_zero_btn` is built at
swiftcut/ui_gtk/doceditor/bottom_panel.py:405-410 and added to the same
suffix box as the four zero buttons (:412-420). Every other button in
that box is gated at :756-759 with `can_zero`; a grep for
`click_to_zero_btn` in the file returns only :405, :408 and :418 — it
never appears in a `set_sensitive` call. It arms the canvas click-to-
zero mode (`set_click_to_zero_mode`, :576-581) which reaches the same
work-origin write as the buttons next to it. So in Machine Coordinate
Mode, or with the machine disconnected, four of the five buttons in one
row are grey and the fifth is live and does the same thing by a
different route.

Citation corrected on verification:
swiftcut/ui_gtk/doceditor/bottom_panel.py:405-410 builds
`self.click_to_zero_btn = icon_button("crosshairs-symbolic", _("Click
Canvas to Set Work Zero"))`; :412-420 adds it to the same suffix_box as
zero_x/y/z_btn and zero_here_btn. Gating block :753-760: `can_zero =
is_active and not is_mcs` / `can_manual = not is_mcs`, then
set_sensitive(can_zero) on zero_x_btn (:756), zero_y_btn (:757),
zero_z_btn (:758), zero_here_btn (:759), and set_sensitive(can_manual)
on edit_offsets_btn (:760). click_to_zero_btn appears only at :405,
:408, :418 - never in a set_sensitive call, and zero_row is only ever
set_visible (:705), so nothing gates it indirectly.

CORRECTION 1 - it is not "the same work-origin write". The arming path
is _on_click_to_zero_toggled (:643-644) -> set_click_to_zero_mode
(:577-581) -> mainwindow.py:516-518 -> surface.set_click_to_zero_mode
(canvas2d/surface.py:887-891); the canvas click is surface.py:585-598,
which sends work_zero_requested (:597) -> mainwindow.py:520-531
`_on_work_zero_requested` -> `await config.machine.set_work_origin(x, y,
0.0)` -> machine.py:1409 -> controller.py:450. The four buttons instead
call _on_zero_axis_clicked (:571-575) -> machine.set_work_origin_here
(machine.py:1423 -> controller.py:493). Both write the active WCS
offset, by different setters.

CORRECTION 2 - the G53 case is a silent no-op, not a wrong write:
controller.py:462-468 refuses an immutable slot (`logger.warning("Cannot
set offset for immutable WCS ...")`, return). The user-visible defect is
a live control that cannot do anything and says nothing, next to four
greyed peers whose tooltip (:766-768) explains "Offsets cannot be set in
Machine Coordinate Mode". This contradicts website/docs/ui/bottom-
panel.md:176 (Click to Zero listed in the "Setting WCS Zero" button
table) and :184-187 ("Zero buttons are disabled when G53 (Machine
Coordinates) is selected, as machine coordinates are fixed by
hardware").

CORRECTION 3 - the proposed fix over-disables. can_zero includes
is_active, but controller.py:470-474 shows set_work_origin intentionally
handles the disconnected case by writing the offset into the model
(`self.machine.update_wcs_offset(slot, (x, y, z))`), and a canvas click
supplies explicit coordinates so it never needs the machine position
that set_work_origin_here bails on at controller.py:496-497. The gate
matching this button's real requirement is can_manual (`not is_mcs`) -
the same one edit_offsets_btn uses at :760.

Fix: Add it to the same `can_zero` application at :756-759 — the row
should be driven by one loop over its buttons rather than four hand-
written lines that a fifth button was appended after.

**D13 — INCONSISTENT — Only one of the five WCS/zero controls that share a condition states its reason; the other four keep construction tooltips**

swiftcut/ui_gtk/doceditor/bottom_panel.py:765-773 is the exemplary
implementation in this codebase: it selects between "Offsets cannot be
set in Machine Coordinate Mode ({wcs})", "Machine must be connected to
set Zero Here" and "Set current position as 0", and writes it to
`zero_here_btn`. But `zero_x_btn`, `zero_y_btn`, `zero_z_btn` are
disabled by the very same `can_zero` at :756-758 and keep the static
text from :383-396 ("Set current X position as 0 for active WCS" etc.),
and `edit_offsets_btn` is disabled by `can_manual` at :760 and keeps
"Edit Offsets Manually" from :331-333. The reason string is already
computed one screen away and is applied to exactly one of the five
widgets.

Citation corrected on verification: Citation is correct as given; two
precision notes. (a) The title's "five controls that share a condition"
is loose: bottom_panel.py:756-759 governs four buttons with `can_zero`,
while :760 governs edit_offsets_btn with the separate `can_manual` — two
conditions, five widgets, one reason tooltip. (b) The messages are not
all transferable verbatim: :769 reads `_("Machine must be connected to
set Zero Here")`, naming one specific button, so a straight loop would
put "Zero Here" on the X/Y/Z and Edit Offsets buttons. Only the is_mcs
branch (:765-767, "Offsets cannot be set in Machine Coordinate Mode
({wcs})") is already generic across the group. Also worth noting as
scope, not correction: bottom_panel.py:601-604 desensitizes
move_ll_btn/move_center_btn/move_ur_btn/move_origin_btn on `has_bounds
and is_active` with no reason tooltip either, and
layer_settings_dialog.py:185 desensitizes its own edit_offsets_btn on
`wcs is not None` with the same static :88 tooltip — the same pattern
appears in at least two more places than the finding claims.

Fix: Apply the message computed at :765-772 to every widget the same
condition governs — one loop over the (widget, condition) pairs. The
correct text already exists; it is the distribution that is missing.

**D14 — INCONSISTENT — The theme's :disabled opacity arm covers three surfaces; the bottom panel and the laser dock are not among them, so two disabled vocabularies sit side by side**

swiftcut/ui_gtk/theme.py:180-190 defines the disabled treatment for
exactly five selectors: `.sc-toolbar > button:disabled`, `.sc-toolbar >
togglebutton:disabled`, `.sc-split > button:disabled`, `.sc-split >
menubutton > button:disabled`, `.sc-jog button:disabled` -> `opacity:
0.4`. The bottom panel's WCS group is `.sc-panel`
(swiftcut/ui_gtk/doceditor/bottom_panel.py:307) and `.sc-panel` has
rules only at theme.py:231, :248 (`togglebutton:checked`) and :342
(`row`) — no `:disabled` arm. The laser dock's toggle carries `.sc-
laser-live` (swiftcut/ui_gtk/machine/laser_control_widget.py:44), and
theme.py:292-298 defines only `.sc-laser-live:checked`. Consequence,
visible in one screenshot: inside the same bottom panel, a disabled jog
arrow (`.sc-jog`) fades to 40% while the disabled Zero X directly beside
it keeps libadwaita's insensitive grey fill. This is exactly the second
half of pass-1 finding X1, on surfaces X1 did not examine. Pass-1 X1
itself is FIXED — swiftcut/ui_gtk/shared/splitbutton.py:37-41 and
swiftcut/ui_gtk/shared/undo_button.py:29-33 now add `sc-split`, and
theme.py:186-187 now carries the `.sc-split` disabled arms with the
comment recording why.

Citation corrected on verification: Every load-bearing citation holds;
two refinements.

1. Exact rule block (swiftcut/ui_gtk/theme.py:180-190) — the finding's
line range is the comment plus the rule; the rule itself is 184-190:
   184 .sc-toolbar > button:disabled,
   185 .sc-toolbar > togglebutton:disabled,
   186 .sc-split > button:disabled,
   187 .sc-split > menubutton > button:disabled,
   188 .sc-jog button:disabled {
   189     opacity: 0.4;
   190 }
   A full-tree grep for sc-panel / sc-laser-live / sc-icon-button
confirms the gap: `.sc-panel` occurs only at theme.py:231 (font-size),
:248 (togglebutton:checked), :342 (row); `.sc-laser-live` only at :292
(:checked); `.sc-icon-button` only at :319 (min size) and :337 (icon
size). No :disabled arm on any of the three.

2. ADDED — the disabled state is actually reached on both uncovered
surfaces, which the finding asserted but did not cite:
   swiftcut/ui_gtk/doceditor/bottom_panel.py:756-760
       self.zero_x_btn.set_sensitive(can_zero)
       self.zero_y_btn.set_sensitive(can_zero)
       self.zero_z_btn.set_sensitive(can_zero)
       self.zero_here_btn.set_sensitive(can_zero)
       self.edit_offsets_btn.set_sensitive(can_manual)
   (also :601-604 for move_ll/center/ur/origin)
   swiftcut/ui_gtk/machine/laser_control_widget.py:236
       self._toggle_btn.set_sensitive(connected and has_heads)
   So this is a state users see, not a theoretical selector gap.

3. Adjacency confirmed: bottom_panel.py:107 `self.jog_widget =
JogWidget()` and :127 `self._jog_laser_box.append(self.jog_widget)` sit
in the same `sc-dock` panel (:63) as the `sc-panel` WCS group (:307);
jog_widget.py:100 `self.add_css_class("sc-jog")`.

4. CORRECTION to the wording "keeps libadwaita's insensitive grey fill".
The WCS buttons are built by swiftcut/ui_gtk/layout.py:107-108
(icon_button) and :121-124 (axis_button), both of which
`add_css_class("flat")` before `add_css_class("sc-icon-button")`; the
laser toggle is also `flat` (laser_control_widget.py:43). libadwaita's
disabled treatment for a *flat* button is a dimmed label over a
transparent background, not the grey capsule fill AUDIT X1 described for
the non-flat split buttons. The two-vocabularies claim stands — 40%
opacity beside libadwaita's own insensitive dimming — but "grey fill" is
borrowed from X1 and does not transfer verbatim to these flat controls.

5. Pass-1 X1 (docs/design/audit/AUDIT.md:327-338) is indeed fixed:
swiftcut/ui_gtk/shared/splitbutton.py:43 and
swiftcut/ui_gtk/shared/undo_button.py:31 both `self.add_css_class("sc-
split")`, and theme.py:186-187 carry the arms. Note X1 as written cites
`.sc-toolbar > .sc-split > button` at "theme.py:128"; the current sheet
uses the un-nested `.sc-split > button` (theme.py:143-144), so the
pass-1 text no longer matches the tree at all — it cannot be a live
duplicate.

6. CAUTION on the fix, not a refutation. The narrow option (`.sc-panel
button:disabled`, `.sc-laser-live:disabled` appended at
theme.py:184-189) is the safe one and is the same shape of edit already
applied for X1. It cannot reach the jog grid: jog_widget carries `sc-
jog` and is a sibling of the WCS group in `_jog_laser_box`, not a
descendant of `sc-panel`, and even if it were the declared value is
identical. The finding's "better" variant — retargeting the opacity onto
a new shared control class every surface applies — would rewrite the
selector list that currently governs `.sc-jog` and `.sc-toolbar`, i.e.
it edits the Swift Cut theme's existing arms rather than extending them.
Prefer the narrow option; the broad refactor should not be taken without
a separate decision.

Fix: The disabled token is a per-surface allowlist, which guarantees the
next surface is missed. Either widen the existing rule at
theme.py:184-189 to the panel surfaces (`.sc-panel button:disabled`,
`.sc-laser-live:disabled`) or, better, define the opacity once against a
shared control class every Swift Cut surface applies, so a new panel
inherits the disabled look instead of opting into it.

PROTECTED: The Swift Cut theme + layout tokens are PROTECTED, and
docs/design/swift-cut-layout.md:238 documents `.sc-split` as the recent
addition. Any new selector is a theme-token change and needs owner sign-
off; reporting the gap only.

**D15 — INCONSISTENT — Three split buttons in one toolbar row use three different rules for disabling their dropdown half**

(a) Arrange: swiftcut/ui_gtk/mainwindow.py:1630
`self.toolbar.arrange_menu_button.set_sensitive(has_selection)` disables
the whole `Gtk.Box`, dropdown included (`SplitMenuButton.set_sensitive`,
swiftcut/ui_gtk/shared/splitbutton.py:67-71, forwards to `super()`). (b)
Tabs: `tab_menu_button` is built at swiftcut/ui_gtk/toolbar.py:126-128
and a tree-wide grep finds it referenced only there and at
swiftcut/ui_gtk/actions.py:587 (`.main_button`, as a popover anchor) —
it is never passed to `set_sensitive`, so its dropdown arrow stays live
in an empty document and opens a popover whose two rows are insensitive
because their actions are (`add-tabs-equidistant`/`add-tabs-cardinal`,
swiftcut/ui_gtk/actions.py:474-476). (c) Undo/Redo:
swiftcut/ui_gtk/shared/undo_button.py:61-65 disables only the dropdown
(`self.menu_button.set_sensitive(can_act)`) and leaves the main button
to its action. Three widgets sitting next to each other, three
behaviours.

Citation corrected on verification: Only one citation is off, by one
line: `SplitMenuButton.set_sensitive` is at
swiftcut/ui_gtk/shared/splitbutton.py:68-72, not 67-71 — `def
set_sensitive(self, sensitive: bool):` (68), docstring "Sets the
sensitivity of the entire composite button." (69), comment lines 70-71,
`super().set_sensitive(sensitive)` (72). All other citations are exact:
swiftcut/ui_gtk/mainwindow.py:1630
`self.toolbar.arrange_menu_button.set_sensitive(has_selection)`;
swiftcut/ui_gtk/toolbar.py:126-128 `self.tab_menu_button =
SplitMenuButton(actions=tab_actions)` / `.set_tooltip_text(_("Add Tabs
to selection"))` / `self.append(self.tab_menu_button)`;
swiftcut/ui_gtk/actions.py:587 `button =
self.win.toolbar.tab_menu_button.main_button`;
swiftcut/ui_gtk/actions.py:474-476 `can_add_tabs = any(wp.boundaries for
wp in target_workpieces)` / `self.actions["add-tabs-
equidistant"].set_enabled(can_add_tabs)` / `self.actions["add-tabs-
cardinal"].set_enabled(can_add_tabs)`;
swiftcut/ui_gtk/shared/undo_button.py:60-65 (`_on_history_changed`,
comment "We only need to control the dropdown arrow's sensitivity
here.", `can_act = self._can_act()`,
`self.menu_button.set_sensitive(can_act)`). Supporting detail the
finding did not cite: the dropdown that is never disabled is created at
swiftcut/ui_gtk/shared/splitbutton.py:58-63 as a bare
`Gtk.MenuButton(child=..., popover=..., tooltip_text=_("Show all
options"))` with no action name, which is why it stays sensitive; its
popover rows inherit sensitivity only from
`button.set_action_name(action_name)` at splitbutton.py:92.

Fix: `SplitMenuButton` should own the rule: the dropdown follows the
sensitivity of the actions it lists (disabled when none of them is
enabled), so callers stop hand-disabling the container. `_HistoryButton`
already implements exactly that rule at undo_button.py:61-65 and is the
model.

**D16 — INCONSISTENT — A cluster of selection-driven actions is never disabled while its immediate menu neighbours are, and they silently no-op**

Actions that never have `set_enabled` called on them anywhere in the
tree, yet require a selection: `flip-horizontal`/`flip-vertical`
(registered swiftcut/ui_gtk/actions.py:396-400; handlers :797-805 do
`items = list(self.win.surface.get_selected_items())` and pass an empty
list straight to `editor.transform.flip_*`), `array-grid`/`array-point-
rotation`/`array-circular` (:403-405; `_open_array_dialog` :821-824 does
`if not items: return` — the menu item is live and clicking it does
nothing at all), and `convert-to-stock` (handler :746-750, `if not
selected_wps: return`). Their neighbours in the very same surfaces ARE
gated: `align-*` on `has_selection` and `spread-*` on `>= 2` at
swiftcut/ui_gtk/mainwindow.py:1620-1629, `split` on `bool(selected_wps)`
and `export-object` on `len(selected_wps) == 1` at actions.py:497-498.
In the arrange split-button popover (built at
swiftcut/ui_gtk/toolbar.py:262-283) Align Left is grey and Flip
Horizontal beside it is not, with an empty selection.

Citation corrected on verification: Corrected surface for the visible
contrast — replace the toolbar-popover sentence.

REAL LOCUS 1, the Arrange main menu,
swiftcut/ui_gtk/main_menu.py:133-156. Four sibling submenus are appended
to the same `arrange_menu`:
  133-140  align_submenu -> "win.align-left" ... "win.align-v-center"
(all gated on has_selection, mainwindow.py:1622-1627)
  142-145  distribute_submenu -> "win.spread-h", "win.spread-v"
(gated on can_distribute >= 2, mainwindow.py:1628-1629)
  147-150  flip_submenu.append(_("Flip Horizontal"), "win.flip-
horizontal") / ("Flip Vertical", "win.flip-vertical")   (NEVER gated)
  152-156  array_submenu.append(_("Grid"), "win.array-grid") / ("Point
Rotation", "win.array-point-rotation") / ("Circular", "win.array-
circular")   (NEVER gated)
With an empty selection, Arrange > Align > Left is insensitive while
Arrange > Flip > Flip Horizontal and Arrange > Array > Grid are live in
the same menu and do nothing on click.

REAL LOCUS 2, the item context menu,
swiftcut/ui_gtk/canvas2d/context_menu.py:98-120
(`_populate_standard_items`). In one flat menu: "win.layer-move-
up"/"win.layer-move-down" (gated, mainwindow.py:1617-1618),
"win.group"/"win.ungroup" (gated, :1608/:1613), "win.remove" (gated,
:1603) — and at :115-117 `Gio.MenuItem.new(_("Convert to Stock"),
"win.convert-to-stock")`, never gated; its handler (actions.py:746-750)
does `if not selected_wps: return`, so right-clicking a Group or
StockItem offers a live item that no-ops.

REFUTED SUB-CLAIM: "In the arrange split-button popover (built at
swiftcut/ui_gtk/toolbar.py:262-283) Align Left is grey and Flip
Horizontal beside it is not, with an empty selection."
swiftcut/ui_gtk/mainwindow.py:1630 reads
`self.toolbar.arrange_menu_button.set_sensitive(has_selection)`, and
swiftcut/ui_gtk/shared/splitbutton.py:68-73 is `def set_sensitive(self,
sensitive: bool): ... super().set_sensitive(sensitive)` on the composite
Gtk.Box — so with an empty selection the whole split button is
insensitive and the popover never opens. (Flip Horizontal/Vertical ARE
in that popover, toolbar.py:286-297, but the contrast is not
observable.)

MINOR CITATION FIXES: flip registration is actions.py:399-400, not
396-400 (398 is the `# Transform Actions` comment). The always-live
accelerators are worth adding: actions.py:80-81 binds `"win.flip-
horizontal": "<Shift>h"` and `"win.flip-vertical": "<Shift>v"`
unconditionally. Note also that `flip_horizontal`/`flip_vertical` guard
themselves at swiftcut/doceditor/transform_cmd.py:145-146 and :183-184
(`if not items: return`), so the empty list reaches the editor but is
dropped there — the outcome is the same silent no-op the finding
describes, no empty undo entry is pushed.

Fix: `update_action_states` should drive a table of (action, predicate)
rather than a hand-written line per action; the six missing entries are
all `has_selection` or `len(selection) >= 1`, the predicate the block
already computes at mainwindow.py:1587-1588. A table also makes
"registered but never gated" auditable.

**D17 — INCONSISTENT — The addon enable switch is left enabled although the model already knows the reason it cannot be turned off**

swiftcut/ui_gtk/addon_manager/addon_list.py:161-173 gates the switch on
the addon state only (`INCOMPATIBLE`, `LOAD_ERROR`, `PENDING_UNLOAD`,
`LICENSE_REQUIRED`) and gives it the static tooltip `_("Enable or
disable this addon")` at :171-173 — so even in those four cases the
disabled switch never says why. Worse, the dependency reason exists as a
first-class value: `AddonManager.can_disable`
(swiftcut/addon_mgr/addon_manager.py:1558-1569) returns `(False,
f"Required by: {…}")`, and the only consumer is
swiftcut/ui_gtk/addon_manager/addon_list.py:350-358, which calls it
AFTER the user flips the switch, shows a "Cannot Disable Addon" dialog
and then calls `populate_addons()` to snap the switch back. The control
that should have been disabled-with-a-reason is instead enabled,
actuated, refused and reverted. (docs/removal-
inventory-2026-09-04.md:181-185 records the related latent bug that
`can_disable` only checks addon-to-addon `requires`, so this is a known-
fragile area.)

Citation corrected on verification:
swiftcut/ui_gtk/addon_manager/addon_list.py:163-171
`self.enable_switch.set_sensitive(state not in
(AddonState.INCOMPATIBLE.value, AddonState.LOAD_ERROR.value,
AddonState.PENDING_UNLOAD.value, AddonState.LICENSE_REQUIRED.value))`;
:172-174 `self.enable_switch.set_tooltip_text(_("Enable or disable this
addon"))` (tooltip call spans 172-174, not 171-173).
swiftcut/addon_mgr/addon_manager.py:1566-1569 `dependents =
self._find_dependents(addon_name); if dependents: return False,
f"Required by: {', '.join(dependents)}"; return True, ""`.

Fix: Call `can_disable` while building the row and feed both halves of
its return into the same gate helper (`set_sensitive(can)` +
`set_tooltip_text(reason)`). This is the one place in the codebase where
a (bool, reason) pair already exists in the exact shape the shared gate
wants — it just is not consumed at build time.

**D18 — INCONSISTENT — The whole right pane is disabled for the duration of a job with no banner and no tooltip anywhere in it**

swiftcut/ui_gtk/mainwindow.py:673-687: `_on_job_started` calls
`_set_inspector_locked(True)`, which is
`self._right_pane.set_sensitive(not locked)`. The docstring at :680-686
states the reason precisely ("Editing the workflow under a job that has
already been encoded and sent would show settings the running job is not
using") — a legitimate "a job is running" case — but nothing renders
that sentence. Every control in the pane greys simultaneously and,
because the container itself is insensitive, no child can offer its own
explanation. Unlocked again at :704 and :717.

Citation corrected on verification: swiftcut/ui_gtk/mainwindow.py:705
`self._set_inspector_locked(False)` and :718
`self._set_inspector_locked(False)` (the finding cited :704/:717, which
are `self.toolbar.set_job_progress(None)`). Toolbar progress area:
swiftcut/ui_gtk/toolbar.py:202-216, `self.job_progress_box =
Gtk.Box(spacing=SPACE_CONTROL)` ...
`self.job_progress_box.set_visible(False)`.

Fix: Pair the container gate with a visible reason: an inline banner at
the top of the locked pane (the toolbar already shows a job-progress
area at swiftcut/ui_gtk/toolbar.py:202-224, so the running state is
already a rendered concept) or a tooltip on the pane's own header. The
docstring text is the copy.

**D19 — MINOR — Go Scale and Cut Scale: the Go Scale tooltip is reset to the generic text on every disabled pass, and Cut Scale's is never touched at all**

swiftcut/ui_gtk/machine/jog_widget.py:812-829 `_update_scale_buttons`.
In the not-scaling branch it unconditionally writes
`self.go_scale_btn.set_tooltip_text(_("Traverse the job outline with the
laser off"))` (:823-826) and only then computes `can_run =
self._can_run_scale()` and applies it to both buttons (:828-829).
`_can_run_scale` (:806-810) is False for two distinct reasons — `not
self.machine.is_connected()` and `not machine_cmd.has_job_ops`
(`has_job_ops` is `doc.has_result()`, swiftcut/machine/cmd.py:434-437) —
and neither is ever named. `cut_scale_btn`'s tooltip is set once at
construction (jog_widget.py:195-200, `_("Cut a rectangle around the job
outline")`) and never written again anywhere in the file. Note the
running case is handled well by contrast (:814-819 swaps the caption to
"Stop" and the tooltip to "Stop the running scale"), which shows the
mechanism exists and was simply not extended to the disabled case.

Citation corrected on verification: Accurate statement of what is
actually there. swiftcut/ui_gtk/machine/jog_widget.py:806-810
`_can_run_scale` returns a bare bool that is False for two distinct
reasons — `if not self.machine or not self.machine.is_connected():
return False` and `return bool(self.machine_cmd and
self.machine_cmd.has_job_ops)` (has_job_ops =
`self._editor.doc.has_result()`, swiftcut/machine/cmd.py:435-437).
:827-829 applies that single bool to both buttons (`can_run =
self._can_run_scale()` / `self.go_scale_btn.set_sensitive(can_run)` /
`self.cut_scale_btn.set_sensitive(can_run)`) and neither reason is ever
surfaced to the operator; go_scale_btn keeps `_("Traverse the job
outline with the laser off")` and cut_scale_btn keeps `_("Cut a
rectangle around the job outline")` (set at :188-200). CORRECTION to the
original evidence: the tooltip write at :823-825 is NOT a defect —
`_update_scale_buttons` is invoked from `_on_scale_done` (:884-888)
after a run ends, so :823-825 is the required restore of the `_("Stop
the running scale")` tooltip written at :816, and cut_scale_btn has no
such alternate state to restore, which is why it is correctly never
rewritten. FURTHER CORRECTION: the disconnected case never reaches this
code at all — `_update_button_sensitivity` :455-458 does `if not
connected: self.go_scale_btn.set_sensitive(False);
self.cut_scale_btn.set_sensitive(False); return` before
`_update_scale_buttons()` at :460. FURTHER CORRECTION: this is not an
inconsistency. The same file disables start_btn/pause_btn/stop_btn
(:450-453) and every jog button (:427-444) with a bare set_sensitive()
and no reason text, and a grep for a disabled-reason helper across
swiftcut/ui_gtk finds none (only layer_column.py:284, an unrelated GTK
drag-cancel parameter) — so the claim that a "(sensitive, reason) pair"
is "used everywhere else" is false.

Fix: `_can_run_scale` should return the reason alongside the boolean and
`_update_scale_buttons` should write both to both buttons through one
helper — the same (sensitive, reason) pair used everywhere else. The
running-state branch already proves the widget is happy to have its
tooltip rewritten.

PROTECTED: Go Scale / Cut Scale are PROTECTED jog panel behaviour.
Tooltip-only change, but on a protected control — report.

**D20 — MINOR — Split-button container tooltips are shadowed by the main button's own tooltip and neither states the disabled reason**

swiftcut/ui_gtk/toolbar.py:110 sets "Arrange selection" and :127 sets
"Add Tabs to selection" on the `SplitMenuButton` boxes, but
`SplitMenuButton._set_active_action` writes the per-action name onto the
inner button at swiftcut/ui_gtk/shared/splitbutton.py:122-124
(`self.main_button.set_tooltip_text(name)`), so hovering the actual
button shows e.g. "Center Horizontally" and the container text only
appears in the seam between the halves. The same double-set exists for
undo/redo: swiftcut/ui_gtk/shared/undo_button.py:36-37 sets "Undo the
last action" on the main button, then swiftcut/ui_gtk/toolbar.py:69 sets
"Undo" on the box. In every case, when the control is disabled (arrange:
`has_selection`, mainwindow.py:1630; tabs: `can_add_tabs` from
`any(wp.boundaries …)`, actions.py:473-476; undo:
`history_manager.can_undo()`, mainwindow.py:1589-1591) the visible
tooltip is the command name, never the reason.

Citation corrected on verification: Corrected line: the split-button
write is swiftcut/ui_gtk/shared/splitbutton.py:126, not 122-124. Lines
121-127 read:
    self._last_action_index = index
    name, icon_name, action_name = self.actions[index]

    # Update the main button's appearance and its active action
    self.main_button.set_child(get_icon(icon_name))
    self.main_button.set_tooltip_text(name)
    self.main_button.set_action_name(action_name)
Two additions the finding understates:
(a) The claim that the container text "only appears in the seam between
the halves" overstates the container tooltip's reach — both composites
call `self.set_spacing(0)` (splitbutton.py:37, undo_button.py:25) and
append exactly two buttons, so there is effectively no uncovered box
area at all. The container strings at toolbar.py:110/127/69 are dead:
they are never displayed, in any state.
(b) The finding misses a fourth instance of the same double-set:
toolbar.py:74 `self.redo_button.set_tooltip_text(_("Redo"))` shadowed by
undo_button.py:37 writing `_("Redo the last action")` (RedoButton,
undo_button.py:157), gated by `history_manager.can_redo()` at
mainwindow.py:1592-1594.
(c) Reinforcing the "main button owns the tooltip" point: toolbar.py:313
`self.arrange_menu_button.update_actions(self.arrange_actions)` re-
enters `_set_active_action(0)` (splitbutton.py:151), rewriting the main
button tooltip at runtime while the container string never changes.

Fix: Pick one owner of the tooltip inside the split widget (the main
button) and have the shared gate helper write the reason there; the
container-level `set_tooltip_text` calls in toolbar.py are then
redundant and should go.

**D21 — MINOR — Read from Device and the VarSet apply buttons are disabled for three distinct reasons with a static label as their tooltip**

swiftcut/ui_gtk/machine/device_settings_page.py:272-282: `read_button`
is disabled when `self._is_busy` (:274) and otherwise gated on
`is_connected and not is_running` (:277); the apply buttons get
`is_connected and not is_running and not self._is_busy` (:280-282) via
swiftcut/ui_gtk/varset/varsetwidget.py:208-210, which loops
`button.set_sensitive(sensitive)` with no tooltip parameter at all.
`read_button`'s tooltip is `_("Read from Device")`, set once at
device_settings_page.py:59. Three legitimate reasons (busy,
disconnected, job running), zero of them explained.

Citation corrected on verification:
swiftcut/ui_gtk/machine/device_settings_page.py:272-282 (verified
verbatim):
```
        if self._is_busy:
            self.spinner.start()
            self.read_button.set_sensitive(False)
        else:
            self.spinner.stop()
            self.read_button.set_sensitive(is_connected and not
is_running)

        for widget in self._varset_widgets:
            widget.set_apply_buttons_sensitive(
                is_connected and not is_running and not self._is_busy
            )
```
swiftcut/ui_gtk/varset/varsetwidget.py:208-210 (verified verbatim):
```
    def set_apply_buttons_sensitive(self, sensitive: bool):
        for button in self._apply_buttons:
            button.set_sensitive(sensitive)
```
Static tooltips, never updated: device_settings_page.py:59
`self.read_button.set_tooltip_text(_("Read from Device"))`;
varsetwidget.py:162-165 `apply_button =
Gtk.Button(child=get_icon("check-symbolic"), tooltip_text=_("Apply
Change"),)`.
Correction to the claim "three reasons, zero of them explained" — two of
the three ARE partially surfaced elsewhere on the page, so the defect
narrows to the running-job case:
- busy: device_settings_page.py:57 `self.spinner = Gtk.Spinner()`, :62
appended to header_box next to read_button, :273 `self.spinner.start()`.
- disconnected: device_settings_page.py:240-246
`self.error_row.set_visible(has_op_error or is_not_connected_state)` ...
`self.error_row.set_title(_("Machine Not Connected"))` /
`set_subtitle(_("The machine is not connected."))` — user-dismissible
via `_not_connected_warning_dismissed` (:372-380).
- job running: `is_running` (device_settings_page.py:212 `is_running =
self.machine.device_state.status == DeviceStatus.RUN`) appears ONLY at
:277 and :281. No banner, error row, tooltip or label anywhere in the
file mentions it, so a connected machine mid-job shows both controls
greyed with no explanation at all.
Correction to the FIX rationale: `grep -rn "set_apply_buttons_sensitive"
--include=*.py .` returns exactly two hits — the definition
(varsetwidget.py:208) and one call site (device_settings_page.py:280).
Changing the signature to carry a reason is therefore a single-page fix,
not a change that "covers every VarSet page at once".

Fix: `set_apply_buttons_sensitive` should become
`set_apply_buttons_gate(sensitive, reason)` — a shared-widget fix that
covers every VarSet page at once rather than per-page tooltips.

**D22 — MINOR — The shared add-button in list panels can be disabled but has no tooltip hook, so a read-only library gives no explanation**

swiftcut/ui_gtk/doceditor/material_list.py:140-143 disables the add
button with `library is not None and not library.read_only`. The button
comes from the shared base `PreferencesGroupWithButton`
(swiftcut/ui_gtk/shared/preferences_group.py:70-73), which sets css
classes and nothing else — no `set_tooltip_text` anywhere in that file,
and none in material_list.py either. "Library is read only" is a fourth
reason class beyond the three legitimate ones and is never shown. The
head-row delete button
(swiftcut/ui_gtk/machine/head_preferences_page.py:184-192) is the
codebase's correct counter-example: `tooltip = None if can_delete else
_("At least one head is required")`, then `set_sensitive(can_delete)`
and `set_tooltip_text(tooltip)` written together in the same loop.

Citation corrected on verification:
swiftcut/ui_gtk/doceditor/material_list.py:141-143 (the set_sensitive
call; :140 is `self._current_library = library`). Counter-example is
head_preferences_page.py:183-192, not 184-192 — :183 `can_delete =
len(self.machine.heads) > 1` is the first line of the pair.

Fix: Give `PreferencesGroupWithButton` a `set_add_gate(sensitive,
reason)` that writes both, modelled on head_preferences_page.py:184-192.
Every list panel that reuses the base gets the explanation for free.

**D23 — MINOR — Save is disabled for a reason outside the three legitimate ones, with the label as its tooltip**

swiftcut/ui_gtk/actions.py:470-471: `is_unsaved = not
self.editor.is_saved; self.actions["save"].set_enabled(is_unsaved)`. The
toolbar button's tooltip is `_("Save")`, set once at
swiftcut/ui_gtk/toolbar.py:45 and never rewritten. "There is nothing to
save" is arguably the "nothing to act on" reason, but a user looking at
a grey Save button with the tooltip "Save" has no way to tell it from a
failure.

Citation corrected on verification: Title should read: "Save is the only
disabled toolbar action that does not state its reason."

swiftcut/ui_gtk/actions.py:470-471 (verbatim):
    is_unsaved = not self.editor.is_saved
    self.actions["save"].set_enabled(is_unsaved)

swiftcut/ui_gtk/toolbar.py:44-47 (verbatim):
    self.save_button = Gtk.Button(child=get_icon("save-symbolic"))
    self.save_button.set_tooltip_text(_("Save"))
    self.save_button.set_action_name("win.save")
    self.append(self.save_button)

The load-bearing correction is the in-repo precedent the original
finding did not cite. swiftcut/ui_gtk/mainwindow.py:1418-1452 rewrites
the sibling export button's tooltip with an explicit reason for every
disabled cause:
    self.toolbar.export_button.set_tooltip_text(
        _("Select a machine to enable G-code export")
    )
    ...
    export_tooltip = _("Generate G-code")
    if task_mgr.has_tasks():
        export_tooltip = _("Cannot export while other tasks are
running")
    elif self.doc_editor.pipeline.is_data_stale:
        export_tooltip = _("Pipeline needs recalculation before export.
Press F5 to recalculate.")
    elif not doc.has_workpiece():
        export_tooltip = _("Add a workpiece to enable export")
    elif not doc.has_result():
        export_tooltip = _("Add or enable a processing step to enable
export")
    self.toolbar.export_button.set_tooltip_text(export_tooltip)

Same file also rewrites frame_button (1489-1493), send_button
(1507-1514) and hold_button (1528-1531). Save is the sole exception.

Supporting context (not itself a finding):
swiftcut/ui_gtk/mainwindow.py:191-193 sets the header to
`Adw.WindowTitle(title=self.get_title() or "", subtitle=__version__ or
"")` with no dirty marker, so nothing else in the window chrome reports
unsaved state. Dirty state itself is sound —
swiftcut/doceditor/editor.py:603-616 derives `is_saved` from
`history_manager.is_at_checkpoint()`.

Fix: Same shared gate; the reason string ("No unsaved changes") is a
one-line addition once the helper exists. Not worth a bespoke patch on
its own.

**D24 — MINOR — The machine console input goes dead when disconnected with no tooltip, placeholder or message**

swiftcut/ui_gtk/machine/console.py:560-568 `_update_sensitivity` sets
`console_input.set_sensitive(is_connected or is_dummy)` (False outright
when `self._machine` is None). The widget is a bare `Gtk.TextView` built
at console.py:126-139 with no tooltip anywhere in the file for it — the
file's only `set_tooltip_text` is on `verbose_toggle` at :87. A
GtkTextView gives no visual disabled affordance as strong as a button's,
so the panel simply stops accepting typing with nothing said.

Fix: Whatever carries the reason for buttons should carry it here too —
a tooltip on the input's scroll container plus a placeholder line in the
console output. Same gate helper, different renderer.


## H — Dialogs and high-DPI

**H1 — BROKEN — Every entry in the workpiece-row file-type icon map names an icon that does not exist — no bundled SVG, no Adwaita fallback**

swiftcut/ui_gtk/doceditor/workpiece_row.py:11-19 defines _ICON_MAP =
{'.svg':'file-svg-generic-symbolic', '.png':'file-png-generic-symbolic',
'.jpg'/'.jpeg':'file-jpg-generic-symbolic', '.dxf':'file-dxf-generic-
symbolic', '.pdf':'file-pdf-generic-symbolic', '.rd':'file-rd-generic-
symbolic'}. The shipped files are file-svg-symbolic.svg, file-png-
symbolic.svg, file-jpg-symbolic.svg, file-dxf-symbolic.svg, file-pdf-
symbolic.svg, file-rd-symbolic.svg (ls swiftcut/resources/icons/ | grep
'^file-'). None of the six '-generic-' names exists under swiftcut/
(checked: find swiftcut -name '*-symbolic.svg' diffed against every
'-symbolic' string literal in swiftcut/**/*.py), and none exists in the
installed Adwaita theme either (find /c/msys64/mingw64/share/icons -name
'file-png-generic-symbolic*' -> nothing; app.py:249 pins gtk-icon-theme-
name to Adwaita). get_icon() (swiftcut/ui_gtk/icons.py:60-75) therefore
fails the local-file branch, logs 'Icon for ... not found. Falling back
to theme.', and returns Gtk.Image.new_from_icon_name() on a name the
theme also lacks. workpiece_row.py:55-60 _get_icon_name() feeds it;
WorkpieceRow is instantiated for every imported workpiece at
swiftcut/ui_gtk/doceditor/layer_column.py:325. So every workpiece row in
the Layers dock renders the missing-image placeholder instead of its
file-type glyph. AUDIT.md I1 checked only the contents of the icons
directory ('All 203 icons ... end in -symbolic.svg ... This criterion is
clean') and did not check that call sites resolve; this is unfixed and
unreported.

Citation corrected on verification: Three details in the original
evidence are imprecise; the conclusion is unaffected.

1. The Adwaita pin is NOT unconditional. swiftcut/app.py:246-249 reads:
       if os.environ.get("SNAP"):
           settings = Gtk.Settings.get_default()
           if settings:
               settings.set_property("gtk-icon-theme-name", "Adwaita")
   So the pin only applies under Snap. It does not matter here - GTK4's
default theme is Adwaita/hicolor regardless, and neither carries any
'file-*-generic-symbolic' name.

2. "every workpiece row ... renders the missing-image placeholder" is
slightly too broad. workpiece_row.py:55-61 is:
       def _get_icon_name(self) -> str:
           source = self.workpiece.source
           if source and source.source_file:
               suffix = source.source_file.suffix.lower()
               return _ICON_MAP.get(suffix, "image-x-generic-symbolic")
           return "image-x-generic-symbolic"
   The default branch returns "image-x-generic-symbolic", which DOES
resolve (swiftcut/resources/icons/image-x-generic-symbolic.svg exists;
verified is_file()=True). Only rows whose source suffix is one of
.svg/.png/.jpg/.jpeg/.dxf/.pdf/.rd hit a broken name - which, since
those are the importable formats, is every imported workpiece in
practice.

3. Line ranges: get_icon() is swiftcut/ui_gtk/icons.py:46-77 (not
60-75), with the fallback at icons.py:75: logger.debug(f"Icon for
'{icon_name}' not found. Falling back to theme.") followed by
icons.py:77 return Gtk.Image.new_from_icon_name(icon_name).
_get_icon_name() is workpiece_row.py:55-61 (not 55-60). The
instantiation site is correct:
swiftcut/ui_gtk/doceditor/layer_column.py:325 `item_row =
WorkpieceRow(item)` inside _rebuild_workpiece_list().

Fix: Shared fix: the six map values should be the shipped names (drop
the '-generic' infix). The durable fix is a resolution guard rather than
six edits — get_icon() currently degrades silently to a theme name that
is also absent; have it assert/warn at import time against the shipped
set (the same diff this audit ran) so a renamed icon fails loudly
instead of drawing a blank.

**H2 — INCONSISTENT — Layer Settings styles a plain 'Close' dismiss button as suggested-action — a blue primary that commits nothing**

swiftcut/ui_gtk/doceditor/layer_settings_dialog.py:42-45: close_button =
Gtk.Button(label=_('Close')); close_button.add_css_class('suggested-
action'); ... header.pack_end(close_button). The dialog is instant-apply
(PatchedDialogWindow, layer_settings_dialog.py:17) so the button only
dismisses. Every other header-bar dialog reserves suggested-action for
the affirmative commit: edit_recipe_dialog.py:62-68 (Save/Add),
gcode_editor.py:75-78 (Save), maintenance_page.py:257-260 (Save),
import_dialog.py:143-151 (Import), array_dialog.py:139-142 (Apply).
Layer Settings is the only place the blue is spent on a dismiss, so the
one control that reads as 'confirm' is the one that does nothing.

Citation corrected on verification:
swiftcut/ui_gtk/doceditor/layer_settings_dialog.py:42-45 (exact, as
cited) — `close_button = Gtk.Button(label=_("Close"))` /
`close_button.add_css_class("suggested-action")` /
`close_button.connect("clicked", lambda w: self.close())` /
`header.pack_end(close_button)`. Class declaration confirming instant-
apply base: layer_settings_dialog.py:17 `class
LayerSettingsDialog(PatchedDialogWindow):`; base class has no
response/commit plumbing
(swiftcut/ui_gtk/shared/patched_dialog_window.py:15-36). Write-through
handlers with no revert path: layer_settings_dialog.py:176-181, 222-238,
240-254, 256-260, 262-270, 272-279. Comparison lines, corrected to the
exact class-application line:
swiftcut/ui_gtk/doceditor/recipes/edit_recipe_dialog.py:63
(`self.save_btn.add_css_class("suggested-action")`, Save/Add, packed
l.68; plain Cancel at l.58-60);
swiftcut/ui_gtk/machine/gcode_editor.py:76 (Save, packed l.78);
swiftcut/ui_gtk/machine/maintenance_page.py:258 (Save, packed l.260;
plain Cancel at l.253-255);
swiftcut/ui_gtk/doceditor/import_dialog.py:143 and :148 (finding said
143-151; the actual block is 141-150 — `css_classes=["suggested-
action"]` is passed inline in the Gtk.Button constructor at l.143 for
Re-Import and l.148 for Import, connect l.149, pack_end l.150, plain
Cancel l.152-154); swiftcut/ui_gtk/array_dialog.py:140
(`apply_btn.add_css_class("suggested-action")`, _Apply, packed l.142).

Fix: Drop the suggested-action class from the Close button. The shared
rule this needs is a single header-bar helper (used by all eight header-
bar dialogs) that takes an optional primary action and applies
suggested-action only to it, so a dismiss-only dialog physically cannot
be given one.

**H3 — INCONSISTENT — LicenseRequiredDialog puts the styled primary in the middle and an unstyled secondary on the right, and sets neither default nor close response**

swiftcut/ui_gtk/addon_manager/license_dialog.py:154-160, in append
order: add_response('cancel', 'Cancel'); then (if purchase_url)
add_response('buy', 'Buy License') + set_response_appearance('buy',
SUGGESTED); then add_response('enter', 'Enter License Key').
Adw.MessageDialog lays responses out in the order added, so the row
reads Cancel | **Buy License (blue)** | Enter License Key — the
rightmost button is not the primary, breaking 'primary on the RIGHT'. It
is also the only multi-choice dialog in the app that omits both
set_default_response and set_close_response; compare
project_cmd.py:42-51, the other three-response dialog, which orders
Cancel | Don't Save (DESTRUCTIVE) | Save (SUGGESTED) and sets default
'save' + close 'cancel'.

Citation corrected on verification:
swiftcut/ui_gtk/addon_manager/license_dialog.py:154-160 (verbatim):
  154  self.add_response("cancel", _("Cancel"))
  155  if purchase_url:
  156      self.add_response("buy", _("Buy License"))
  157      self.set_response_appearance(
  158          "buy", Adw.ResponseAppearance.SUGGESTED
  159      )
  160  self.add_response("enter", _("Enter License Key"))
The full LicenseRequiredDialog class spans lines 124-190 and contains no
set_default_response and no set_close_response call.

Counter-example line range corrected from 42-51 to
swiftcut/ui_gtk/project_cmd.py:42-52:
  42  dialog.add_response("cancel", _("_Cancel"))
  43  dialog.add_response("discard", _("_Don't Save"))
  44  dialog.add_response("save", _("_Save"))
  45  dialog.set_default_response("save")
  46  dialog.set_close_response("cancel")
  47-49  set_response_appearance("save", SUGGESTED)
  50-52  set_response_appearance("discard", DESTRUCTIVE)
These two are indeed the only three-response dialogs in the tree
(verified across every add_response call site in swiftcut/).

DROP the claim that LicenseRequiredDialog is "the only multi-choice
dialog in the app that omits both set_default_response and
set_close_response" - it is false. Other multi-choice dialogs omitting
both: swiftcut/ui_gtk/addon_manager/addon_dialog.py:267-268;
swiftcut/ui_gtk/addon_manager/addon_list.py:407-408 and 459-460;
swiftcut/ui_gtk/doceditor/recipes/recipe_list.py:209-210; swiftcut/ui_gt
k/doceditor/step_settings/recipe_control_widget.py:292-293;
swiftcut/ui_gtk/machine/maintenance_page.py:106-107, 143-144, 399-400.
(A per-file grep of license_dialog.py appears to show
set_default_response/set_close_response present, but those are at lines
44-45 inside the sibling LicenseEntryDialog, not LicenseRequiredDialog.)

SOFTEN the layout claim: replace "the row reads Cancel | Buy License |
Enter License Key - the rightmost button is not the primary" with
"responses render in the order added, so the SUGGESTED response is not
last; Adw.MessageDialog may stack these three long labels vertically
rather than in a row, so the defect is 'suggested response is not the
final one', not specifically 'not rightmost'."

Restated accurate finding: LicenseRequiredDialog appends its SUGGESTED
response ('buy') before the plain 'enter' response, so the primary is
not the final response, and unlike the codebase's only other three-
response dialog (project_cmd.py:42-52) it wires neither a default nor a
close response.

Fix: Add 'enter' before 'buy' so the suggested response is appended
last, and add set_default_response('buy') +
set_close_response('cancel'). The shared fix is a small builder (e.g.
add_confirm_responses(dialog, cancel_label, primary_id, primary_label,
appearance, extras)) that appends cancel first, extras next and the
primary last, and wires default/close in one place — it would settle
this finding and findings on close-response and default-response below
at the same call sites.

**H4 — INCONSISTENT — The three array dialogs ship an Apply with no Cancel — the only confirming dialogs in the app with no cancel control**

swiftcut/ui_gtk/array_dialog.py:134-142 _build_header() packs exactly
one button: apply_btn = Gtk.Button(label='_Apply');
apply_btn.add_css_class('suggested-action'); header.pack_end(apply_btn).
Nothing is packed to start. All three subclasses inherit it
(GridArrayDialog:279, PointRotationArrayDialog:401,
CircularArrayDialog:451). The dialog is non-modal (array_dialog.py:78
set_modal(False)) and mutates a live canvas preview
(array_dialog.py:81-83, 105). Every sibling header-bar dialog packs an
explicit Cancel to start: import_dialog.py:153-155,
edit_recipe_dialog.py:56-58, gcode_editor.py:55-57,
maintenance_page.py:254-256. Escape does close the window
(patched_dialog_window.py:23-27) but there is no visible cancel
affordance.

Citation corrected on verification:
swiftcut/ui_gtk/array_dialog.py:134-143 - `def _build_header(self,
title: str) -> Adw.HeaderBar:` / `header = Adw.HeaderBar()` / `apply_btn
= Gtk.Button(label=_("_Apply"), use_underline=True)` /
`apply_btn.add_css_class("suggested-action")` /
`apply_btn.connect("clicked", self._on_apply_clicked)` /
`header.pack_end(apply_btn)` - the pack_end is line 142, so the method
spans 134-143, not 134-142. Non-modal is `self.set_modal(False)` at line
77 (not 78); preview attach is lines 81-82 (`self._preview =
OutlineElement()` / `self._surface.root.add(self._preview)`) plus
`self._update_preview()` at 106. Subclass lines 279 / 401 / 451 are
exact and none override _build_header (grep finds a single `def
_build_header` at 134). Sibling paths were given as bare filenames; the
real paths are swiftcut/ui_gtk/doceditor/import_dialog.py:153-155
(`cancel_button = Gtk.Button(label=_("Cancel"))` ...
`header_bar.pack_start(cancel_button)`),
swiftcut/ui_gtk/doceditor/recipes/edit_recipe_dialog.py:56-58,
swiftcut/ui_gtk/machine/gcode_editor.py:55-57, and
swiftcut/ui_gtk/machine/maintenance_page.py:253-255 (not 254-256).
Escape/Ctrl+W closing is
swiftcut/ui_gtk/shared/patched_dialog_window.py:23-28 (`_on_key_pressed`
... `if keyval == Gdk.KEY_Escape or (is_primary_modifier(state) and
keyval == Gdk.KEY_w): self.close()`). One overstatement to correct:
"there is no visible cancel affordance" is too strong - _build_header
never calls set_show_end_title_buttons(False), so the Adw window-close X
is present. The accurate claim is that there is no labeled Cancel
button, unlike every sibling committing dialog. Dismissal is non-
destructive: _on_close_request at array_dialog.py:262-264 calls
_detach_preview(), which only clears the OutlineElement overlay and
disconnects signals (266-273); no document mutation occurs unless
_on_apply_clicked (254-260) runs create_array.

Fix: Pack a Cancel to start in _build_header() — one edit covers all
three dialogs because they share the base. Better: route it through the
shared header-bar helper proposed above so Cancel-left/primary-right is
structural rather than per-author.

**H5 — INCONSISTENT — The 'Update Recipe' confirm says 'permanently overwrite ... cannot be undone' but is styled suggested-action, unlike every other 'cannot be undone' confirm**

swiftcut/ui_gtk/doceditor/step_settings/recipe_control_widget.py:284-
296: heading 'Update Recipe {name}?', body 'This will permanently
overwrite the saved recipe with the current step settings. This action
cannot be undone.', then add_response('cancel'), add_response('update'),
set_response_appearance('update', Adw.ResponseAppearance.SUGGESTED).
Every other dialog whose body carries 'cannot be undone' uses
DESTRUCTIVE: hook_list.py:113-122 (Reset hook),
maintenance_page.py:139-147 (Remove Counter), recipe_list.py:203-213
(Delete recipe), color_presets_page.py:335-343 (Delete color rule). It
also sets neither set_default_response nor set_close_response.

Citation corrected on verification:
swiftcut/ui_gtk/doceditor/step_settings/recipe_control_widget.py:284-298
(cited as 284-296; the dialog block actually runs through .present() at
L298):

    dialog = Adw.MessageDialog(
        transient_for=parent_window,
        heading=_("Update Recipe '{name}'?").format(name=recipe.name),
        body=_(
            "This will permanently overwrite the saved recipe with the "
            "current step settings. This action cannot be undone."
        ),
    )
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("update", _("Update"))
    dialog.set_response_appearance(
        "update", Adw.ResponseAppearance.SUGGESTED
    )

Complete outlier set (finding cited 4 of 6; the two additional ones
below also use DESTRUCTIVE and were missed):
- swiftcut/ui_gtk/machine/hook_list.py:115-123 — DESTRUCTIVE +
set_default_response("cancel")
- swiftcut/ui_gtk/machine/maintenance_page.py:140-147 — DESTRUCTIVE, no
default response
- swiftcut/ui_gtk/doceditor/recipes/recipe_list.py:206-213 —
DESTRUCTIVE, no default response
- swiftcut/ui_gtk/settings/color_presets_page.py:336-343 — DESTRUCTIVE,
no default response
- swiftcut/ui_gtk/doceditor/material_list.py:195-203 — DESTRUCTIVE +
set_default_response("cancel")  [NOT cited by the finding]
- swiftcut/ui_gtk/doceditor/material_library_list.py:200-208 —
DESTRUCTIVE + set_default_response("cancel")  [NOT cited by the finding]

REFINEMENT on the secondary claim: the finding notes this dialog "sets
neither set_default_response nor set_close_response". True, but that
omission is NOT unique — maintenance_page.py, recipe_list.py and
color_presets_page.py also omit set_default_response, and none of the
seven set set_close_response. The genuinely unique, one-of-seven defect
is the SUGGESTED appearance at L294-296. The missing safe default is a
broader 4-of-7 gap, best reported as its own consistency item rather
than folded into this one.

FIX-PREMISE CORRECTION: no shared confirm-dialog builder exists. grep
for a confirm helper across swiftcut/ui_gtk/ returns only the local
closure `def confirm(speed, power)` at
swiftcut/ui_gtk/machine/jog_widget.py:862 (protected, unrelated). All
seven dialogs construct Adw.MessageDialog inline.

Fix: One rule, not one patch: 'destructive-action iff the action is
irreversible', enforced by making the shared confirm-dialog builder take
an `irreversible: bool` that picks the appearance and the safe default
response together. That builder then also settles the missing
default/close response here.

PROTECTED: Reached from swiftcut/ui_gtk/doceditor/step_settings/ — the
step/recipe system. Restyling the response changes no behaviour, but the
change belongs in the shared builder, not in the step settings widget.

**H6 — INCONSISTENT — Four confirm dialogs give their affirmative response no appearance at all — no primary is visible**

No set_response_appearance is called for the affirmative in:
swiftcut/ui_gtk/doceditor/import_handler.py:253-256 (Cancel | Import All
— default and close ARE set, only the styling is missing);
swiftcut/ui_gtk/addon_manager/addon_dialog.py:267-268 (Cancel | Install,
on a dialog carrying an Adw.EntryRow at :265, so Enter also does nothing
because no default response is set);
swiftcut/ui_gtk/addon_manager/addon_list.py:407-408 (Cancel | Enable
All); swiftcut/builtin_addons/rayforge-addon-
sketcher/sketcher/ui_gtk/sketchcanvas.py:266-269 (Cancel | OK). All
comparable dialogs do style theirs — wcs_dialog.py:23,
step_type_selection_dialog.py:80, model_selection_dialog.py:92,
debug_log_dialog.py:65, add_material_dialog.py:28/37, grid_tool.py:81.
'Exactly one primary action, styled suggested-action' fails at four
sites.

Citation corrected on verification: Citation is accurate as written; one
line-range refinement and one addition. Refinement: addon_dialog.py is
better cited as :265-268 rather than :267-268, since the Adw.EntryRow at
:265 and set_extra_child at :266 are what make the missing
set_default_response a real defect. Addition (not a correction):
swiftcut/ui_gtk/addon_manager/addon_list.py:459-463 styles its
affirmative in the same file — `dialog.add_response("delete",
_("Uninstall"))` then `dialog.set_response_appearance("delete",
Adw.ResponseAppearance.DESTRUCTIVE)` — making the unstyled `Enable All`
at :407-408 an intra-file inconsistency.

Fix: The shared confirm-dialog builder above: taking (cancel_label,
primary_label, irreversible) makes appearance non-optional, so a dialog
cannot be constructed without exactly one styled primary.

**H7 — INCONSISTENT — 24 of the 34 cancel-bearing Adw.MessageDialog sites never set a close response, so Escape reports 'close' rather than 'cancel'**

Only 10 sites call set_close_response: sketchcanvas.py:269,
grid_tool.py:85, license_dialog.py:45, debug_log_dialog.py:64,
import_handler.py:256, cut_scale_dialog.py:39, wcs_dialog.py:25,
project_cmd.py:46, general_preferences_page.py:369,
sanity_check_dialog.py:36 (plus missing_features_dialog.py:34, which has
no cancel). The other 24 do not — e.g. add_material_dialog.py:26-40,
material_list.py:198-203,
material_library_list.py:203-208/231-236/284-287,
recipe_list.py:209-213, color_presets_page.py:72-86/339-343,
hook_list.py:118-123, maintenance_page.py:106-108/143-145/399-401,
license_settings_page.py:210-215, step_type_selection_dialog.py:78-81,
model_selection_dialog.py:89-93, material_selector.py:106-107,
recipe_selector_dialog.py:104-105, addon_list.py:407-408/459-461,
addon_dialog.py:267-268, license_dialog.py:154-160,
recipe_control_widget.py:292-296. Escape still closes the window (that
is Adw.MessageDialog's own behaviour), but it emits the default id
'close', which no handler in these files matches, so the cancel branch
never runs and the two halves of the same contract disagree from dialog
to dialog.

Citation corrected on verification: Citations are exact; two wording
corrections to the impact clause, and one to the FIX.

Impact wording: the finding says "no handler in these files matches, so
the cancel branch never runs." In the 24 uncovered files there is no
cancel branch at all to fail to run — the handlers only test the
affirmative id and then destroy unconditionally, e.g.
swiftcut/ui_gtk/doceditor/material_list.py:205-216 `def on_response(d,
response_id): if response_id == "delete": ... d.destroy()`, and
swiftcut/ui_gtk/machine/maintenance_page.py:114-117 `def
_on_reset_response(self, dialog, response): if response == "reset":
self.machine.machine_hours.reset_counter(...)`. The accurate statement
is: Escape emits "close", falls through the affirmative guard, and
produces the same visible result as Cancel — so there is no user-visible
breakage today. The defect is that the same contract is declared at 10
sites and left implicit at 24, and the implicit sites are a trap: adding
an `elif response_id == "cancel":` cleanup branch to any of them would
silently never fire.

Second correction, in the finding's favour: the risky inverse pattern
does exist in the codebase — swiftcut/ui_gtk/mainwindow.py:1706 `if
response == "cancel": return  # Do nothing, window remains open.` and
swiftcut/ui_gtk/project_cmd.py:72/120/211. These are the unsaved-changes
dialog, and they are safe only because that one dialog sets it, at
swiftcut/ui_gtk/project_cmd.py:46 `dialog.set_close_response("cancel")`.
This is the concrete proof that the omission matters wherever a cancel
branch is later added.

FIX correction: "that is the missing shared widget" overstates it. A
shared home already exists but is an empty stub —
swiftcut/ui_gtk/shared/patched_dialog_window.py:40-42 defines `class
PatchedMessageDialog(Adw.MessageDialog):` whose `__init__` only calls
`super().__init__(**kwargs)`, and grep shows zero usages anywhere in
swiftcut/. The fix is to give that existing stub the
`set_close_response("cancel")` default and route the 24 sites through
it, not to invent a new widget.

Fix: Set it once, in the shared confirm-dialog builder, rather than at
24 call sites. Nothing in the token map covers dialog response wiring;
that is the missing shared widget, not a missing token.

PROTECTED: maintenance_page.py and hook_list.py sit under
swiftcut/ui_gtk/machine/. The change is response-id plumbing only and
touches no driver or job-path code.

**H8 — INCONSISTENT — The same add/save dialog shape defaults to the affirmative in four places and to Cancel in two**

Affirmative default: add_material_dialog.py:31
set_default_response('save') and :40 set_default_response('add');
color_presets_page.py:77 set_default_response('save') and :86
set_default_response('add'). Cancel default for the identical shape:
material_library_list.py:231-236 (Cancel | Save,
set_default_response('cancel')) and :284-287 (Cancel | Add,
set_response_appearance('add', SUGGESTED) then
set_default_response('cancel')). In the last case the button is painted
blue as the primary while Enter selects Cancel, so the styling and the
keyboard disagree inside one dialog.

Fix: The shared builder should derive the default response from the
appearance: SUGGESTED primary -> default = primary; DESTRUCTIVE primary
-> default = cancel. That removes the choice from the call site and
settles this finding and the destructive-default split below together.

**H9 — INCONSISTENT — Destructive confirm dialogs split three ways on what Enter does — safe default, no default, or (Cut Scale) the destructive action itself**

Four set the safe default: hook_list.py:123, material_list.py:203,
material_library_list.py:208, license_settings_page.py:215 — all
set_default_response('cancel'). Five set no default at all, so Enter
does nothing: recipe_list.py:209-213, color_presets_page.py:339-343,
addon_list.py:459-461, maintenance_page.py:106-108, :143-145, :399-401.
And sanity_check_dialog.py:33-43 explicitly picks the safe one —
add_response('cancel'); add_response('proceed');
set_default_response('cancel'); then DESTRUCTIVE on 'proceed' when
report.has_errors. Three behaviours for one dialog shape.

Citation corrected on verification: sanity_check_dialog.py:32-44
(finding said 33-43): add_response at 32-33,
set_default_response("cancel") at 35, set_close_response at 36, the
has_errors DESTRUCTIVE/SUGGESTED branch at 37-44. recipe_list.py dialog
is 209-211 with no set_default_response anywhere in the file.

Fix: Same shared builder: appearance decides the default. Nothing here
needs a per-dialog decision.

PROTECTED: sanity_check_dialog.py gates the job send path — cite it as
the correct reference implementation; do not change it.

**H10 — INCONSISTENT — Four call sites reach past the bundled Swift Cut icon set to an Adwaita stock glyph that has a bundled equivalent**

swiftcut/ui_gtk/shared/sanity_check_dialog.py:152-153 returns 'dialog-
error-symbolic' / 'dialog-warning-symbolic';
swiftcut/ui_gtk/settings/color_presets_page.py:200 uses
Gtk.Image.new_from_icon_name('dialog-warning-symbolic');
swiftcut/ui_gtk/shared/model_selection_dialog.py:64 uses get_icon('edit-
clear-symbolic'); swiftcut/ui_gtk/machine/nogo_zones_page.py:58 uses
icon_name='edit-delete-symbolic'. None of those four names exists under
swiftcut/ (verified by diffing every '-symbolic' literal in
swiftcut/**/*.py against find swiftcut -name '*-symbolic.svg'), so
get_icon() falls through to the theme (icons.py:71-75) and draws the
Adwaita glyph. The bundled equivalents are shipped and used elsewhere:
error-symbolic.svg, warning-symbolic.svg (used at
machine/settings_dialog.py:79 for the maturity banner — so the machine-
settings warning and the sanity-check warning are two different glyphs),
clear-symbolic.svg, delete-symbolic.svg. AUDIT.md I1 concluded 'Nothing
mixes an old set with the design set. This criterion is clean' — that
check looked at the directory contents, not at what the call sites
resolve to.

Citation corrected on verification: Citations are right; the mechanism
sentence is wrong. Only ONE of the four sites goes through get_icon(),
not all four:
- C:\Users\Robotics\rayforge\swiftcut\ui_gtk\shared\model_selection_dial
og.py:64 — `get_icon("edit-clear-symbolic")` (the only get_icon() site;
this one does hit the icons.py:71-75 theme fallback as described).
- C:\Users\Robotics\rayforge\swiftcut\ui_gtk\shared\sanity_check_dialog.
py:120 — `icon = Gtk.Image.new_from_icon_name(icon_name)`, where
icon_name comes from `_get_icon_name` at :152-153. Direct GTK call,
never reaches get_icon().
- C:\Users\Robotics\rayforge\swiftcut\ui_gtk\settings\color_presets_page
.py:200 — `Gtk.Image.new_from_icon_name("dialog-warning-symbolic")`.
Direct GTK call.
-
C:\Users\Robotics\rayforge\swiftcut\ui_gtk\machine\nogo_zones_page.py:58
— `Gtk.Button(icon_name="edit-delete-symbolic", ...)`. Direct GTK call.

The load-bearing correction: there is NO `Gtk.IconTheme.add_search_path`
anywhere in swiftcut (grep for add_search_path/IconTheme returns only
icons.py:19 `register_icon_path` and its one addon caller,
laser_essentials/frontend.py:22). The bundled icons are reachable ONLY
through get_icon(), which builds a `Gio.FileIcon` from an absolute path
(icons.py:60-68). Therefore the finding's FIX — "point the four sites at
the bundled names" — would regress three of them: renaming
nogo_zones_page.py:58 to `icon_name="delete-symbolic"` asks the GTK
theme for a name Adwaita does not define, yielding a missing-image
placeholder instead of today's working stock trash glyph. Those three
sites must be converted to `get_icon(...)` (or `set_from_gicon`) as well
as renamed. Likewise, the proposed startup resolution guard inside
get_icon() would catch only model_selection_dialog.py:64 — the other
three bypass it entirely, so the guard as proposed does not close the
drift it is meant to close.

Also worth recording: the intended guard already exists but is hand-
maintained and does not cover these names.
C:\Users\Robotics\rayforge\tests\ui_gtk\test_swift_cut_icons.py states
in its module docstring "What is worth guarding is that every name the
map uses still resolves to a file, so a rename cannot quietly fall back
to the system theme", then asserts `path.is_file()` only over a
hardcoded ALL_ICONS list (JOG + SCALE_AND_ACTION + CORNER + TOOLBAR +
PANEL). None of the four names is in that list, which is exactly why the
drift went unnoticed.

Fix: Point the four sites at the bundled names. The shared fix is the
same resolution guard proposed for the workpiece-row map: get_icon()
should be able to report, at startup, every name it could not resolve
locally — silent theme fallback is what let all of these drift.

PROTECTED: sanity_check_dialog.py is on the job send path; only the
icon-name strings at :152-153 change, not the report logic.

**H11 — INCONSISTENT — get_icon_pixbuf() rasterizes SVGs at a fixed logical pixel size and its three consumers all paint through Cairo at device scale — blurry at 200%**

swiftcut/ui_gtk/icons.py:81-107: @lru_cache def
get_icon_pixbuf(icon_name, size=24) ->
GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True). The
size is a logical pixel count; no display scale is consulted. Three
consumers: (1) swiftcut/ui_gtk/canvas/overlays.py:31-39 caches the
result in a module-level global _move_gizmo_pixbuf at 24px on first call
and never re-rasterizes, then overlays.py:206-216 does
ctx.scale(icon_size/pb_w, ...) with cairo.FILTER_BILINEAR to stretch it
to size*0.65; (2) swiftcut/ui_gtk/shared/piemenu.py:56 self.icon_size =
24 and :255 get_icon_pixbuf(item.icon_name, self.icon_size); (3)
swiftcut/ui_gtk/canvas/cursor.py:72 get_icon_pixbuf(icon_name, size/2) =
16px. All three draw into a Cairo context that GTK4 renders at the
target scale — Canvas.do_snapshot
(swiftcut/ui_gtk/canvas/canvas.py:215-217) uses
snapshot.append_cairo(bounds), so at 200% the surface is 2x while the
pixbuf is still 1x. Root cause: get_scale_factor() is never called
anywhere in the tree (grep for get_scale_factor/set_device_scale across
swiftcut/ returns nothing; the only 'scale_factor' hits are unrelated
geometry fitting in doceditor/file_cmd.py and image/ops_renderer.py).

Citation corrected on verification: Line ranges drift by 1-4 lines;
content is right. Corrections:

- swiftcut/ui_gtk/icons.py:80-106 (not 81-107). L80 `@lru_cache`, L81
`def get_icon_pixbuf(icon_name: str, size: int = 24):` — no return
annotation; L98-100 `pixbuf =
GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), size, size, True)`;
L106 `return None` on failure.

- swiftcut/ui_gtk/canvas/overlays.py:31-39 — exact as cited. Stronger
than the finding states: L206 calls `_get_move_gizmo_pixbuf()` with NO
size argument, so the global is always filled at the 24px default and
the function's `size` parameter is unreachable after the first call.

- swiftcut/ui_gtk/canvas/overlays.py:206-217 (not 206-216); L217 is the
closing `ctx.restore()`. L208 `icon_size = size * 0.65`, L212
`ctx.scale(icon_size / pb_w, icon_size / pb_h)`, L214
`ctx.get_source().set_filter(cairo.FILTER_BILINEAR)`.

- swiftcut/ui_gtk/canvas/canvas.py:216-220 (not 215-217). L216 `def
do_snapshot(self, snapshot):`, L220 `ctx =
snapshot.append_cairo(bounds)`.

- swiftcut/ui_gtk/canvas/cursor.py:67 `size = 32`, L68 `hotspot = 16`,
L72 `pixbuf = get_icon_pixbuf(icon_name, size / 2)` — note this passes
the FLOAT 16.0, which is also a distinct lru_cache key from the int 16
any other caller would use. L115-127 build a fixed 32x32
`cairo.ImageSurface` / `Gdk.MemoryTexture` and L127
`Gdk.Cursor.new_from_texture(texture, hotspot, hotspot)`, so the entire
cursor (not just its icon) is 1x.

- swiftcut/ui_gtk/shared/piemenu.py:56 and :255 — exact as cited.

Fix: One change at the shared seam: give get_icon_pixbuf a `scale`
argument (rasterize at size*scale, keep it in the lru_cache key) and
have the three call sites pass widget.get_scale_factor().
overlays.py:31-39 additionally has to lose the module-level global,
which pins the first rasterization for the process lifetime and cannot
follow a window moved between monitors.

**H12 — INCONSISTENT — All custom cursors are baked as fixed 32/33-pixel textures with no scale factor in the size or the cache key**

swiftcut/ui_gtk/canvas/cursor.py builds three cursor families, each at a
hard-coded pixel size: get_tool_cursor :67-68 size=32, hotspot=16,
surface cairo.ImageSurface(FORMAT_ARGB32, 32, 32) at :152-153 ->
Gdk.MemoryTexture.new(32,32,...) at :186-192 ->
Gdk.Cursor.new_from_texture(texture, hotspot, hotspot) at :196;
get_rotated_cursor :146-147 size=32; get_rotated_arc_cursor :212-213
size=33. The caches are keyed on content only and carry no scale:
_cursor_cache: dict[int, Gdk.Cursor] keyed by rounded angle (:13,
:143-144), _arc_cursor_cache likewise (:14, :208-209),
_tool_cursor_cache keyed by (icon_name, rgba) (:15, :63-65). Nothing
calls get_scale_factor(). At 200% the cursor is handed to the compositor
as a 32-device-pixel image, so it does not track the rest of the UI, and
the cache would return the 1x texture even if the size were computed.

Citation corrected on verification: swiftcut/ui_gtk/canvas/cursor.py —
caches, all content-only keys with no scale component:
  :13  _cursor_cache: dict[int, Gdk.Cursor] = {}
  :14  _arc_cursor_cache: dict[int, Gdk.Cursor] = {}
  :15  _tool_cursor_cache: dict[tuple[str, ColorRGBA], Gdk.Cursor] = {}

get_tool_cursor (def :41):
  :63  cache_key = (icon_name, rgba)          (:64-65 cache hit return)
  :67  size = 32
  :68  hotspot = 16  # Center of the crosshair
  :72  pixbuf = get_icon_pixbuf(icon_name, size / 2)
  :82  surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
  :87  ctx.set_line_width(3)   and  :95 ctx.set_line_width(1)   (fixed
device-pixel strokes)
  :118-124  texture = Gdk.MemoryTexture.new(size, size,
Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, bytes_data,
surface.get_stride())
  :127 cursor = Gdk.Cursor.new_from_texture(texture, hotspot, hotspot)
  :128 _tool_cursor_cache[cache_key] = cursor

get_rotated_cursor (def :132):
  :144 angle_key = round(angle_deg)           (:145-146 cache hit
return)
  :148 size = 32
  :149 hotspot = size // 2
  :152 surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
  :158 ctx.set_line_width(2)   and  :180 ctx.set_line_width(1)
  :186-192 texture = Gdk.MemoryTexture.new(size, size, ...)
  :195 cursor = Gdk.Cursor.new_from_texture(texture, hotspot, hotspot)
  :196 _cursor_cache[angle_key] = cursor

get_rotated_arc_cursor (def :200):
  :211 angle_key = round(angle_deg)           (:212-213 cache hit
return)
  :215 size = 33
  :216 hotspot = size // 2
  :218 surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
  :224 ctx.set_line_width(2)   and  :268 ctx.set_line_width(1);  :227
radius = 14;  :236-237 arrow_length = 5 / arrow_width = 5
  :274-280 texture = Gdk.MemoryTexture.new(size, size, ...)
  :282 cursor = Gdk.Cursor.new_from_texture(texture, hotspot, hotspot)
  :283 _arc_cursor_cache[angle_key] = cursor

Callers (no scale is passed in at either site):
  swiftcut/ui_gtk/canvas/canvas.py:655  cursor = get_cursor_for_region(
  swiftcut/builtin_addons/rayforge-addon-
sketcher/sketcher/ui_gtk/editor.py:153  return
get_tool_cursor(current_tool.CURSOR_ICON, color)

Corroborating absence: grep -rn "get_scale_factor" --include=*.py
swiftcut/ -> no matches; the only "scale_factor" hits are
document/raster geometry (doceditor/file_cmd.py:426,448,823-844,892-916
and image/ops_renderer.py:74-82), unrelated to widget scale.

Fix: Take the scale from the widget at the call site, multiply
size/hotspot and the Cairo line widths by it, and add scale to all three
cache keys. This is one helper (a `_make_cursor(draw_fn, size, scale)`)
rather than three parallel edits, since the three functions already
share the surface -> MemoryTexture -> Cursor tail verbatim.

**H13 — INCONSISTENT — Asset-browser thumbnails are fetched at a fixed 64px and cached until explicitly invalidated, so they upscale at 200%**

swiftcut/ui_gtk/doceditor/asset_browser.py:33 THUMBNAIL_SIZE = 64;
:100-101 self._draw_area.set_content_width(THUMBNAIL_SIZE) /
set_content_height(THUMBNAIL_SIZE) — logical units, so 128 device px at
200%; :137-140 refresh() calls png =
self.asset.get_thumbnail(THUMBNAIL_SIZE) then
Gdk.Texture.new_from_bytes(bytes_data), guarded by `if self._texture is
None`, so it is fetched once and re-fetched only via invalidate() at
:131-132 (which no scale change calls); :154-173 _draw_thumbnail
computes scale = min(width/tex_w, height/tex_h) and appends the texture
into the widget's Cairo context, which GTK has already scaled.
get_thumbnail takes a size argument at every implementation
(swiftcut/core/asset.py:60,124, source_asset.py:116,
stock_asset.py:179), so a larger render is available and simply is not
requested.

Citation corrected on verification:
swiftcut/ui_gtk/doceditor/asset_browser.py:132-133 is `def
invalidate(self): self._texture = None` (finding said 131-132);
refresh() is 135-140 (finding said 137-140); _draw_thumbnail is 155-175
(finding said 154-173), with `scale = min(width / tex_w, height /
tex_h)` at 161.

Fix: Request THUMBNAIL_SIZE * self.get_scale_factor() in refresh() and
invalidate the texture on notify::scale-factor. The API already supports
it; only the call site assumes 1x.

**H14 — MINOR — Cut Scale is the only dialog in the app whose Enter-default fires a destructive action, directly contradicting the sanity-check sheet it sits beside in the send flow**

swiftcut/ui_gtk/machine/cut_scale_dialog.py:35-39:
add_response('cancel'); add_response('cut');
set_response_appearance('cut', Adw.ResponseAppearance.DESTRUCTIVE);
set_default_response('cut'); set_close_response('cancel'). The body at
:26-29 reads 'Cuts a rectangle around the job's bounding box from the
head's current corner. The laser fires.' Order, appearance, title and
Escape are all correct; the outlier is that Enter commits the
destructive response. Every other DESTRUCTIVE-primary dialog either
defaults to cancel (hook_list.py:123, material_list.py:203,
material_library_list.py:208, license_settings_page.py:215,
sanity_check_dialog.py:35) or sets no default (recipe_list.py:209-213,
color_presets_page.py:339-343, addon_list.py:459-461,
maintenance_page.py x3). sanity_check_dialog.py:33-43 is the closest
sibling — same laser-firing family, opposite choice.

Fix: Reported, not proposed. If the general rule (DESTRUCTIVE primary ->
default = cancel) is adopted in the shared builder, Cut Scale must be an
explicit, commented opt-out rather than an accident — the point of this
finding is that today nothing records which it is.

PROTECTED: PROTECTED: the Cut Scale sheet
(swiftcut/ui_gtk/machine/cut_scale_dialog.py) is named protected, and
the response ids feed the laser-firing callback at :62-67. Do not change
the default response without an explicit decision; this entry is an
inventory item only.

**H15 — MINOR — The About dialog is the only PatchedDialogWindow that never sets a window title**

swiftcut/ui_gtk/about.py:188-198 AboutDialog.__init__ calls
set_default_size and set_hide_on_close only; _build_ui at :432-438 sets
three Adw.WindowTitle widgets into the header bar via set_title_widget
(:425-429) but self.set_title() is never called anywhere in the file
(the other set_title calls at :363 and :404 are on
Adw.PreferencesGroup). Adw.WindowTitle paints the header; it does not
set the window's title property, which is what the taskbar and Alt-Tab
read. Every sibling dialog does set it: array_dialog.py:75,
import_dialog.py:106, edit_recipe_dialog.py:42,
stock_properties_dialog.py:45, layer_settings_dialog.py:32,
gcode_editor.py:46, image_metadata_dialog.py:20, addon_dialog.py:29,
step_settings/dialog.py:37, machine/settings_dialog.py:50/56,
settings/settings_dialog.py:44, maintenance_page.py:232.

Citation corrected on verification: Core citation is accurate; two
secondary details in the sibling list need correction.

Verified core:
- swiftcut/ui_gtk/about.py:188 "class AboutDialog(PatchedDialogWindow):"
- swiftcut/ui_gtk/about.py:194-199 "def __init__(self, **kwargs): /
super().__init__(modal=True, **kwargs) / self.set_default_size(500, 700)
/ self.set_hide_on_close(True) / self._build_ui()"
- swiftcut/ui_gtk/about.py:433-437 "self.main_title =
Adw.WindowTitle(title=_('About
{app_name}').format(app_name=const.APP_NAME))", ":436 self.sysinfo_title
= Adw.WindowTitle(...)", ":437 self.supporters_title =
Adw.WindowTitle(...)" (the finding wrote :432-438; the actual span is
433-437)
- swiftcut/ui_gtk/about.py:425/427/429
"self.header_bar.set_title_widget(...)"
- swiftcut/ui_gtk/shared/patched_dialog_window.py:15-21
PatchedDialogWindow(Adw.Window).__init__ passes **kwargs straight
through and adds only a key controller — no title default
- swiftcut/ui_gtk/mainwindow.py:2080 "dialog =
AboutDialog(transient_for=self)" — no title kwarg supplied at the call
site

Corrections to the sibling list:
1. Two of the cited siblings set the title via the constructor kwarg,
not a set_title call. swiftcut/ui_gtk/machine/maintenance_page.py:232 is
"super().__init__(" and the title lives one line lower at :233
"title=_('Edit Counter'),". The finding's phrasing "Every sibling dialog
does set it: ... maintenance_page.py:232" is therefore off by one line
and mischaracterises the mechanism.
2. The finding's list omits a 14th subclass that also sets a title by
kwarg: swiftcut/builtin_addons/rayforge-addon-print-and-
cut/print_and_cut/wizard.py:53 "class
PrintAndCutWizard(PatchedDialogWindow):" with :63-67
"super().__init__(transient_for=parent, default_width=1150,
default_height=780, title=_('Print & Cut'),". Including it strengthens
rather than weakens the claim: 13 of 14 subclasses set a window title,
AboutDialog is the sole exception.

All other cited sibling lines were checked verbatim and are correct:
array_dialog.py:75 "self.set_title(title)",
doceditor/import_dialog.py:106 "self.set_title(_('Import Image'))",
doceditor/recipes/edit_recipe_dialog.py:42 "self.set_title(title)",
doceditor/stock_properties_dialog.py:45 "self.set_title(_('Stock
Properties'))", doceditor/layer_settings_dialog.py:32
"self.set_title(_('{name} - Settings').format(name=layer.name))",
machine/gcode_editor.py:46 "self.set_title(_('Edit Macro'))",
doceditor/image_metadata_dialog.py:20 "self.set_title(_('Image
Metadata'))", addon_manager/addon_dialog.py:29 "self.set_title(_('Addon
Registry'))", doceditor/step_settings/dialog.py:37
"self.set_title(_('{name} Settings').format(name=step.name))",
machine/settings_dialog.py:50 "self.set_title(" and :56
"self.set_title(_('Machine Settings'))", settings/settings_dialog.py:44
"self.set_title(_('Settings'))".

Fix: Add self.set_title(_('About {app_name}')) alongside the
WindowTitle. The shared version: have the header-bar helper set both the
window title and the title widget from one string, so they cannot
diverge.

**H16 — MINOR — The step-type sheet falls back to 'step-symbolic', which does not exist; the workflow row uses a different, working fallback for the same case**

swiftcut/ui_gtk/doceditor/step_type_selection_dialog.py:97: icon =
get_icon(cls.ICON or 'step-symbolic'). swiftcut/core/step.py:72 declares
ICON: str = '' as the base default, so the fallback is reachable. 'step-
symbolic' is not among the 206 files in swiftcut/resources/icons/ (the
shipped name is step-settings-symbolic.svg) and is not in the installed
Adwaita theme (find /c/msys64/mingw64/share/icons -name 'step-symbolic*'
-> nothing). The same 'step with no ICON' case is handled at
swiftcut/ui_gtk/doceditor/workflow_row.py:49,164 with _FALLBACK_ICON =
'laser-path-symbolic', which does exist. Today every registered concrete
step sets ICON (contour_step.py:41, frame_step.py:36,
material_test.py:32, raster_step.py:52, shrinkwrap_step.py:44,
wavefront_step.py:30), so this only fires for a third-party addon step —
latent, not currently visible.

Citation corrected on verification: Citation accurate as written;
verified line-by-line. Additional corroboration found (not a
correction): a THIRD fallback for the same "step class has no ICON" case
exists at swiftcut/core/recipe.py:293 -- `return step_class.ICON or
"recipe-symbolic"` -- and `recipe-symbolic.svg` IS present in
swiftcut/resources/icons/. So the tree has three fallbacks for this case
(workflow_row.py:49 'laser-path-symbolic', recipe.py:293 'recipe-
symbolic', step_type_selection_dialog.py:97 'step-symbolic') and only
the dialog's names a nonexistent icon. Also worth recording for the fix:
get_icon (swiftcut/ui_gtk/icons.py:46-76) degrades silently --
get_icon_path returns a non-existent path, `path.is_file()` is False,
and it falls through to `Gtk.Image.new_from_icon_name(icon_name)`, so
the symptom is a missing-image glyph, not an exception. And
material_test.py sets HIDDEN = True (line 35), so the dialog's `not
cls.HIDDEN` filter excludes it regardless.

Fix: One fallback constant for 'step with no icon', shared by both call
sites — workflow_row.py:49 already has it, so the sheet should import it
rather than invent a second name.

PROTECTED: Touches the step-type sheet and the step system. The change
is a fallback string only; it does not alter step registration or the
layer/step model.

**H17 — MINOR — The Windows splash is baked at one 480x320 size from the SVG with no high-DPI variant**

SwiftCut.spec:18-19 splash = Splash('swiftcut_splash.png', ...) and
:31,:51 wire it into the EXE. The image is generated by
scripts/win/win_create_splash.py:33 WIDTH, HEIGHT = 480, 320 with
GLYPH_SIZE = 150 and a 40pt font (:113-119); it renders the vector
source (:29 org.ilab.SwiftCut.svg, :47-67 render_glyph via Rsvg) but
emits a single 1x PNG at :178 out.save(splash_path, format='PNG').
Nothing consults a display scale, and PyInstaller's Tk splash draws the
bitmap at its pixel size. Notably, the sibling generator gets this
right: scripts/win/win_create_icon.py:23 SIZES = [256,128,64,48,32,16]
renders the same SVG natively at every size ('rather than downscaling a
single raster, so the mark stays crisp at 16 and 32 px', :3-4) — the
splash script simply did not adopt the same approach.

Citation corrected on verification: Corrected citations (the finding's
line numbers are off; one points past EOF):

- C:\Users\Robotics\rayforge\SwiftCut.spec:18-19 — CORRECT as cited:
    splash = Splash(
        'swiftcut_splash.png',
  and :31 `splash,` inside EXE(...), :51 `splash.binaries,` inside
COLLECT(...) — both CORRECT.

- C:\Users\Robotics\rayforge\scripts\win\win_create_splash.py:32
(finding said :33) —
    WIDTH, HEIGHT = 480, 320
  (:33 is `RADIUS = 20`; :34 is `GLYPH_SIZE = 150`.)

- win_create_splash.py:29 — `source_path = here /
"swiftcut/resources/icons/org.ilab.SwiftCut.svg"` — CORRECT.

- win_create_splash.py:46-65 (finding said :47-67) — `def
render_glyph(size):` … Rsvg.Handle.new_from_data / cairo.ImageSurface /
handle.render_document.

- win_create_splash.py:113-119 — the 40pt font block — CORRECT as cited
(ImageFont.truetype("segoeuisb.ttf", 40) at :114, "segoeuib.ttf", 40 at
:117).

- win_create_splash.py:154 (finding said :178 — the file is only 155
lines, so :178 does not exist) —
    out.save(splash_path, format="PNG")
  This is the single, sole raster emitted; it is the substantive claim
and it is accurate at :154.

- C:\Users\Robotics\rayforge\scripts\win\win_create_icon.py:22 (finding
said :23) —
    SIZES = [256, 128, 64, 48, 32, 16]
  and :3-4 docstring — CORRECT as quoted: "Renders the vector source
natively at every icon size, rather than / downscaling a single raster,
so the mark stays crisp at 16 and 32 px."

Additional corroboration the finding did not cite:
- `grep -n -i "dpi|scale|scaling|hidpi|2x"` over win_create_splash.py,
SwiftCut.spec and scripts/win/win_build.sh returns ZERO hits — "nothing
consults a display scale" is confirmed, not asserted.
- C:\Users\Robotics\rayforge\scripts\win\win_build.sh:69 is a SECOND
wiring path the finding missed: `--splash "swiftcut_splash.png" \` on
the pyinstaller command line (:34 runs win_create_splash.py first). So
the single 1x PNG feeds both the .spec and the shell build.
- The shipped artifact confirms it: swiftcut_splash.png is exactly (480,
320) RGBA, dpi=None.
- The "Tk draws the bitmap at its pixel size" claim is provable in-repo,
which the finding did not know:
C:\Users\Robotics\rayforge\build\SwiftCut\Splash-00_script.tcl:35-59
sets `set image_width [image width splash_image]` / `image_height`,
sizes the canvas `-width $image_width -height $image_height`, and does
`create image [expr {$image_width / 2}] ... -image splash_image`. There
is no `zoom`, `subsample`, or `tk scaling` call anywhere in the script —
it is a strict 1:1 blit.

Caveat on the proposed FIX (do not adopt as written): because that Tcl
blits 1:1 and never downscales, "render at 2x (960x640) and let the
bootloader scale down" would simply produce a 960x640 splash window on a
1x display. A correct fix must either pick the size at build time or
emit at the target scale — not rely on bootloader downscaling that does
not exist.

Fix: Render the splash at 2x (960x640) and let the bootloader scale
down, or emit both and pick by scale at build time. Packaging-only;
nothing in the running UI is affected. Lowest-value item in this lens —
listed for completeness because the brief asked for the splash
specifically.

**H18 — MINOR — PatchedMessageDialog is a dead no-op subclass with zero references**

swiftcut/ui_gtk/shared/patched_dialog_window.py:40-42 defines class
PatchedMessageDialog(Adw.MessageDialog) whose entire body is `def
__init__(self, **kwargs): super().__init__(**kwargs)`. grep for
PatchedMessageDialog across swiftcut/ and tests/ returns only that
definition — every message dialog in the app instantiates
Adw.MessageDialog directly (34 sites). The module docstring at :5-12
documents only PatchedDialogWindow and its Adw focus fix. docs/removal-
inventory-2026-09-04.md:66 records the verdict for this file:
'TrackedPreferencesPage / PatchedDialogWindow classes | KEEP, gut
tracking only | ~24 preference pages and ~23 dialogs inherit them; the
Adw focus fix is load-bearing and unrelated to telemetry.' It names
PatchedDialogWindow as the keep and does not mention
PatchedMessageDialog, which inherits nothing and is inherited by
nothing.

Citation corrected on verification:
swiftcut/ui_gtk/shared/patched_dialog_window.py:40-42 (file is 42 lines
total): `class PatchedMessageDialog(Adw.MessageDialog):` / `    def
__init__(self, **kwargs):` / `        super().__init__(**kwargs)`.
Module docstring :5-12 documents only PatchedDialogWindow ("A
replacement for Adw.Window that fixes wrong window being focused when a
dialog is closed on windows", citing bugzilla 112404 and gtk#7313).
CORRECTION to the count: the finding says "34 sites" instantiate
Adw.MessageDialog directly; the actual figures over swiftcut/ + tests/
are 29 matches for `Adw.MessageDialog(` (direct instantiation) and 14
for `(Adw.MessageDialog)` (direct subclass declaration), 54 textual
occurrences of `Adw.MessageDialog` overall. The substantive claim is
unchanged: none of those 43 direct-use sites routes through
PatchedMessageDialog. Zero-reference claim re-verified with an
unrestricted `grep -rn "PatchedMessageDialog\|patched-message-
dialog\|patchedmessagedialog" swiftcut/ tests/`, which returns only
patched_dialog_window.py:40 and the matching
__pycache__/patched_dialog_window.cpython-314.pyc. All 14 importers of
the module (about.py:15, array_dialog.py:34,
addon_manager/addon_dialog.py:13, doceditor/{image_metadata_dialog.py:8,
import_dialog.py:28, layer_settings_dialog.py:10,
recipes/edit_recipe_dialog.py:14, step_settings/dialog.py:19,
stock_properties_dialog.py:10}, machine/{gcode_editor.py:9,
maintenance_page.py:12, settings_dialog.py:14},
settings/settings_dialog.py:8, print_and_cut/wizard.py:15-17) import
PatchedDialogWindow only. docs/removal-inventory-2026-09-04.md:66
verdict quoted verbatim in the reason field; line number 66 confirmed
correct.

Fix: Delete the class. Flagged, not removed — per the surgical-changes
rule this is a pre-existing orphan, so it is reported for a decision
rather than deleted here.

**H19 — MINOR — Two dialogs add a second Escape key controller that duplicates the one their base class already installs**

swiftcut/ui_gtk/shared/patched_dialog_window.py:18-28 installs a
Gtk.EventControllerKey on every PatchedDialogWindow and closes on
Gdk.KEY_Escape (and Ctrl+W). swiftcut/ui_gtk/machine/gcode_editor.py:15
subclasses PatchedDialogWindow yet adds its own at :121-124 with a
handler at :247-251 that does exactly self.close() on Escape;
swiftcut/ui_gtk/doceditor/image_metadata_dialog.py:13 does the same at
:61-64 and :257-262. Two controllers now race for the same key on the
same window. No other PatchedDialogWindow subclass adds one
(array_dialog.py, import_dialog.py, edit_recipe_dialog.py,
stock_properties_dialog.py, layer_settings_dialog.py, addon_dialog.py,
about.py, settings dialogs, step_settings/dialog.py,
maintenance_page.py:223 all rely on the base).

Citation corrected on verification: Both handler citations are off by
one on their start line; the substance is otherwise exact. Corrected:
swiftcut/ui_gtk/machine/gcode_editor.py:246-251 (not 247-251) - line 246
is `def _on_key_pressed(self, controller, keyval, keycode, state):`, 247
the docstring `"""Handler for key press events on the window."""`, 248
`if keyval == Gdk.KEY_Escape:`, 249 `self.close()`, 250 `return True  #
Event handled, stop propagation`, 251 `return False`.
swiftcut/ui_gtk/doceditor/image_metadata_dialog.py:258-262 (not 257-262)
- line 258 is `def _on_key_pressed(self, controller, keyval, keycode,
state):`, 259 the docstring `"""Handle key press events, closing the
dialog on Escape."""`, 260 `if keyval == Gdk.KEY_Escape:`, 261
`self.close()`, 262 `return True`. The duplicate-controller install
sites cited are exact: gcode_editor.py:122-124 and
image_metadata_dialog.py:62-64. The base class citation is exact as a
range but worth tightening: patched_dialog_window.py:19-21 is the
controller install inside __init__ and :23-29 is _on_key_pressed, which
handles `Gdk.KEY_Escape or (is_primary_modifier(state) and keyval ==
Gdk.KEY_w)` - the finding's ":18-28" spans both correctly.

Fix: Delete both local controllers and their handlers; the base already
provides the behaviour and provides Ctrl+W besides. Behaviour-
preserving.


## G — Token gaps and token conformance

**G1 — BROKEN — The laser-live spark indicator loses its glyph colour and border to a more specific toolbar rule in the same stylesheet**

swiftcut/ui_gtk/theme.py:292-298 defines `.sc-laser-live:checked {
background-image: linear-gradient(...); border-color: @sc_spark_bottom;
color: #1D1D1F; }` — specificity (0,2,0). theme.py:193-198 defines `.sc-
toolbar > togglebutton:checked { background-color: @sc_accent_soft;
color: @sc_accent_text; border-color: transparent; }` — specificity
(0,2,1). The toolbar's laser button is a Gtk.ToggleButton appended
directly to the `.sc-toolbar` box (toolbar.py:175-177:
`self.focus_button = Gtk.ToggleButton()` then `add_css_class("sc-laser-
live")`), so both rules match it and the higher-specificity one wins on
`color` and `border-color` regardless of source order. The gradient
still paints (different property), but the glyph renders @sc_accent_text
and the border transparent instead of the near-black ink and spark
border the rule asks for — on the one widget swift-cut-tokens.md §1.1
reserves the spark palette for ("`spark` … is used on exactly one
widget: the laser-live indicator"). The same widget in the dock
(laser_control_widget.py:41-44) is not under `.sc-toolbar` and does
render correctly, so the two laser-live indicators in the app disagree.

Fix: Raise the spark rule above the generic toggle rule by scoping it
the same way: change theme.py:292 to `.sc-toolbar > togglebutton.sc-
laser-live:checked, .sc-laser-live:checked` so the toolbar arm is
(0,3,1) and beats (0,2,1), keeping the unscoped arm for the dock
instance. Do not reorder _RULES — order will not fix a specificity loss.

PROTECTED: theme.py — Swift Cut theme, PROTECTED. The laser-live toggle
sits on the machine control path, but this is a colour rule only.

**G2 — INCONSISTENT — Three tokens from swift-cut-tokens.md §1.2 are never defined in theme.py: sc_fg_faint, sc_accent_ghost, sc_layer_magenta**

docs/design/swift-cut-tokens.md §1.2 lists 23 surface tokens including
`sc_fg_faint` (light rgba(60,60,67,0.5) / dark rgba(235,235,245,0.5)),
`sc_accent_ghost` (rgba(47,123,255,0.12) both themes) and
`sc_layer_magenta` (#D63AD6 both themes). swiftcut/ui_gtk/theme.py:25-43
(_LIGHT_TOKENS), :47-65 (_DARK_TOKENS) and :71-118 (_SHARED_TOKENS)
define every other row of that table and none of these three. `grep -rn
"sc_fg_faint\|sc_accent_ghost\|sc_layer_magenta" --include=*.py
swiftcut/` returns zero hits repo-wide. Any widget written against the
documented map would silently resolve to nothing.

Citation corrected on verification: swiftcut/ui_gtk/theme.py block
boundaries: _LIGHT_TOKENS :25-43, _DARK_TOKENS :47-65, _SHARED_TOKENS
:71-118 — none contains sc_fg_faint, sc_accent_ghost or
sc_layer_magenta. docs/design/swift-cut-tokens.md:57, :61, :66 carry the
three documented rows; :31 marks layer-magenta 'unchanged, kept as-is'.
swiftcut/machine/models/laser.py:40 — `self.cut_color: str = "#ff00ff"
# Magenta for cut` is the only magenta actually in code.

Fix: Add the three missing `@define-color` rows to
_LIGHT_TOKENS/_DARK_TOKENS/_SHARED_TOKENS exactly as §1.2 states them:
`sc_fg_faint` rgba(60,60,67,0.5) / rgba(235,235,245,0.5) in the per-
theme blocks, `sc_accent_ghost` rgba(47,123,255,0.12) and
`sc_layer_magenta` #D63AD6 in _SHARED_TOKENS beside
sc_accent/sc_danger/sc_ok.

PROTECTED: theme.py is the Swift Cut theme, listed PROTECTED in
docs/removal-inventory-2026-09-04.md. Adding a token definition is
additive and changes no existing rule, but the file is protected.

**G3 — INCONSISTENT — The 8px "inner card, wcs group" radius from the token map is implemented nowhere in theme.py**

docs/design/swift-cut-tokens.md §1.4 and docs/design/swift-cut-layout.md
§4 both list six radii; the 8px row is "Inner card, wcs group".
swiftcut/ui_gtk/theme.py implements 7px (:147), 6px (:155), 10px
(_LAYOUT :349-352), 9px (:354-356) and 5px (:358-360). There is no 8px
rule in the file. The only 8px radii in the tree are hand-rolled outside
the theme: swiftcut/ui_gtk/doceditor/layer_column.py:35 and :46, and
swiftcut/ui_gtk/doceditor/asset_browser.py:56 — none of which is an
"inner card" or the wcs group. The wcs group
(swiftcut/ui_gtk/doceditor/bottom_panel.py:305-307) is an
Adw.PreferencesGroup and therefore picks up the 10px `list.boxed-list`
rule, not the 8px the map assigns it.

Citation corrected on verification:
swiftcut/ui_gtk/doceditor/layer_column.py:35 `border-radius: 8px;` and
:46 `border-radius: 8px 8px 0 0;`;
swiftcut/ui_gtk/doceditor/asset_browser.py:56 `border-radius: 8px;`;
swiftcut/ui_gtk/doceditor/bottom_panel.py:305-307 `self.wcs_group =
Adw.PreferencesGroup()` / `add_css_class("compact")` /
`add_css_class("sc-panel")`.

Fix: Add the missing radius rule to theme.py's _LAYOUT beside the other
three (`.sc-panel list.boxed-list, .card .card { border-radius: 8px;
}`), then point layer_column.py:35,46 and asset_browser.py:56 at it by
class instead of restating 8px.

PROTECTED: theme.py — Swift Cut theme, PROTECTED. bottom_panel.py's wcs
group is the dock jog/WCS panel; changing its radius is presentational
only but sits next to jog panel behaviour.

**G4 — INCONSISTENT — layout.py defines CONTROL_SIZE, ROW_MIN_HEIGHT, ROW_MIN_HEIGHT_COMPACT, ICON_GLYPH and UNKNOWN as public tokens; four of the five have zero callers repo-wide**

swiftcut/ui_gtk/layout.py:44 CONTROL_SIZE=32, :51 ICON_GLYPH=16, :57
ROW_MIN_HEIGHT=48, :60 ROW_MIN_HEIGHT_COMPACT=40, :70 UNKNOWN="—".
Grepping every .py in the repo excluding layout.py itself returns 0
references for CONTROL_SIZE, ROW_MIN_HEIGHT, ROW_MIN_HEIGHT_COMPACT,
ICON_GLYPH and UNKNOWN (UNKNOWN is used only inside layout.py's own
format_position at :136). By contrast SPACE_TIGHT has 51 references,
PANEL_MAX_WIDTH 3 and JOG_CELL 3. The 32/40/16 values do reach the app,
but only as CSS literals restated inside theme.py (_LAYOUT :320-322
`min-width/min-height: 32px`, :338 `-gtk-icon-size: 16px`, :343 `min-
height: 40px`), so the Python constants and the CSS numbers can drift
apart with nothing catching it. ROW_MIN_HEIGHT (48, "Dialog and page
rows" per layout doc §3) reaches the app in neither form — there is no
48px rule in theme.py at all.

Citation corrected on verification: SPACE_TIGHT is 47 references under
swiftcut/ (not 51); everything else as cited. swiftcut/ui_gtk/theme.py
has no `48px` anywhere, confirming ROW_MIN_HEIGHT (layout.py:57) has no
implementation in either language.

Fix: Either interpolate the constants into the CSS (build _LAYOUT with
an f-string from layout.CONTROL_SIZE / ICON_GLYPH /
ROW_MIN_HEIGHT_COMPACT so there is one number per role), or drop the
unreferenced constants from layout.py so the CSS is the single home. Add
the missing `row { min-height: 48px }` rule for ROW_MIN_HEIGHT, which is
currently a documented row contract with no implementation anywhere.

PROTECTED: swiftcut/ui_gtk/layout.py and theme.py — Swift Cut theme +
layout tokens, PROTECTED.

**G5 — INCONSISTENT — Pass-1 T2 is only half fixed: .sc-title now exists in theme.py but no widget wears it, and the two widgets that should still use title-4 / caption-heading**

Pass-1 AUDIT.md T2 says "`theme.py` has no `.sc-title` rule and no
widget adds the class". Half of that is now fixed —
swiftcut/ui_gtk/theme.py:365-367 defines `.sc-title { font-weight: 600;
}`. The other half is not: `grep -rho 'add_css_class("sc-[a-z-]*")'
--include=*.py swiftcut/` lists fourteen sc- classes and `sc-title` is
not among them. theme.py's own comment at :363-364 says "dim-label,
caption, title-4 and caption-heading all collapse into these", yet
swiftcut/ui_gtk/machine/gcode_editor.py:167 still calls
`var_title.add_css_class("title-4")` and
swiftcut/ui_gtk/shared/sanity_check_dialog.py:108 still calls
`label.add_css_class("caption-heading")`. Those two are the last legacy
type classes in the tree (`caption`, `title-1..3`, `heading` are all at
zero uses), so the "Title (semibold)" role of swift-cut-tokens.md §1.5
still does not render anywhere in the app.

Citation corrected on verification: Fifteen sc- classes are added by
widgets, not fourteen; sc-title is absent from all of them.
swiftcut/ui_gtk/machine/gcode_editor.py:167
`var_title.add_css_class("title-4")`;
swiftcut/ui_gtk/shared/sanity_check_dialog.py:108
`label.add_css_class("caption-heading")`.

Fix: Replace `title-4` at gcode_editor.py:167 and `caption-heading` at
sanity_check_dialog.py:108 with `sc-title`. Also give the rule its
documented size — layout doc §5.1 and tokens §1.5 both say the title
role is "13px, weight 600" and theme.py:365-367 sets only the weight, so
add `font-size: 13px;` so the class is self-contained wherever it lands.

PROTECTED: theme.py — Swift Cut theme, PROTECTED.

**G6 — INCONSISTENT — Four theme selectors match no widget: .numeric, .sc-jog .numeric, .sc-jog togglebutton:checked and .sc-toolbar > button.suggested-action**

swiftcut/ui_gtk/theme.py:240-244 styles `.sc-jog .numeric, .numeric,
.sc-numeric` — but `grep -rno '"numeric"' --include=*.py swiftcut/`
returns 0; only `sc-numeric` is ever added (jog_widget.py:213), so two
of those three selectors are dead. theme.py:193-198 styles `.sc-jog
togglebutton:checked` — `grep -n "ToggleButton"
swiftcut/ui_gtk/machine/jog_widget.py` returns nothing, so the jog grid
contains no toggle at all. theme.py:200-205 styles `.sc-toolbar >
button.suggested-action` — `grep -n "suggested-action"
swiftcut/ui_gtk/toolbar.py` returns nothing, so the toolbar's Send
button (toolbar.py:146-148) never gets the class; only the jog arm of
that rule matches (jog_widget.py:226). swift-cut-tokens.md §2.4 requires
"Toolbar send (**primary**) | `send` | `-b` | `-b`", i.e. the deck's
single primary action, and it is unmarked. This is the same shape as
pass-1 X1/X2 (both of which ARE now fixed — splitbutton.py:43 and
undo_button.py:31 add `sc-split`, dock_area.py:73 adds `sc-rail`).

Citation corrected on verification: The send button is
swiftcut/ui_gtk/toolbar.py:146-149 (`self.send_button =
Gtk.Button(child=get_icon("send-symbolic"))` …
`self.append(self.send_button)`), not 146-148; it carries no css class
at all. Toolbar is a Gtk.Box carrying `sc-toolbar` at toolbar.py:36, so
`.sc-toolbar > button.suggested-action` would match it if the class were
added.

Fix: Add `self.send_button.add_css_class("suggested-action")` at
toolbar.py:146-148 so the documented primary action wears the rule that
already exists for it. Delete the `.numeric` and `.sc-jog .numeric` arms
at theme.py:240-241 and the `.sc-jog togglebutton:checked` arm at
theme.py:194, and update swift-cut-tokens.md §1.5, which still names
`.numeric` and `.caption` as "(existing)" classes that no longer exist
in the app.

PROTECTED: theme.py — Swift Cut theme, PROTECTED. toolbar.py's send
button is the Start/send path; adding a style class changes no handler,
but the widget is on the protected job path.

**G7 — INCONSISTENT — .sc-panel is worn by exactly one widget, so the dock's other settings group gets none of the compact density contract**

`grep -rn 'add_css_class("sc-panel")' --include=*.py swiftcut/` returns
a single hit: swiftcut/ui_gtk/doceditor/bottom_panel.py:307 on the WCS
group. theme.py attaches three rules to that class — `.sc-panel { font-
size: 11.5px }` (:231-233), `.sc-panel row { min-height: 40px }`
(_LAYOUT :342-344) and `.sc-panel togglebutton:checked { background-
color: @sc_accent; color: #FFFFFF }` (:248-251). The Laser panel in the
same dock builds its own Adw.PreferencesGroup at
swiftcut/ui_gtk/machine/laser_control_widget.py:34-35 and adds only
`compact`, never `sc-panel`, so it renders at 13px with libadwaita's row
height while the WCS group beside it renders at 11.5px / 40px.
docs/design/swift-cut-layout.md §6.2 defines `.sc-panel` as "a settings
group in a dock panel", which describes both.

Fix: Add `self._group.add_css_class("sc-panel")` at
laser_control_widget.py:35 beside the existing `compact`, so both dock
groups carry the one density class the layout doc names.

PROTECTED: laser_control_widget.py drives Min/Max power and laser fire;
this is a style-class addition only and touches no handler, but the
widget is on the protected power path.

**G8 — INCONSISTENT — popover_menu.py declares font-family: 'Roboto', which swift-cut-tokens.md §1.5 and §3.3 forbid outright**

swiftcut/ui_gtk/shared/popover_menu.py:10-16: `.popover-menu-label {
font-family: 'Roboto', sans-serif; font-size: 14px; margin: 12px; }`.
docs/design/swift-cut-tokens.md §1.5 states "System font at system
sizes. **No bundled font, no `font-family` declaration at all** — GTK's
default font *is* the system font, and naming a family would break the
non-Latin fallback chain", and §3.3 repeats it. Roboto is not bundled
(no font files under swiftcut/resources/), so this either falls through
to sans-serif or picks up an unrelated installed Roboto. 14px is also
outside the type scale, whose steps are 13 / 11.5 / 11 / 9.5 / 9. This
is live code: PopoverMenu is used at doceditor/asset_browser.py:690 and
doceditor/workflow_row.py:379.

Citation corrected on verification: The stylesheet is installed by the
widget itself at swiftcut/ui_gtk/shared/popover_menu.py:37-45 and
applied at :65, so the rule is live. Call sites are three, not two:
doceditor/asset_browser.py:690, doceditor/workflow_row.py:379 and
doceditor/workflow_view.py:135.

Fix: Delete the `font-family` line entirely (§1.5) and drop `font-size:
14px` so the label inherits the 13px window base, which is the "Row
title" role in §1.5. Keep `margin: 12px` — that is SPACE_GROUP.

**G9 — INCONSISTENT — The canvas drop overlay is entirely untokenised: literal white, two literal rgba blacks, a 24px font and a 48px pad**

swiftcut/ui_gtk/canvas2d/drag_drop_cmd.py:62-72 builds `.drop-overlay {
font-size: 24px; font-weight: bold; color: white; background-color:
rgba(0, 0, 0, 0.7); border-radius: 10px; padding: 24px 48px; box-shadow:
0 4px 12px rgba(0, 0, 0, 0.3); }` and loads it with its own
Gtk.CssProvider at :75-79. Nothing here is theme-aware — it is the same
slab of black in light and dark. `rgba(0,0,0,0.7)` matches no token in
swift-cut-tokens.md §1.2; the two shadow rgbas duplicate what
`sc_shadow` exists for; 24px is off the §1.5 type scale entirely; 48 is
off the §1 spacing scale (SPACE_PAGE is 24, the largest step).

Fix: `color: white` → @sc_on_accent (see the on-accent TOKEN GAP above,
or #FFFFFF once that token lands); `box-shadow` rgba → @sc_shadow;
`padding: 24px 48px` → `24px` on both axes (SPACE_PAGE). For the scrim
there is no token: TOKEN GAP — propose `sc_scrim` = rgba(0,0,0,0.55)
light / rgba(0,0,0,0.70) dark, which is the standard modal-scrim role
the app has nowhere else. `font-size: 24px` also has no token: it is a
display size above the whole scale — either drop it to the 13px base
with weight 600 (`.sc-title`) or add `sc_type_display` = 20px to §1.5.

**G10 — INCONSISTENT — draglist.py paints a hairline as #00000020 and its drop indicators as #f00, both outside the palette**

swiftcut/ui_gtk/shared/draglist.py:19 `border-bottom: 1px solid
#00000020;` — an eight-digit hex (≈ rgba(0,0,0,0.125)) where swift-cut-
tokens.md §1.2 defines `sc_hairline` as exactly this role at
rgba(0,0,0,0.10) light / rgba(255,255,255,0.12) dark. Because it is a
literal it does not invert, so the row separators are near-invisible in
the dark theme. Lines 31 and 35 use `border: 1px solid #f00;` for the
drop-above / drop-below indicators. §1.1 restricts red: "`red` |
`#FF3B30` | Stop button and no-go zones only" — a drag-drop position
marker is neither, and every other drop indicator in the app uses the
accent (layer_column.py:80,83,89,92; dock_area.py:29,35;
dock_item.py:13,18). This is live code: DragListBox is imported by
doceditor/workflow_view.py:10.

Citation corrected on verification: layer_column.py:80,83 use
@accent_bg_color (which theme.py:78 aliases to @sc_accent), not
@sc_accent directly — the finding's characterisation 'uses the accent'
is accurate, the token name is one alias removed.

Fix: draglist.py:19 `#00000020` → `@sc_hairline`. Lines 31 and 35 `#f00`
→ `@sc_accent`, matching the drop indicators in layer_column.py and
dock_area.py so the app has one drop-target colour.

**G11 — INCONSISTENT — Three shadows are drawn with alpha(black, …) instead of @sc_shadow, so none of them inverts with the theme**

swiftcut/ui_gtk/mainwindow.py:72 `box-shadow: 0 2px 12px alpha(black,
0.2);` on `.right-panel-overlay`, mainwindow.py:79 `box-shadow: 0 2px
6px alpha(black, 0.15);` on `.status-message-overlay`, and
swiftcut/ui_gtk/shared/expander.py:11 `box-shadow: 0 4px 10px
alpha(black, 0.06);` on `.expander-card`. swift-cut-tokens.md §1.2
defines `sc_shadow` for exactly this — rgba(4,34,122,0.10) light (the
deck's shadow-blue at low alpha, §1.1) and rgba(0,0,0,0.40) dark — and
theme.py:42/:64 define it. Three panel shadows, three different alphas,
none of them the token, and all of them neutral black rather than the
blue-tinted shadow the deck specifies.

Fix: Replace all three `alpha(black, N)` colours with `@sc_shadow`,
keeping each rule's own offset/blur geometry. §1.1 is explicit that
panel drop shadows are shadow-blue at low alpha, which is what
@sc_shadow already encodes.

**G12 — INCONSISTENT — console.py declares a font-family, sizes in pt, and falls back to six Tango hex colours**

swiftcut/ui_gtk/machine/console.py:22-32 sets `font-family: Monospace;
font-size: 10pt;` twice. swift-cut-tokens.md §1.5 forbids `font-family`
and specifies the scale in "GTK `pt`-free `px`"; 10pt is ~13.3px, which
lands between the 13px base and nothing else on the scale. Lines 162-212
then hard-code a Tango fallback for every style lookup: `"#888A85"`
(:162, :191), `"#729FCF"` (:169, :205), `"#EF2929"` (:177), `"#F57900"`
(:184), `"#8AE234"` (:198), `"#4A90D9"` (:212). None appears in §1.1 or
§1.2; the app's own equivalents are @sc_fg_dim, @sc_accent_text,
@sc_danger, @sc_ok. Whenever a lookup misses, the console renders in a
palette from a different design system.

Fix: Fallbacks: `#888A85` → the literal value of sc_fg_dim,
`#729FCF`/`#4A90D9` → `#0B3BD1`/`#7CBEFF` (sc_accent_text), `#EF2929` →
`#FF3B30` (sc_danger), `#8AE234` → `#34C759` (sc_ok). `#F57900` has no
token: TOKEN GAP — propose `sc_warn` = #FF9F0A (light) / #FF9F0A (dark),
which §1.1 lacks entirely (see the jog `.warning` finding). For the
type: keep a monospace family here (a terminal legitimately needs one —
worth an explicit carve-out in §1.5 rather than a silent violation) but
state it as `font-family: monospace` and convert `10pt` to `11.5px`, the
§1.5 mono readout size.

**G13 — INCONSISTENT — The jog grid marks limit-exceeding directions with a `warning` class for which no token, and no rule, exists**

swiftcut/ui_gtk/machine/jog_widget.py:497-518 calls
`add_css_class("warning")` on ten jog buttons when
`would_jog_exceed_limits` is true. theme.py has no `.warning` or `.sc-
jog button.warning` rule, and swift-cut-tokens.md §1.1/§1.2 define no
warning colour at all — theme.py:71-101 redefines accent, destructive
and success for libadwaita but not `warning_color`, which is therefore
the one semantic colour still resolving to the stock theme. Meanwhile
theme.py:145-152 sets `color: @sc_fg` on every `.sc-jog button` from a
provider installed at STYLE_PROVIDER_PRIORITY_APPLICATION
(theme.py:408-412), which outranks libadwaita's own stylesheet, so
whatever `.warning` would have tinted is overridden. The same undefined
token is depended on at mainwindow.py:98 (`.warning-label { color:
@warning_color }`, used by toolbar.py:188) and
machine/settings_dialog.py:28 (`alpha(@warning_color, 0.15)`).

Fix: TOKEN GAP. Add `sc_warn` = #FF9F0A (light) / #FF9F0A (dark) to §1.2
and _SHARED_TOKENS, alias `@define-color warning_color @sc_warn;` next
to the existing `success_color` alias at theme.py:101, and add one rule
`.sc-jog button.warning { color: @sc_warn; }` so the ten existing call
sites in jog_widget.py light up without any change to jog behaviour.
Amber is the right third colour: §1.1 reserves red for Stop and no-go
zones, and an at-limit direction is a caution, not a stop.

PROTECTED: jog_widget.py is jog panel behaviour, PROTECTED — but the fix
adds only a CSS rule and a token; jog_widget.py itself needs no edit,
which is the point of doing it in the theme.

**G14 — INCONSISTENT — The two canvas overlays use two different backgrounds, and neither is the glass token §3.1 assigns them**

swiftcut/ui_gtk/shared/visibility_overlay.py:10-15 paints `.visibility-
overlay { background-color: alpha(@theme_bg_color, 0.75); padding: 4px;
}`; swiftcut/ui_gtk/shared/time_estimate_overlay.py:8-13 paints `.time-
estimate-overlay { background-color: @theme_bg_color; padding: 4px 8px;
}` — fully opaque. Both widgets also add `sc-overlay`
(visibility_overlay.py:40, time_estimate_overlay.py:25) and
theme.py:354-356 gives that class only a 9px radius, no background.
swift-cut-tokens.md §3.1 states the fallback for the canvas overlay:
"the header and the canvas overlay use their rgba token (`@sc_header_bg`
at 0.88)". So two overlays a few hundred pixels apart on the same canvas
sit at 0.75 alpha and 1.0 alpha, and neither is 0.88.

Citation corrected on verification: visibility_overlay.py:11-14 (block
10-15) is the precise span for the 0.75 background;
time_estimate_overlay.py:9-12 (block 8-13) for the opaque one.

Fix: Move the background onto the shared class: add `background-color:
@sc_header_bg;` to theme.py's `.sc-overlay` rule at :354-356 (which is
already the documented home of the overlay's radius), and delete the
`background-color` line from both widget CSS strings, leaving each its
own padding. One rule, one alpha, both overlays.

PROTECTED: theme.py — Swift Cut theme, PROTECTED.

**G15 — INCONSISTENT — workflow_row.py contradicts four separate token rules in eighteen lines of CSS**

swiftcut/ui_gtk/doceditor/workflow_row.py:20-47. (a) `:29-30` `min-
width/min-height: 28px` on `.workflow-step-button` — CONTROL_SIZE is 32
(layout.py:44), and pass-1 S5 already listed 28 as one of the five sizes
the layout pass was meant to collapse. (b) `:33` `border-radius: 6px` —
swift-cut-tokens.md §1.4 gives 6px to the jog button and 7px to "Toolbar
/ panel button", which is what this is. (c) `:45` `border-radius: 1px` —
pass-1 S8 names this exact line ("`doceditor/workflow_row.py:44` — 1px")
among the eight radii to retire; swift-cut-layout.md §4 confirms
"Retired: … 1 (workflow row)". Still there. (d) `:41-45` `.workflow-
drop-indicator { min-width: 2px; min-height: 24px; background-color:
@accent_color; border-radius: 1px; }` — swift-cut-tokens.md §1.5 closes
with "No accent lines and no decorative bars anywhere."

Citation corrected on verification: The drop-indicator block is :41-46,
not :41-45 (:41 `.workflow-drop-indicator {`, :45 `border-radius: 1px;`,
:46 `}`). The `border-radius: 1px` line is :45 as claimed -- pass-1 S8
cites it as :44, so the line moved by one since the audit.

Fix: 28px → 32px (or interpolate layout.CONTROL_SIZE); 6px → 7px, the
panel-button radius; drop `border-radius: 1px` at :45 — a 2px-wide bar
needs no radius and the value is explicitly retired. The drop indicator
is the one judgement call: it is a transient drag affordance, not
decoration, so it should stay, but it should be reconciled with §1.5 in
the doc rather than left as a silent exception — and it should use the
same treatment as the other drop indicators (see the draglist finding).

PROTECTED: workflow_row.py renders the layer/step workflow, which is
PROTECTED as a system; these are presentational CSS values and touch no
step wiring.

**G16 — INCONSISTENT — layer_column.py and asset_browser.py set type sizes with `smaller`, `13px` and `1.1em` — none of which is on the scale**

swiftcut/ui_gtk/doceditor/layer_column.py:57-59 `.layer-column-header
.dim-label { font-size: smaller; }` — a relative keyword whose result
depends on whatever the parent resolved to, so it is unpredictable by
construction. swiftcut/ui_gtk/doceditor/asset_browser.py:63-66 `.asset-
card-label { font-size: 13px; }` — restates the window base that §1.5
says to inherit ("Window base | 13px | inherit (no rule)"), and
asset_browser.py:78-81 `.asset-browser-empty-buttons button { font-size:
1.1em; }` — 14.3px, off the scale entirely. layer_column.py:53-54 also
sets `min-width/min-height: 28px` on its flat header buttons, the same
off-CONTROL_SIZE value as workflow_row.py.

Fix: layer_column.py:58 `font-size: smaller` → drop the rule and give
the label the `sc-caption` class (11px + @sc_fg_dim in one), which is
the "Caption" role in swift-cut-layout.md §5.1. asset_browser.py:64 →
delete the line and inherit. asset_browser.py:80 `1.1em` → delete; if
the empty-state buttons must read larger, that is the `.sc-title` role
(13px/600), not a new size. layer_column.py:53-54 28px → CONTROL_SIZE.

**G17 — INCONSISTENT — Nine call sites build a row suffix box by hand instead of going through layout.suffix_box(), the one rule pass 1 A1 exists to enforce**

swift-cut-layout.md §3 rule 3 is unambiguous: "**Suffixes are built one
way.** Every row's trailing controls go in a box from
`layout.suffix_box()` — one spacing, one alignment, one trailing edge."
Six call sites obey (doceditor/bottom_panel.py:335,370,413,483;
shared/pref_rows/base.py:101; shared/optional_spin_row.py:47). Nine do
not, each re-creating the same `Gtk.Box(spacing=SPACE_CONTROL,
valign=Gtk.Align.CENTER)` inline and shadowing the imported helper's
name with a local variable: addon_manager/addon_list.py:139,
doceditor/material_library_list.py:74, doceditor/material_list.py:88,
doceditor/recipes/recipe_list.py:56, machine/macro_list.py:41,
machine/maintenance_page.py:75, machine/rotary_module_page.py:67,
settings/color_presets_page.py:196, machine/laser_control_widget.py:94.
None of them gets the `sc-suffix` class, and
laser_control_widget.py:94-95 additionally sets `set_hexpand(False)`
that the helper does not, so that row's trailing edge differs from every
other. This is the same recurring edit/delete pair pass-1 I2 identified
as "One shared row-actions widget would fix eight of these at once".

Citation corrected on verification: Two details are wrong. (1)
"shadowing the imported helper's name" -- none of the nine imports
`suffix_box`. Verified import lines: addon_list.py:16,
material_library_list.py:12, material_list.py:14, recipe_list.py:12,
macro_list.py:8, maintenance_page.py:11, rotary_module_page.py:17,
color_presets_page.py:15, laser_control_widget.py:9 all pull only
SPACE_CONTROL/SPACE_GROUP/icon_button. `suffix_box` is a plain local
name that would collide with a future import, not a shadow of a current
one. (2) laser_control_widget.py:94 is `Gtk.Box(spacing=SPACE_CONTROL)`
with no `valign=Gtk.Align.CENTER`, so it is not "the same" box as the
other eight -- it differs on two axes (missing valign, extra hexpand),
not one.

Fix: Replace all nine inline boxes with `layout.suffix_box(*children)`.
Eight of the nine are the identical edit/delete list-row pair, so the
stronger shared fix is the row-actions widget pass-1 §7 item 8 already
specified, built on suffix_box + layout.icon_button (which also carries
the mandatory tooltip that pass-1 I2 found missing on 28 buttons).

PROTECTED: laser_control_widget.py is on the Min/Max power path; the
change is to how its suffix box is constructed, not to the power rows
themselves.

**G18 — INCONSISTENT — Post-audit surface — the Cut Scale dialog's Power caption names its unit, which §5.3 forbids and the plain SpinRow gives it nowhere else to go**

swiftcut/ui_gtk/machine/cut_scale_dialog.py was reworked for Commit C
and again in 3a8aefb81 (speed/power persistence), both after the audit.
It is correctly tokenised in one respect — :33 `self.add_css_class("sc-
sheet")`, which theme.py:264-269 styles. But :51-57 builds the Power row
as a plain `SpinRow` with subtitle `_("Percent of full power")`. swift-
cut-layout.md §5.3 says "Units appear exactly once, in the field … Never
in the title, never in the caption, never only in a tooltip", and §5.2
says a caption "never names a unit — that is the field's job". The row
cannot obey: swiftcut/ui_gtk/shared/pref_rows/base.py:101 builds the
suffix as `suffix_box(self._spin_button)` with no unit label, and only
UnitSpinRow adds one (shared/pref_rows/unit_spin_row.py:71-74,
`self._unit_label.add_css_class("sc-caption")` appended to
`self._suffix`). Percent is not a Unit in the quantity system, so the
one row in the app that expresses a percentage has no tokenised place to
say so. The Speed row beside it does obey — SpeedSpinRow inherits
UnitSpinRow and gets the in-field `.sc-caption` suffix — so the two rows
of this one sheet state their units two different ways.

Citation corrected on verification: Minor: theme.py:264-269 styles `.sc-
sheet .response-area button.destructive-action` only (the destructive
Cut button), not the sheet surface generally — the finding's "which
theme.py:264-269 styles" overstates the coverage. Everything else is
exact.

Fix: TOKEN GAP in the row contract, not in the colour map. Give the base
SpinRow an optional fixed suffix label — `SpinRow(..., unit_suffix="%")`
appending a `.sc-caption` label to `self._suffix` exactly as
unit_spin_row.py:71-74 does — then cut_scale_dialog.py:51-57 can pass
`unit_suffix="%"` and drop the subtitle, satisfying §5.2 and §5.3 with
one change that also serves every other percentage row. Fixing it at the
call site instead would put a literal "%" label in the dialog and leave
the next percentage row to reinvent it.

PROTECTED: cut_scale_dialog.py is Cut Scale, PROTECTED: "Go Scale and
Cut Scale, including Cut Scale's speed/power confirmation before firing"
(swift-cut-tokens.md §5) and Min/Max power. The proposed change moves
where a unit is displayed and must not touch _on_response's
`self.power_row.get_value() / 100.0` at :67 or the response wiring; the
handler-count test must pass unmodified.

**G19 — MINOR — layout.suffix_box() adds .sc-suffix, and no stylesheet in the repo defines a rule for it**

swiftcut/ui_gtk/layout.py:83 `box.add_css_class("sc-suffix")` puts the
class on every row suffix in the app (bottom_panel.py:335,370,413,483;
shared/pref_rows/base.py:101; shared/optional_spin_row.py:47). `grep -o
"\.sc-[a-z-]*" swiftcut/ui_gtk/theme.py | sort -u` lists fifteen sc-
selectors and `.sc-suffix` is not one of them, and no other CSS string
in the tree mentions it either. It is the only sc- class added by a
widget with no rule behind it — the mirror image of the pass-1 X1/X2
problem.

Fix: Either give `.sc-suffix` the rule the layout doc §3 rule 3
describes (one trailing edge — `.sc-suffix { margin-right: 0; }` plus
whatever normalises Gtk.SpinButton's own end padding, which is the
actual cause of pass-1 A1), or drop the class from layout.py:83 and keep
the spacing/alignment purely in Python. A class that exists for
documentation only invites a widget to key off it later.

PROTECTED: layout.py — Swift Cut layout tokens, PROTECTED.

**G20 — MINOR — round_button.py and icon_tab_widget.py are unreachable, yet they are two of the thirteen files theme.py's alias block was written to serve**

`grep -rn "RoundButton\|round_button" --include=*.py .` and the same for
IconTabWidget return exactly one hit each, and it is the prose comment
at swiftcut/ui_gtk/theme.py:106 ("…round_button, key, icon_tab_widget,
expression_entry"). Neither module has an importer. Pass-1 S5 already
flagged icon_tab_widget.py as dead ("It is **dead code** — nothing in
the tree imports it — so it is reported, not changed"); round_button.py
is dead too and pass 1 did not say so, it only recorded its 32px radius
under S8 as "intentional: a circle". Between them they carry six
@theme_* uses, six literal `rgba(0,0,0,…)` box-shadows
(round_button.py:14,15,21,22,27,28), a 24px font-size (:12), a 64px
control size (:5-6) and a 36px/6px control size
(icon_tab_widget.py:10-14) — none of which can be reached, and all of
which will be found and copied by the next person styling a button.

Citation corrected on verification: The '@theme_* uses' count is wrong:
round_button.py carries 4 (@theme_selected_bg_color at :10,:20,:26 and
@theme_selected_fg_color at :11) and icon_tab_widget.py carries 5, i.e.
9 between them, not six (verified by `grep -rc "@theme_"`, where every
hit is one per line).

Fix: Reported, not changed — per CLAUDE.md §3 pre-existing dead code is
flagged, not deleted, and docs/removal-inventory-2026-09-04.md does not
list either file. The shared fix if the owner does want them gone:
delete both modules and correct theme.py:104-112, whose comment also
still names "the canvas and 3D overlays" although the 3D subsystem was
removed wholesale (removal inventory item 4).

**G21 — MINOR — Two of the five deck tint semantics still disagree with swift-cut-tokens.md §2.4: the dock rail active pip and the canvas overlay toggle**

Pass-1 I3 says "Tint semantics are applied to two surfaces out of five …
The dock rail and canvas overlay still colour themselves from the legacy
`@theme_selected_bg_color`". The colours now resolve correctly through
the aliases, but the *treatment* still differs from the map. §2.4 row
"Dock rail (active pip) | `gcode`, `jog` | `-w` on `@sc_accent` | `-w`
on `@sc_accent`" asks for a white glyph on solid accent;
swiftcut/ui_gtk/shared/dock_area.py:23-26 renders `background:
alpha(@theme_selected_bg_color, 0.2); color: @theme_selected_bg_color` —
a 20% tint with an accent-coloured glyph. §2.4 row "Canvas overlay
toggles (all active) | `-d` on `@sc_accent_soft` | `-w` on
`@sc_accent_soft`" asks for the resting foreground on soft accent;
theme.py:254-257 renders `background-color: @sc_accent_soft; color:
@sc_accent_text`, i.e. blue-on-blue rather than the ink glyph the deck
draws.

Fix: dock_area.py:23-26 → `background: @sc_accent; color:
@sc_on_accent;` (the solid pip §2.4 specifies). theme.py:256 `color:
@sc_accent_text` → `color: @sc_fg`, which is `-d` in light and `-w` in
dark exactly as the §2.4 row reads. Both are one-line colour swaps in
rules that already exist.

PROTECTED: theme.py — Swift Cut theme, PROTECTED.

**G22 — MINOR — Pass-1 S1/S2 has one survivor: gcodeedit/viewer.py still uses 9 and 3, the two scales the layout doc retired**

A repo-wide sweep for `set_margin_*(n)` / `spacing=n` where n is outside
{0,4,8,12,16,24} returns only four production hits. Three are in
swiftcut/shared/gcodeedit/viewer.py: :42 `set_margin_top(9)`, :66
`set_margin_bottom(3)`, :67 `set_margin_end(3)`. swift-cut-layout.md
§1's conversion table maps them directly — "9, 10 → `SPACE_GROUP` (12) —
all are panel padding" and "2, 3, 5 → `SPACE_TIGHT` (4)". This file is
the last carrier of the 9px scale that pass-1 S2 named, and it survived
because it lives under `swiftcut/shared/`, not `swiftcut/ui_gtk/`, which
is where the layout pass swept. The fourth hit is
swiftcut/builtin_addons/rayforge-addon-print-and-
cut/print_and_cut/wizard.py:195 and :239, both `set_margin_end(32)`,
which §1 maps to "32, 50 → `SPACE_PAGE` (24)". The file already imports
SPACE_CONTROL and SPACE_GROUP at :19 and uses SPACE_GROUP/SPACE_TIGHT on
the other three sides of the same box.

Citation corrected on verification: The count is loose: the sweep
returns five off-scale production lines in two files (viewer.py:42,66,67
and wizard.py:195,239), not 'four production hits'. Unrelated but
adjacent: wizard.py uses SPACE_TIGHT (:196,:240), SPACE_SECTION (:99)
and SPACE_PAGE (:381,:382) while :19 imports only SPACE_CONTROL and
SPACE_GROUP — a latent NameError in that addon, outside this finding's
scope.

Fix: viewer.py:42 → `SPACE_GROUP`, :66 and :67 → `SPACE_TIGHT`,
importing from swiftcut.ui_gtk.layout the way the other widgets do.
wizard.py:195 and :239 → `SPACE_PAGE`. That closes the spacing scale
completely — after these five lines every margin and spacing literal in
the tree is on the 4px scale except mainwindow.py:322, which the layout
doc explicitly exempts.

PROTECTED: gcodeedit/viewer.py renders the Ruida job preview and is a
KEEP in docs/removal-inventory-2026-09-04.md item 6; these are margin
values only and touch no rendering or op-map logic.

**G23 — MINOR — Five widgets restate CONTROL_SIZE (32) as a literal size request instead of importing the token**

swiftcut/ui_gtk/addon_manager/addon_dialog.py:55,
swiftcut/ui_gtk/doceditor/add_material_dialog.py:46,
swiftcut/ui_gtk/machine/head_preferences_page.py:511 and :524 all call
`set_size_request(32, 32)`;
swiftcut/ui_gtk/settings/color_presets_page.py:103 calls
`set_size_request(48, 32)`. swiftcut/ui_gtk/layout.py:44 defines
`CONTROL_SIZE = 32` for exactly this — "Every icon button, toggle and
stepper in a compact context" — and swift-cut-layout.md §2 says a widget
"never picks its own … control size". Each of these files already
imports from ..layout (addon_dialog.py:12, head_preferences_page.py:16),
so the token is one name away. Two more restate a different token:
swiftcut/ui_gtk/shared/expression_entry.py:146 `set_size_request(-1,
40)` is ROW_MIN_HEIGHT_COMPACT verbatim.

Citation corrected on verification: Quote attribution is off: "a widget
never picks its own spacing, control size or row height" is in the
swift-cut-layout.md preamble (lines 8-9), not §2. §2 (lines 56-79) is
the density-context table itself: "| **Compact** | toolbar, panel rows,
dock rail, canvas overlay | `CONTROL_SIZE` | 32x32 |". Strongest single
fact, verified: CONTROL_SIZE and ROW_MIN_HEIGHT_COMPACT each have
exactly zero references outside layout.py.

Fix: Import CONTROL_SIZE from ..layout and use it at all five sites
(color_presets_page.py:103 becomes `set_size_request(48, CONTROL_SIZE)`
— the 48 is a swatch width, a different quantity).
expression_entry.py:146 → ROW_MIN_HEIGHT_COMPACT. This is also what
gives the currently-zero-reference CONTROL_SIZE constant a reason to
exist.

**G24 — MINOR — key.py sizes at 12px and dock_item/dock_layout size at 6px, three values off the type and spacing scales**

swiftcut/ui_gtk/shared/key.py:12 `font-size: 12px;` — swift-cut-
tokens.md §1.5's scale is 13 / 11.5 / 11 / 9.5 / 9; 12 is on none of
them. (The rest of key.py is correct: `border-radius: 5px` is the chip
radius and `padding: 4px 8px` is SPACE_TIGHT/SPACE_CONTROL.)
swiftcut/ui_gtk/shared/dock_item.py:5-6 `min-width: 6px; min-height:
6px;` on the dock edge zones and
swiftcut/ui_gtk/shared/dock_layout.py:30 `_DIVIDER_WIDTH = 6` — 6 is the
GNOME step swift-cut-layout.md §1 converts away ("6 | `SPACE_CONTROL`
(8) | between controls").

Fix: key.py:12 `12px` → `11px`, the caption size (a keycap is caption-
scale text). dock_item.py:5-6 and dock_layout.py:30 `6` →
`SPACE_CONTROL` (8), per §1's conversion table. Note dock_layout.py:30
is a Python constant, so it belongs in layout.py if the drag-target
width is a real role — otherwise just take the 8.

**G25 — MINOR — mainwindow.py still carries CSS for the machine dropdown, a widget removed in the Ruida-only conversion**

swiftcut/ui_gtk/mainwindow.py:102-105 declares `dropdown.machine-
dropdown button { padding-top: 4px; padding-bottom: 4px; }`.
docs/removal-inventory-2026-09-04.md item 7 lists `machine_dropdown.py`
as REMOVE ("Machine picker; `update_eta()` … must be rehomed first"),
and it is gone — `ls swiftcut/ui_gtk/machine_dropdown.py` fails and
`grep -rn "machine-dropdown\|machine_dropdown" --include=*.py swiftcut/`
returns only this one CSS line. The rule can never match.

Fix: Delete mainwindow.py:102-105. Per CLAUDE.md §3 this is an orphan
created by a prior removal rather than pre-existing dead code, and the
removal inventory is the authority saying the widget was deliberately
removed.

**G26 — MINOR — Post-audit surface — the toolbar job progress bar is sized 120px with no token, on a widget introduced after the audit**

swiftcut/ui_gtk/toolbar.py:204-212 builds the job-progress box (Commit C
in swift-cut-tokens.md §4, "job-progress in the toolbar driven by the
**estimate**"), and :210 sets
`self.job_progress_bar.set_size_request(120, -1)`. 120 is on neither
scale: swift-cut-layout.md §1 tops out at SPACE_PAGE 24 and §2 names
only CONTROL_SIZE 32 and JOG_CELL 60. The rest of the widget is
correctly tokenised — spacing SPACE_CONTROL (:204), margin SPACE_GROUP
(:205), classes `sc-job-progress` (:207) and `sc-caption` (:212) — and
theme.py:274-288 styles it, so this single literal is the one
untokenised value on an otherwise clean post-audit surface. The 5px
trough height at theme.py:275,281 is also duplicated as a literal in
swiftcut/ui_gtk/shared/progress_bar.py:25 (`progressbar.thin-progress-
bar { min-height: 5px; }`) — the same number for the same role in two
files.

Citation corrected on verification: "This single literal is the one
untokenised value on an otherwise clean post-audit surface" is
overstated. theme.py:276 and :282 also set `border-radius: 3px` on the
same trough and progress, and 3px is on neither swift-cut-tokens.md
§1.4's map (5/6/7/8/9/10/11) nor swift-cut-layout.md §4 -- indeed swift-
cut-layout.md:123-124 lists "3 (G-code viewer)" among the retired radii.
That strengthens the finding rather than weakening it, but the surface
is not otherwise clean.

Fix: TOKEN GAP. No token covers an inline meter's track length. Propose
`METER_TRACK` = 120 in layout.py under a "Meters" heading in swift-cut-
layout.md §2, used at toolbar.py:210 and available to any future inline
progress bar. Also propose `METER_HEIGHT` = 5 so theme.py:275,281 and
progress_bar.py:25 stop restating it — a single source for the one bar
thickness the app draws.

PROTECTED: toolbar.py's progress bar reflects Start/Pause/Stop job
state, PROTECTED behaviour; the finding is a size literal and touches no
state wiring.

**G27 — MINOR — Post-audit surface — the splash screen introduces a fifth brand blue (#001B7A) that appears in no token document**

scripts/win/win_create_splash.py was added in 8720bf367 / 226b53e24,
well after the audit, and its header comment cites the token map ("#
Brand tokens, from docs/design/swift-cut-tokens.md." at :38). Four of
the five constants check out — BLUE_LIGHT #7CBEFF, BLUE_BRAND #2F7BFF,
BLUE_DEEP #0B3BD1 (:39-41) are §1.1's blue-light / blue-brand / blue-
deep verbatim. `DEEP_SHADE = (0x00, 0x1B, 0x7A)` at :42 is not: §1.1's
only darker blue is `shadow-blue` #04227A, and #001B7A is a different
colour used at :102 as a 35% shading stop over the brand gradient.
`RADIUS = 20` at :33 is also outside the §1.4 radius map, whose largest
entry is 11px (window, "window-managed, untouched"), and :114-119 hard-
code `ImageFont.truetype("segoeuisb.ttf", 40)` with a `segoeuib.ttf`
fallback — a bundled-font decision the §1.5/§3.3 no-font-family rule was
written to prevent, made for a raster asset where the rule arguably does
not apply but was never reconciled either way.

Citation corrected on verification: The font fallback is at :117, not
:118 (:114 truetype segoeuisb, :116 except OSError, :117 truetype
segoeuib, :119 load_default) -- the stated :114-119 range is correct.

Fix: Either change DEEP_SHADE at :42 to shadow-blue #04227A, the token
§1.1 already provides for exactly this role ("Panel drop shadows (at low
alpha)"), or — if the gradient genuinely needs a fifth stop — add it to
§1.1 by name. TOKEN GAP for the other two: the splash plate is a brand
surface the token map never covers, so §1.4 needs a "Splash plate |
20px" row and §1.5 needs an explicit carve-out saying raster brand
assets may name a font because PIL has no system-font fallback chain to
break. Right now the file both cites the doc and departs from it in
three places with nothing recording that.

**G28 — MINOR — Four fixed widths are set in widget code with no token and no shared home: 130, 200, 200 and 100**

swiftcut/ui_gtk/shared/adwfix.py:3 `_SPINROW_MIN_WIDTH_CSS = "row
spinbutton { min-width: 130px; }"`, installed globally at :20-28 — it is
the app-wide spin-button width, set from a helper module rather than
from layout.py. swiftcut/ui_gtk/shared/slider.py:8-9 `SLIDER_TRACK_WIDTH
= 200` and `VALUE_LABEL_WIDTH = 60`, with :24
`set_size_request(SLIDER_TRACK_WIDTH, 60 if draw_value else -1)`
restating 60 a second time.
swiftcut/ui_gtk/shared/expression_entry.py:73 `set_size_request(200,
-1)`. swiftcut/ui_gtk/machine/hardware_page.py:73 `set_size_request(100,
-1)`. swift-cut-layout.md §6 says the Python half of the map — "margins,
box spacing, size requests" — lives in layout.py; these four are size
requests living elsewhere, and 130/200/100 correspond to nothing in the
doc.

Citation corrected on verification: Two imprecisions, neither fatal. (1)
slider.py:9 `VALUE_LABEL_WIDTH = 60` is not "restated" at :24 — `grep
-rn VALUE_LABEL_WIDTH swiftcut/` returns only the definition, so the
constant is entirely unused dead code, and the 60 at :24 is the scale's
*height* argument, a different dimension. (2) The rule quoted as "swift-
cut-layout.md §6 says the Python half of the map — margins, box spacing,
size requests — lives in layout.py" is actually layout.py's own module
docstring (layout.py:7-9); swift-cut-layout.md:201 reads "| Spacing
scale, control sizes, row heights, max widths |
`swiftcut/ui_gtk/layout.py` (constants) |". Also unmentioned but
supporting: base.py:34 `_SPINROW_WIDTH_CHARS = 10` is a fifth field-
sizing magic number outside layout.py.

Fix: TOKEN GAP — the layout map has spacing, control sizes, row heights
and one max width, but no *field* widths, which is why four files
invented their own. Propose one field-width scale in swift-cut-layout.md
§3 and layout.py: `FIELD_NARROW` = 100, `FIELD` = 130 (the value
adwfix.py already imposes app-wide), `FIELD_WIDE` = 200. Then
adwfix.py:3 interpolates FIELD, slider.py:8 takes FIELD_WIDE,
expression_entry.py:73 takes FIELD_WIDE and hardware_page.py:73 takes
FIELD_NARROW. Also collapse slider.py's duplicated 60 into a single
constant.


## B — Text: branding, units, debug strings

**B1 — BROKEN — data/org.ilab.SwiftCut.desktop launches `Exec=rayforge`, a binary that no longer exists**

`data/org.ilab.SwiftCut.desktop:12` is `Exec=rayforge`. The only
console/gui entry point declared is `pyproject.toml:22-23`
`[project.gui-scripts]` / `swiftcut = "swiftcut.app:main"`, and
`snap/snapcraft.yaml:9` uses `command: bin/swiftcut`. `grep -rn rayforge
pyproject.toml MANIFEST.in` returns nothing, so no `rayforge` script is
installed by any packaging path. `pyproject.toml:72` installs this exact
file to `share/applications`, so the app-menu / launcher entry is dead
on a real install. This is the only .desktop file in the tree (`find .
-name '*.desktop'` outside build/dist).

Fix: One shared rule: the launcher command is the name declared in
`[project.gui-scripts]`. Set `Exec=swiftcut` in the .desktop and add a
packaging test that asserts the .desktop `Exec=` key equals the sole
`project.gui-scripts` key, so the two cannot drift again. Same test
should cover `snapcraft.yaml`'s `command:`.

**B2 — BROKEN — metainfo.xml: remote app icon points into the deleted `rayforge/` package path, and release notes still say Rayforge**

`data/org.ilab.SwiftCut.metainfo.xml:56` is `<icon type="remote">https:/
/raw.githubusercontent.com/ilab/swiftcut/refs/heads/main/rayforge/resour
ces/icons/org.ilab.SwiftCut.svg</icon>` -- the `rayforge/` path segment
does not exist after commit 1e0b2c53f renamed the package, so the app-
store icon 404s. Four user-visible release-note bodies still read
Rayforge: `:501` "Import LightBurn layer settings as Rayforge step",
`:586` "File dialogs prefer Rayforge MIME types over ZIP", `:1364` "It's
Rayforge's Birthday Release!", `:1366` "Rayforge experience". `:4` is
`<developer id="org.rayforge">`. Separately `:29-31` of the
`<description>` still claims "SwiftCut support communicating with GRBL
based laser cutters" -- the GRBL driver was removed per `docs/removal-
inventory-2026-09-04.md` A2 item 5 ("driver/grbl/** ... REMOVE, gate
PASSES") -- and carries a grammar error ("support").

Citation corrected on verification: The GRBL sentence is at
data/org.ilab.SwiftCut.metainfo.xml:30 specifically (the cited 29-31 is
a range around it). Two further rayforge strings the finding did not
list, both in the same file: :23 `<translation type="gettext"
source_locale="en">rayforge</translation>` (the gettext domain — check
against the installed domain before changing) and :40-41
`<mediatype>application/x-rayforge-project</mediatype>` /
`<mediatype>application/x-rayforge-sketch</mediatype>`, which mirror
data/org.ilab.SwiftCut.desktop:9 and are format identifiers rather than
display text.

Fix: Fix the icon URL to
`swiftcut/resources/icons/org.ilab.SwiftCut.svg` (the file that actually
exists -- verified by `ls swiftcut/resources/icons/`), rewrite the four
release-note strings and the `<developer id>`, and rewrite
`<description>` to state the Ruida-only scope. Then add the metainfo and
desktop files to the branding gate's scan set so XML/desktop text is
covered by the same rule as Python text.

**B3 — BROKEN — Material-test grid engraves its speed axis in mm/min while the dialog that set it reads mm/s**

`swiftcut/builtin_addons/rayforge-addon-
laser/laser_essentials/widgets/material_test_grid_page.py:236-254`
builds Minimum/Maximum Speed as `SpeedSpinRow(...,
value_in_base=min_speed)`, so `step.speed_range` holds application base
units = mm/min (`shared/units/definitions.py:111`). Those raw base
values are handed to the geometry generator unconverted:
`steps/material_test.py:67-68` `kwargs["min_speed"] =
self.speed_range[0]`, and `material_test_helpers.py:117-119` passes
`min_speed=params.get("speed_range",...)[0]` /
`label_speed=params.get("label_speed", 1000.0)` into
`generate_material_test_grid_preview`. The generator documents its own
unit as mm/min: `dist/SwiftCut/_internal/raygeo/ops/assembly/material_te
st_grid/__init__.pyi:92-93` ":param min_speed: Minimum speed in mm/min",
`:108` ":param label_speed: Feed rate for label engraving in mm/min",
and `:84-87` says the column headers and axis titles are generated from
those numbers. Net effect: a cell the dialog describes as 166.7 mm/s is
labelled "10000" both in the on-canvas preview and in the text
physically burned into the material.

Citation corrected on verification: Line-number correction:
`min_speed=params.get("speed_range", (100.0, 500.0))[0]` is at
material_test_helpers.py:103 (and max_speed at :104), NOT :117. Only
`label_speed=params.get("label_speed", 1000.0)` is at :119 (:117 is
`include_labels=`, :118 is `label_power_percent=`). Caveat on the
severity: the actual glyph rendering happens inside the compiled raygeo
extension, so "a cell the dialog describes as 166.7 mm/s is labelled
10000" is inferred from the .pyi docstring, not observed - it is the
strongest evidence obtainable without running the app, which the read-
only constraint forbids.

Fix: raygeo's numeric contract is mm/min and must not change -- so the
label, not the value, is what is wrong. raygeo renders the label text
itself, so the app cannot restyle it; the honest shared fix is to state
the unit once in the dialog next to the grid ('axis values are mm/min')
or, better, raise it upstream as a raygeo label-unit parameter. Missing
token: there is no 'unit of the burned annotation' concept anywhere --
the app assumes every rendered speed is mm/s and this one is not.

PROTECTED: laser_essentials is listed KEEP / "PROTECTED and load-
bearing" in docs/removal-inventory-2026-09-04.md (A2 item 11 and the
explicit KEEP list), and mm/s units are PROTECTED. Do not convert
`speed_range` storage; only the label.

**B4 — BROKEN — Toast messages render as Pango markup and are never escaped, so a filename with & or < blanks the toast**

`swiftcut/ui_gtk/mainwindow.py:1138` builds every notification with
`Adw.Toast.new(message)` and never calls `set_use_markup(False)`.
Verified by introspection against the installed runtime (libadwaita
1.9.3): `Adw.Toast` exposes a `use-markup` property whose default value
is `True`, and a fresh `Adw.Toast.new('x').get_use_markup()` returns
`True`. The messages interpolate unescaped user data and raw exception
text: `swiftcut/doceditor/file_cmd.py:1116` `_("Failed to export object:
{error}").format(error=str(e))`, and the same shape at `:1170`, `:1198`,
`:1276` (`_("Load failed: {error}")`), plus
`swiftcut/doceditor/editor.py:356` and `file_cmd.py:1255` which
interpolate an addon name. Nothing in the chain escapes: `grep -rn
markup_escape swiftcut/` finds escaping only in `about.py:361`,
`device_settings_page.py:194-197`, `gcode_editor.py:175` and
`main_menu.py:278-280` -- never on the toast path. Opening a project
named 'Cut & Engrave.ryp' that fails to parse produces a markup-invalid
toast body.

Citation corrected on verification: file_cmd.py:1255 does NOT
interpolate an addon name - the message there is `_("{count} asset(s)
require disabled addon(s)").format(count=len(unknown_assets))`, a plain
integer that can never contain markup. Only editor.py:356-359
interpolates a name: `_("{count} asset(s) require disabled addon
'{addon}'").format(count=..., addon=addon_name)`. The load-bearing
senders are the four `str(e)` ones at file_cmd.py:1116/1170/1198/1276.

Fix: One line at the single sink rather than escaping at ~15 senders: in
`_on_editor_notification` call `toast.set_use_markup(False)` before
`_add_toast(toast)` (no current caller passes markup --
`main_menu.py:278-280` is the one place that escapes, and it feeds a
menu label, not a toast). If a future toast needs markup, add an
explicit `markup: bool = False` kwarg to the signal. This is the shared-
widget fix; the per-call alternative would be `GLib.markup_escape_text`
at every sender.

**B5 — INCONSISTENT — All five bundled addons are attributed to "Rayforge Team" in Settings > Addons**

Every `swiftcut/builtin_addons/*/rayforge-addon.yaml` carries `author:\n
name: "Rayforge Team"\n  email: "noreply@rayforge.org"` (laser:8-9,
materials:6-7, post:6-7, print-and-cut:6-7, sketcher:6-7). That value is
rendered to the user twice:
`swiftcut/ui_gtk/addon_manager/addon_list.py:186-187` appends
`self.addon.metadata.author.name` to the row subtitle (`" |
".join(parts)` at :189), and
`swiftcut/ui_gtk/addon_manager/addon_dialog.py:176-180` builds
`Gtk.Label(label=f"by {author_name}")` as a row suffix. The Addons page
is a live captured surface (`docs/design/audit/app-settings-
addons-*.png`). This is invisible to the existing gate:
`tests/ui_gtk/test_no_rayforge_branding.py:37-43` only scans
`swiftcut/ui_gtk` and `swiftcut/resources` for *Python string literals*,
and this text is YAML data flowing through a variable.

Citation corrected on verification: 'rendered to the user twice'
overstates the second site. addon_dialog.py:176-178 (`author_name =
addon.author.name` / `if author_name:` / `lbl = Gtk.Label(label=f"by
{author_name}")`) sits inside `_populate_list`, which is fed by
`context.addon_mgr.fetch_registry()` (addon_dialog.py:115) — i.e. the
remote registry, not the five bundled manifests. The bundled 'Rayforge
Team' string reaches the user through addon_list.py:186-189 only.

Fix: Token-class fix, not five one-offs: the bundled-addon vendor
identity is one value. Set `author.name` from a single constant (e.g.
`const.APP_VENDOR = "SwiftCut"`) in all five manifests, and widen the
branding gate rather than patching sites -- extend
`test_no_rayforge_branding.py` with a second parametrised test that
walks every `swiftcut/builtin_addons/*/rayforge-addon.yaml` and asserts
no user-rendered field (`display_name`, `description`, `author.name`,
`license.name`) contains "rayforge".

**B6 — INCONSISTENT — Ruida job preview prints SPEED/TRAVEL_SPEED as a bare mm/min number while every UI field says mm/s**

`swiftcut/machine/driver/ruida/ruida_encoder.py:449,453` emit
`text.append(f"SPEED {speed:.1f}")` and `:472`
`text.append(f"TRAVEL_SPEED {speed:.1f}")` with no unit token. The value
is mm/min, proven twice in the same file: the handler docstring at
`:444` "set cutting speed in mm/min", and `_speed_to_um_s(self, mm_min:
float)` at `:240-249` ("Speeds reach the encoder in the application base
unit, mm/min"). Base unit is confirmed at
`swiftcut/shared/units/definitions.py:111` `set_base_unit("speed",
"mm/min")`. That text reaches the user unchanged: `ruida_encoder.py:199`
returns `EncodedOutput(text="\n".join(text_lines), ...)`;
`swiftcut/ui_gtk/mainwindow.py:1213` passes
`final_artifact.machine_code` to `_update_gcode_preview`, which at
`:765` calls `self.bottom_panel.gcode_viewer.set_gcode(gcode_string)` --
the dock tab captured as `docs/design/audit/dock-gcode-*.png`. So a job
cut at the row that reads "200.0 mm/s" shows as `SPEED 12000.0`. Same
pane also prints `POWER 30.0` (:335,338,353,740), `FREQUENCY {freq}`
(:488) and `PULSE_WIDTH {pw:.1f}` (:510) with no %, Hz or us.

Citation corrected on verification: The fix's claim "there is no unit-
formatting helper outside `UnitSpinRow`; add one
`format_in_display_unit(value_base, quantity) -> str` in
`shared/units/`" is WRONG - it already exists:
swiftcut/shared/units/formatter.py:13 `def format_value(value_in_base:
float, quantity: str) -> str:` ... returns
`f"{display_value:.{display_unit.precision}f} {display_unit.label}"`,
reading `config.unit_preferences.get(quantity, ...)`. The fix should say
"route the preview line through the existing
`shared/units/formatter.format_value`", not "add a missing helper". Also
mainwindow.py: the `machine_code` hand-off is at :1213-1214 (call opens
on 1213, argument on 1214).

Fix: The preview text is the *display* half of the encoder, not the wire
half -- the binary chunk list is untouched by any change to `text`. The
shared rule the app already owns is `Unit.from_base()` / `Unit.label`
(`shared/units/definitions.py:29-36`): render the preview line through
it, so it reads `SPEED 200.0 mm/s` in whatever unit
`config.unit_preferences['speed']` names, matching every SpeedSpinRow.
Missing token today: there is no unit-formatting helper outside
`UnitSpinRow`; add one `format_in_display_unit(value_base, quantity) ->
str` in `shared/units/` and let both the spin row and the preview use
it.

PROTECTED: swiftcut/machine/driver/ruida/** (ruida_encoder.py) and the
.rd/build_rd_bytes job path. The change is confined to the `text:
list[str]` argument; the `binary: list[bytes]` chunks and
`_speed_to_um_s` conversion must not be touched. Reported, not to be
edited without owner sign-off.

**B7 — INCONSISTENT — Console dock prints the Home/park speed in mm/min, four rows from a jog field reading mm/s**

`swiftcut/machine/driver/ruida/ruida_driver.py:798-803` logs `f"Home:
parking at the top-left corner (...) mm at {self._jog_speed_mm_min}
mm/min"` with `extra=self._log_extra("MACHINE_EVENT")`. That category is
admitted to the user-facing console: `swiftcut/logging_setup.py:39-45`
lists `MACHINE_EVENT` in `UILogFilter.UI_CATEGORIES`, `:244` sets
`ui_handler.setLevel(logging.INFO)`, and
`swiftcut/ui_gtk/machine/console.py:243-249,411-427` renders exactly
those records into the Console dock (`docs/design/audit/dock-
console-*.png`). The default is `DEFAULT_JOG_SPEED = 12000  # mm/min,
200 mm/s` (`ruida_driver.py:80`), so the Console reads "12000 mm/min"
while the Jog Speed SpeedSpinRow in the same bottom panel
(`swiftcut/ui_gtk/doceditor/bottom_panel.py:425-426`) reads "200.0
mm/s". I checked every console-visible log call (31 with a UI category)
by AST; this is the only one that states a speed unit, so it is a single
site, not a pattern.

Citation corrected on verification: Same fix-section error as idx 120:
the finding proposes a new `format_in_display_unit` helper, but
swiftcut/shared/units/formatter.py:13 `def format_value(value_in_base:
float, quantity: str) -> str` already does exactly this (returns value +
`display_unit.label`). The fix is "call the existing formatter", not
"add a shared helper".

Fix: Same shared rule as the preview: any speed shown to a user goes
through the display-unit formatter. Because this is one call site the
correct fix is still the shared helper (`format_in_display_unit`), not
an inline `/60` -- an inline divide would make this the second place in
the app that knows the mm/min:mm/s ratio.

PROTECTED: swiftcut/machine/driver/ruida/** (PROTECTED) and jog-panel
behaviour. Only the log message text changes; `self._jog_speed_mm_min`
and `_set_travel_speed(self._jog_speed_mm_min)` at :804 must stay in
mm/min.

**B8 — INCONSISTENT — Pass-1 T5 is only half fixed: units now appear as a suffix AND still in titles AND still in subtitles**

The unit-aware half IS fixed --
`swiftcut/ui_gtk/shared/pref_rows/unit_spin_row.py:70-73` now creates
`self._unit_label` and appends it to `self._suffix`, and `:118` sets
`self._unit_label.set_label(self._unit.label)`, so Max Cut Speed /
Acceleration / Offset now show mm/s, mm/s2, mm inline. T5's "Distance in
machine units" on Jog Distance is gone (an AST scan of every user-
visible string for 'machine unit' returns only the Machine Unit System
combo at `swiftcut/ui_gtk/machine/general_preferences_page.py:164`).
Still unfixed, T5 convention 1 (unit in the title):
`swiftcut/ui_gtk/settings/general_preferences_page.py:262` `'Cache
budget (MB)'` -- the exact example pass-1 cited -- plus
`material_test_grid_page.py:187,203,215,330` `'Fixed Power (%)'`,
`'Minimum Power (%)'`, `'Maximum Power (%)'`, `'Label Engrave Power
(%)'`. Still unfixed, T5 convention 2 (unit in the subtitle):
`swiftcut/ui_gtk/machine/laser_control_widget.py:93` `'Laser power in
percent'`, `swiftcut/ui_gtk/machine/head_preferences_page.py:475,606`
`'Power value in percent to use when focusing/framing. 0 to disable'`,
`.../laser_essentials/widgets/rows/pwm_row.py:51` `'Laser PWM frequency
in Hz'`, `.../widgets/raster_page.py:272` `'Angle of scan lines in
degrees'`. So the app now shows three unit conventions at once instead
of two.

Citation corrected on verification: Off-by-one line numbers: the
`_unit_label` creation/append is unit_spin_row.py:71-74 (not 70-73), and
`self._unit_label.set_label(self._unit.label)` is at :119 (not :118).
raster_page.py: the ActionRow statement opens at :272 but the subtitle
string is at :274. material_test_grid_page.py :187/:203/:215/:330 are
the `create_slider_row(` statement starts; the `(%)` title strings are
on :188/:204/:216/:331. Also incomplete: the old tooltip convention was
NOT retired - unit_spin_row.py:120-122 still sets `_("Value in {unit}")`
on the spin button alongside the new suffix, so the unit is now stated
twice on every unit-aware row.

Fix: The suffix slot already exists and already works --
`UnitSpinRow._unit_label`. The token gap is that `%`, `Hz`, `MB` and
`deg` are not registered quantities, so a row carrying one of them has
no way to reach that slot. Register them as fixed (non-convertible,
`selectable=False`) quantities in `shared/units/definitions.py`, give
`SpinRow` a plain `unit_suffix: str | None` that paints the same `sc-
caption` label, then strip the `(%)`/`(MB)` parenthetical from the 5
titles and the 'in <unit>' clause from the 5 subtitles. One widget
change, ten string edits, no new convention.

PROTECTED: Min/Max power labelling is PROTECTED. Changing 'Fixed Power
(%)' to 'Fixed Power' + a '%' suffix is a text move only; do not touch
the power value semantics or the Min/Max power rows in the step
settings.

**B9 — INCONSISTENT — Material-test dialog mixes unit-aware speed rows with hard-mm length rows in the same group**

In one dialog, `material_test_grid_page.py:236,246` use `SpeedSpinRow`
(follows `config.unit_preferences['speed']`, shows a live unit suffix)
while `:294-302`, `:305-313`, `:393-400`, `:408-415` use plain `SpinRow`
with the unit frozen into the caption: `'Bidir scan X-offset for first
row (mm)'`, `'Bidir scan X-offset for last row (mm)'`, `'Size of each
test square (mm)'`, `'Gap between test squares (mm)'`. `LengthSpinRow`
exists and is exported from the same package the file already imports
(`swiftcut/ui_gtk/shared/pref_rows/__init__.py`,
`length_spin_row.py:7`), so this is not a missing capability. If a user
selects inches in App Settings > General, Minimum Offset and Shape Size
stay in millimetres and still claim '(mm)' while the speed rows beside
them switch.

Fix: Shared-widget fix: swap the four `SpinRow` calls for
`LengthSpinRow` (passing `value_in_base=` instead of `value=`) and
delete the '(mm)' from their captions, since `UnitSpinRow` now paints
the unit itself. That is the same substitution the speed rows in this
file already made.

PROTECTED: laser_essentials is a KEEP/load-bearing addon per
docs/removal-inventory-2026-09-04.md. The four values are geometry
inputs to the material-test step; the swap must preserve base-unit
storage (`value_in_base`), not just rename the class.

**B10 — INCONSISTENT — 31 user-visible "G-code" strings in a Ruida-only fork, including the primary export button and the .gcode file it writes**

The toolbar's main export button is `_("Generate G-code")`
(`swiftcut/ui_gtk/toolbar.py:60`, restated at
`swiftcut/ui_gtk/mainwindow.py:1436`), its disabled tooltip is
`_("Select a machine to enable G-code export")` (`mainwindow.py:1419`),
and the menu item is `_("Export G-code...")` bound to `win.export`
(`swiftcut/ui_gtk/main_menu.py:40`) -- sitting one line above the
correctly-named `_("Export Ruida Job (.rd)...")` at `:41-42`. What
`win.export` actually writes is the Ruida pseudo-assembly:
`mainwindow.py:1878` calls `export_gcode_to_path`, which at
`swiftcut/doceditor/file_cmd.py:984-987` writes `artifact.machine_code`
-- the `SPEED/POWER/CUT_ABS` text built by `ruida_encoder.py:199` --
into a file the dialog names `output.gcode` with filter `_("G-code
files")` and mime `text/x.gcode`
(`swiftcut/ui_gtk/doceditor/file_dialogs.py:81,83,90,91`). The dock tab
showing that same text is `_("G-code Viewer")`
(`swiftcut/ui_gtk/doceditor/bottom_panel.py:184`). `docs/removal-
inventory-2026-09-04.md` A2 item 6 keeps the widget on the grounds that
"It renders the Ruida job preview" and keeps `hooks_macros_page` while
noting it is "Titled 'G-code Hooks' but macros run through run_raw" --
so the inventory's own verdict is that the feature stays and the *name*
was never revisited. Full inventory of the 31 strings obtained by AST
scan of every `_()`/setter literal.

Citation corrected on verification: file_cmd.py:984-987 is the guard `if
artifact.machine_code is None: raise ValueError("Final artifact is
missing G-code data.")`, NOT the write. The write is
file_cmd.py:989-991: `file_path.write_text(artifact.machine_code,
encoding="utf-8")`. Second overstatement: "What `win.export` actually
writes is the Ruida pseudo-assembly" is only true for a Ruida machine.
`swiftcut/machine/driver/` still holds `dummy.py` alongside `ruida/`,
and dummy.py:86-89 `create_encoder` returns a real
`GcodeEncoder(machine.dialect)`, which intent_builder.py:975-982 falls
back to - so on a NoDeviceDriver machine the button writes genuine
G-code and the label is correct. Finally, the "31 strings" figure is
unverified: a one-line-literal AST scan of swiftcut/ui_gtk finds 13
`_()` strings containing G-code/GCode, and a full-tree constant scan
finds ~25 plausibly user-visible ones; treat 31 as approximate.

Fix: One naming token, applied everywhere: the artifact this fork
produces is a 'machine job' (the code already calls it `machine_code`).
Rename the user-visible strings to that -- 'Export Job...', 'Generate
Job', 'Job Preview', 'Machine Commands' -- rather than renaming widget
by widget. Note that `_("Save G-code File")` / `_("G-code files")` in
`file_dialogs.py:67-99` is reachable only via `win.export`; if the owner
decides `win.export` is redundant next to `win.export-rd`, deleting the
action retires 6 of the 31 strings at once. Do not delete without an
owner decision -- the two exports produce different files.

PROTECTED: The `win.export` action runs through the pipeline job path
(`file_cmd.export_gcode_to_path` -> `artifact.machine_code`), which is
PROTECTED. Only the labels/tooltips/filter names should change; the
action wiring and the artifact must not.

**B11 — INCONSISTENT — Three different one-line descriptions of the product, one of them factually wrong**

`swiftcut/app.py:521-522` gives `swiftcut --help` the description `_("A
GCode generator for laser cutters.")` -- wrong for a fork whose only
driver is Ruida (`docs/removal-inventory-2026-09-04.md` A2 item 5
removes grbl/marlin/octoprint/smoothie; only 3 device profiles remain
under `swiftcut/resources/devices/`), and inconsistent in spelling with
the 31 'G-code' strings elsewhere. `data/org.ilab.SwiftCut.desktop:6`
says `Comment=Laser cutting and engraving`.
`data/org.ilab.SwiftCut.metainfo.xml:13` says `<summary>A desktop
application for laser cutting and engraving</summary>` while its
`<description>` at `:29-31` still claims GRBL support. Three surfaces,
three strings, no shared source.

Citation corrected on verification: The GRBL sentence is on a single
line, metainfo.xml:30: `SwiftCut support communicating with GRBL based
laser cutters.` (the cited :29-31 spans it, and the sic 'support' is in
the file). Minor overstatement, same as idx 126: 'a fork whose only
driver is Ruida' - `driver/dummy.py` (NoDeviceDriver) survives as an
explicit KEEP (removal-inventory line: "**`driver/dummy.py`
(NoDeviceDriver)** | **KEEP** | Protocol requires one no-device driver")
and dummy.py:86-89 still returns a `GcodeEncoder`, so the app is Ruida-
plus-no-device, not Ruida-only.

Fix: Missing token: there is an `APP_NAME` constant but no
`APP_TAGLINE`. Add `const.APP_TAGLINE` and use it for the argparse
description; make the .desktop `Comment` and the metainfo `<summary>`
copies of that same wording, and cover the three with the same
packaging-consistency test proposed for `Exec=`.

**B12 — INCONSISTENT — The published website is entirely still Rayforge: 500 files, 3434 lines, rayforge.org domain**

`grep -rli rayforge website/ | grep -v node_modules | wc -l` -> 500
files; 3434 matching lines. The site's own identity is Rayforge, not
just its prose: `website/docusaurus.config.js:22` `url:
'https://rayforge.org'`, `:28` `projectName: 'rayforge'`, `:3-10` a
`rayforgeVersionPlugin` injecting `RAYFORGE_VERSION`, `:70` registering
it. Blog posts are authored by `rayforge_team` and titled 'Welcome to
Rayforge: Modern Laser Control Software'
(`website/blog/2024-12-15-welcome-to-rayforge.md:2-6`), with GitHub
links pointing at `github.com/barebaric/rayforge` while the app's own
metadata already points at `github.com/ilab/swiftcut`
(`pyproject.toml:19-20`, `metainfo.xml:8-10`). The i18n trees replicate
every doc page across de/es/fr/pt-BR/uk/zh-CN, which is why the file
count is so high. Content is also stale beyond the name -- the docs
describe GRBL/G-code workflows and multi-laser gantries that this Ruida-
only fork removed.

Fix: Not a text-substitution job -- a scope decision that belongs to the
owner before any edit. Two coherent options: (a) if the site is not
being published for SwiftCut, delete `website/` and the
`.github/workflows/website.yml` that builds it, and record the verdict
in `docs/removal-inventory-2026-09-04.md` (which currently says nothing
about `website/`); (b) if it is, rebrand `docusaurus.config.js` first
(url/projectName/plugin name/version env var) since every page inherits
those, then regenerate the i18n trees rather than hand-editing 500
files. Flagging option (a) as likely, since commits be21b03a4/cb0a6baa1
already removed outbound links to properties that do not exist.

**B13 — MINOR — Untranslated developer English in two user-visible surfaces**

`swiftcut/ui_gtk/doceditor/image_metadata_dialog.py:115,122,129` call
`row.set_title("Source File")`, `row.set_title("UID")`,
`row.set_title("Renderer")` with bare literals, while the sibling group
header two lines above at `:108,110` correctly uses `_("Basic
Information")` and `_("Basic image properties like dimensions and
format.")`. `swiftcut/ui_gtk/addon_manager/addon_dialog.py:178` builds
`Gtk.Label(label=f"by {author_name}")` -- an untranslated f-string with
an English preposition, in the addon-install list. An AST scan of every
bare (non-`_()`) English literal reaching a GTK text setter across
`swiftcut/**/ui_gtk/**` returns exactly these plus two proper nouns that
correctly stay untranslated (`about.py:293` 'Samuel Abels', `:298` 'MIT
X11') and one dead `__main__` demo (`shared/draglist.py:244`, inside `if
__name__ == "__main__":` at `:239`).

Citation corrected on verification: The exhaustiveness claim ('an AST
scan ... returns exactly these plus two proper nouns and one dead
__main__ demo') is slightly incomplete. My own AST walk of bare string
constants reaching GTK text setters/kwargs across swiftcut/ui_gtk
(excluding tests) also returns swiftcut/ui_gtk/about.py:274 `'© 2025
Samuel Abels'` and swiftcut/ui_gtk/addon_manager/addon_dialog.py:265
`'URL'`. Both are defensible as untranslated (a copyright line and an
acronym), so the four sites the finding names are still the right four
to fix - but the scan it describes returns six, not four plus two.

Fix: Wrap the four strings in `_()` (`_("by
{author}").format(author=author_name)` for the addon label, so
translators can move the preposition). The durable fix is a gate, not
four edits: the existing `tests/ui_gtk/test_no_rayforge_branding.py`
already walks every UI text sink by AST -- add a second assertion in the
same walker that a multi-word English literal reaching a text setter is
wrapped in `_()`, with a small allow-list for proper nouns.

**B14 — MINOR — Raw Python exception text shown as a preference-row subtitle**

`swiftcut/ui_gtk/varset/adapter/appkey.py:220-223` sets
`self._row.set_subtitle(_("Connection failed:
{err}").format(err=str(e)))` where `e` is an
`OSError`/`TimeoutError`/`ValueError` from `urllib` -- so an
`Adw.ActionRow` subtitle in machine settings shows untranslated
developer text such as "<urlopen error [Errno 11001] getaddrinfo
failed>". The two neighbouring arms of the same try/except get this
right: `:207` `_("Too many requests. Try again later.")` and `:215`
`_("Request failed: {code}").format(code=e.code)` interpolate only a
code. An AST scan for `str(<exception>)` / `f"{e}"` reaching a text
setter across `swiftcut/**` returns this as the only such site outside
the toast path.

Citation corrected on verification: Supporting line numbers are off.
`_("Too many requests. Try again later.")` is at appkey.py:213 (not :207
-- line 207 is `if not app_token:`); `_("Request failed:
{code}").format(code=e.code)` is at appkey.py:217 (not :215 -- line 215
is the bare `else:`). The claim that this is 'the only such site outside
the toast path' is false: swiftcut/ui_gtk/about.py:121 `msg = f"failed
to find pyvips version: {e}"` and :130 `msg = f"failed to find libvips
version: {e}"` are each appended to the user-visible dependency list
(`graphics_deps.append(("pyvips", msg))` at :123,
`graphics_deps.append(("libvips", msg))` at :132), putting raw exception
text into the About dialog's system-info section. There are three such
sites, not one.

Fix: Follow the rule the same function already applies two lines up:
show a translated cause, log the detail. Replace with `_("Could not
reach the device. Check the hostname and port.")` and
`logger.warning(..., exc_info=e)`. This is the same class as the toast
finding -- the shared rule worth writing down once is 'exception text
goes to the log, never to a label'.

**B15 — MINOR — Translation catalogs were never regenerated after the rebrand, so the one rebranded _() string loses all six translations**

The catalogs are still keyed on the old domain and old msgids:
`swiftcut/locale/rayforge.pot` and `swiftcut/locale/{de,en,es,fr,pt,uk,z
h_CN}/LC_MESSAGES/rayforge.{po,mo}`. The gettext binding matches them,
so translation itself works (`swiftcut/app.py:85-86`
`bindtextdomain("rayforge", ...)` / `textdomain("rayforge")`, and
`data/org.ilab.SwiftCut.metainfo.xml:23` `<translation
...>rayforge</translation>`). The breakage is msgid drift:
`swiftcut/ui_gtk/about.py:391-394` now reads "...donated to support
SwiftCut! You keep the coffee and the AI tokens flowing!", but the
catalogs still key that entry on the Rayforge wording
(`locale/rayforge.pot:7603`, `de/.../rayforge.po:8063-8066`, and the
same in es/fr/pt/uk/zh_CN), so the lookup misses and the About dialog
falls back to English in all six locales. An AST scan confirms this is
the only live `_()` string containing 'SwiftCut', so the blast radius is
one string. The other 12 Rayforge msgids in the .pot are dead -- I
grepped each and none has a live call site (they belong to the removed
update checker and telemetry consent, `docs/removal-
inventory-2026-09-04.md` A1 items 2 and 3).

Fix: Regenerate the .pot from source and merge into the seven .po files
(`msgmerge`), then rebuild the .mo -- that both restores the About line
and drops the 12 dead Rayforge msgids in one pass. If the domain is ever
renamed rayforge->swiftcut, all four places must move atomically:
`app.py:85-86`, the `LC_MESSAGES/*.mo` filenames, the .pot, and
`metainfo.xml:23`. Renaming any one alone silently disables every
translation in the app, which is why this belongs with the internal-
identifier group below rather than being done piecemeal.

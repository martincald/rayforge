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
`.sc-toolbar > .sc-split > button`, but `SplitMenuButton`
(`shared/splitbutton.py:37`) adds only `linked`. The undo/redo,
arrange and tabs split buttons therefore keep libadwaita's grey
capsule while every plain toolbar button beside them is a white
bezel button — plainly visible in `toolbar-light-1280.png`, where the
row reads as two different button families.

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

# Swift Cut layout tokens

The companion to `swift-cut-tokens.md`. That document maps colour,
radius and type; this one maps **space, size and rhythm** — the layer
the reskin never had, and the one
`docs/design/audit/AUDIT.md` found missing in every panel.

The rule this document exists to enforce: **a widget never picks its
own spacing, control size or row height.** It names a role, and the
role has one value. Every value lives in one module,
`swiftcut/ui_gtk/layout.py`: Python reads its constants (margins, box
spacing, size requests), and every stylesheet in `ui_gtk` - the theme's
in `swiftcut/ui_gtk/theme.py` and each widget's own - names a role from
its `CSS_LENGTHS` through `layout.stylesheet()` instead of writing a
length. No other module in `ui_gtk` writes a pixel length; a test
(`tests/ui_gtk/test_dock_density.py`) greps for one.

**Units.** Every px value below is a size *at the design's 13px type*,
not a pixel count. `layout.scaled()` multiplies it by the system UI
font over 13px, and `theme.py` writes it as `rem` (`layout.rem()`), so
the layout follows the platform's type size: 12px on macOS (the
tokens run at 12/13), 14.7px for GNOME's 11pt at 96 dpi. libadwaita
lengths in `sp` are pixels × dpi/96, which is 0.75 on macOS, so a
token handed to libadwaita (`Adw.Clamp`, `Adw.Breakpoint`) is given in
`px`. Captures at 13" and 27" sizes are in `screens/macos-fit/`.

---

## 1. Spacing — a 4px scale, by role

Five steps. Nothing between them, nothing outside them.

| Token | px | Role |
| --- | --- | --- |
| `SPACE_TIGHT` | 4 | Inside one control: icon to its caption, a chip's padding |
| `SPACE_CONTROL` | 8 | Between sibling controls: buttons in a row, cells in the jog grid |
| `SPACE_GROUP` | 12 | Between groups, and a panel's own padding |
| `SPACE_SECTION` | 16 | Between sections of a page |
| `SPACE_PAGE` | 24 | A page's outer margin |

The app arrived at three overlapping scales (audit S1): 12 and 6 from
GNOME, 4/8/16/24 from a 4px scale, and 9/10/18/2/3/5 from nowhere.
Converting to the table above:

| was | becomes | because |
| --- | --- | --- |
| 2, 3, 5 | `SPACE_TIGHT` (4) | all of them are icon-to-label or chip padding |
| 6 | `SPACE_CONTROL` (8) | between controls |
| 6 | `SPACE_TIGHT` (4) | when it is inside one control |
| 9, 10 | `SPACE_GROUP` (12) | all are panel padding |
| 18, 20 | `SPACE_SECTION` (16) | |
| 32, 50 | `SPACE_PAGE` (24) | all are dialog page insets |

libadwaita's own internal row padding is not ours to move; the scale
governs the space **we** put between widgets.

One number stays as a number: `mainwindow.py`'s `set_margin_end(454)`
on the canvas overlays. It is not a gap but the right pane's width
plus its margins, used to keep the overlay clear of the pane, and it
should really be derived from that width rather than restated — a
separate fix from this one.

---

## 2. Control sizes — one density

The brief asks for one size per type per density context. There is
one context, **compact** (`layout.COMPACT`), and it covers the toolbar,
the dock rail, the canvas overlays and the whole dock: layer cards,
machine panel, jog grid, scale buttons and position readout.

| Token | px | Role |
| --- | --- | --- |
| `CONTROL_SIZE` | 32×32 | every icon and short-label button |
| `ICON_GLYPH` | 16 | every icon glyph |
| `JOG_CELL` | 40×40 | every button in the jog grid, bezel included |
| `SPIN_WIDTH` × `SPIN_HEIGHT` | 96×28 | every spin field in the dock, − and + included |
| `COMPACT_SPACE_CONTROL` | 4 | between sibling controls in the dock |
| `COMPACT_SPACE_GROUP` | 8 | a dock panel's side padding, between its groups |

The jog grid used to be a second, *touch* context at 60×60. At 2×
HiDPI that made the dock 40% of a 13" window, so it joins the compact
density at 40: still the biggest target in the app, but one cell of
the same system.

Every icon glyph is `ICON_GLYPH` = **16px**, in both contexts. A jog
button is a bigger target, not a bigger picture.

Images that are not icons keep their own sizes and are not governed
here: the About logo, asset thumbnails, the controller product shot.

This replaces the five sizes the audit found (S5): toolbar ~30×28,
rail 28 padded 2, overlay 28 padded 0, panel rows 40×auto, jog 60×60.

---

## 3. The row contract

A settings row is the app's most repeated shape, so it gets the
tightest contract.

| Token | px | Rule |
| --- | --- | --- |
| `ROW_MIN_HEIGHT` | 48 | Dialog and page rows |
| `ROW_MIN_HEIGHT_COMPACT` | 32 | Rows in the dock: settings rows, layer headers, operations |
| `PANEL_MAX_WIDTH` | 400 | A group inside a dock panel stops here |

Three rules follow from those numbers:

1. **A caption is one line.** Row height varied by up to 40% inside a
   single group (audit S3) purely because subtitles wrapped. A
   minimum height only helps if nothing exceeds it, so the caption
   rule in §5 is load-bearing, not cosmetic.
2. **A group does not stretch.** `PANEL_MAX_WIDTH` is what closes the
   100-140px hole between a label and its controls in the dock
   (audit S4). Rows in a dialog keep libadwaita's own clamp.
3. **Suffixes are built one way.** Every row's trailing controls go in
   a box from `layout.suffix_box()` — one spacing, one alignment, one
   trailing edge. A flat icon button has no frame, so what the eye
   lines up on is its *glyph*, inset by half the button; dropping the
   button from 40px to `CONTROL_SIZE` cuts that inset from 12px to
   8px and makes it the same in every row, which is what closes the
   ragged right edge the audit measured (A1).

---

## 4. Radii

No new values. The map in `swift-cut-tokens.md` §1.4 is the whole
set; the audit found eight radii in use against its five, all of the
extras predating the reskin.

| Role | px | Applies to |
| --- | --- | --- |
| Toolbar / panel button | 7 | `.sc-toolbar button`, panel row buttons |
| Jog button | 6 | `.sc-jog button` |
| Panel, workflow card | 10 | `.card`, preferences groups |
| Inner card, wcs group | 8 | nested cards |
| Floating surface | 10 | `.sc-overlay`: the Workflow and Properties cards, canvas toolbars, drop HUD, status labels (`swift-cut-tokens.md` §3.6) |
| Chip, spinner, dock pip | 5 | `.sc-rail button`, tags, badges |

Retired: 12 (was preferences groups and expanders), 4 (dock rail), 1
(workflow row), 3 (G-code viewer), 9 (canvas overlays, now the one
floating radius). `round_button`'s 32px stays — it is a circle, not
a radius.

---

## 5. Typography, captions and units

### 5.1 Four roles, one class each

| Role | Class | Rule |
| --- | --- | --- |
| Title | `.sc-title` | 13px, weight 600 |
| Label | *(inherit)* | 13px, the row title |
| Dimmed label | `dim-label` | 13px, dimmed — a full-size secondary label |
| Caption | `.sc-caption` | 11px, `@sc_fg_dim`, **one line** — one step below the body, everywhere |
| Mono numeric | `.sc-numeric` | tabular figures |

The body is the system font, in the dock as everywhere else: the 11.5px
panel body and the 9px jog caption of `swift-cut-tokens.md` §1.5 are
gone, so a caption is one step below whatever the body is.

The audit called `dim-label` and `caption` two vocabularies for one
role (T1). They are not quite: a *dimmed label* is full-size
secondary text (an empty-state placeholder, a hint) and a *caption*
is 11px. The fault was that seven of the ten `caption` uses also
carried `dim-label`, which is what made the pair look
interchangeable — a caption is dim by definition, so `.sc-caption`
sets the colour and the size together and the pairing is gone.

`.sc-title` is defined in `swift-cut-tokens.md` §1.5 but was never
implemented; this is where it lands.

### 5.2 A caption earns its line

A caption **says something the label does not**. It never restates
the label ("Jog Speed" / "Speed"), never repeats it verbatim
("Width" / "Width"), and never names a unit — that is the field's
job. If there is nothing to add, there is no caption; the row is
shorter and the group is more even for it.

### 5.3 Units appear exactly once, in the field

The unit is a **suffix inside the field**, rendered as
`.sc-caption` immediately after the value. Never in the title, never
in the caption, never only in a tooltip.

This is a reversal of a deliberate earlier choice —
`UnitSpinRow.update_unit_and_bounds()` put the unit in a tooltip
*"rather than repeated in every subtitle or as a suffix"*. The reason
to reverse it is in the audit (T5): four rows checked at random
(Max Cut Speed, Acceleration, Offset, Overcut) show a bare number
with no visible unit anywhere, and a value whose unit is only
discoverable by hovering is a value an operator will get wrong.

Because every unit-aware row goes through `UnitSpinRow`, this is one
change serving 110 rows, not 110 edits.

### 5.4 One placeholder

An unknown value is `—`, one em dash, everywhere. Not `---`, not
`-`, not an empty string.

### 5.5 One position readout

Position is rendered by one widget in one format:

```
X 12.3  Y 45.6        machine coordinates, 1 decimal, .sc-numeric
```

The dock panel showed three readouts in three formats four rows apart
(audit T3). The WCS row keeps its *offsets* — those are a different
quantity — but in the same format, and the duplicate
"Current Position" row goes.

---

## 6. Where each rule lives

| Rule | Home |
| --- | --- |
| Every value: spacing, control sizes, row heights, max widths, radii, strokes, shadows | `swiftcut/ui_gtk/layout.py` (`COMPACT`, constants, `CSS_LENGTHS`) |
| Icon-button sizing, dock row rhythm, spin fields, radii, type roles | `swiftcut/ui_gtk/theme.py` (`_LAYOUT`, naming roles) |
| Suffix box, row-action buttons, compact spin field, position formatting | `swiftcut/ui_gtk/layout.py` (helpers) |
| Unit suffix | `swiftcut/ui_gtk/shared/pref_rows/unit_spin_row.py` |

### 6.1 The legacy colour names

`theme.py` now also defines the GTK3-era `@theme_*` names in terms of
the Swift Cut tokens, because 14 files still colour themselves with
them (audit X3) and were following the stock theme as a result:

| Legacy name | Swift Cut token |
| --- | --- |
| `@theme_bg_color` | `@sc_panel_bg` |
| `@theme_fg_color` | `@sc_fg` |
| `@theme_base_color` | `@sc_card_bg` |
| `@theme_selected_bg_color` | `@sc_accent` |
| `@theme_selected_fg_color` | `#FFFFFF` |

Every one of those 39 uses is a background, a subtle `alpha()` fill,
or a selection highlight, so the mapping is exact. Defining the
aliases is preferred over editing 14 files: it is one rule, and it
keeps working for code not yet written.

### 6.2 Density classes

Three container classes carry the compact context, alongside the two
that already exist:

| Class | Surface | Added by |
| --- | --- | --- |
| `.sc-toolbar` | main toolbar | existing |
| `.sc-jog` | jog grid | existing |
| `.sc-panel` | a settings group in a dock panel | existing |
| `.sc-rail` | dock icon strip | **new** — the rule existed, nothing wore the class |
| `.sc-overlay` | every floating surface: canvas toolbars, the Workflow and Properties cards, drop HUD, status labels; also the one material (`swift-cut-tokens.md` §3.6) | **new** |
| `.sc-split` | split menu buttons | **new** — same, the rule existed and matched nothing |

---

## 7. The dock at compact density

The dock is built from `layout.COMPACT` and nothing else. At a 13"
MacBook's 1440×900 it used to take 351 of 900 pixels (39%); it now
takes 209 (23%), which leaves 70.6% of the window above it for the
toolbar and canvas. Captures and measurements at 1440×900 and
2560×1440, light and dark, are in `screens/compact-dock/`, taken with
`scripts/screenshot/dock_fit.py`.

- **Layer cards.** One header line - colour chip, name, what the layer
  is as a caption beside it, then its actions - and one operations
  row. The item list below grows with its items from a minimum of one
  row and scrolls once the dock is shorter than it. A card is as tall
  as its content, and a long layer never makes the dock taller.
- **Machine panel.** Rows are one compact row, title and caption
  included. The settings list stops at `PANEL_MAX_WIDTH`, and every
  row's controls end at one edge: the spin fields are one width and
  their units share one column.
- **Jog grid.** Every button - arrows, Home, Go Scale, Cut Scale and
  the job column - asks for one `JOG_CELL`, and the readout is a cell
  of the same grid.
- **Height.** The dock opens at its content's height. The paned handle
  above it drags it taller; View ▸ Show Bottom Panel (and the toolbar
  and status bar toggles) collapses it and brings it back at the same
  height. A height the user dragged to is kept across launches; one
  the paned only worked out from the content is not, so the default
  follows the content.
- **Windows.** Same tokens, same values. They are design pixels at the
  system font, and GTK folds the platform's DPI into that font, so a
  scaled Windows display scales the dock the way it scales its text.
  Were a platform ever to need other values, `layout.COMPACT` is the
  one place that would say so.

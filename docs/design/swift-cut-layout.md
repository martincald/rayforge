# Swift Cut layout tokens

The companion to `swift-cut-tokens.md`. That document maps colour,
radius and type; this one maps **space, size and rhythm** — the layer
the reskin never had, and the one
`docs/design/audit/AUDIT.md` found missing in every panel.

The rule this document exists to enforce: **a widget never picks its
own spacing, control size or row height.** It names a role, and the
role has one value. Where GTK CSS can express the rule it lives in
`rayforge/ui_gtk/theme.py`; where only Python can (margins, box
spacing, size requests) it lives in `rayforge/ui_gtk/layout.py`.

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

## 2. Control sizes — two density contexts

The brief asks for one size per type per density context, so the
contexts are named first. There are two, not five:

| Context | Where | Token | Size |
| --- | --- | --- | --- |
| **Compact** | toolbar, panel rows, dock rail, canvas overlay | `CONTROL_SIZE` | 32×32 |
| **Touch** | the jog grid, and only the jog grid | `JOG_CELL` | 60×60 |

The jog grid is the one surface an operator hits while watching the
machine rather than the screen; everything else is pointer work at
pointer size. That is the whole justification for a second context,
and no third one is warranted.

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
| `ROW_MIN_HEIGHT_COMPACT` | 40 | Rows in a dock panel (`.sc-panel`) |
| `PANEL_MAX_WIDTH` | 340 | A group inside a dock panel stops here |

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
| Panel, workflow card | 10 | `.card`, preferences groups, expanders |
| Inner card, wcs group | 8 | nested cards |
| Canvas overlay | 9 | `.sc-overlay` |
| Chip, spinner, dock pip | 5 | `.sc-rail button`, tags, badges |

Retired: 12 (was preferences groups and expanders), 4 (dock rail), 1
(workflow row), 3 (G-code viewer). `round_button`'s 32px stays — it
is a circle, not a radius.

---

## 5. Typography, captions and units

### 5.1 Four roles, one class each

| Role | Class | Rule |
| --- | --- | --- |
| Title | `.sc-title` | 13px, weight 600 |
| Label | *(inherit)* | 13px, the row title |
| Dimmed label | `dim-label` | 13px, dimmed — a full-size secondary label |
| Caption | `.sc-caption` | 11px, `@sc_fg_dim`, **one line** |
| Jog caption | `.sc-jog .sc-caption` | 9px, from `swift-cut-tokens.md` §1.5 |
| Mono numeric | `.sc-numeric` | tabular figures |

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
| Spacing scale, control sizes, row heights, max widths | `rayforge/ui_gtk/layout.py` (constants) |
| Icon-button sizing, row minimum height, radii, type roles | `rayforge/ui_gtk/theme.py` (`_LAYOUT`) |
| Suffix box, row-action buttons, position formatting | `rayforge/ui_gtk/layout.py` (helpers) |
| Unit suffix | `rayforge/ui_gtk/shared/pref_rows/unit_spin_row.py` |

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
| `.sc-overlay` | canvas overlays | **new** |
| `.sc-split` | split menu buttons | **new** — same, the rule existed and matched nothing |

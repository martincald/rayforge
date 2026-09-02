# Swift Cut reskin — token and icon map

Direction A only: *"Reskin, same layout, new material"* (deck slides
5–7). Every panel, control and signal handler stays where and what it
is. Only surfaces, tokens, icons, typography and a few in-place
presentational details change.

**Source of truth.** `Swift Cut Redesign.dc.html`, turn 3, artboards
`3a` (light) and `3b` (dark), in the Claude Design project
`51c7ad84-fcc2-466d-9e3f-ed1c51f24c47`, imported through the
`claude_design` MCP. Turn 1 (Apple pass) and turn 2 (docked
exploration, 3D simulation) are explicitly **out of scope**.

Every value below was read out of those two artboards, not invented.

---

## 1. Token map

### 1.1 Palette (deck brief)

| Token | Value | Where it is allowed |
| --- | --- | --- |
| `blue-light` | `#7CBEFF` | Accent text on dark only |
| `blue-brand` | `#2F7BFF` | Selection, focus, the single primary action |
| `blue-deep` | `#0B3BD1` | Accent text on light only |
| `shadow-blue` | `#04227A` | Panel drop shadows (at low alpha) |
| `glass-white` | `#FFFFFF` → `#C9D0FF` | Light bezel fill |
| `glass-shade` | `#3E7BE6` | Dark bezel fill |
| `spark` | `#FFF6DC` → `#FFE9AB` | **Reserved:** laser-live indicator only |
| `layer-magenta` | `#D63AD6` | Layer colour — unchanged, kept as-is |
| `red` | `#FF3B30` | Stop button and no-go zones only |

`spark` appears nowhere in artboards 3a/3b. It comes from the deck
brief and is used on exactly one widget: the laser-live indicator.

### 1.2 Surface tokens

GTK name is the `@define-color` this reskin installs. Light and dark
are swapped wholesale when the colour scheme changes (§3.4).

| GTK token | Light | Dark |
| --- | --- | --- |
| `sc_window_bg` | `#F5F5F7` | `#1C1C1E` |
| `sc_canvas_bg` | `#F5F5F7` | `#1C1C1E` |
| `sc_header_bg` | `rgba(246,246,248,0.88)` | `rgba(44,44,46,0.88)` |
| `sc_panel_bg` | `#FBFBFD` | `#232325` |
| `sc_rail_bg` | `#F2F2F5` | `#1E1E20` |
| `sc_card_bg` | `#FFFFFF` | `rgba(255,255,255,0.05)` |
| `sc_button_bg` | `#FFFFFF` | `rgba(255,255,255,0.10)` |
| `sc_button_hover` | `#F7F7F9` | `rgba(255,255,255,0.14)` |
| `sc_bezel` | `rgba(0,0,0,0.15)` | `rgba(255,255,255,0.12)` |
| `sc_hairline` | `rgba(0,0,0,0.10)` | `rgba(255,255,255,0.12)` |
| `sc_hairline_soft` | `rgba(0,0,0,0.08)` | `rgba(255,255,255,0.10)` |
| `sc_fg` | `#1D1D1F` | `#F5F5F7` |
| `sc_fg_dim` | `rgba(60,60,67,0.6)` | `rgba(235,235,245,0.6)` |
| `sc_fg_faint` | `rgba(60,60,67,0.5)` | `rgba(235,235,245,0.5)` |
| `sc_accent` | `#2F7BFF` | `#2F7BFF` |
| `sc_accent_text` | `#0B3BD1` | `#7CBEFF` |
| `sc_accent_soft` | `rgba(47,123,255,0.14)` | `rgba(47,123,255,0.28)` |
| `sc_accent_ghost` | `rgba(47,123,255,0.12)` | `rgba(47,123,255,0.12)` |
| `sc_fill_subtle` | `rgba(0,0,0,0.03)` | `rgba(255,255,255,0.035)` |
| `sc_shadow` | `rgba(4,34,122,0.10)` | `rgba(0,0,0,0.40)` |
| `sc_ok` | `#34C759` | `#34C759` |
| `sc_danger` | `#FF3B30` | `#FF3B30` |
| `sc_layer_magenta` | `#D63AD6` | `#D63AD6` |

### 1.3 Bezel — the "half-pixel edge"

The deck draws button edges differently per theme. Both become a 1px
inset border with alpha (see §3.2 for why half-pixel is dropped):

* **Light** — outer ring `0 0 0 .5px rgba(0,0,0,.15)` plus a
  `0 1px 1px rgba(0,0,0,.06)` lift → `border: 1px solid @sc_bezel`
  over `@sc_button_bg`.
* **Dark** — top highlight `inset 0 .5px 0 rgba(255,255,255,.12)`
  over a `rgba(255,255,255,.1)` fill → `border: 1px solid @sc_bezel`
  over `@sc_button_bg`.

Separators are 1px `@sc_hairline`, never a decorative bar.

### 1.4 Radii

| Element | Deck | GTK |
| --- | --- | --- |
| Window | 11px | window-managed, untouched |
| Toolbar / panel button | 7px | `7px` |
| Jog button | 6px | `6px` |
| Panel, workflow card | 10px | `10px` |
| Inner card, wcs group | 8px | `8px` |
| Canvas overlay | 9px | `9px` |
| Chip, spinner, dock pip | 5px | `5px` |

### 1.5 Typography

System font at system sizes. **No bundled font, no `font-family`
declaration at all** — GTK's default font *is* the system font, and
naming a family would break the non-Latin fallback chain.

Only sizes are set, from the deck's scale (deck px → GTK `pt`-free
`px` at the same nominal 13px base):

| Role | Deck | Rule |
| --- | --- | --- |
| Window base | 13px | inherit (no rule) |
| Title (semibold) | 13px / 600 | `.sc-title` |
| Row title | 13px | inherit |
| Row subtitle, dim caption | 11px | `.caption` (existing) |
| Panel body, wcs rows | 11.5px | `.sc-panel` |
| Position readout, mono | 11.5px | `.numeric` (existing) |
| Jog button caption | 9px | `.sc-jog caption` |
| Ruler / axis label | 9.5px | canvas-drawn, unchanged |

`font-variant-numeric: tabular-nums` on readouts — GTK equivalent is
`font-feature-settings: "tnum" 1`, which the position readout and the
G-code line counter get.

No accent lines and no decorative bars anywhere.

---

## 2. Icon map

### 2.1 What the design actually ships

`assets/icons/` holds 48 icons × 5 tints (`-b` brand blue, `-d` dark
ink `#1D1D1F`, `-g` grey, `-r` red, `-w` white) = 240 files.

**They are not new artwork.** Each is the *existing Rayforge icon
geometry*, byte-identical in path data, with only the `fill`
attribute changed and a C2PA metadata block added. Verified against
`arrow-north`, `frame` and `home`; the design project also carries a
copy of `rayforge/resources/icons/*-symbolic.svg` that matches the
repo exactly. The five tints exist because HTML `<img>` cannot
recolour an SVG — they are a mockup device, not a deliverable.

All 48 names the deck uses already exist in
`rayforge/resources/icons/` (checked, zero missing).

### 2.2 Consequence for GTK

GTK4 recolours any icon whose filename ends in `-symbolic.svg` by
injecting `path { fill: <color> !important }`, so one asset already
serves both themes and every tint. The brief's own preference —
*"prefer symbolic recoloring where GTK allows so one asset serves
both themes, else use the -d/-w variants"* — therefore resolves to
**import nothing**. Copying 240 hard-tinted duplicates in would
*remove* theme-following behaviour the app has today.

So Commit B is not an asset import. It is wiring the deck's **tint
semantics** — which tint appears where — onto the existing symbolic
icons via the CSS `color` property.

### 2.3 Tint semantics (deck → GTK)

| Deck tint | Meaning in the deck | GTK rule |
| --- | --- | --- |
| `-d` (`#1D1D1F`) @ 78% | Resting icon, light theme | `color: @sc_fg` at `opacity: .78` |
| `-w` (`#FFFFFF`) | Icon on a filled blue/magenta chip | `color: #fff` on `.suggested-action`, active toggle |
| `-b` (`#2F7BFF`) | Icon in an *active* toggle | `color: @sc_accent` on `:checked` |
| `-r` (`#FF3B30`) | Stop only | `color: @sc_danger` on `.destructive-action` |
| `-g` | Disabled / rail | `:disabled` at theme alpha |

### 2.4 Per-widget map

Names below are the existing `get_icon()` names; the "deck tint"
column records which variant the artboard uses so the CSS matches.

| Widget | Icon name | Light | Dark |
| --- | --- | --- | --- |
| Toolbar open / save / save-as / download / export | `open`, `save`, `save-as`, `download`, `export` | `-d` .78 | `-w` .78 |
| Toolbar undo / redo (split) | `undo`, `redo` | `-d` .78 | `-w` .78 |
| Toolbar 3D / refresh | `3d`, `refresh` | `-d` .78 | `-w` .78 |
| Toolbar jog toggle (**active**) | `jog` | `-b` on `@sc_accent_soft` | `-b` on `@sc_accent_soft` |
| Toolbar align / tabs (split) | `align-horizontal-center`, `tabs-equidistant` | `-d` .78 | `-w` .78 |
| Toolbar home / frame | `home`, `frame` | `-d` .78 | `-w` .78 |
| Toolbar send (**primary**) | `send` | `-b` | `-b` |
| Toolbar pause / stop / clear-alarm / laser | `pause`, `stop`, `clear-alarm`, `laser-on` | `-d` .78 | `-w` .78 |
| Canvas overlay toggles (all active) | `visibility-on`, `tabs-visible`, `travel-path`, `block` | `-d` on `@sc_accent_soft` | `-w` on `@sc_accent_soft` |
| Workflow add | `add` | `-d` | `-w` |
| Step settings / delete | `settings` | `-d` .7 | `-w` .7 |
| Dock rail (inactive) | `image-x-generic`, `terminal`, `layers`, `laser-on` | `-d` .55 | `-w` .55 |
| Dock rail (active pip) | `gcode`, `jog` | `-w` on `@sc_accent` | `-w` on `@sc_accent` |
| WCS edit | `edit` | `-d` | `-w` |
| Current-position corners | `bottom-left`, `center`, `top-right`, `goto-origin` | `-d` | `-w` |
| **Start corner (unselected)** | `top-left`, `top-right`, `bottom-left`, `bottom-right` | `-d` | `-w` |
| **Start corner (selected)** | same | `-w` on `@sc_accent` | `-w` on `@sc_accent` |
| Zero axes | `zero-here`, `crosshairs` | `-d` | `-w` |
| **Jog arrows ×8** | `arrow-{north,north-east,east,south-east,south,south-west,west,north-west}` | `-d` | `-w` |
| **Jog Home (centre)** | `home` | `-d` .75 | `-w` .75 |
| **Go Scale** | `frame` | `-d` .75 | `-w` .75 |
| **Cut Scale** | `laser-on` ← *was* `frame` | `-d` .75 | `-w` .75 |
| **Start (primary)** | `send` | `-w` on `@sc_accent` | `-w` on `@sc_accent` |
| **Pause** | `pause` | `-d` | `-w` |
| **Stop** | `stop` | `-r` | `-r` |
| **Z up / Z down** | `arrow-z-up`, `arrow-z-down` | `-d` | `-w` |

The only icon *name* change in the whole map is **Cut Scale**:
`frame-symbolic` → `laser-on-symbolic`, which is what artboard 3a
draws and which stops Go Scale and Cut Scale being the same glyph.
The button's label, handler and confirmation flow are untouched.

---

## 3. Platform reality check

### 3.1 True vibrancy — not possible

The deck's header, canvas overlay and job card use
`backdrop-filter: blur(30px) saturate(180%)`. GTK4 CSS has no
`backdrop-filter` and no way to sample what is behind a widget.

**Fallback, in order:**

1. Where the compositor gives the window an alpha channel, the
   header and the canvas overlay use their rgba token
   (`@sc_header_bg` at 0.88) so they at least sit *lighter* than the
   window and pick up the window background beneath them.
2. Otherwise the alpha composites against the opaque window
   background, which lands on solid `#F6F6F8` / `#2C2C2E` — the
   glass-white / glass-shade fallback the brief asks for. This is
   what will happen on Windows in practice.

No blur, no saturation boost. Documented, not attempted.

### 3.2 Half-pixel bezel — approximated

GTK4 rounds border and box-shadow spreads to device pixels, so
`0.5px` is either 0 or 1 depending on scale factor and is not
stable across monitors. Per the brief, the bezel is drawn as a
**1px inset border with alpha** (`@sc_bezel`), which reads at the
same weight at 1× and stays crisp at 2×.

### 3.3 System font — no bundle

GTK's default font is already the platform system font. The theme
sets sizes only and never `font-family`. No font is bundled.

### 3.4 Light/dark switching

libadwaita picks dark by swapping its own stylesheet, so a single
static sheet cannot carry both token sets. The theme installs one
`Gtk.CssProvider` and reloads it with the light or dark
`@define-color` block on `AdwStyleManager::notify::dark`. The
existing `apply_css()` helper is `@once_per_object` and appends a
provider per call, so it cannot reload — the theme owns its own
provider and leaves `apply_css()` alone.

### 3.5 Dropped — cannot be done without moving a control

| Deck element | Why it is skipped |
| --- | --- |
| **Traffic-light window buttons** | Decoration layout is the platform's. The deck itself says *"on Windows they'd stay on the right."* Forcing macOS-style controls would move a control, which Direction A forbids. |
| **In-header menu bar** (File/Edit/View…) | The app has an in-window `PopoverMenuBar` already; the deck's flat spacing is a layout change, not a surface change. Existing placement kept. |
| **Canvas backdrop blur** | §3.1. |
| **`transform: scale(.96)` press state** | GTK4 CSS has no `transform` on widgets. Substituted with the existing `:active` background shift. |
| **Kerf gradient on the workpiece contour** | Canvas-drawn, and Commit D territory. Only attempted if A–C land clean. |

---

## 4. Commit plan

| Commit | Content | Verify |
| --- | --- | --- |
| — | This document | committed before any code |
| **A** | `rayforge/ui_gtk/theme.py`: token blocks + rules, light/dark provider, installed from `MainWindow`. Typography sizes. Canvas background follows theme. | app starts; suite green |
| **B** | Icon tint semantics in the theme CSS; `Cut Scale` icon → `laser-on-symbolic`. No asset import (§2.2). | jog/scale/corner tests pass unmodified |
| **C** | Cut Scale sheet styling (same fields, same handler); machine settings sidebar + Device page surface; job-progress in the toolbar driven by the **estimate**; inspector locked while running; Stop red; branding → "Swift Cut". | protected-behaviour tests + handler-count test |
| **D** *(optional)* | Estimate-driven kerf hairline, labelled estimated. Skipped if it needs pipeline/driver changes. | — |

Branding changes `APP_NAME` in `rayforge/const.py` only. Module and
package names stay `rayforge`; there is no code rename.

## 5. Protected behaviour

Unchanged, byte-for-byte in behaviour, and covered by tests that must
pass **unmodified**:

* 4×4 jog grid — eight arrows with press-and-hold plus single-step,
  Home in the centre, Z up/down, the safety release paths.
* Go Scale and Cut Scale, including Cut Scale's speed/power
  confirmation before firing.
* X/Y position readout; start-corner selector (TL/TR/BL/BR).
* mm/s everywhere; Min Power / Max Power; Start / Pause / Stop.
* Export Ruida job (`.rd`); layer colour magenta `#D63AD6`.
* Every signal handler and `machine_cmd` wiring — **zero handler
  removals**, asserted by a test that counts `connect()` calls.

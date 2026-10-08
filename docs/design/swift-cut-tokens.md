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
| `sc_overlay_solid` | `#F6F6F8` | `#2C2C2E` |
| `sc_overlay_bg` | `alpha(@sc_overlay_solid, 0.92)` | same |
| `sc_overlay_border` | `@sc_hairline` | same |
| `sc_overlay_shadow` | `@sc_shadow` | same |

The four `sc_overlay_*` tokens are the one floating material (§3.6).

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
| Canvas overlay | 9px | `10px`, one radius for every floating surface (§3.6) |
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

**They are not new artwork.** Each is the *existing SwiftCut icon
geometry*, byte-identical in path data, with only the `fill`
attribute changed and a C2PA metadata block added. Verified against
`arrow-north`, `frame` and `home`; the design project also carries a
copy of `swiftcut/resources/icons/*-symbolic.svg` that matches the
repo exactly. The five tints exist because HTML `<img>` cannot
recolour an SVG — they are a mockup device, not a deliverable.

All 48 names the deck uses already exist in
`swiftcut/resources/icons/` (checked, zero missing).

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
   header uses its rgba token (`@sc_header_bg` at 0.88) so it at
   least sits *lighter* than the window and picks up the window
   background beneath it.
2. Otherwise the alpha composites against the opaque window
   background, which lands on solid `#F6F6F8` / `#2C2C2E` — the
   glass-white / glass-shade fallback the brief asks for. This is
   what will happen on Windows in practice.

The canvas overlay and every other floating surface no longer use
`@sc_header_bg`: they are the one material of §3.6, the same
glass-white / glass-shade at 0.92 over the work itself.

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
| **Device page "On connect" group** — home-on-start, clear-alarm-on-connect | Both settings exist and are already surfaced, on the **Advanced** page (`advanced_preferences_page.py`). Artboard 2d groups them under Device. Relocating them is a control move, which the constraints forbid outright, so they stay on Advanced and pick up the new material there. |
| **Hold-jog speed on the Device page** | Same reason. It is the jog panel's existing Jog Speed row; duplicating or moving it onto Device would move a control. |
| **Ruida connection on the Device page** | The connection *is* shown, but on **General**, not Device. Hostname, Main Port 50200 and Jog Port 50207 are the Ruida driver's setup `VarSet` (`RuidaDriver.get_setup_vars`), which this app renders in General's "Driver Settings" group; the Device page is for settings read back *off* the controller, and says so when the driver cannot. Artboard 2d puts both on one page. Merging them is a control move. Both pages are captured for review instead. |
| **Canvas watermark** | There is no watermark to rename — the app draws none, and artboard 3a shows none either (the "Swift Cut" lettering in the mock is *document content*, a workpiece). Branding is the one `APP_NAME` string, which carries the window title, the About dialog and the file-dialog filter labels. |
| **In-header menu bar** (File/Edit/View…) | The app has an in-window `PopoverMenuBar` already; the deck's flat spacing is a layout change, not a surface change. Existing placement kept. |
| **Canvas backdrop blur** | §3.1. |
| **`transform: scale(.96)` press state** | GTK4 CSS has no `transform` on widgets. Substituted with the existing `:active` background shift. |
| **Kerf gradient on the workpiece contour** | Canvas-drawn, and Commit D territory. Only attempted if A–C land clean. |

---

### 3.6 One material for floating surfaces

**The rule.** Everything that floats over the work is one surface,
with one fill, one rim, one radius and one shadow, and only the
theme's `.sc-overlay` class paints it. A floating widget adds the
class and declares no background, border colour, radius or shadow of
its own (widget stylesheets load after the theme at the same
priority, so one that did would win). The surfaces that wear it:

* the Workflow card and the Workpiece Properties cards (`Expander`);
* the canvas toolbar (`VisibilityOverlay`) and the time estimate
  (`TimeEstimateOverlay`);
* the "Drop files to import" HUD and the status message label;
* the G-code viewer's line/size label.

The right pane that holds the two cards is a transparent column, not
a surface. Its left margin sits inside its scroller so the cards'
shadows are not clipped. Toasts, popovers and menus stay
libadwaita's.

**The token set**, colours in `theme.py`, lengths in `layout.py`:

| Part | Token | Light | Dark |
| --- | --- | --- | --- |
| Blur fallback colour | `sc_overlay_solid` | `#F6F6F8` glass-white | `#2C2C2E` glass-shade |
| Background alpha | `sc_overlay_bg` | 0.92 of the solid | 0.92 of the solid |
| 1px hairline rim | `sc_overlay_border` = `@sc_hairline` | `rgba(0,0,0,0.10)` | `rgba(255,255,255,0.12)` |
| Radius | `$radius_overlay` | 10px | 10px |
| Shadow | `$shadow_overlay` `@sc_overlay_shadow` | `0 2px 6px` shadow-blue 0.10 | `0 2px 6px` black 0.40 |

`.sc-overlay list` is transparent: libadwaita paints a `list` with
the opaque view colour, which made the Properties card's body a
second, solid surface inside the glass one.

**Why 0.92.** The work beneath a panel can be anything, so contrast
is measured with the surface composited over black, white and the
canvas colour (WCAG 2 relative luminance):

| Alpha | Body text, worst case | Dim caption, worst case |
| --- | --- | --- |
| 0.75 (the old canvas toolbar's alpha) | 5.70:1 | 2.58:1 |
| 0.88 (`@sc_header_bg`) | 8.74:1 | 2.99:1 |
| 0.90 | 9.34:1 | 3.05:1 |
| **0.92** | **9.97:1** | **3.11:1** |
| 1.00 (opaque) | 12.80:1 | 3.34:1 |

The worst case is a light panel over a black shape for captions and a
dark panel over white for body text. The dim caption (`@sc_fg_dim`)
is 3.34:1 even on the opaque glass colour, so it is the binding
constraint: 3:1 is crossed near 0.89. At 0.92 body text keeps WCAG
AAA (7:1) with room, a caption keeps 3.1:1 (it loses under 7% of its
opaque contrast), and 8% of the work still shows through, enough to
read the panel as a layer above it.
`tests/ui_gtk/test_overlay_material.py` re-checks these from the
tokens.

**Research** (2026-10-08):

* Apple HIG, Materials
  (<https://developer.apple.com/design/human-interface-guidelines/materials>):
  Liquid Glass "forms a distinct functional layer for controls and
  navigation elements … that floats above the content layer". Its
  *regular* variant "blurs and adjusts the luminosity of background
  content to maintain legibility"; use it "when components have a
  significant amount of text, such as alerts, sidebars, or popovers".
  The *clear* variant is for media backgrounds only. "Thicker
  materials, which are more opaque, can provide better contrast for
  text and other elements with fine features." Both variants change
  when people turn on Reduce Transparency or Increase Contrast. Our
  panels are text-heavy, so the regular variant is the model; without
  blur, a thick tint is its honest approximation. Also: WWDC25 "Meet Liquid Glass"
  (<https://developer.apple.com/videos/play/wwdc2025/219/>).
* libadwaita style classes
  (<https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/style-classes.html>):
  `.osd` "usually makes the widget background dark and partially
  transparent"; with `.toolbar` it makes a floating toolbar. The
  installed libadwaita 1.9.3 paints `.osd` `rgb(0 0 0 / 70%)` with
  90% white text, `border: none`, and `toolbar.osd` gets `padding:
  12px; border-radius: 15px`. It is dark in both themes; the old drop
  HUD copied it (black at 0.7, white text) and so read as a different
  family. The one-material rule rejects it for our surfaces. Its `.card` is a 1px hairline
  ring plus a soft two-layer shadow (`0 1px 3px 1px`, `0 2px 6px
  2px`), the same rim-and-shadow anatomy used here.
* GTK 4 CSS properties
  (<https://docs.gtk.org/gtk4/css-properties.html>): there is no
  `backdrop-filter`; `filter` applies to the widget itself. So the
  solid colour per theme *is* the material, and the alpha is a tint,
  not glass.

## 4. Commit plan

| Commit | Content | Verify |
| --- | --- | --- |
| — | This document | committed before any code |
| **A** | `swiftcut/ui_gtk/theme.py`: token blocks + rules, light/dark provider, installed from `MainWindow`. Typography sizes. Canvas background follows theme. | app starts; suite green |
| **B** | Icon tint semantics in the theme CSS; `Cut Scale` icon → `laser-on-symbolic`. No asset import (§2.2). | jog/scale/corner tests pass unmodified |
| **C** | Cut Scale sheet text and styling (same fields, same handler); job-progress in the toolbar driven by the **estimate**; inspector locked while running; Stop red; branding → "Swift Cut". | protected-behaviour tests + handler-count test |
| **D** *(optional)* | Estimate-driven kerf hairline. **Not built** — see §6. | — |

Branding changes `APP_NAME` in `swiftcut/const.py` only. Module and
package names stay `rayforge`; there is no code rename.

The machine settings dialog is already the System-Settings layout the
deck draws: `Adw.NavigationSplitView` with a category list on the left
and a page stack on the right, and a Device page that already renders
the Ruida driver's own var set — host, port 50200, jog port 50207 —
plus live connection state. It needed no restructuring; Commit A's
`sidebar_bg_color` / `view_bg_color` overrides give it the new
material where it stands.

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

## 6. Commit D — the kerf animation, and why it is not here

A–C landed clean, which was the gate for attempting D, and the stated
skip condition did not apply: a kerf overlay needs no pipeline,
encoder or driver change. The machinery is already in the tree —
`simulator/op_player.py` has `seek_to_fraction()` and `render_state()`,
which the 3D playback view already drives, and after Commit C the live
`progress_fraction` reaches the UI.

It is still not built, for a reason the brief's own gate does not
cover: **it cannot be verified here.** The overlay only draws while a
job is actually running on the controller, and this machine has no
reachable Ruida (the capture run logged straight through connect and
disconnect against 192.168.1.100). Shipping an animated canvas
element — in the part of the app with the least coverage of visual
output — on the strength of "it compiles and the other commits pass"
would be worse work than saying so.

It is also the one item that stops being a reskin. A–C change
surfaces, tokens, icons, typography and four in-place presentational
details. A progress-driven animated overlay is a new feature wearing
the reskin's clothes.

What a follow-up needs, for whoever picks it up:

1. An `OpPlayer` seeded from the running job's ops, seeked from the
   `progress_fraction` the job monitor already publishes.
2. A canvas2d overlay element drawing the traversed prefix as a
   magenta hairline with the spark gradient at the head — the one
   place §1.1 allows spark.
3. A label saying the position is estimated, because Ruida reports no
   granular progress and the head shown is inferred, not measured.
4. A machine, or a `ruida_simulator` run, to watch it against.

"""
The Swift Cut theme: one stylesheet in a light and a dark variant.

libadwaita switches to dark by swapping its own stylesheet, so a
single static sheet cannot carry both token sets. This module keeps
one ``Gtk.CssProvider`` and reloads it with the light or the dark
token block whenever ``AdwStyleManager`` flips, which is why it does
not go through ``shared.gtk.apply_css`` (that helper is
``@once_per_object`` and appends a provider per call, so it cannot
reload).

The token values come from ``docs/design/swift-cut-tokens.md``, which
reads them out of the design's light and dark artboards. Every length
is named, not written: the rules below take them from
:data:`swiftcut.ui_gtk.layout.CSS_LENGTHS`, where type and control
sizes are in ``rem`` so they follow the system font rather than fixing
the design's pixels on every display.
"""

import logging

from gi.repository import Adw, Gdk, Gtk

from .layout import stylesheet

logger = logging.getLogger(__name__)

# Surface tokens, read off artboard 3a. The libadwaita names are
# redefined from our own so the whole app follows without every
# widget needing a rule of its own.
_LIGHT_TOKENS = """
@define-color sc_window_bg #F5F5F7;
@define-color sc_canvas_bg #F5F5F7;
@define-color sc_header_bg rgba(246, 246, 248, 0.88);
@define-color sc_panel_bg #FBFBFD;
@define-color sc_rail_bg #F2F2F5;
@define-color sc_card_bg #FFFFFF;
@define-color sc_button_bg #FFFFFF;
@define-color sc_button_hover #F7F7F9;
@define-color sc_bezel rgba(0, 0, 0, 0.15);
@define-color sc_hairline rgba(0, 0, 0, 0.10);
@define-color sc_hairline_soft rgba(0, 0, 0, 0.08);
@define-color sc_fg #1D1D1F;
@define-color sc_fg_dim rgba(60, 60, 67, 0.6);
@define-color sc_accent_text #0B3BD1;
@define-color sc_accent_soft rgba(47, 123, 255, 0.14);
@define-color sc_fill_subtle rgba(0, 0, 0, 0.03);
@define-color sc_shadow rgba(4, 34, 122, 0.10);
"""

# Artboard 3b. Only the surfaces move; the accent, the danger red and
# the layer magenta are the same ink in both themes.
_DARK_TOKENS = """
@define-color sc_window_bg #1C1C1E;
@define-color sc_canvas_bg #1C1C1E;
@define-color sc_header_bg rgba(44, 44, 46, 0.88);
@define-color sc_panel_bg #232325;
@define-color sc_rail_bg #1E1E20;
@define-color sc_card_bg rgba(255, 255, 255, 0.05);
@define-color sc_button_bg rgba(255, 255, 255, 0.10);
@define-color sc_button_hover rgba(255, 255, 255, 0.14);
@define-color sc_bezel rgba(255, 255, 255, 0.12);
@define-color sc_hairline rgba(255, 255, 255, 0.12);
@define-color sc_hairline_soft rgba(255, 255, 255, 0.10);
@define-color sc_fg #F5F5F7;
@define-color sc_fg_dim rgba(235, 235, 245, 0.6);
@define-color sc_accent_text #7CBEFF;
@define-color sc_accent_soft rgba(47, 123, 255, 0.28);
@define-color sc_fill_subtle rgba(255, 255, 255, 0.035);
@define-color sc_shadow rgba(0, 0, 0, 0.40);
"""

#: blue-brand (``docs/design/swift-cut-tokens.md``). The stylesheet's
#: sc_accent, and the canvas draws its selection handles in it.
ACCENT_HEX = "#2F7BFF"

# Blue is the selection and focus colour and the colour of the one
# primary action, nothing else. Red belongs to Stop and to the no-go
# zones. Spark is the laser-live indicator only. Layer magenta is
# left exactly as the document defines it.
_SHARED_TOKENS = f"""
@define-color sc_accent {ACCENT_HEX};
@define-color sc_danger #FF3B30;
@define-color sc_ok #34C759;
@define-color sc_spark_top #FFF6DC;
@define-color sc_spark_bottom #FFE9AB;

@define-color window_bg_color @sc_window_bg;
@define-color window_fg_color @sc_fg;
@define-color view_bg_color @sc_panel_bg;
@define-color view_fg_color @sc_fg;
@define-color headerbar_bg_color @sc_header_bg;
@define-color headerbar_fg_color @sc_fg;
@define-color headerbar_border_color @sc_hairline;
@define-color sidebar_bg_color @sc_rail_bg;
@define-color sidebar_fg_color @sc_fg;
@define-color sidebar_border_color @sc_hairline;
@define-color secondary_sidebar_bg_color @sc_panel_bg;
@define-color card_bg_color @sc_card_bg;
@define-color card_fg_color @sc_fg;
@define-color dialog_bg_color @sc_panel_bg;
@define-color dialog_fg_color @sc_fg;
@define-color popover_bg_color @sc_panel_bg;
@define-color popover_fg_color @sc_fg;
@define-color accent_bg_color @sc_accent;
@define-color accent_fg_color #FFFFFF;
@define-color accent_color @sc_accent_text;
@define-color destructive_bg_color @sc_danger;
@define-color destructive_fg_color #FFFFFF;
@define-color destructive_color @sc_danger;
@define-color success_color @sc_ok;
@define-color borders @sc_hairline;

/* The GTK3-era names, which 14 files still colour themselves with -
   the dock, the layer column, the asset browser, the canvas and 3D
   overlays, round_button, key, icon_tab_widget, expression_entry.
   Until these are defined they resolve to the stock theme, which is
   the main reason the reskin looked applied in some places and not
   others. Every one of the 39 uses is a background, a subtle alpha()
   fill or a selection highlight, so the mapping is exact; defining
   the aliases beats editing 14 files and keeps working for code not
   yet written. */
@define-color theme_bg_color @sc_panel_bg;
@define-color theme_fg_color @sc_fg;
@define-color theme_base_color @sc_card_bg;
@define-color theme_selected_bg_color @sc_accent;
@define-color theme_selected_fg_color #FFFFFF;
"""

# Rules are scoped to the surfaces the reskin actually covers. A bare
# `button` rule would reach into every dialog and preference row in
# the app, which is a layout risk this direction does not take.
_RULES = stylesheet("""
/* --- Canvas ---------------------------------------------------- */
.sc-canvas {
    background-color: @sc_canvas_bg;
}

/* --- Hairline separators --------------------------------------- */
.sc-toolbar separator,
.sc-dock separator {
    background-color: @sc_hairline;
    min-width: $hairline;
    min-height: $hairline;
}

/* --- Bezel buttons --------------------------------------------- */
/* The design's half-pixel edge, drawn as a hairline alpha border:
   GTK rounds sub-pixel spreads to the device grid, so half a pixel
   is 0 or 1 depending on the monitor. */
.sc-toolbar > button,
.sc-toolbar > togglebutton,
.sc-split > button,
.sc-split > menubutton > button,
.sc-jog button {
    border: $hairline solid @sc_bezel;
    border-radius: $radius_button;
    background-image: none;
    background-color: @sc_button_bg;
    box-shadow: none;
    color: @sc_fg;
}

.sc-jog button {
    border-radius: $radius_cell;
}

/* The two halves of a split button keep the bezel but stay joined,
   so the pair still reads as one control. The action button is
   always first and the menu button second in both split widgets. */
.sc-split > button {
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
}

.sc-split > menubutton > button {
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
    border-left-width: 0;
}

.sc-toolbar > button:hover,
.sc-toolbar > togglebutton:hover,
.sc-split > button:hover,
.sc-split > menubutton > button:hover,
.sc-jog button:hover {
    background-color: @sc_button_hover;
}

/* Without the .sc-split arms here, a disabled split button keeps
   libadwaita's insensitive grey fill while every disabled button
   beside it fades - which is what made undo, redo, align and tabs
   read as a different family of button in an empty document. */
.sc-toolbar > button:disabled,
.sc-toolbar > togglebutton:disabled,
.sc-split > button:disabled,
.sc-split > menubutton > button:disabled,
.sc-jog button:disabled {
    opacity: 0.4;
}

/* Blue is selection, focus and the one primary action. */
.sc-toolbar > togglebutton:checked,
.sc-jog togglebutton:checked {
    background-color: @sc_accent_soft;
    color: @sc_accent_text;
    border-color: transparent;
}

.sc-toolbar > button.suggested-action,
.sc-jog button.suggested-action {
    background-color: @sc_accent;
    border-color: @sc_accent;
    color: #FFFFFF;
}

/* Stop keeps the bezel and turns its glyph red, the way the deck
   draws it - a filled red button here would read as the primary
   action. */
.sc-jog button.destructive-action {
    background-color: @sc_button_bg;
    border-color: @sc_bezel;
    color: @sc_danger;
}

.sc-toolbar > button:focus-visible,
.sc-jog button:focus-visible {
    outline: $stroke solid @sc_accent;
    outline-offset: -$hairline;
}

/* --- Panels ----------------------------------------------------- */
.sc-dock {
    background-color: @sc_panel_bg;
}

.sc-dock .sc-rail {
    background-color: @sc_rail_bg;
}

/* Readouts hold their column when the digits change. */
.sc-jog .numeric,
.numeric,
.sc-numeric {
    font-feature-settings: "tnum" 1;
}

/* The chosen start corner is a selection, so it takes the solid
   accent and a white glyph. */
.sc-panel togglebutton:checked {
    background-color: @sc_accent;
    color: #FFFFFF;
}

/* Canvas overlay toggles read as active with the soft accent. */
.visibility-overlay button:checked {
    background-color: @sc_accent_soft;
    color: @sc_accent_text;
}

/* --- Cut Scale sheet --------------------------------------------- */
/* The deck fires a solid red Cut. libadwaita tints destructive
   responses instead, which reads as one more row rather than as
   the thing that starts the laser. Scoped to this sheet so every
   other confirmation keeps the platform styling. */
.sc-sheet .response-area button.destructive-action {
    background-image: none;
    background-color: @sc_danger;
    color: #FFFFFF;
    font-weight: bold;
}

/* --- Job progress ---------------------------------------------- */
/* Driven by the job monitor's distance estimate, since Ruida
   reports nothing granular. */
.sc-job-progress progressbar trough {
    min-height: $progress_bar;
    border-radius: $radius_bar;
    background-color: @sc_fill_subtle;
}

.sc-job-progress progressbar progress {
    min-height: $progress_bar;
    border-radius: $radius_bar;
    background-color: @sc_accent;
}

.sc-job-progress label {
    color: @sc_fg_dim;
}

/* --- Laser live -------------------------------------------------- */
/* The only place the spark gradient is allowed. */
.sc-laser-live:checked {
    background-image: linear-gradient(
        to bottom, @sc_spark_top, @sc_spark_bottom
    );
    border-color: @sc_spark_bottom;
    color: #1D1D1F;
}
""")

# The layout layer, from docs/design/swift-cut-layout.md. Kept apart
# from _RULES because it answers a different question: _RULES says
# what a surface is made of, this says how big it is and where it
# sits. Every length in it is a role from layout.CSS_LENGTHS, and the
# Python half of the same map - margins, box spacing, size requests -
# reads the same table in swiftcut/ui_gtk/layout.py.
_LAYOUT = stylesheet("""
/* --- Control sizes: the compact density ------------------------- */
/* Icon buttons only: a text button sizes itself from its label, and
   a bare `.sc-overlay button` rule would crush the 3D playback speed
   button ("1x") into a square. */
.sc-toolbar > button,
.sc-toolbar > togglebutton,
.sc-split > button,
.sc-rail button,
.sc-icon-button {
    min-width: $control_size;
    min-height: $control_size;
    padding: 0;
}

/* Every button in the jog grid is one cell: the arrows, Home, the
   two scale buttons and the job column. The cell is the buttons'
   size request, bezel included, so nothing here adds to it. */
.sc-jog button {
    min-width: 0;
    min-height: 0;
    padding: 0;
}

/* One glyph size everywhere. A jog button is a bigger target, not a
   bigger picture. */
.sc-toolbar image,
.sc-jog image,
.sc-rail image,
.sc-overlay image,
.sc-icon-button image {
    -gtk-icon-size: $icon_glyph;
}

/* --- The dock: row rhythm ---------------------------------------- */
/* libadwaita draws a row fifty pixels tall with six above and below
   its title. A dock row is one compact row, title and caption included;
   every row the dock grows is a row the canvas loses. */
.sc-dock list.boxed-list > row {
    min-height: $compact_row;
    padding: 0;
}

.sc-dock list.boxed-list > row > box.header {
    min-height: $compact_row;
    margin-left: $compact_space_group;
    margin-right: $compact_space_group;
    border-spacing: $compact_space_control;
}

.sc-dock list.boxed-list > row > box.header > box.title {
    margin-top: 0;
    margin-bottom: 0;
    border-spacing: 0;
}

.sc-dock list.boxed-list > row > box.header > box.title > .subtitle {
    font-size: $caption_font;
}

.sc-dock list.boxed-list > row > box.header > .suffixes {
    border-spacing: $compact_space_control;
}

/* A row's trailing controls: the regular gap, the compact one in the
   dock. */
.sc-suffix {
    border-spacing: $space_control;
}

.sc-dock .sc-suffix {
    border-spacing: $compact_space_control;
}

/* A spin field in the dock is one size whatever it holds. The - and
   + shrink to their glyph so the value keeps the room. */
.sc-compact-spin {
    min-width: 0;
    min-height: $spin_height;
}

.sc-compact-spin > text {
    min-width: 0;
    padding: 0 $compact_space_control;
}

.sc-compact-spin > button {
    min-width: $icon_glyph;
    min-height: 0;
    padding: 0;
}

/* --- Radii ------------------------------------------------------- */
/* The map in swift-cut-tokens.md 1.4 is the whole set. These three
   are the surfaces that predate the reskin and drifted off it. */
list.boxed-list,
.card {
    border-radius: $radius_card;
}

.sc-overlay {
    border-radius: $radius_overlay;
}

.sc-rail button {
    border-radius: $radius_chip;
}

/* --- Type roles -------------------------------------------------- */
/* Four roles, one class each. dim-label, caption, title-4 and
   caption-heading all collapse into these. A caption is one step
   below the body, and the body is the system font. */
.sc-title {
    font-weight: 600;
}

.sc-caption {
    font-size: $caption_font;
    color: @sc_fg_dim;
}
""")

_provider: Gtk.CssProvider | None = None


def _css_for(dark: bool) -> str:
    tokens = _DARK_TOKENS if dark else _LIGHT_TOKENS
    return tokens + _SHARED_TOKENS + _RULES + _LAYOUT


def _reload(style_manager: Adw.StyleManager, *args) -> None:
    if _provider is None:
        return
    _provider.load_from_string(_css_for(style_manager.get_dark()))


def install() -> None:
    """
    Install the Swift Cut stylesheet and keep it following the theme.

    Safe to call more than once, and a no-op when there is no display
    (headless test runs import the UI without one).
    """
    global _provider
    if _provider is not None:
        return

    display = Gdk.Display.get_default()
    if display is None:
        logger.warning("No default Gdk display; Swift Cut theme skipped.")
        return

    style_manager = Adw.StyleManager.get_default()
    _provider = Gtk.CssProvider()
    _provider.load_from_string(_css_for(style_manager.get_dark()))
    Gtk.StyleContext.add_provider_for_display(
        display,
        _provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    style_manager.connect("notify::dark", _reload)

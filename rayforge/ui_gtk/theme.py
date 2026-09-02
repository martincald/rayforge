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
reads them out of the design's light and dark artboards.
"""

import logging

from gi.repository import Adw, Gdk, Gtk

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

# Blue is the selection and focus colour and the colour of the one
# primary action, nothing else. Red belongs to Stop and to the no-go
# zones. Spark is the laser-live indicator only. Layer magenta is
# left exactly as the document defines it.
_SHARED_TOKENS = """
@define-color sc_accent #2F7BFF;
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
"""

# Rules are scoped to the surfaces the reskin actually covers. A bare
# `button` rule would reach into every dialog and preference row in
# the app, which is a layout risk this direction does not take.
_RULES = """
/* --- Canvas ---------------------------------------------------- */
.sc-canvas {
    background-color: @sc_canvas_bg;
}

/* --- Hairline separators --------------------------------------- */
.sc-toolbar separator,
.sc-dock separator {
    background-color: @sc_hairline;
    min-width: 1px;
    min-height: 1px;
}

/* --- Bezel buttons --------------------------------------------- */
/* The design's half-pixel edge, drawn as a 1px alpha border: GTK
   rounds sub-pixel spreads to the device grid, so 0.5px is 0 or 1
   depending on the monitor. */
.sc-toolbar > button,
.sc-toolbar > togglebutton,
.sc-toolbar > .sc-split > button,
.sc-jog button {
    border: 1px solid @sc_bezel;
    border-radius: 7px;
    background-image: none;
    background-color: @sc_button_bg;
    box-shadow: none;
    color: @sc_fg;
}

.sc-jog button {
    border-radius: 6px;
}

.sc-toolbar > button:hover,
.sc-toolbar > togglebutton:hover,
.sc-jog button:hover {
    background-color: @sc_button_hover;
}

.sc-toolbar > button:disabled,
.sc-toolbar > togglebutton:disabled,
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
    outline: 2px solid @sc_accent;
    outline-offset: -1px;
}

/* --- Panels ----------------------------------------------------- */
.sc-dock {
    background-color: @sc_panel_bg;
}

.sc-dock .sc-rail {
    background-color: @sc_rail_bg;
}

.sc-panel {
    font-size: 11.5px;
}

.sc-jog .caption {
    font-size: 9px;
}

/* Readouts hold their column when the digits change. */
.sc-jog .numeric,
.numeric {
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
    min-height: 5px;
    border-radius: 3px;
    background-color: @sc_fill_subtle;
}

.sc-job-progress progressbar progress {
    min-height: 5px;
    border-radius: 3px;
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
"""

_provider: Gtk.CssProvider | None = None


def _css_for(dark: bool) -> str:
    tokens = _DARK_TOKENS if dark else _LIGHT_TOKENS
    return tokens + _SHARED_TOKENS + _RULES


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

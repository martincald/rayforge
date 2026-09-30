"""
Layout tokens: the space, size and rhythm the reskin never defined.

The rule these constants exist to enforce is that a widget never
picks its own spacing, control size or row height - it names a role,
and the role has one value. This is the one module in ``ui_gtk`` that
holds lengths. Python reads the constants below (margins, box spacing,
size requests); every stylesheet, :mod:`swiftcut.ui_gtk.theme`'s and
each widget's own, names a role from :data:`CSS_LENGTHS` through
:func:`stylesheet` instead of writing a length. A few helpers keep row
suffixes, icon buttons and position readouts identical wherever they
are built.

The values come from ``docs/design/swift-cut-layout.md``, which gives
them in pixels at the design's 13-pixel type. They are not used as
pixels: each one scales with the system UI font, so the layout keeps
its proportions at whatever type size the platform and the user chose.
A 12pt macOS system font gets a slightly tighter layout than the
design, an 11pt GNOME one at 96 dpi a slightly looser one. Only
hairlines, radii and shadows stay fixed, in :data:`CSS_LENGTHS`.
"""

from dataclasses import dataclass
from string import Template

from gi.repository import Gtk, Pango

from .icons import get_icon

#: The type size the tokens below were drawn at: the design's 13px
#: window base (``docs/design/swift-cut-tokens.md`` 1.5).
DESIGN_FONT_PX = 13.0


def system_font_px() -> float:
    """
    The system UI font size in logical pixels.

    Falls back to the design base when there is no display to ask,
    which is how the tokens keep their design values headless.
    """
    settings = Gtk.Settings.get_default()
    if settings is None:
        return DESIGN_FONT_PX
    font = Pango.FontDescription.from_string(settings.props.gtk_font_name)
    size = font.get_size() / Pango.SCALE
    if size <= 0:
        return DESIGN_FONT_PX
    if font.get_size_is_absolute():
        return size
    xft_dpi = settings.props.gtk_xft_dpi
    dpi = xft_dpi / 1024 if xft_dpi > 0 else 96.0
    return size * dpi / 72.0


_FONT_SCALE = system_font_px() / DESIGN_FONT_PX


def scaled(design_px: float) -> int:
    """A design pixel size at the system font's scale."""
    return max(1, round(design_px * _FONT_SCALE))


def rem(design_px: float) -> str:
    """A design pixel size as CSS relative to the system font."""
    return f"{design_px / DESIGN_FONT_PX:.4f}rem"


# --- Spacing: a 4px scale, by role -----------------------------------
# Five steps, nothing between them and nothing outside them.

#: Inside one control: an icon and its caption, a chip's padding.
SPACE_TIGHT = scaled(4)

#: Between sibling controls: buttons in a row, cells in the jog grid.
SPACE_CONTROL = scaled(8)

#: Between groups, and a panel's own padding.
SPACE_GROUP = scaled(12)

#: Between sections of a page.
SPACE_SECTION = scaled(16)

#: A page's outer margin.
SPACE_PAGE = scaled(24)


# --- Density ---------------------------------------------------------


@dataclass(frozen=True)
class Density:
    """The sizes one density context is built at, in design pixels.

    Read them through :func:`scaled` in Python and :func:`rem` in a
    stylesheet, never as pixels.
    """

    #: Between sibling controls.
    space_control: float
    #: A panel's own padding, and the gap between its groups.
    space_group: float
    #: A settings row, a layer card's header, an operations row.
    row_height: float
    #: Every icon and short-label button.
    control_size: float
    #: Every icon glyph. A bigger button is a bigger target, not a
    #: bigger picture.
    icon_glyph: float
    #: One jog grid cell: the arrows, Home, the scale buttons and the
    #: job column all share it.
    jog_cell: float
    #: A spin field with its - and + buttons. The unit is a label
    #: after it, not part of it.
    spin_width: float
    spin_height: float
    #: The widest a settings group grows before it stops stretching.
    panel_max_width: float
    #: The floating panels over the canvas: Layer Workflow and
    #: Workpiece Properties.
    overlay_panel_width: float
    #: Caption text: one step below the body, which is the system font.
    caption_font: float


#: The dock, and the pointer surfaces around it: the toolbar, the dock
#: rail and the canvas overlays. Every row the dock grows is a row the
#: canvas loses, so this is the one density the app has.
#:
#: Windows gets the same values. They are design pixels at the system
#: font, and GTK folds the platform's DPI into that font (its xft dpi),
#: so a 125% or 150% Windows display scales the dock the way it scales
#: the text. Were a platform ever to need different values, this is
#: the one place that would say so.
COMPACT = Density(
    space_control=4,
    space_group=8,
    row_height=32,
    control_size=32,
    icon_glyph=16,
    jog_cell=40,
    spin_width=96,
    spin_height=28,
    panel_max_width=400,
    overlay_panel_width=360,
    caption_font=11,
)

#: Every icon button, toggle and stepper.
CONTROL_SIZE = scaled(COMPACT.control_size)

#: A jog grid cell, and every other button in the jog grid.
JOG_CELL = scaled(COMPACT.jog_cell)

#: Every icon glyph.
ICON_GLYPH = scaled(COMPACT.icon_glyph)

#: Between sibling controls in the dock.
COMPACT_SPACE_CONTROL = scaled(COMPACT.space_control)

#: The dock's panel padding, and the gap between its groups.
COMPACT_SPACE_GROUP = scaled(COMPACT.space_group)

#: A spin field in the dock, - and + included.
SPIN_WIDTH = scaled(COMPACT.spin_width)
SPIN_HEIGHT = scaled(COMPACT.spin_height)


# --- Row rhythm ------------------------------------------------------

#: Dialog and page rows.
ROW_MIN_HEIGHT = scaled(48)

#: Rows in the dock: settings rows, layer card headers, operations.
ROW_MIN_HEIGHT_COMPACT = scaled(COMPACT.row_height)

#: A settings group inside a dock panel stops here instead of
#: stretching to the panel edge and leaving a hole in the middle.
PANEL_MAX_WIDTH = scaled(COMPACT.panel_max_width)

#: The floating panels over the canvas. Taller than this share of the
#: canvas, they scroll inside themselves instead of covering it.
OVERLAY_PANEL_WIDTH = scaled(COMPACT.overlay_panel_width)
OVERLAY_PANEL_HEIGHT_FRACTION = 0.6


# --- Dock furniture --------------------------------------------------

#: The gap between two dock areas, which is also where it is dragged.
DOCK_DIVIDER = scaled(6)

#: The narrowest a dock area that expands is squeezed to.
DOCK_AREA_MIN_WIDTH = scaled(50)

#: The picture in an empty dock tab: a hint, not a poster.
EMPTY_STATE_ICON = scaled(64)

#: The widest a layer card grows; wider than this it is a gap.
LAYER_CARD_MAX_WIDTH = scaled(400)


# --- Canvas selection ------------------------------------------------
# Fixed logical pixels, like a hairline: a handle is a pointer target,
# and the canvas overlay draws in the widget's logical pixels.

#: A resize handle as drawn: a square on a corner or an edge midpoint.
HANDLE_SIZE = 8

#: A handle's outline, and every line the selection overlay draws.
HANDLE_STROKE = 1

#: The pointer target around a corner or an edge, larger than the
#: square it is drawn as.
HANDLE_HIT_SIZE = 20

#: The arc a rotate drag draws around the selection's centre.
ROTATION_ARC_RADIUS = 24

#: The crosshair on the start corner of the job.
START_CORNER_MARKER = 12

#: The dashed tick from the start corner toward the opposite one.
START_CORNER_TICK = 24


# --- Stylesheet lengths ----------------------------------------------
# Every length a stylesheet in ui_gtk may write, by role. Sizes follow
# the system font (rem); hairlines, strokes, radii and shadows are the
# few things that do not, and are the only pixels in the app.

CSS_LENGTHS = {
    # Spacing, the 4px scale above.
    "space_tight": rem(4),
    "space_control": rem(8),
    "space_group": rem(12),
    "space_section": rem(16),
    "space_page": rem(24),
    "space_page_wide": rem(48),
    # The compact density.
    "compact_space_control": rem(COMPACT.space_control),
    "compact_space_group": rem(COMPACT.space_group),
    "compact_row": rem(COMPACT.row_height),
    "control_size": rem(COMPACT.control_size),
    "icon_glyph": rem(COMPACT.icon_glyph),
    "spin_width": rem(COMPACT.spin_width),
    "spin_height": rem(COMPACT.spin_height),
    # Type. The body is the system font and needs no rule.
    "caption_font": rem(COMPACT.caption_font),
    "body_font": rem(DESIGN_FONT_PX),
    "keycap_font": rem(12),
    "menu_label_font": rem(14),
    "display_font": rem(24),
    # Control sizes outside the density: a tab strip, a floating action
    # button, a layer card, a settings row's spin field, a drop line.
    "tab_button": rem(36),
    "fab_size": rem(64),
    "fab_radius": rem(32),
    "layer_card_min_width": rem(160),
    "row_spin_min_width": rem(130),
    "drop_indicator": rem(24),
    # Fixed: hairlines and strokes.
    "hairline": "1px",
    "stroke": "2px",
    "stroke_wide": "3px",
    "progress_bar": "5px",
    "dock_edge": f"{DOCK_DIVIDER}px",
    # Fixed: radii, from swift-cut-tokens.md 1.4.
    "radius_marker": "1px",
    "radius_bar": "3px",
    "radius_chip": "5px",
    "radius_cell": "6px",
    "radius_button": "7px",
    "radius_inner": "8px",
    "radius_overlay": "9px",
    "radius_card": "10px",
    "radius_group": "12px",
    # Fixed: shadows.
    "shadow_card": "0 4px 10px alpha(black, 0.06)",
    "shadow_panel": "0 2px 12px alpha(black, 0.2)",
    "shadow_toast": "0 2px 6px alpha(black, 0.15)",
    "shadow_drop_overlay": "0 4px 12px rgba(0, 0, 0, 0.3)",
    "shadow_fab": (
        "0 3px 6px rgba(0, 0, 0, 0.16), 0 3px 6px rgba(0, 0, 0, 0.23)"
    ),
    "shadow_fab_hover": (
        "0 4px 8px rgba(0, 0, 0, 0.19), 0 6px 12px rgba(0, 0, 0, 0.23)"
    ),
    "shadow_fab_active": (
        "0 2px 4px rgba(0, 0, 0, 0.16), 0 2px 4px rgba(0, 0, 0, 0.23)"
    ),
}


def stylesheet(template: str, **extra: str) -> str:
    """Fill a stylesheet's ``$role`` placeholders from the tokens.

    An unknown role raises, so a typo fails at import rather than
    quietly leaving a rule without its length.
    """
    return Template(template).substitute(CSS_LENGTHS, **extra)


# --- Placeholders ----------------------------------------------------

#: One em dash, everywhere a value is unknown.
UNKNOWN = "—"


def suffix_box(*children: Gtk.Widget) -> Gtk.Box:
    """Build a row's trailing control box.

    Every row's suffix goes through here so a spin button and a flat
    icon button end at the same x. Built by hand, they do not: a
    ``Gtk.SpinButton`` carries end padding a flat button has none of.
    The gap between its controls is the stylesheet's, so a suffix in
    the dock takes the compact gap and one in a dialog the regular.
    """
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    box.set_valign(Gtk.Align.CENTER)
    box.add_css_class("sc-suffix")
    for child in children:
        box.append(child)
    return box


def icon_button(
    icon_name: str,
    tooltip: str,
    *,
    toggle: bool = False,
) -> Gtk.Button:
    """Build a compact icon button.

    The tooltip is required rather than optional: the audit found 28
    icon-only buttons with none, and every one of them was built by
    hand from a bare ``Gtk.Button``.
    """
    button: Gtk.Button = Gtk.ToggleButton() if toggle else Gtk.Button()
    button.set_child(get_icon(icon_name))
    button.set_tooltip_text(tooltip)
    button.set_valign(Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.add_css_class("sc-icon-button")
    return button


def axis_button(label: str, tooltip: str) -> Gtk.Button:
    """Build a short-label button that matches the icon buttons beside it.

    The X / Y / Z zeroing buttons sit in a row of icon buttons, so
    they take the same box: a text button that sizes itself from its
    label would be a different width in every language.
    """
    button = Gtk.Button(label=label)
    button.set_tooltip_text(tooltip)
    button.set_valign(Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.add_css_class("sc-icon-button")
    return button


def compact_spin_button(spin_button: Gtk.SpinButton) -> None:
    """Build a spin field at the compact density.

    One size for every spin field in the dock, so their edges line up
    whatever the value. The field's own width in characters is dropped
    to one, or the text would ask for more room than the size given.
    """
    spin_button.set_width_chars(1)
    spin_button.set_size_request(SPIN_WIDTH, SPIN_HEIGHT)
    spin_button.add_css_class("sc-compact-spin")


def format_position(x: float | None, y: float | None) -> str:
    """Render a machine position the one way the app renders it.

    One decimal, no colons, an em dash where an axis is unknown. The
    dock panel used to carry three readouts in three formats four
    rows apart.
    """

    def axis(value: float | None) -> str:
        return UNKNOWN if value is None else f"{value:.1f}"

    return f"X {axis(x)}  Y {axis(y)}"

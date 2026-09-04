"""
Layout tokens: the space, size and rhythm the reskin never defined.

The rule these constants exist to enforce is that a widget never
picks its own spacing, control size or row height - it names a role,
and the role has one value. Anything GTK CSS can express lives in
:mod:`rayforge.ui_gtk.theme` instead; this module holds what only
Python can set (margins, box spacing, size requests) plus the few
helpers that keep row suffixes, icon buttons and position readouts
identical wherever they are built.

The values come from ``docs/design/swift-cut-layout.md``.
"""

from gi.repository import Gtk

from .icons import get_icon

# --- Spacing: a 4px scale, by role -----------------------------------
# Five steps, nothing between them and nothing outside them.

#: Inside one control: an icon and its caption, a chip's padding.
SPACE_TIGHT = 4

#: Between sibling controls: buttons in a row, cells in the jog grid.
SPACE_CONTROL = 8

#: Between groups, and a panel's own padding.
SPACE_GROUP = 12

#: Between sections of a page.
SPACE_SECTION = 16

#: A page's outer margin.
SPACE_PAGE = 24


# --- Control sizes: two density contexts -----------------------------
# Compact is pointer work - the toolbar, panel rows, the dock rail,
# canvas overlays. Touch is the jog grid, the one surface an operator
# hits while watching the machine instead of the screen.

#: Every icon button, toggle and stepper in a compact context.
CONTROL_SIZE = 32

#: A jog grid cell. The only non-compact control in the app.
JOG_CELL = 60

#: Every icon glyph, in both contexts. A jog button is a bigger
#: target, not a bigger picture.
ICON_GLYPH = 16


# --- Row rhythm ------------------------------------------------------

#: Dialog and page rows.
ROW_MIN_HEIGHT = 48

#: Rows in a dock panel, where vertical space is scarce.
ROW_MIN_HEIGHT_COMPACT = 40

#: A settings group inside a dock panel stops here instead of
#: stretching to the panel edge and leaving a hole in the middle.
PANEL_MAX_WIDTH = 340


# --- Placeholders ----------------------------------------------------

#: One em dash, everywhere a value is unknown.
UNKNOWN = "—"


def suffix_box(*children: Gtk.Widget) -> Gtk.Box:
    """Build a row's trailing control box.

    Every row's suffix goes through here so a spin button and a flat
    icon button end at the same x. Built by hand, they do not: a
    ``Gtk.SpinButton`` carries end padding a flat button has none of.
    """
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    box.set_spacing(SPACE_CONTROL)
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
    button: Gtk.Button = (
        Gtk.ToggleButton() if toggle else Gtk.Button()
    )
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


def format_position(x: float | None, y: float | None) -> str:
    """Render a machine position the one way the app renders it.

    One decimal, no colons, an em dash where an axis is unknown. The
    dock panel used to carry three readouts in three formats four
    rows apart.
    """

    def axis(value: float | None) -> str:
        return UNKNOWN if value is None else f"{value:.1f}"

    return f"X {axis(x)}  Y {axis(y)}"

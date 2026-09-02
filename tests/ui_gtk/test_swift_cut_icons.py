"""The Swift Cut icon map resolves to real assets.

The design ships each icon in five tints (-b/-d/-g/-r/-w), but those
are the same geometry the app already carries, recoloured so an HTML
mockup could show them: `<img>` cannot recolour an SVG. GTK can - it
recolours any `-symbolic.svg` from the widget's own colour - so the
reskin keeps one asset per icon and drives the tints from CSS. See
docs/design/swift-cut-tokens.md section 2.

What is worth guarding is that every name the map uses still resolves
to a file, so a rename cannot quietly fall back to the system theme.
"""

from importlib.resources import files

import pytest

from rayforge.resources import icons as icon_resources

# The 4x4 jog grid, whose geometry the reskin must not disturb.
JOG_ICONS = [
    "arrow-north-west-symbolic",
    "arrow-north-symbolic",
    "arrow-north-east-symbolic",
    "arrow-west-symbolic",
    "home-symbolic",
    "arrow-east-symbolic",
    "arrow-south-west-symbolic",
    "arrow-south-symbolic",
    "arrow-south-east-symbolic",
    "arrow-z-up-symbolic",
    "arrow-z-down-symbolic",
]

# Row 3 of the jog grid plus its action column.
SCALE_AND_ACTION_ICONS = [
    "frame-symbolic",
    "laser-on-symbolic",
    "send-symbolic",
    "pause-symbolic",
    "stop-symbolic",
]

# The start-corner selector and the current-position shortcuts.
CORNER_ICONS = [
    "top-left-symbolic",
    "top-right-symbolic",
    "bottom-left-symbolic",
    "bottom-right-symbolic",
    "center-symbolic",
    "goto-origin-symbolic",
    "crosshairs-symbolic",
    "zero-here-symbolic",
]

TOOLBAR_ICONS = [
    "open-symbolic",
    "save-symbolic",
    "save-as-symbolic",
    "download-symbolic",
    "export-symbolic",
    "undo-symbolic",
    "redo-symbolic",
    "3d-symbolic",
    "refresh-symbolic",
    "jog-symbolic",
    "align-horizontal-center-symbolic",
    "tabs-equidistant-symbolic",
    "clear-alarm-symbolic",
    "laser-off-symbolic",
    "play-arrow-symbolic",
]

PANEL_ICONS = [
    "visibility-on-symbolic",
    "tabs-visible-symbolic",
    "travel-path-symbolic",
    "block-symbolic",
    "add-symbolic",
    "edit-symbolic",
    "settings-symbolic",
    "layers-symbolic",
    "gcode-symbolic",
    "terminal-symbolic",
    "image-x-generic-symbolic",
]

ALL_ICONS = (
    JOG_ICONS
    + SCALE_AND_ACTION_ICONS
    + CORNER_ICONS
    + TOOLBAR_ICONS
    + PANEL_ICONS
)


@pytest.mark.parametrize("icon_name", ALL_ICONS)
def test_icon_resolves_to_a_file(icon_name):
    path = files(icon_resources).joinpath(f"{icon_name}.svg")
    assert path.is_file(), f"{icon_name} is missing from resources/icons"


@pytest.mark.parametrize("icon_name", ALL_ICONS)
def test_icon_is_symbolic_so_gtk_recolours_it(icon_name):
    """
    GTK only recolours icons whose filename ends in `-symbolic.svg`.
    A name that lost the suffix would render as fixed black ink and
    disappear against the dark theme.
    """
    assert icon_name.endswith("-symbolic")


def test_go_scale_and_cut_scale_do_not_share_a_glyph():
    """
    Artboard 3a draws Go Scale with the frame glyph and Cut Scale
    with the laser glyph. They used to be the same icon, which left
    the two actions indistinguishable in the grid.
    """
    from rayforge.ui_gtk.machine import jog_widget

    source = files("rayforge.ui_gtk.machine").joinpath("jog_widget.py")
    text = source.read_text(encoding="utf-8")
    assert jog_widget is not None
    go_at = text.index("self.go_scale_btn = create_button(")
    cut_at = text.index("self.cut_scale_btn = create_button(")
    assert "frame-symbolic" in text[go_at : go_at + 120]
    assert "laser-on-symbolic" in text[cut_at : cut_at + 120]

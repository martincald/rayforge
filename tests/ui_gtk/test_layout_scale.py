"""Layout tokens follow the system font rather than fixed pixels.

The design gives every size in pixels at its 13px type; the app scales
them by the system UI font, and the stylesheet states them in rem.
"""

import re
from types import SimpleNamespace

import pytest

from swiftcut.ui_gtk import layout, theme


def _settings(font: str, xft_dpi: int):
    return SimpleNamespace(
        props=SimpleNamespace(gtk_font_name=font, gtk_xft_dpi=xft_dpi)
    )


@pytest.mark.parametrize(
    "font, xft_dpi, expected",
    [
        # macOS: GTK reports the system font at 72 dpi.
        (".AppleSystemUIFont 12", 72 * 1024, 12.0),
        # GNOME's default, at 96 dpi.
        ("Cantarell 11", 96 * 1024, 11 * 96 / 72),
        # No dpi set means GTK's 96.
        ("Segoe UI 9", -1, 12.0),
        # An absolute size is already pixels.
        ("Inter 14px", 96 * 1024, 14.0),
    ],
)
def test_the_system_font_size_in_pixels(monkeypatch, font, xft_dpi, expected):
    monkeypatch.setattr(
        layout.Gtk.Settings, "get_default", lambda: _settings(font, xft_dpi)
    )

    assert layout.system_font_px() == pytest.approx(expected)


def test_no_display_means_the_design_size(monkeypatch):
    monkeypatch.setattr(layout.Gtk.Settings, "get_default", lambda: None)

    assert layout.system_font_px() == layout.DESIGN_FONT_PX


def test_tokens_are_the_design_size_at_the_font_scale(monkeypatch):
    monkeypatch.setattr(layout, "_FONT_SCALE", 12.0 / 13.0)

    assert layout.scaled(60) == 55
    assert layout.scaled(32) == 30
    assert layout.scaled(4) == 4


def test_rem_is_relative_to_the_design_base():
    assert layout.rem(13) == "1.0000rem"
    assert layout.rem(32) == "2.4615rem"


@pytest.mark.parametrize("dark", [False, True])
def test_the_stylesheet_sets_no_font_or_control_size_in_px(dark):
    css = theme._css_for(dark)

    assert "$" not in css
    assert not re.search(r"font-size:\s*[\d.]+px", css)
    assert not re.search(r"-gtk-icon-size:\s*[\d.]+px", css)
    assert re.search(r"min-width:\s*[\d.]+rem", css)

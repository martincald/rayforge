# flake8: noqa: E402
"""The About dialog shows the SwiftCut brand and keeps the Rayforge
MIT attribution (the original author's copyright notice), which the
MIT license requires we preserve.
"""

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from swiftcut import const
from swiftcut.ui_gtk.about import AboutDialog

ATTRIBUTION = (
    "Based on Rayforge by Samuel Abels, used under the MIT License."
)


def _iter_widgets(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _iter_widgets(child)
        child = child.get_next_sibling()


def _label_texts(dialog) -> list[str]:
    return [
        w.get_label()
        for w in _iter_widgets(dialog)
        if isinstance(w, Gtk.Label) and w.get_label()
    ]


@pytest.mark.ui
def test_about_dialog_shows_swiftcut_and_keeps_mit_attribution():
    dialog = AboutDialog()
    try:
        assert dialog.main_title.get_title() == f"About {const.APP_NAME}"

        texts = _label_texts(dialog)
        assert any(const.APP_NAME in text for text in texts)
        assert "© 2025 Samuel Abels" in texts
    finally:
        dialog.destroy()


@pytest.mark.ui
def test_about_dialog_shows_the_rayforge_attribution_as_plain_text():
    dialog = AboutDialog()
    try:
        assert ATTRIBUTION in _label_texts(dialog)
    finally:
        dialog.destroy()


@pytest.mark.ui
def test_about_dialog_has_no_link_rows_and_no_supporters():
    dialog = AboutDialog()
    try:
        rows = [
            w for w in _iter_widgets(dialog) if isinstance(w, Adw.ActionRow)
        ]
        activatable = [r.get_title() for r in rows if r.get_activatable()]
        # The only clickable row navigates inside the dialog.
        assert activatable == ["System Information"]

        license_row = next(r for r in rows if r.get_title() == "License")
        assert license_row.get_subtitle() == "MIT X11"

        assert dialog.view_stack.get_child_by_name("supporters") is None
        assert "Supporters" not in _label_texts(dialog)
    finally:
        dialog.destroy()


def test_dependency_list_names_only_what_the_app_talks_through():
    """No rows for the network libraries of removed features."""
    from swiftcut.ui_gtk.about import get_dependency_info

    comm = dict(get_dependency_info()["File Formats & Communication"])

    assert list(comm) == ["ezdxf", "pypdf", "PyYAML", "pyserial"]

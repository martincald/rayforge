# flake8: noqa: E402
"""The About dialog shows the SwiftCut brand and keeps the Rayforge
MIT attribution (the original author's copyright notice), which the
MIT license requires we preserve.
"""

from pathlib import Path

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from swiftcut import const
from swiftcut.ui_gtk.about import AboutDialog

AUTHOR = "Martín Calderón"
AUTHOR_LINE = f"SwiftCut, made by {AUTHOR}"
COPYRIGHT = f"© 2026 {AUTHOR}"
ATTRIBUTION = (
    "Based on Rayforge, created by Samuel Abels, used under the MIT License."
)
RAYFORGE_COPYRIGHT = "© 2025 Samuel Abels"
VERSION = (Path(__file__).parents[2] / "VERSION").read_text().strip()


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
        assert RAYFORGE_COPYRIGHT in texts
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
def test_about_dialog_credits_the_author_then_rayforge():
    dialog = AboutDialog()
    try:
        texts = _label_texts(dialog)
        order = [AUTHOR_LINE, COPYRIGHT, ATTRIBUTION, RAYFORGE_COPYRIGHT]
        assert [texts.index(text) for text in order] == sorted(
            texts.index(text) for text in order
        )
    finally:
        dialog.destroy()


@pytest.mark.ui
def test_about_dialog_credits_rayforge_in_a_caption():
    """Rayforge's credit is smaller than SwiftCut's own."""
    dialog = AboutDialog()
    try:
        labels = {
            w.get_label(): w
            for w in _iter_widgets(dialog)
            if isinstance(w, Gtk.Label)
        }
        for text in (ATTRIBUTION, RAYFORGE_COPYRIGHT):
            assert labels[text].has_css_class("sc-caption")
        for text in (AUTHOR_LINE, COPYRIGHT):
            assert not labels[text].has_css_class("sc-caption")
    finally:
        dialog.destroy()


@pytest.mark.ui
def test_about_dialog_names_the_author_as_lead_developer():
    dialog = AboutDialog()
    try:
        rows = [
            w for w in _iter_widgets(dialog) if isinstance(w, Adw.ActionRow)
        ]
        dev_row = next(r for r in rows if r.get_title() == "Lead Developer")
        assert dev_row.get_subtitle() == AUTHOR
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


@pytest.mark.ui
def test_about_dialog_shows_the_version_file():
    dialog = AboutDialog()
    try:
        assert VERSION in _label_texts(dialog)
    finally:
        dialog.destroy()

# flake8: noqa: E402
"""The About dialog shows the SwiftCut brand and keeps the Rayforge
MIT attribution (the original author's copyright notice), which the
MIT license requires we preserve.
"""

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk

from swiftcut import const
from swiftcut.ui_gtk.about import AboutDialog


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

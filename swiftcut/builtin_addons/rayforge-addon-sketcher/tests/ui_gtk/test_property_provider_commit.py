# flake8: noqa: E402
"""The Sketch Parameters card applies a committed number at once."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import pytest
from gi.repository import GLib
from sketcher.ui_gtk.property_provider import SketchPropertyProvider

from swiftcut.shared.util.glib import discrete_edit


def _provider():
    provider = SketchPropertyProvider()
    provider.create_widgets()
    provider.items = [object()]
    applied = []
    provider._apply_debounced_changes = lambda: applied.append(
        dict(provider._pending_changes)
    )
    return provider, applied


@pytest.mark.ui
def test_its_spin_rows_commit_typed_values():
    provider, _applied = _provider()
    assert provider.varset_widget.numeric_entries is True


@pytest.mark.ui
def test_a_committed_number_is_applied_at_once():
    provider, applied = _provider()
    with discrete_edit():
        provider._on_params_changed(provider.varset_widget, "width")
    assert applied == [{"width": None}]
    assert provider._debounce_timer_id == 0


@pytest.mark.ui
def test_other_changes_still_wait():
    provider, applied = _provider()
    provider._on_params_changed(provider.varset_widget, "name")
    try:
        assert applied == []
        assert provider._debounce_timer_id != 0
    finally:
        GLib.source_remove(provider._debounce_timer_id)

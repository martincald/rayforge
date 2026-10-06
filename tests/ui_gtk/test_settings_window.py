# flake8: noqa: E402
"""The app Settings window has no Licenses page; every built-in page
opens by its id, and addon pages still add and remove behind the
built-in ones."""

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw

from swiftcut.ui_gtk.settings.registry import settings_page_registry
from swiftcut.ui_gtk.settings.settings_dialog import SettingsWindow

_TEST_ADDON = "test-settings-window-addon"


class _AddonPage(Adw.PreferencesPage):
    key = "test-addon-page"

    def __init__(self):
        super().__init__(title="Test Addon Page")

    def get_icon_name(self):
        return "addon-symbolic"


def _window(initial_page: str = "general") -> SettingsWindow:
    return SettingsWindow(initial_page=initial_page)


def _close(win: SettingsWindow):
    # A never-presented window gets no close-request, so drop the
    # registry handler here.
    settings_page_registry.changed.disconnect(win._registry_handler)
    win.destroy()


def _stack_keys(win: SettingsWindow) -> list[str]:
    pages = win.content_stack.get_pages()
    return [
        getattr(pages.get_item(i).get_child(), "key", "")
        for i in range(pages.get_n_items())
    ]


def _row_count(win: SettingsWindow) -> int:
    count = 0
    while win.sidebar_list.get_row_at_index(count) is not None:
        count += 1
    return count


@pytest.mark.ui
def test_settings_window_has_no_licenses_page(ui_context_initializer):
    assert "licenses" not in SettingsWindow.PAGE_INDICES
    win = _window()
    try:
        assert "licenses" not in _stack_keys(win)
        assert _row_count(win) == SettingsWindow._BUILTIN_PAGE_COUNT + len(
            settings_page_registry.get_pages()
        )
    finally:
        _close(win)


@pytest.mark.ui
def test_every_builtin_page_opens_by_its_id(ui_context_initializer):
    for page_id in SettingsWindow.PAGE_INDICES:
        win = _window(page_id)
        try:
            assert win.content_stack.get_visible_child().key == page_id
        finally:
            _close(win)


@pytest.mark.ui
def test_unknown_initial_page_falls_back_to_general(ui_context_initializer):
    win = _window("licenses")
    try:
        assert win.content_stack.get_visible_child().key == "general"
    finally:
        _close(win)


@pytest.mark.ui
def test_addon_page_adds_and_removes_after_builtin_pages(
    ui_context_initializer,
):
    win = _window()
    try:
        builtin_keys = _stack_keys(win)[: SettingsWindow._BUILTIN_PAGE_COUNT]
        assert builtin_keys == list(SettingsWindow.PAGE_INDICES)
        addon_count = len(win._addon_page_classes)

        settings_page_registry.register(_AddonPage, _TEST_ADDON)
        added_at = SettingsWindow._BUILTIN_PAGE_COUNT + addon_count
        assert _stack_keys(win)[added_at] == _AddonPage.key

        settings_page_registry.unregister_all_from_addon(_TEST_ADDON)
        assert _AddonPage.key not in _stack_keys(win)
        assert _row_count(win) == added_at
        assert (
            _stack_keys(win)[: SettingsWindow._BUILTIN_PAGE_COUNT]
            == builtin_keys
        )
    finally:
        settings_page_registry.unregister_all_from_addon(_TEST_ADDON)
        _close(win)

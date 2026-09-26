"""The dock is as tall as its content until the user drags it.

Once dragged, that height is the dock's - across a collapse and across
launches. A height the paned only worked out from the content is not
remembered, or the default would freeze at today's content.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from gi.repository import Gtk

from swiftcut.ui_gtk.mainwindow import MainWindow


def _window(
    *,
    user_height=None,
    visible=True,
    position_set=True,
    paned_height=900,
    position=691,
):
    # Specced, so a method Gtk.Paned does not have fails here too.
    paned = MagicMock(spec=Gtk.Paned)
    paned.props = SimpleNamespace(position_set=position_set)
    paned.get_height.return_value = paned_height
    paned.get_position.return_value = position
    panel = SimpleNamespace(
        user_height=user_height, get_visible=lambda: visible
    )
    # Stands in for the window, which is all these methods read.
    win: Any = SimpleNamespace(
        vertical_paned=paned,
        bottom_panel=panel,
        _apply_dock_height_once=MagicMock(),
    )
    return win, paned, panel


def test_a_height_the_user_dragged_to_is_remembered():
    win, paned, panel = _window(position=691)

    MainWindow._on_vertical_pane_position_changed(win, paned, None)

    assert panel.user_height == 209


def test_the_content_height_is_not_remembered():
    win, paned, panel = _window(position_set=False)

    MainWindow._on_vertical_pane_position_changed(win, paned, None)

    assert panel.user_height is None


def test_a_collapsed_dock_remembers_nothing():
    win, paned, panel = _window(visible=False, user_height=240)

    MainWindow._on_vertical_pane_position_changed(win, paned, None)

    assert panel.user_height == 240


def test_without_a_remembered_height_the_dock_fits_its_content():
    win, paned, _ = _window(user_height=None)

    MainWindow._apply_dock_height(win)

    paned.set_position.assert_called_once_with(-1)


def test_a_remembered_height_is_put_back():
    win, paned, _ = _window(user_height=300, paned_height=900)

    MainWindow._apply_dock_height(win)

    paned.set_position.assert_called_once_with(600)


def test_a_remembered_height_waits_for_the_first_allocation():
    win, paned, _ = _window(user_height=300, paned_height=0)

    MainWindow._apply_dock_height(win)

    paned.set_position.assert_not_called()
    signal, handler = paned.connect.call_args.args
    assert signal == "notify::max-position"

    with patch("swiftcut.ui_gtk.mainwindow.GLib.idle_add") as idle_add:
        handler(paned, None)

    paned.disconnect.assert_called_once()
    idle_add.assert_called_once_with(win._apply_dock_height_once)


@pytest.mark.ui
def test_the_dock_carries_its_height_across_launches(
    ui_context_initializer, ui_task_mgr
):
    from swiftcut.doceditor.editor import DocEditor
    from swiftcut.ui_gtk.doceditor.bottom_panel import BottomPanel

    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    machine = ui_context_initializer.config.machine
    try:
        panel = BottomPanel(machine, editor, MagicMock())
        assert "height" not in panel.to_dict()

        panel.user_height = 240
        saved = panel.to_dict()
        relaunched = BottomPanel(machine, editor, MagicMock())
        relaunched.from_dict(saved)

        assert saved["height"] == 240
        assert relaunched.user_height == 240
    finally:
        editor.cleanup()

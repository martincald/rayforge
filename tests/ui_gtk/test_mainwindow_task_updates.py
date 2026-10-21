"""Task progress refreshes the main window's actions once per idle,
with the latest tasks, however many updates arrive before it."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from gi.repository import GLib

from swiftcut.ui_gtk.mainwindow import MainWindow

pytestmark = pytest.mark.ui


def _drain():
    context = GLib.main_context_default()
    while context.pending():
        context.iteration(False)


def test_a_burst_of_task_updates_refreshes_once():
    win = SimpleNamespace(
        _latest_tasks=[],
        _tasks_update_pending=False,
        _update_actions_and_ui=MagicMock(),
        _update_status_message=MagicMock(),
    )
    win._on_tasks_changed_idle = lambda: MainWindow._on_tasks_changed_idle(win)

    for n in range(50):
        MainWindow.on_running_tasks_changed(
            win, None, tasks=[f"task{n}"], progress=n / 50
        )
    win._update_actions_and_ui.assert_not_called()
    _drain()

    win._update_actions_and_ui.assert_called_once_with()
    win._update_status_message.assert_called_once_with(["task49"])

    MainWindow.on_running_tasks_changed(win, None, tasks=[], progress=1.0)
    _drain()
    assert win._update_actions_and_ui.call_count == 2
    win._update_status_message.assert_called_with([])

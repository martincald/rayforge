# flake8: noqa: E402
"""
Auto Layout in the main window: the GTK main loop keeps running while
the 40-piece benchmark is laid out through the real action, and the
progress row's Cancel leaves the document as it was.
"""

import os
import sys
import time

import pytest

if sys.platform.startswith("linux"):
    if not os.environ.get("DISPLAY"):
        pytest.skip(
            "DISPLAY not set on Linux, skipping UI tests. Run with xvfb-run.",
            allow_module_level=True,
        )

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

from swiftcut.context import get_context
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.doceditor.layout_cmd import AUTO_LAYOUT_KEY
from swiftcut.shared.tasker import task_mgr
from swiftcut.ui_gtk.mainwindow import MainWindow
from tests.doceditor import layout_bench as bench

#: The longest the main loop may go without running a 16 ms timer.
MAX_GAP_S = 0.1


def _iterate_until(condition, timeout: float = 60.0):
    """Runs the main loop until the condition holds."""
    context = GLib.main_context_default()
    deadline = time.monotonic() + timeout
    # Wakes the loop up at least this often, so the condition is seen.
    source = GLib.timeout_add(10, lambda: GLib.SOURCE_CONTINUE)
    try:
        while not condition():
            assert time.monotonic() < deadline, "timed out"
            context.iteration(True)
    finally:
        GLib.source_remove(source)


def _settle(win):
    """Runs the main loop until the editor has been idle for a while."""
    quiet = 0.5
    idle_since = [None]

    def idle():
        now = time.monotonic()
        if task_mgr.has_tasks() or win.doc_editor.is_processing:
            idle_since[0] = None
        elif idle_since[0] is None:
            idle_since[0] = now
        return idle_since[0] is not None and now - idle_since[0] > quiet

    _iterate_until(idle)


def _build(win, folder, pieces):
    """Imports the pieces one after another; returns their workpieces."""
    doc = win.doc_editor.doc
    workpieces = []
    for n, piece in enumerate(pieces):
        path = bench.write_svg(folder / f"{n:02d}-{piece.name}.svg", piece)
        before = set(doc.all_workpieces)
        win.doc_editor.file.load_file_from_path(path, None, PassthroughSpec())
        _iterate_until(lambda before=before: set(doc.all_workpieces) - before)
        (workpiece,) = set(doc.all_workpieces) - before
        workpieces.append(workpiece)
    _settle(win)
    return workpieces


@pytest.fixture
def app_and_window(ui_context_initializer, request):
    """The main window on the 1400 x 900 mm ilab-614 bed."""
    get_context().config.machine.set_axis_extents(1400, 900)

    class TestApp(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)
            self.win.set_default_size(1280, 800)

    test_name = request.node.name.replace("_", "-")
    app = TestApp(application_id=f"org.swiftcut.swiftcut.test.{test_name}")
    app.register(None)
    app.activate()
    win = app.win
    win.present()
    _iterate_until(lambda: win.get_mapped())

    yield app, win

    win.doc_editor.cleanup()
    # The document has unsaved changes: closing would leave an Unsaved
    # Changes dialog open for the tests after this one.
    win.destroy()
    app.quit()
    _settle(win)


def _longest_gap(win) -> float:
    """
    Runs Ctrl+Alt+A's action; returns the longest the main loop went
    without running a 16 ms timer, from the press until the result is
    in the document and one more tick has run after it.
    """
    undo = win.doc_editor.history_manager.undo_stack
    entries = len(undo)
    gaps = []
    last = [time.perf_counter()]

    def tick():
        now = time.perf_counter()
        gaps.append(now - last[0])
        last[0] = now
        return GLib.SOURCE_CONTINUE

    source = GLib.timeout_add(16, tick)
    try:
        last[0] = time.perf_counter()
        win.activate_action("win.layout-pixel-perfect", None)
        _iterate_until(lambda: len(undo) > entries)
        ticks = len(gaps)
        _iterate_until(lambda: len(gaps) > ticks)
    finally:
        GLib.source_remove(source)
    _settle(win)
    return max(gaps)


@pytest.mark.ui
def test_main_loop_keeps_running_during_auto_layout(app_and_window, tmp_path):
    _app, win = app_and_window
    workpieces = _build(win, tmp_path, bench.FORTY)
    before = [wp.matrix.copy() for wp in workpieces]
    pool_started = task_mgr._pool is not None

    # The first layout also starts the worker pool, which can hold the
    # main loop near the bar (docs/auto-layout-notes.md): measured, not
    # asserted. The same layout again, undone first, runs on the
    # started pool.
    cold = _longest_gap(win)
    win.doc_editor.history_manager.undo()
    _settle(win)
    warm = _longest_gap(win)

    print(
        f"\nFRAMES pool_started_before={pool_started} "
        f"cold_max_gap={cold * 1000:.0f}ms warm_max_gap={warm * 1000:.0f}ms"
    )
    assert warm < MAX_GAP_S
    assert [wp.matrix for wp in workpieces] != before
    assert bench.clashes(workpieces) == {"overlap": 0, "close": 0}


@pytest.mark.ui
def test_cancel_in_the_progress_row_changes_nothing(app_and_window, tmp_path):
    _app, win = app_and_window
    workpieces = _build(win, tmp_path, bench.FORTY)
    before = [wp.matrix.copy() for wp in workpieces]
    undo = win.doc_editor.history_manager.undo_stack
    entries = len(undo)
    row = win.layout_progress
    assert not row.get_visible()

    win.activate_action("win.layout-pixel-perfect", None)
    _iterate_until(lambda: row.progress_bar.get_fraction() > 0)
    assert row.get_visible()
    task = task_mgr.get_task(AUTO_LAYOUT_KEY)
    row.cancel_button.emit("clicked")
    _iterate_until(lambda: not row.get_visible())
    # The worker stops at its next piece; its last word, which would
    # have been the result, clears the task.
    _iterate_until(lambda: not task_mgr._zombie_tasks)
    _settle(win)

    assert task.get_status() == "canceled"
    assert [wp.matrix for wp in workpieces] == before
    assert len(undo) == entries

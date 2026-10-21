"""Preview starts at once on a real document, connected or not.

A real window on the bundled ilab-614 profile, its Ruida driver's
connection stubbed out so it stays disconnected, with
tests/perf/large.dxf imported and its job generated. Pressing Preview
shows the job and plays it within 100 ms, and the first frame of
playback draws; the same again with the machine presenting as
connected, for the same job.
"""

import asyncio
import mimetypes
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from gi.repository import Adw, GLib, Gtk

from swiftcut.machine.transport import TransportStatus
from swiftcut.shared.tasker import task_mgr

pytestmark = pytest.mark.ui

LARGE = Path(__file__).resolve().parents[1] / "perf" / "large.dxf"
#: What "starts within 100 ms" allows.
BUDGET_S = 0.1


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    context = GLib.main_context_default()
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def _settle(win, quiet: float = 0.6, timeout: float = 180.0) -> None:
    """Runs the main loop until the editor has been idle for quiet s."""
    idle_since = None
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _pump(0.05)
        now = time.monotonic()
        if task_mgr.has_tasks() or win.doc_editor.is_processing:
            idle_since = None
        elif idle_since is None:
            idle_since = now
        elif now - idle_since > quiet:
            return
    raise TimeoutError("the editor did not settle")


@pytest.fixture
def ilab_614(tmp_path, monkeypatch, ui_task_mgr):
    """
    A context on the bundled ilab-614 profile, the machine the owner
    runs, whose driver never connects: no device, no network.
    """
    from swiftcut import config
    from swiftcut import context as context_module
    from swiftcut.context import get_context
    from swiftcut.machine.driver.driver import Driver
    from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
    from swiftcut.shared import tasker

    async def no_connection(self):
        pass

    monkeypatch.setattr(Driver, "connect", no_connection)
    monkeypatch.setattr(RuidaDriver, "_connect_implementation", no_connection)
    folder = tmp_path / "config"
    monkeypatch.setattr(config, "CONFIG_DIR", folder)
    monkeypatch.setattr(config, "DIALECT_DIR", folder / "dialects")
    monkeypatch.setattr(config, "MACHINE_DIR", folder / "machines")
    monkeypatch.setattr(config, "ADDONS_DIR", folder / "addons")
    monkeypatch.setattr(config, "CONFIG_FILE", folder / "config.yaml")
    monkeypatch.setattr(config, "AI_CONFIG_FILE", folder / "ai.yaml")
    monkeypatch.setattr(tasker.task_mgr, "_instance", ui_task_mgr)

    # No placeholder machine: an empty machine folder gets ilab-614.
    context = get_context()
    _ = context.addon_mgr
    context.machine_mgr.initialize_connections()
    yield context

    # The driver's tasks live on the task manager's loop: shut down
    # there, not on a new loop.
    asyncio.run_coroutine_threadsafe(
        context.shutdown(), ui_task_mgr.loop
    ).result(timeout=10)
    context_module._context_instance = None


@pytest.fixture
def win(ilab_614):
    from swiftcut.ui_gtk.mainwindow import MainWindow

    class App(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)
            self.win.set_default_size(1280, 800)

    app = App(application_id="org.swiftcut.swiftcut.test.job-preview-start")
    app.register(None)
    app.activate()
    window = app.win
    window.present()
    _pump(0.5)
    yield window
    for toplevel in Gtk.Window.list_toplevels():
        if toplevel.get_transient_for() is window:
            toplevel.destroy()
    window.doc_editor.cleanup()
    window.destroy()
    app.quit()
    _pump(0.2)


def _press_preview(win):
    """
    Presses Preview on the current job; returns how long until the
    preview was shown and playing, and what it drew one frame later.
    """
    bar = win._time_estimate_overlay.preview_bar
    began = time.perf_counter()
    bar.toggle.set_active(True)
    model = win.surface._job_preview_element.model
    playing = bar.playing
    took = time.perf_counter() - began
    assert model is not None and playing, "the job was not current"

    # One frame of playback, 33 ms at x1.
    win._on_job_preview_tick(
        win.surface, SimpleNamespace(get_frame_time=lambda: 1_000_000)
    )
    win._on_job_preview_tick(
        win.surface, SimpleNamespace(get_frame_time=lambda: 1_033_333)
    )
    played = bar.time
    return SimpleNamespace(
        took=took,
        model=model,
        handle=win._job_preview_handle,
        done=model.index_at(played),
        path=model.path_at(played),
    )


def test_preview_plays_at_once_connected_or_not(win, ilab_614):
    machine = ilab_614.config.machine
    assert (machine.name, machine.driver_name) == ("ilab-614", "RuidaDriver")
    assert machine.axis_extents[:2] == (1400.0, 900.0)
    win.doc_editor.file.load_file_from_path(
        LARGE, mimetypes.guess_type(LARGE)[0], None
    )
    _settle(win)
    _pump(1.0)
    _settle(win)
    assert win.doc_editor.pipeline.get_existing_job_handle() is not None
    bar = win._time_estimate_overlay.preview_bar

    assert machine.is_connected() is False
    disconnected = _press_preview(win)
    bar.toggle.set_active(False)

    status = machine.connection_status
    machine.connection_status = TransportStatus.CONNECTED
    try:
        with patch.object(type(machine), "is_connected", return_value=True):
            machine.connection_status_changed.send(
                machine, status=TransportStatus.CONNECTED
            )
            _pump(0.2)
            connected = _press_preview(win)
    finally:
        machine.connection_status = status

    for press in (disconnected, connected):
        assert press.took < BUDGET_S
        # The first frame already draws the job's first cut.
        assert press.done >= 1
        assert len(press.path) > 1
    # The same job, previewed the same way.
    assert connected.handle is disconnected.handle
    for name in ("total_time", "start_time", "count"):
        assert getattr(connected.model, name) == getattr(
            disconnected.model, name
        )
    assert (connected.done, connected.path) == (
        disconnected.done,
        disconnected.path,
    )

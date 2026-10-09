"""Job history in the window: the recorder that follows both Starts
without touching the send path, and Machine > Job History with Load
and Run Again.

The send itself is faked at MachineCmd._start_job, so run_send_job's
one-job guard, its job_state_changed and its when_done are the real
ones; the fake sends job_started and the machine's job_finished the
way the real path does, through the main-thread scheduler.
"""

import asyncio
import json
import threading
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import gi
import pytest
import yaml

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402
from raygeo.ops import Ops  # noqa: E402

from swiftcut.context import get_context  # noqa: E402
from swiftcut.core.doc import Doc  # noqa: E402
from swiftcut.core.layer import Layer  # noqa: E402
from swiftcut.doceditor.file_cmd import project_json  # noqa: E402
from swiftcut.machine.cmd import MachineCmd  # noqa: E402
from swiftcut.machine.driver.driver import DeviceStatus  # noqa: E402
from swiftcut.machine.models.machine import Machine  # noqa: E402
from swiftcut.machine.transport import TransportStatus  # noqa: E402
from swiftcut.pipeline.artifact import JobArtifact  # noqa: E402
from swiftcut.shared.units.formatter import format_value  # noqa: E402
from swiftcut.shared.util.time_format import format_clock  # noqa: E402

TWO_LAYERS = Path(__file__).parent.parent / "assets" / "twolayer.ryp"


def _pump(seconds: float = 0.1) -> None:
    end = time.monotonic() + seconds
    context = GLib.main_context_default()
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def _wait(condition, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        _pump(0.02)


@pytest.fixture
def main_window(ui_context_initializer, tmp_path, monkeypatch):
    from swiftcut import config
    from swiftcut.ui_gtk.mainwindow import MainWindow

    monkeypatch.setattr(config, "JOB_HISTORY_DIR", tmp_path / "history")

    class App(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)
            self.win.set_default_size(1280, 800)

    app = App(application_id="org.swiftcut.swiftcut.test.job-history")
    app.register(None)
    app.activate()
    win = app.win
    win.present()
    _pump(0.3)
    assert win.job_history.root == tmp_path / "history"
    yield win
    win.doc_editor.cleanup()
    win.close()
    app.quit()
    _pump(0.2)


def _machine():
    return get_context().config.machine


@contextmanager
def _fake_send(
    win, *, reaches_driver=True, fails=False, release=None, pipeline=None
):
    """
    Stands in for the pipeline and the driver behind run_send_job.

    reaches_driver=False is a Start that ends before the job reaches
    the driver (a refused Crawford pre-move); fails raises once it has,
    as a driver error does, so the machine never says job_finished;
    pipeline holds the job before the driver, as the pipeline's wait
    does, and release holds it running, until each is set.
    """
    cmd = win.machine_cmd

    async def start_job(machine, job_name, final_job_action, **kwargs):
        if pipeline is not None:
            await asyncio.to_thread(pipeline.wait, 10)
        if not reaches_driver:
            return
        cmd._scheduler(cmd.job_started.send, cmd)
        if release is not None:
            await asyncio.to_thread(release.wait, 10)
        if fails:
            raise RuntimeError("the machine is busy")
        cmd._scheduler(machine.job_finished.send, machine)

    with (
        patch.object(cmd, "_start_job", new=start_job),
        patch.object(
            win,
            "_run_sanity_check_and_proceed",
            side_effect=lambda proceed: proceed(),
        ),
        patch.object(cmd, "cancel_job"),
    ):
        yield


def _toolbar_start(win):
    win.on_send_clicked(None, None)


def _panel_start(win):
    win.bottom_panel.jog_widget.start_btn.emit("clicked")


def _wait_for_the_send(win):
    _wait(lambda: not win.machine_cmd.is_job_running)
    _pump(0.05)


def _job_handle(win, ops: Ops, estimate: float = 42.0):
    artifact = JobArtifact(
        ops=ops, distance=0.0, generation_id=1, time_estimate=estimate
    )
    return win.doc_editor.pipeline.artifact_store.put(artifact, "job")


# A last job's start, for Crawford mode's Start sheet.
LAST = (120.0, 80.0)


def _raster_ops() -> Ops:
    ops = Ops()
    ops.set_power(0.5)
    for row in range(4):
        ops.move_to(0, row)
        ops.scan_to(20, row, power_values=[255] * 20)
    return ops


# --- The recorder ---------------------------------------------------


@pytest.mark.ui
@pytest.mark.parametrize("start", [_toolbar_start, _panel_start])
def test_a_start_that_ran_is_recorded(main_window, start):
    win = main_window
    editor = win.doc_editor
    editor.set_file_path(Path("/lab/sign.ryp"))
    at_start = project_json(editor.doc)
    handle = _job_handle(win, _raster_ops())

    with (
        _fake_send(win),
        patch.object(
            editor.pipeline, "get_existing_job_handle", return_value=handle
        ),
    ):
        start(win)
        # An edit made once the job is under way is not the job.
        editor.doc.add_layer(Layer(name="Added later"))
        _wait_for_the_send(win)

    (entry,) = win.job_history.entries(_machine().name)
    assert entry.machine == _machine().name
    assert entry.document == "sign"
    assert entry.stopped is False
    assert entry.estimate_s == 42.0
    assert entry.duration_s >= 0
    assert entry.thumbnail_path is not None
    stored = zipfile.ZipFile(entry.project_path).read("project.json")
    assert stored.decode() == at_start


@pytest.mark.ui
@pytest.mark.parametrize("stop", ["toolbar", "panel"])
def test_a_stop_during_the_job_is_recorded_as_stopped(main_window, stop):
    win = main_window
    release = threading.Event()

    with _fake_send(win, release=release):
        _toolbar_start(win)
        recorder = win.job_history_recorder
        _wait(
            lambda: recorder._run is not None
            and recorder._run.started_at is not None
        )
        if stop == "toolbar":
            cancel = win.action_manager.get_action("machine-cancel")
            cancel.set_enabled(True)
            cancel.activate(None)
        else:
            win.bottom_panel.jog_widget.stop_btn.emit("clicked")
        win.machine_cmd.cancel_job.assert_called_once_with(_machine())
        release.set()
        _wait_for_the_send(win)

    (entry,) = win.job_history.entries(_machine().name)
    assert entry.stopped is True


@pytest.mark.ui
def test_a_stop_with_no_job_running_marks_nothing(main_window):
    win = main_window

    with _fake_send(win):
        win.bottom_panel.jog_widget.stop_btn.emit("clicked")
        _toolbar_start(win)
        _wait_for_the_send(win)

    (entry,) = win.job_history.entries(_machine().name)
    assert entry.stopped is False


@pytest.mark.ui
def test_a_second_start_while_one_runs_is_refused_and_not_recorded(
    main_window,
):
    win = main_window
    release = threading.Event()
    editor = win.doc_editor
    editor.set_file_path(Path("/lab/first.ryp"))

    with _fake_send(win, release=release):
        _toolbar_start(win)
        editor.set_file_path(Path("/lab/second.ryp"))
        _panel_start(win)
        _toolbar_start(win)
        release.set()
        _wait_for_the_send(win)

    entries = win.job_history.entries(_machine().name)
    assert [e.document for e in entries] == ["first"]


@pytest.mark.ui
def test_a_start_refused_while_another_job_runs_records_nothing(main_window):
    """A frame or a scale is running: run_send_job refuses the Start."""
    win = main_window

    with (
        _fake_send(win),
        patch.object(
            MachineCmd,
            "is_job_running",
            new_callable=PropertyMock,
            return_value=True,
        ),
    ):
        _toolbar_start(win)
        # The running job's own state changes come and go.
        win.machine_cmd.job_state_changed.send(win.machine_cmd)
        assert win.doc_editor.task_manager.get_task("send-job") is None

    assert win.job_history_recorder._pending is None
    assert win.job_history_recorder._run is None
    win.machine_cmd.job_state_changed.send(win.machine_cmd)
    assert win.job_history.entries(_machine().name) == []


@pytest.mark.ui
def test_a_start_that_never_reached_the_driver_records_nothing(main_window):
    win = main_window

    with _fake_send(win, reaches_driver=False):
        _toolbar_start(win)
        _wait_for_the_send(win)

    assert win.job_history.entries(_machine().name) == []


@pytest.mark.ui
def test_a_failed_start_records_nothing(main_window):
    win = main_window

    with _fake_send(win, fails=True):
        _panel_start(win)
        _wait_for_the_send(win)

    assert win.job_history.entries(_machine().name) == []


@pytest.mark.ui
def test_a_frame_job_is_not_a_start(main_window):
    """job_started also comes for frames and Cut Scale."""
    win = main_window
    cmd = win.machine_cmd
    machine = _machine()

    cmd.job_state_changed.send(cmd)
    cmd.job_started.send(cmd)
    machine.job_finished.send(machine)
    cmd.job_state_changed.send(cmd)

    assert win.job_history.entries(machine.name) == []


@pytest.mark.ui
def test_a_start_from_another_window_is_not_this_ones(main_window):
    from swiftcut.ui_gtk.machine.start_position_dialog import start_chosen

    start_chosen.send(object(), machine=_machine())

    assert main_window.job_history_recorder._pending is None


@pytest.mark.ui
@pytest.mark.parametrize("first", ["cut scale", "start"])
def test_a_start_whose_job_lost_to_cut_scale_records_nothing(
    main_window, first
):
    """
    Cut Scale is still measuring, so nothing runs and the jog panel's
    Start is accepted. Whichever job reaches MachineCmd's one-job check
    first runs, and the other is refused there. Cut Scale's job_started
    and job_finished are not the Start's: a Start whose job was refused
    records nothing, and one whose job ran is recorded.

    Both jobs go through the real _execute_monitored_job, Cut Scale
    from its real "cut-scale" task and the Start from its real
    "send-job" task; only the measuring, the pipeline's wait and the
    driver are held.
    """
    win = main_window
    cmd = win.machine_cmd
    tasks = win.doc_editor.task_manager
    machine = _machine()
    win.doc_editor.set_file_path(Path("/lab/sign.ryp"))
    measured = threading.Event()
    assembled = threading.Event()
    driven = threading.Event()
    reached_driver = []

    async def scale(run, job_name):
        await asyncio.to_thread(measured.wait, 10)
        await run(10.0, 10.0)

    async def start_job(machine, job_name, final_job_action, **kwargs):
        await asyncio.to_thread(assembled.wait, 10)
        await cmd._execute_monitored_job(
            _raster_ops(), machine, encoded=MagicMock()
        )

    async def driver_run(encoded, doc, ops, on_command_done=None):
        reached_driver.append(ops)
        await asyncio.to_thread(driven.wait, 10)
        # From the loop's thread, as the drivers send it; the machine
        # passes it on to the main thread.
        machine.driver.job_finished.send(machine.driver)

    with (
        patch.object(cmd, "_scale", new=scale),
        patch.object(cmd, "_start_job", new=start_job),
        patch.object(machine.driver, "run", new=driver_run),
    ):
        cmd.run_cut_scale(machine, 600, 0.5)
        assert not cmd.is_job_running
        _panel_start(win)
        assert win.job_history_recorder._run is not None

        if first == "cut scale":
            winner, loser, refused = measured, assembled, "send-job"
        else:
            winner, loser, refused = assembled, measured, "cut-scale"
        winner.set()
        _wait(lambda: len(reached_driver) == 1)
        _pump(0.1)
        loser.set()
        _wait(lambda: tasks.get_task(refused) is None)
        _pump(0.1)
        driven.set()
        _wait(
            lambda: not cmd.is_job_running
            and tasks.get_task("cut-scale") is None
            and tasks.get_task("send-job") is None
        )
        _pump(0.1)

    assert len(reached_driver) == 1
    entries = win.job_history.entries(machine.name)
    if first == "cut scale":
        assert entries == []
    else:
        (entry,) = entries
        assert entry.document == "sign"


@pytest.mark.ui
def test_the_duration_runs_from_the_driver_to_the_end_of_the_send(
    main_window,
):
    """The pipeline's wait before the job reached the driver is not in it."""
    win = main_window
    recorder = win.job_history_recorder
    assembled = threading.Event()
    release = threading.Event()
    now = [1000.0]
    clock = SimpleNamespace(monotonic=lambda: now[0])

    with (
        patch("swiftcut.ui_gtk.machine.job_history_recorder.time", clock),
        _fake_send(win, pipeline=assembled, release=release),
    ):
        _toolbar_start(win)
        _wait(lambda: recorder._run is not None)
        now[0] += 30.0
        assembled.set()
        _wait(lambda: recorder._run.started_at is not None)
        now[0] += 95.5
        release.set()
        _wait_for_the_send(win)

    (entry,) = win.job_history.entries(_machine().name)
    assert entry.duration_s == 95.5


@pytest.mark.ui
def test_a_stop_before_the_job_reached_the_driver_does_not_mark_it(
    main_window,
):
    """The job that then runs is not one that was stopped."""
    win = main_window
    recorder = win.job_history_recorder
    assembled = threading.Event()

    with _fake_send(win, pipeline=assembled):
        _toolbar_start(win)
        _wait(lambda: recorder._run is not None)
        win.bottom_panel.jog_widget.stop_btn.emit("clicked")
        assembled.set()
        _wait_for_the_send(win)

    (entry,) = win.job_history.entries(_machine().name)
    assert entry.stopped is False


@pytest.mark.ui
@pytest.mark.parametrize(
    "answer, start_at", [("current", None), ("last", LAST)]
)
def test_a_start_chosen_on_the_crawford_sheet_is_recorded(
    main_window, answer, start_at
):
    from swiftcut.ui_gtk.machine.start_position_dialog import (
        StartPositionDialog,
    )

    win = main_window
    get_context().config.set_crawford_mode(True)
    _machine().set_last_job_start(LAST)

    with (
        _fake_send(win),
        patch.object(
            win.machine_cmd,
            "run_send_job",
            wraps=win.machine_cmd.run_send_job,
        ) as run_send_job,
    ):
        _toolbar_start(win)
        _pump()
        run_send_job.assert_not_called()
        (sheet,) = [
            w
            for w in Gtk.Window.list_toplevels()
            if isinstance(w, StartPositionDialog) and w.get_visible()
        ]
        sheet.response(answer)
        _wait_for_the_send(win)
        sheet.destroy()

    assert run_send_job.call_args.kwargs.get("start_at") == start_at
    (entry,) = win.job_history.entries(_machine().name)
    assert entry.stopped is False


# --- Machine > Job History ------------------------------------------


def _record(win, machine=None, document="sign", minutes=0, **kwargs):
    from datetime import datetime, timedelta, timezone

    from swiftcut.doceditor.job_history import render_thumbnail

    doc = Doc()
    doc.active_layer.set_name(document)
    step = {
        "type": "Contour",
        "speed": 600,
        "power": 0.8,
        "min_power": 0.5,
        "passes": 2,
    }
    fields = {
        "machine": machine or _machine().name,
        "document": document,
        "project": project_json(doc),
        "layers": [{"name": "Cut", "steps": [step]}],
        "duration_s": 125.0,
        "estimate_s": 120.0,
        "stopped": False,
        "thumbnail": render_thumbnail(_raster_ops()),
        "when": datetime(2026, 10, 8, 9, tzinfo=timezone.utc)
        + timedelta(minutes=minutes),
    }
    fields.update(kwargs)
    return win.job_history.record(**fields)


def _descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


def _rows(window) -> list[list[str]]:
    """Each row's labels, top to bottom."""
    rows = []
    row = window.list.get_first_child()
    while row is not None:
        rows.append(
            [
                w.get_label()
                for w in _descendants(row)
                if isinstance(w, Gtk.Label)
            ]
        )
        row = row.get_next_sibling()
    return rows


def _open_history(win):
    from swiftcut.ui_gtk.machine.job_history_dialog import JobHistoryWindow

    win.activate_action("win.job-history", None)
    _pump()
    (window,) = [
        w
        for w in Gtk.Window.list_toplevels()
        if isinstance(w, JobHistoryWindow) and w.get_visible()
    ]
    return window


@pytest.fixture
def history_window(main_window):
    window = None

    def open_it():
        nonlocal window
        window = _open_history(main_window)
        return window

    yield open_it
    if window is not None:
        window.destroy()


def _run_again_buttons(window) -> list[Gtk.Button]:
    return [button for _entry, button in window._run_buttons]


@pytest.mark.ui
def test_the_machine_menu_opens_the_job_history(main_window, history_window):
    from tests.ui_gtk.test_mainwindow import _menu_actions, _submenu

    machine_menu = _submenu(main_window.menu_model, "_Machine")
    assert "win.job-history" in _menu_actions(machine_menu)

    window = history_window()

    assert window.get_transient_for() is main_window
    assert window.stack.get_visible_child_name() == "empty"


@pytest.mark.ui
def test_the_list_shows_the_machines_jobs_newest_first(
    main_window, history_window
):
    win = main_window
    first = _record(win, document="first", minutes=0)
    _record(win, document="second", minutes=5, stopped=True)
    _record(win, machine="ilab-626", document="elsewhere")

    window = history_window()

    rows = _rows(window)
    assert [labels[0] for labels in rows] == ["second", "first"]
    date = first.date.astimezone().strftime("%Y-%m-%d %H:%M")
    assert rows[1][1] == " · ".join(
        [date, format_clock(125.0), _machine().name]
    )
    assert rows[0][1].endswith(" · Stopped")
    speed = format_value(600, "speed")
    assert speed == "10.0 mm/s"
    assert rows[1][2] == (
        f"Cut: Contour · {speed} · Max 80% · Min 50% · 2 passes"
    )
    pictures = [
        w for w in _descendants(window.list) if isinstance(w, Gtk.Picture)
    ]
    assert [p.get_file().get_path() for p in pictures] == [
        str(e.thumbnail_path)
        for e in win.job_history.entries(_machine().name)
    ]


@pytest.mark.ui
def test_the_list_follows_a_machine_switch_and_new_jobs(
    main_window, history_window, ui_context_initializer
):
    win = main_window
    _record(win, document="on this one")
    other = Machine(ui_context_initializer)
    other.name = "ilab-626"
    ui_context_initializer.machine_mgr.add_machine(other)
    _record(win, machine="ilab-626", document="on the other")
    first = _machine()
    window = history_window()
    assert [r[0] for r in _rows(window)] == ["on this one"]

    get_context().config.set_machine(other)
    assert [r[0] for r in _rows(window)] == ["on the other"]

    _record(win, machine="ilab-626", document="just ran", minutes=9)
    assert [r[0] for r in _rows(window)] == ["just ran", "on the other"]

    get_context().config.set_machine(first)
    assert [r[0] for r in _rows(window)] == ["on this one"]


@pytest.mark.ui
def test_run_again_needs_the_machine_connected_idle_and_its_own(
    main_window, history_window
):
    win = main_window
    machine = _machine()
    mine = _record(win, document="mine", minutes=1)
    copied = _record(win, document="copied")
    data = yaml.safe_load((copied.path / "entry.yaml").read_text())
    data["machine"] = "ilab-626"
    (copied.path / "entry.yaml").write_text(yaml.safe_dump(data))
    window = history_window()
    assert [e.document for e, _b in window._run_buttons] == [
        "mine",
        "copied",
    ]
    assert mine.machine == machine.name

    assert [b.get_sensitive() for b in _run_again_buttons(window)] == [
        False,
        False,
    ]

    with patch.object(type(machine), "is_connected", return_value=True):
        machine.connection_status_changed.send(
            machine, status=TransportStatus.CONNECTED
        )
        assert [b.get_sensitive() for b in _run_again_buttons(window)] == [
            True,
            False,
        ]

        with patch.object(
            MachineCmd,
            "is_job_running",
            new_callable=PropertyMock,
            return_value=True,
        ):
            win.machine_cmd.job_state_changed.send(win.machine_cmd)
            assert not any(
                b.get_sensitive() for b in _run_again_buttons(window)
            )


@pytest.mark.ui
def test_load_asks_about_unsaved_changes_then_opens_a_copy(
    main_window, history_window
):
    win = main_window
    editor = win.doc_editor
    entry = _record(win, document="from history")
    stored = json.loads(
        zipfile.ZipFile(entry.project_path).read("project.json")
    )
    editor.mark_as_unsaved()
    before = editor.doc
    window = history_window()
    load = next(
        w
        for w in _descendants(window.list)
        if isinstance(w, Gtk.Button) and w.get_label() == "Load"
    )

    with patch.object(
        win.project_cmd,
        "show_unsaved_changes_dialog",
        side_effect=lambda answer: answer("cancel"),
    ) as ask:
        load.emit("clicked")
    ask.assert_called_once()
    assert editor.doc is before
    assert window.get_visible()

    with patch.object(
        win.project_cmd,
        "show_unsaved_changes_dialog",
        side_effect=lambda answer: answer("discard"),
    ):
        load.emit("clicked")
    _pump()

    assert editor.doc is not before
    assert editor.doc.to_dict() == stored
    assert editor.file_path is None
    assert editor.is_saved
    assert not window.get_visible()


@pytest.mark.ui
def test_run_again_loads_then_starts_through_machine_send(
    main_window, history_window
):
    win = main_window
    editor = win.doc_editor
    entry = _record(win, document="again")
    window = history_window()
    send = win.action_manager.get_action("machine-send")
    sends = []
    send.connect("activate", lambda action, param: sends.append(param))
    run_again = _run_again_buttons(window)[0]

    with (
        patch.object(win, "_update_actions_and_ui"),
        patch.object(win, "_run_sanity_check_and_proceed") as checked,
    ):
        send.set_enabled(True)
        run_again.emit("clicked")
        assert editor.file_path is None
        assert editor.doc.active_layer.name == "again"
        _wait(lambda: sends)
        _pump(0.3)

    assert sends == [None]
    # The real Start handler ran: its sanity check comes next, and
    # after it E's Start sheet when Crawford mode is on.
    checked.assert_called_once()
    assert not window.get_visible()
    assert entry.project_path.exists()


@pytest.mark.ui
def test_run_again_on_a_connected_idle_machine_starts_it_once(
    main_window, history_window
):
    """
    Nothing in the window is patched: Start is enabled by its own
    rules once the loaded job is ready, on a machine faked connected
    and idle, and Run Again activates win.machine-send once.
    """
    win = main_window
    machine = _machine()
    _record(win, document="twice", project=TWO_LAYERS.read_text())
    send = win.action_manager.get_action("machine-send")
    sends = []
    send.connect("activate", lambda action, param: sends.append(param))
    driver = MagicMock(state=MagicMock(error=None))

    with (
        patch.object(machine, "connection_status", TransportStatus.CONNECTED),
        patch.object(
            type(machine),
            "driver",
            new_callable=PropertyMock,
            return_value=driver,
        ),
        _fake_send(win),
    ):
        machine.device_state.status = DeviceStatus.IDLE
        window = history_window()
        (run_again,) = _run_again_buttons(window)
        assert run_again.get_sensitive()
        run_again.emit("clicked")
        _wait(lambda: sends, timeout=30)
        _wait_for_the_send(win)
        _pump(0.5)

    assert sends == [None]
    assert not window.get_visible()
    again, first = win.job_history.entries(machine.name)
    assert again.document == first.document == "twice"


@pytest.mark.ui
def test_a_job_run_from_the_history_keeps_its_name(
    main_window, history_window
):
    """Until the copy is saved, or another document replaces it."""
    win = main_window
    editor = win.doc_editor
    _record(win, document="badge")
    window = history_window()
    load = next(
        w
        for w in _descendants(window.list)
        if isinstance(w, Gtk.Button) and w.get_label() == "Load"
    )

    with (
        patch.object(
            win.project_cmd,
            "show_unsaved_changes_dialog",
            side_effect=lambda answer: answer("discard"),
        ),
        _fake_send(win),
    ):
        load.emit("clicked")
        _pump()
        assert editor.file_path is None
        _toolbar_start(win)
        _wait_for_the_send(win)
        editor.set_file_path(Path("/lab/badge v2.ryp"))
        _toolbar_start(win)
        _wait_for_the_send(win)
        editor.set_doc(Doc())
        editor.set_file_path(None)
        _toolbar_start(win)
        _wait_for_the_send(win)

    assert [e.document for e in win.job_history.entries(_machine().name)] == [
        "Untitled",
        "badge v2",
        "badge",
        "badge",
    ]


@pytest.mark.ui
def test_a_damaged_entry_never_keeps_the_window_from_opening(
    main_window, history_window
):
    win = main_window
    _record(win, document="fine", minutes=1)
    damaged = _record(win, document="truncated")
    entry_yaml = damaged.path / "entry.yaml"
    text = entry_yaml.read_text()
    # Cut off inside the first step, after its type.
    entry_yaml.write_text(text[: text.index("speed:")])

    window = history_window()

    assert [labels[0] for labels in _rows(window)] == ["fine"]


@pytest.mark.ui
def test_a_run_again_start_waits_for_the_loaded_job(main_window):
    win = main_window
    editor = win.doc_editor
    send = win.action_manager.get_action("machine-send")
    sends = []
    send.connect("activate", lambda action, param: sends.append(param))

    with (
        patch.object(win, "_update_actions_and_ui"),
        patch.object(win, "_run_sanity_check_and_proceed"),
        patch.object(
            type(editor),
            "is_processing",
            new_callable=PropertyMock,
            return_value=True,
        ),
    ):
        send.set_enabled(True)
        win.start_when_settled()
        _pump()
        assert sends == []

        editor.document_settled.send(editor)
        editor.document_settled.send(editor)
        _pump()

    assert sends == [None]


@pytest.mark.ui
def test_a_run_again_start_is_dropped_for_another_document(main_window):
    win = main_window
    editor = win.doc_editor
    send = win.action_manager.get_action("machine-send")
    sends = []
    send.connect("activate", lambda action, param: sends.append(param))

    with (
        patch.object(win, "_update_actions_and_ui"),
        patch.object(win, "_run_sanity_check_and_proceed"),
        patch.object(
            type(editor),
            "is_processing",
            new_callable=PropertyMock,
            return_value=True,
        ),
    ):
        send.set_enabled(True)
        win.start_when_settled()
        editor.set_doc(Doc())
        editor.mark_as_saved()
        editor.document_settled.send(editor)
        _pump()

    assert sends == []


@pytest.mark.ui
def test_a_run_again_the_machine_cannot_start_says_so(main_window):
    win = main_window
    send = win.action_manager.get_action("machine-send")
    sends = []
    send.connect("activate", lambda action, param: sends.append(param))

    with (
        patch.object(win, "_update_actions_and_ui"),
        patch.object(win, "_on_editor_notification") as notify,
    ):
        send.set_enabled(False)
        win.start_when_settled()
        _wait(lambda: notify.called)

    assert sends == []
    assert "cannot start" in notify.call_args.kwargs["message"]


@pytest.mark.ui
def test_the_recorder_never_breaks_a_start(main_window):
    """A job history that cannot take the document still lets Start run."""
    win = main_window

    with (
        _fake_send(win),
        patch(
            "swiftcut.ui_gtk.machine.job_history_recorder.project_json",
            side_effect=RuntimeError("no"),
        ),
        patch.object(
            win.machine_cmd,
            "run_send_job",
            wraps=win.machine_cmd.run_send_job,
        ) as run_send_job,
    ):
        _toolbar_start(win)
        _wait_for_the_send(win)

    run_send_job.assert_called_once()
    assert win.job_history.entries(_machine().name) == []


@pytest.mark.ui
def test_a_history_that_cannot_be_written_never_breaks_the_send(
    main_window,
):
    win = main_window
    done = MagicMock()

    with (
        _fake_send(win),
        patch.object(
            win.job_history, "record", side_effect=OSError("disk full")
        ),
        patch.object(win, "_on_send_done", done),
    ):
        _toolbar_start(win)
        _wait_for_the_send(win)

    # The send's own end still ran after the history's failure.
    done.assert_called_once()

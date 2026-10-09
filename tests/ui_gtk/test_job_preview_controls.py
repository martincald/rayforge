"""The job preview's controls, and how the window drives the preview.

A Preview toggle beside the time estimate; once the job is ready,
play/pause, a scrub bar, elapsed / total and x1/x4/x16. Playback runs
on the canvas' frame clock and pauses at the end. The preview ends,
and the bar resets, when it is toggled off, when a newer job is
generated, when the document or the machine changes and when a job
starts.
"""

import time
from pathlib import Path
from types import SimpleNamespace

import cairo
import pytest
from gi.repository import Adw, GLib, Gtk
from raygeo.geo import Geometry
from raygeo.ops import Ops
from raygeo.ops.types import CommandCategory

from swiftcut.core.source_asset import SourceAsset
from swiftcut.core.source_asset_segment import SourceAssetSegment
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.image import SVG_RENDERER
from swiftcut.machine.models.machine import Machine
from swiftcut.pipeline.artifact import JobArtifact
from swiftcut.ui_gtk.canvas2d.elements.job_preview import theme_colors
from swiftcut.ui_gtk.shared.job_preview_bar import JobPreviewBar
from swiftcut.ui_gtk.shared.time_estimate_overlay import (
    TimeEstimateOverlay,
)

pytestmark = pytest.mark.ui


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    context = GLib.main_context_default()
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def _pump_until(condition, timeout: float = 30.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        _pump(0.05)
    return condition()


class _Recorder:
    """The bar's signals, as they are sent."""

    def __init__(self, bar: JobPreviewBar):
        self.toggled: list[bool] = []
        self.times: list[float] = []
        self.playing: list[bool] = []
        bar.preview_toggled.connect(self._on_toggled, weak=False)
        bar.time_changed.connect(self._on_time, weak=False)
        bar.playing_changed.connect(self._on_playing, weak=False)

    def _on_toggled(self, sender, *, active):
        self.toggled.append(active)

    def _on_time(self, sender, *, time):
        self.times.append(time)

    def _on_playing(self, sender, *, playing):
        self.playing.append(playing)


# --- The bar ---------------------------------------------------------


@pytest.fixture
def bar(ui_context_initializer):
    return JobPreviewBar()


class TestTheBar:
    def test_the_preview_toggle_sits_beside_the_estimate(
        self, ui_context_initializer
    ):
        overlay = TimeEstimateOverlay()

        assert overlay.preview_bar.get_parent() is overlay
        assert overlay.preview_bar.get_visible() is False

        overlay.set_estimated_time(90.0)
        assert overlay.preview_bar.get_visible() is True
        assert overlay._label.get_text() == "~01:30"

        overlay.set_estimated_time(None)
        assert overlay.preview_bar.get_visible() is False

    def test_the_transport_shows_once_a_preview_loads(self, bar):
        assert bar.toggle.get_visible() is True
        assert bar.controls.get_visible() is False

        bar.load(90.0)

        assert bar.controls.get_visible() is True
        assert bar.scale.get_adjustment().get_upper() == 90.0
        assert bar.label.get_text() == "00:00 / 01:30"

    def test_toggle(self, bar):
        recorder = _Recorder(bar)

        bar.toggle.set_active(True)
        bar.toggle.set_active(False)

        assert recorder.toggled == [True, False]

    def test_loading_plays_from_the_start(self, bar):
        recorder = _Recorder(bar)

        bar.load(90.0)

        assert (bar.time, bar.playing) == (0.0, True)
        assert recorder.times == [0.0]
        assert recorder.playing == [True]
        assert bar.play_button.get_tooltip_text() == "Pause"

    def test_play_and_pause(self, bar):
        recorder = _Recorder(bar)
        bar.load(90.0)

        bar.play_button.emit("clicked")
        assert bar.playing is False
        bar.advance(1.0)
        assert bar.time == 0.0

        bar.play_button.emit("clicked")
        assert bar.playing is True
        assert recorder.playing == [True, False, True]
        assert bar.play_button.get_tooltip_text() == "Pause"

    def test_scrub(self, bar):
        recorder = _Recorder(bar)
        bar.load(90.0)

        bar.scale.set_value(30.0)

        assert bar.time == 30.0
        assert recorder.times[-1] == 30.0
        assert bar.label.get_text() == "00:30 / 01:30"

    def test_scrub_is_clamped_to_the_job(self, bar):
        bar.load(90.0)

        bar.set_time(500.0)
        assert bar.time == 90.0
        bar.set_time(-5.0)
        assert bar.time == 0.0

    @pytest.mark.parametrize("speed", [1, 4, 16])
    def test_the_speed_multiplies_the_time_played(self, bar, speed):
        bar.load(90.0)

        bar.speed_buttons[speed].set_active(True)
        bar.advance(0.5)

        assert bar.speed == speed
        assert bar.time == pytest.approx(0.5 * speed)
        assert bar.label.get_text().startswith(
            f"00:{round(0.5 * speed):02d} / "
        )

    def test_the_speeds_are_one_choice(self, bar):
        bar.speed_buttons[16].set_active(True)

        assert [b.get_active() for b in bar.speed_buttons.values()] == [
            False,
            False,
            True,
        ]
        assert bar.speed_buttons[4].get_parent().has_css_class("linked")

    def test_playback_pauses_at_the_end(self, bar):
        recorder = _Recorder(bar)
        bar.load(10.0)

        bar.advance(4.0)
        assert bar.playing is True
        bar.advance(7.0)

        assert (bar.time, bar.playing) == (10.0, False)
        assert recorder.playing == [True, False]
        assert bar.label.get_text() == "00:10 / 00:10"

    def test_play_at_the_end_starts_over(self, bar):
        bar.load(10.0)
        bar.advance(20.0)

        bar.play_button.emit("clicked")

        assert (bar.time, bar.playing) == (0.0, True)

    def test_reset_turns_it_all_off(self, bar):
        bar.toggle.set_active(True)
        bar.load(90.0)
        bar.set_time(30.0)
        recorder = _Recorder(bar)

        bar.reset()

        assert bar.active is False
        assert bar.controls.get_visible() is False
        assert (bar.time, bar.total, bar.playing) == (0.0, 0.0, False)
        assert recorder.toggled == [False]
        assert recorder.playing == [False]


# --- The window ------------------------------------------------------


@pytest.fixture
def win(ui_context_initializer):
    from swiftcut.ui_gtk.mainwindow import MainWindow

    class App(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)
            self.win.set_default_size(1280, 800)

    app = App(application_id="org.swiftcut.swiftcut.test.job-preview")
    app.register(None)
    app.activate()
    window = app.win
    window.present()
    _pump(0.5)
    yield window
    # A sheet the window raised (Missing Features, when a test's project
    # names a step type this context lacks) goes with it.
    for toplevel in Gtk.Window.list_toplevels():
        if toplevel.get_transient_for() is window:
            toplevel.destroy()
    window.doc_editor.cleanup()
    window.destroy()
    app.quit()
    _pump(0.2)


def _job_ops() -> Ops:
    ops = Ops()
    ops.set_power(1.0)
    ops.move_to(10.0, 10.0)
    ops.line_to(60.0, 10.0)
    ops.move_to(60.0, 40.0)
    ops.line_to(10.0, 40.0)
    return ops


def _serve_job(win, monkeypatch):
    """
    The window's pipeline hands out a job artifact from its store, the
    way generate_job_artifact does once the job is current. Returns
    the handle, and the when_done callbacks it was asked with.
    """
    pipeline = win.doc_editor.pipeline
    ops = _job_ops()
    artifact = JobArtifact(
        ops=ops,
        distance=ops.distance(),
        generation_id=1,
        time_estimate=ops.estimate_time(
            pipeline.machine.max_cut_speed,
            pipeline.machine.max_travel_speed,
            pipeline.machine.acceleration,
        ),
    )
    handle = pipeline.artifact_store.put(artifact, "job")
    asked = []

    def generate_job_artifact(when_done):
        asked.append(when_done)
        when_done(handle, None)

    monkeypatch.setattr(
        pipeline, "generate_job_artifact", generate_job_artifact
    )
    return handle, asked


def _shown(win):
    return win.surface._job_preview_element.model


def _bar(win) -> JobPreviewBar:
    return win._time_estimate_overlay.preview_bar


@pytest.fixture
def previewing(win, monkeypatch):
    """A window showing a preview of a two-cut job."""
    handle, asked = _serve_job(win, monkeypatch)
    win._time_estimate_overlay.set_estimated_time(12.0)
    _bar(win).toggle.set_active(True)
    assert _shown(win) is not None
    return SimpleNamespace(win=win, handle=handle, asked=asked)


def _assert_cleared(win):
    assert _shown(win) is None
    assert win.surface._job_preview_element.visible is False
    bar = _bar(win)
    assert bar.active is False
    assert bar.controls.get_visible() is False
    assert bar.playing is False
    assert win._job_preview_tick_id is None


class TestTheWindow:
    def test_toggle_on_previews_the_checked_out_job(self, previewing):
        win = previewing.win
        model = _shown(win)
        store = win.doc_editor.pipeline.artifact_store

        with store.checkout_handle(previewing.handle) as artifact:
            ops = artifact.ops
            moving = [
                i
                for i in range(len(ops))
                if ops.category(i) == CommandCategory.MOVING
            ]
            estimate = artifact.time_estimate
        assert [s.op_index for s in model.segments] == moving
        assert model.total_time == pytest.approx(estimate)
        bar = _bar(win)
        assert bar.total == model.total_time
        assert bar.playing is True
        assert bar.controls.get_visible() is True

    def test_the_canvas_draws_it_in_the_theme_colours(self, previewing):
        win = previewing.win
        element = win.surface._job_preview_element
        _bar(win).set_time(_shown(win).total_time)
        target = cairo.ImageSurface(
            cairo.FORMAT_ARGB32,
            win.surface.get_width(),
            win.surface.get_height(),
        )

        element.draw_overlay(cairo.Context(target))

        assert theme_colors() is not None
        assert element._finished_count == len(_shown(win).segments)

    def test_playback_runs_on_the_surface_frame_clock(self, previewing):
        win = previewing.win
        bar = _bar(win)
        bar.speed_buttons[4].set_active(True)

        assert win._job_preview_tick_id is not None
        win._on_job_preview_tick(
            win.surface, SimpleNamespace(get_frame_time=lambda: 1_000_000)
        )
        win._on_job_preview_tick(
            win.surface, SimpleNamespace(get_frame_time=lambda: 1_500_000)
        )

        # Half a second of frames, played at x4.
        assert bar.time == pytest.approx(2.0)
        assert win.surface._job_preview_element.time == pytest.approx(2.0)

    def test_playback_stops_ticking_at_the_end(self, previewing):
        win = previewing.win
        bar = _bar(win)

        bar.advance(bar.total + 1.0)

        assert bar.playing is False
        assert win._job_preview_tick_id is None
        assert _shown(win) is not None

    @pytest.mark.parametrize("wait_for_the_job", [True, False])
    def test_a_real_pipeline_job_previews_and_matches_the_estimate(
        self, win, wait_for_the_job
    ):
        """
        End to end: a real document, the real pipeline. Asked for
        before the job is generated, the preview waits for it, and
        nothing the pipeline does meanwhile may end it.
        """
        doc = win.doc_editor.doc
        workpiece = WorkPiece(name="rect.svg")
        source = SourceAsset(
            Path(workpiece.name),
            original_data=b"""<svg width="50mm" height="30mm"
                xmlns="http://www.w3.org/2000/svg">
                <rect width="50" height="30" /></svg>""",
            renderer=SVG_RENDERER,
        )
        doc.add_asset(source)
        workpiece.source_segment = SourceAssetSegment(
            source_asset_uid=source.uid,
            pristine_geometry=Geometry(),
            vectorization_spec=PassthroughSpec(),
        )
        workpiece.set_size(50, 30)
        workpiece.pos = 10, 20
        doc.active_layer.add_workpiece(workpiece)
        bar = _bar(win)
        if wait_for_the_job:
            assert _pump_until(lambda: bar.get_visible())
            assert _pump_until(
                lambda: (
                    win.doc_editor.pipeline.get_existing_job_handle()
                    is not None
                )
            )

        bar.toggle.set_active(True)
        if not wait_for_the_job:
            # The job is still to come: the preview waits for it.
            assert _shown(win) is None

        assert _pump_until(lambda: _shown(win) is not None)
        pipeline = win.doc_editor.pipeline
        handle = pipeline.get_existing_job_handle()
        with pipeline.artifact_store.checkout_handle(handle) as artifact:
            ops = artifact.ops
            moving = [
                i
                for i in range(len(ops))
                if ops.category(i) == CommandCategory.MOVING
            ]
            estimate = artifact.time_estimate
        model = _shown(win)
        assert moving and [s.op_index for s in model.segments] == moving
        assert model.total_time == pytest.approx(estimate)
        assert bar.total == model.total_time
        assert bar.active is True

    def test_toggle_off_clears(self, previewing):
        _bar(previewing.win).toggle.set_active(False)

        _assert_cleared(previewing.win)

    def test_a_newer_job_generation_clears(self, previewing):
        win = previewing.win
        pipeline = win.doc_editor.pipeline

        # The job it shows, sent again, keeps it.
        pipeline.job_generation_finished.send(
            pipeline, handle=previewing.handle, task_status="completed"
        )
        assert _shown(win) is not None

        newer = pipeline.artifact_store.put(
            JobArtifact(ops=_job_ops(), distance=0.0, generation_id=2), "job"
        )
        pipeline.job_generation_finished.send(
            pipeline, handle=newer, task_status="completed"
        )

        _assert_cleared(win)

    def test_a_generation_answering_a_pending_preview_does_not_clear(
        self, win, monkeypatch
    ):
        handle, _asked = _serve_job(win, monkeypatch)
        pending = []
        pipeline = win.doc_editor.pipeline
        monkeypatch.setattr(
            pipeline,
            "generate_job_artifact",
            lambda when_done: pending.append(when_done),
        )
        win._time_estimate_overlay.set_estimated_time(12.0)
        _bar(win).toggle.set_active(True)

        # The generation it waits for finishes: the window hears the
        # signal, then the request is answered.
        pipeline.job_generation_finished.send(
            pipeline, handle=handle, task_status="completed"
        )
        pending[0](handle, None)

        assert _shown(win) is not None
        assert _bar(win).active is True

    def test_a_document_edit_clears(self, previewing):
        doc = previewing.win.doc_editor.doc

        doc.updated.send(doc)

        _assert_cleared(previewing.win)

    def test_a_new_document_clears(self, previewing):
        editor = previewing.win.doc_editor

        editor.document_changed.send(editor)

        _assert_cleared(previewing.win)

    def test_a_machine_change_clears(self, previewing):
        win = previewing.win
        context = win.doc_editor.context
        config = context.config

        # A config change on the same machine keeps it.
        config.changed.send(config)
        assert _shown(win) is not None

        other = Machine(context)
        other.driver_name = config.machine.driver_name
        context.machine_mgr.add_machine(other)
        config.set_machine(other)

        _assert_cleared(win)

    def test_a_job_start_clears(self, previewing):
        cmd = previewing.win.machine_cmd

        cmd.job_started.send(cmd)

        _assert_cleared(previewing.win)

    def test_a_late_answer_after_toggle_off_is_ignored(self, win, monkeypatch):
        handle, _asked = _serve_job(win, monkeypatch)
        pending = []
        monkeypatch.setattr(
            win.doc_editor.pipeline,
            "generate_job_artifact",
            lambda when_done: pending.append(when_done),
        )
        win._time_estimate_overlay.set_estimated_time(12.0)
        bar = _bar(win)
        bar.toggle.set_active(True)
        bar.toggle.set_active(False)

        pending[0](handle, None)

        _assert_cleared(win)

    def test_a_failed_preview_turns_the_toggle_back_off(
        self, win, monkeypatch
    ):
        """It runs inside the pipeline's signal: it must not raise."""
        _serve_job(win, monkeypatch)
        monkeypatch.setattr(
            "swiftcut.ui_gtk.mainwindow.JobPreviewModel.from_ops",
            lambda *args: (_ for _ in ()).throw(ValueError("broken")),
        )
        win._time_estimate_overlay.set_estimated_time(12.0)

        _bar(win).toggle.set_active(True)

        _assert_cleared(win)

    def test_no_job_turns_the_toggle_back_off(self, win, monkeypatch):
        monkeypatch.setattr(
            win.doc_editor.pipeline,
            "generate_job_artifact",
            lambda when_done: when_done(None, RuntimeError("no job")),
        )
        win._time_estimate_overlay.set_estimated_time(12.0)

        _bar(win).toggle.set_active(True)

        _assert_cleared(win)

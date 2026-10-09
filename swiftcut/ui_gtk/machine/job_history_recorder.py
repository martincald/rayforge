import logging
import time
import weakref
from dataclasses import dataclass
from gettext import gettext as _
from typing import TYPE_CHECKING, Any

from ...doceditor.file_cmd import project_json
from ...doceditor.job_history import JobHistory, job_layers, render_thumbnail
from ...pipeline.artifact import JobArtifact
from .start_position_dialog import start_chosen

if TYPE_CHECKING:
    from ...machine.models.machine import Machine
    from ...shared.tasker.task import Task
    from ..mainwindow import MainWindow

logger = logging.getLogger(__name__)

# The key run_send_job gives the task that runs an accepted Start.
SEND_TASK_KEY = "send-job"


@dataclass
class _Run:
    """A Start being followed, from the moment it was accepted."""

    machine: "Machine"
    document: str
    project: str
    layers: list[dict[str, Any]]
    # The Start's own "send-job" task; None until it is known.
    task: "Task | None" = None
    # Monotonic seconds when the job reached the driver.
    started_at: float | None = None
    estimate_s: float | None = None
    thumbnail: bytes | None = None
    stopped: bool = False


class JobHistoryRecorder:
    """
    Records each Start that ran, from the toolbar or the jog panel,
    into the job history.

    It follows the Start from outside MachineCmd's send path, which it
    leaves as it is:

    - request_start's start_chosen comes just before either Start
      runs. With nothing running, run_send_job will accept it (it
      refuses only while a job runs), so the document is taken then,
      before the pipeline runs;
    - the job_state_changed run_send_job sends as it accepts makes
      that the run;
    - the run is bound to its own "send-job" task. run_send_job adds
      the task right after that job_state_changed, and the task
      manager's tasks_updated for the addition is queued then, before
      the task can run, so it lists the task while it surely exists.
      A task that ends fast is gone before anything queued later
      could look it up by key;
    - job_started while the run is bound says the job reached the
      driver, and hands over the job for the thumbnail and the
      estimate. Jobs run one at a time: a frame or Cut Scale that got
      there first makes the Start's own job refused, and its task
      fail;
    - the run ends once its task is done. It is recorded only if the
      task completed and a job reached the driver while it ran: a
      refused or failed Start records nothing.

    A Stop pressed once the job reached the driver, from either Stop,
    marks it stopped. No handler raises: they run inside the Start and
    the send path.
    """

    def __init__(self, win: "MainWindow", history: JobHistory):
        self._win = win
        self._editor = win.doc_editor
        self._machine_cmd = win.machine_cmd
        self.history = history
        self._pending: _Run | None = None
        self._run: _Run | None = None
        # The document a history entry was loaded into, and its name.
        self._copy: tuple[weakref.ref, str] | None = None
        start_chosen.connect(self._on_start_chosen)
        self._machine_cmd.job_state_changed.connect(
            self._on_job_state_changed
        )
        self._editor.task_manager.tasks_updated.connect(
            self._on_tasks_updated
        )
        self._machine_cmd.job_started.connect(self._on_job_started)

    def stop_pressed(self):
        """A Stop was pressed; a running job is recorded as stopped."""
        if self._run is not None and self._run.started_at is not None:
            self._run.stopped = True

    def copy_loaded(self, document: str):
        """
        The document just loaded is a copy of the history's job named
        document; a job it runs keeps that name until it is saved.
        """
        self._copy = (weakref.ref(self._editor.doc), document)

    def _document_name(self) -> str:
        file_path = self._editor.file_path
        if file_path:
            return file_path.stem
        if self._copy is not None:
            doc, document = self._copy
            if doc() is self._editor.doc:
                return document
        return _("Untitled")

    def _on_start_chosen(self, sender, *, machine: "Machine"):
        if sender is not self._win or self._machine_cmd.is_job_running:
            return
        try:
            self._pending = _Run(
                machine=machine,
                document=self._document_name(),
                project=project_json(self._editor.doc),
                layers=job_layers(self._editor.doc),
            )
        except Exception:
            logger.exception("Job history: could not take the document")

    def _on_job_state_changed(self, sender):
        if self._pending is not None:
            run, self._pending = self._pending, None
            if self._machine_cmd.is_job_running:
                self._run = run
            return
        run = self._run
        if run is None:
            return
        if run.task is not None:
            if run.task.is_final():
                self._end()
        elif not self._machine_cmd.is_job_running:
            # Its task was never seen; it cannot have run a job.
            self._end()

    def _on_tasks_updated(self, sender, *, tasks, **kwargs):
        run = self._run
        if run is None or run.task is not None:
            return
        for task in tasks:
            if task.key == SEND_TASK_KEY:
                run.task = task
                return

    def _on_job_started(self, sender):
        run = self._run
        if run is None or run.task is None or run.started_at is not None:
            return
        run.started_at = time.monotonic()
        pipeline = self._editor.pipeline
        handle = pipeline.get_existing_job_handle()
        if handle is None:
            return
        try:
            with pipeline.artifact_store.checkout_handle(handle) as artifact:
                if isinstance(artifact, JobArtifact):
                    run.estimate_s = artifact.time_estimate
                    run.thumbnail = render_thumbnail(artifact.ops)
        except Exception:
            logger.exception("Job history: no thumbnail for this job")

    def _end(self):
        run, self._run = self._run, None
        assert run is not None
        status = run.task.get_status() if run.task else None
        if run.started_at is None or status != "completed":
            logger.info(
                f"Job history: the Start ran no job to its end (send "
                f"task {status}); not recorded"
            )
            return
        try:
            self.history.record(
                machine=run.machine.name,
                document=run.document,
                project=run.project,
                layers=run.layers,
                duration_s=time.monotonic() - run.started_at,
                estimate_s=run.estimate_s,
                stopped=run.stopped,
                thumbnail=run.thumbnail,
            )
        except Exception:
            logger.exception("Job history: could not record the job")

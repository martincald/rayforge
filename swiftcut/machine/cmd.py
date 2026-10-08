from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from gettext import gettext as _
from typing import TYPE_CHECKING

import numpy as np
from blinker import Signal
from raygeo.ops import Ops
from raygeo.ops.axis import Axis
from raygeo.ops.types import CommandType

from ..context import get_context
from ..pipeline.artifact import JobArtifact
from ..pipeline.artifact.handle import BaseArtifactHandle
from ..pipeline.encoder.base import EncodedOutput
from .driver import acceleration_run_up_mm, get_driver_cls
from .driver.dummy import NoDeviceDriver
from .driver.ruida.ruida_driver import _job_size_mm
from .job_monitor import JobMonitor
from .models.coordspace import MachineSpace

if TYPE_CHECKING:
    from ..doceditor.editor import DocEditor
    from .models.laser import Laser
    from .models.machine import Machine


logger = logging.getLogger(__name__)

# How close the head has to come to the last job's start before a
# Crawford Start runs: the driver's own jog settle tolerance.
PREMOVE_TOLERANCE_MM = 0.5


class MachineCmd:
    """Handles commands sent to the machine driver."""

    def __init__(self, editor: DocEditor):
        self._editor = editor
        self._scheduler = editor.task_manager.schedule_on_main_thread
        self.job_started = Signal()
        # Sent on the main thread whenever is_job_running may have
        # changed, so Start can follow it.
        self.job_state_changed = Signal()
        self._current_monitor: JobMonitor | None = None
        # From an accepted Start until its send task is done, which
        # covers the pipeline run before the monitor exists.
        self._send_active = False
        self._on_progress_callback: Callable[[dict], None] | None = None
        # A Stop pressed while a scale is still measuring its outline
        # has no job on the driver to stop yet, so it is latched here
        # and the scale refuses to start.
        self._scale_cancelled = False
        # The same for a Start still moving the head to the last job's
        # start: Stop ends the move, and the job must not follow it.
        self._premove_cancelled = False
        self._cancel_in_flight = False

    @property
    def is_job_running(self) -> bool:
        """Whether a job is running, or a Start is preparing one."""
        return self._current_monitor is not None or self._send_active

    def select_tool(self, machine: Machine, head_index: int):
        """Adds a 'select_head' task to the task manager."""
        if not (0 <= head_index < len(machine.heads)):
            logger.error(f"Invalid head index {head_index} for tool selection")
            return

        head = machine.heads[head_index]
        tool_number = head.tool_number

        self._editor.task_manager.add_coroutine(
            lambda ctx: machine.select_tool(tool_number), key="select-head"
        )

    def _job_motion_extent(
        self, ops: Ops, machine: Machine
    ) -> tuple[float, float, float, float]:
        """
        Where the head will actually go, in job-local millimeters.

        Travel moves count, and on a controller that overscans natively
        the raster run-up is added back: it never appears in the op
        stream, but the head still travels it.
        """
        min_x, min_y, max_x, max_y = ops.rect(True)
        driver = machine.driver
        if driver is None or not driver.native_overscan:
            return min_x, min_y, max_x, max_y

        acceleration = float(machine.acceleration or 0)
        pad = 0.0
        rate = 0.0
        for i in range(ops.len()):
            command = ops.command_type(i)
            if command == CommandType.SET_FEED_RATE:
                rate = float(ops.rate(i) or 0.0)
            elif command == CommandType.SCAN_LINE:
                pad = max(pad, acceleration_run_up_mm(rate, acceleration))
        return min_x - pad, min_y, max_x + pad, max_y

    def _warn_if_job_overruns_bed(self, ops: Ops, machine: Machine) -> None:
        """
        Toast, without blocking, when the job cannot fit from here.

        The job is anchored where the head is now, so a rectangle that
        fits the bed on its own can still run off the far edge.
        """
        bed_w, bed_h = machine.axis_extents
        if bed_w <= 0 or bed_h <= 0:
            return
        try:
            min_x, min_y, max_x, max_y = self._job_motion_extent(ops, machine)
        except Exception:
            logger.debug("Could not measure job extent", exc_info=True)
            return

        pos = machine.device_state.machine_pos
        start_x = float(pos[0] or 0.0)
        start_y = float(pos[1] or 0.0)
        width = max_x - min_x
        height = max_y - min_y
        if start_x + width <= bed_w and start_y + height <= bed_h:
            return

        logger.warning(
            f"Job extent {width:.1f} x {height:.1f} mm from "
            f"({start_x:.1f}, {start_y:.1f}) leaves the "
            f"{bed_w:.0f} x {bed_h:.0f} mm bed"
        )
        self._editor.notification_requested.send(
            self,
            message=_(
                "This job needs {width:.0f} x {height:.0f} mm from the "
                "current position and would run past the bed."
            ).format(width=width, height=height),
        )

    def _progress_handler(self, sender, metrics):
        """Signal handler for job progress updates."""
        logger.debug(f"JobMonitor progress: {metrics}")
        if self._on_progress_callback:
            self._scheduler(self._on_progress_callback, metrics)

    async def _execute_monitored_job(
        self,
        ops: Ops,
        machine: Machine,
        on_progress: Callable[[dict], None] | None = None,
        encoded: EncodedOutput | None = None,
    ):
        """
        Internal helper to execute a job on a driver while managing
        a JobMonitor for progress reporting.
        """
        if self._current_monitor:
            msg = "Tried to start a job while another is running."
            logger.warning(msg)
            # A running job is a failure condition for starting a new one.
            raise RuntimeError(msg)

        if ops.is_empty():
            logger.warning("Job has no operations. Skipping execution.")
            if machine.driver:
                machine.driver.job_finished.send(machine.driver)
            return

        self._warn_if_job_overruns_bed(ops, machine)

        # Store the callback
        self._on_progress_callback = on_progress

        def cleanup_monitor():
            """Cleans up the monitor when the job is done."""
            logger.debug("Job finished, cleaning up monitor.")
            if self._current_monitor:
                try:
                    self._current_monitor.progress_updated.disconnect(
                        self._progress_handler
                    )
                finally:
                    # Ensure the flag is cleared even if disconnect fails.
                    self._current_monitor = None
            self._on_progress_callback = None

        try:
            self._current_monitor = JobMonitor(ops)

            if self._on_progress_callback:
                logger.debug("Connecting progress handler to JobMonitor")
                self._current_monitor.progress_updated.connect(
                    self._progress_handler
                )

            # Signal that the job has started.
            self._scheduler(self.job_started.send, self)
            self._scheduler(self.job_state_changed.send, self)

            # Pipeline must have produced encoded output.
            if encoded is None:
                raise RuntimeError("Pipeline did not produce encoded output.")

            if machine.reports_granular_progress:
                await machine.driver.run(
                    encoded,
                    self._editor.doc,
                    ops,
                    on_command_done=self._current_monitor.update_progress,
                )
            else:
                await machine.driver.run(
                    encoded,
                    self._editor.doc,
                    ops,
                    on_command_done=None,
                )
                if self._current_monitor:
                    self._current_monitor.mark_as_complete()

            estimated_seconds = ops.estimate_time(
                default_feed_rate=machine.max_cut_speed,
                default_rapid_rate=machine.max_travel_speed,
                acceleration=machine.acceleration,
            )
            estimated_hours = estimated_seconds / 3600.0
            machine.add_machine_hours(estimated_hours)
            logger.info(
                f"Job completed. Estimated time: {estimated_hours:.3f}h "
                f"added to machine hours."
            )
        finally:
            cleanup_monitor()
            self._scheduler(self.job_state_changed.send, self)

    async def _run_frame_action(
        self,
        artifact: JobArtifact,
        machine: Machine,
        on_progress: Callable[[dict], None] | None,
    ):
        """The specific machine action for a framing job."""
        if not isinstance(artifact, JobArtifact):
            raise TypeError("_run_frame_action received a non-JobArtifact")
        ops = artifact.ops

        head = machine.get_default_laser_head()
        if head is None:
            raise ValueError("Machine has no laser heads configured.")
        if not head.frame_power_percent:
            logger.warning("Framing cancelled: Frame power is zero.")
            return

        frame_speed = (
            head.frame_speed
            if head.frame_speed > 0
            else machine.max_travel_speed
        )

        min_x, min_y, max_x, max_y = ops.rect()

        frame_ops = Ops()
        frame_ops.set_head(head.uid)
        frame_ops.set_power(head.frame_power_percent)
        frame_ops.set_feed_rate(frame_speed)

        corners = [
            (min_x, min_y),
            (min_x, max_y),
            (max_x, max_y),
            (max_x, min_y),
            (min_x, min_y),
        ]
        prev = corners[0]
        for corner in corners[1:]:
            frame_ops.move_to(*prev)
            frame_ops.line_to(*corner)
            if head.frame_corner_pause > 0:
                frame_ops.dwell(head.frame_corner_pause * 1000)
            prev = corner

        frame_with_laser = frame_ops * head.frame_repeat_count
        frame_with_laser.job_end()

        # Transform world-space frame ops to machine space.
        space = MachineSpace.from_machine(machine)
        combined = space.get_world_to_machine_matrix()
        if machine.reverse_z_axis:
            z_flip = np.eye(4)
            z_flip[2, 2] = -1.0
            combined = z_flip @ combined
        frame_with_laser.transform(combined)

        # Encode via the driver encoder (no pre-processing needed).
        encoder = _create_driver_encoder(machine)
        encoded = encoder.encode(frame_with_laser, machine, self._editor.doc)

        await self._execute_monitored_job(
            frame_with_laser,
            machine,
            on_progress=on_progress,
            encoded=encoded,
        )

    async def _run_send_action(
        self,
        artifact: JobArtifact,
        machine: Machine,
        on_progress: Callable[[dict], None] | None,
    ):
        """The specific machine action for a send job."""
        if not isinstance(artifact, JobArtifact):
            raise TypeError("_run_send_action received a non-JobArtifact")

        # Taken before the run: a Stop mid-job reads the position
        # again, so afterwards it is wherever the head stopped.
        anchor = self._job_anchor(artifact.ops, machine)
        await self._execute_monitored_job(
            artifact.ops,
            machine,
            on_progress=on_progress,
            encoded=artifact.encoded_output,
        )
        self._start_job_ended(machine, anchor)

    def _start_corner_offset(
        self, ops: Ops, machine: Machine
    ) -> tuple[float, float]:
        """How far the driver moves the head before it sends this job."""
        return machine.panel.start_corner_offset(
            machine.start_corner, *_job_size_mm(ops)
        )

    def _job_anchor(
        self, ops: Ops, machine: Machine
    ) -> tuple[float, float] | None:
        """
        Where a job about to run is anchored, in machine-space mm.

        That is the head's position plus the start-corner move the
        driver makes before it sends, so the point the job is cut
        from. None for an empty job or an unknown position.
        """
        x, y = machine.device_state.machine_pos[:2]
        if ops.is_empty() or x is None or y is None:
            return None
        dx, dy = self._start_corner_offset(ops, machine)
        return x + dx, y + dy

    def _start_job_ended(
        self, machine: Machine, anchor: tuple[float, float] | None
    ) -> None:
        """
        A Start job's run returned without raising.

        The one place a Start is known to have ended, so anything that
        follows a job belongs here. The driver also returns quietly
        when a job is stopped, or refused once its start-corner move
        fails, so this means "ended", not "cut".
        """
        if anchor is not None:
            self._scheduler(machine.set_last_job_start, anchor)

    async def _premove_to_start(
        self,
        ops: Ops,
        machine: Machine,
        start_at: tuple[float, float],
        speed: int | None,
    ) -> bool:
        """
        Jog the head so this job is anchored at start_at.

        The driver still makes its own start-corner move before it
        sends, so the head goes that far short of start_at and the
        driver's move lands it there. The jog is the jog panel's
        primitive: ignored while the machine is busy, waited out until
        it settles, and ended by Stop.

        Returns whether the job may go ahead: only once the head is
        there. A move that was stopped, was ignored, or could not
        reach the target (a clamped one, say) refuses the job.
        """
        x, y = machine.device_state.machine_pos[:2]
        if x is None or y is None:
            self._refuse_start(
                "the head position is unknown",
                _("Job not sent: the head position is unknown."),
            )
            return False

        dx, dy = self._start_corner_offset(ops, machine)
        target = (start_at[0] - dx, start_at[1] - dy)

        def arrived() -> bool:
            hx, hy = machine.device_state.machine_pos[:2]
            return (
                hx is not None
                and hy is not None
                and abs(target[0] - hx) <= PREMOVE_TOLERANCE_MM
                and abs(target[1] - hy) <= PREMOVE_TOLERANCE_MM
            )

        # The latch is checked before the jog as well: a Stop pressed
        # while the job was still being prepared must not move the head.
        if not self._premove_cancelled and not arrived():
            logger.info(
                f"Moving to the last job's start: ({target[0]:.2f}, "
                f"{target[1]:.2f}) mm"
            )
            await machine.jog(
                {Axis.X: target[0] - x, Axis.Y: target[1] - y}, speed
            )

        if self._premove_cancelled:
            self._refuse_start(
                "the move to the last job's start position was stopped",
                _(
                    "Job not sent: the move to the last job's start "
                    "position was stopped."
                ),
            )
            return False
        if not arrived():
            self._refuse_start(
                f"the head did not reach the last job's start position "
                f"({target[0]:.2f}, {target[1]:.2f}) mm; it is at "
                f"{machine.device_state.machine_pos}",
                _(
                    "Job not sent: the head did not reach the last "
                    "job's start position."
                ),
            )
            return False
        return True

    def _refuse_start(self, reason: str, message: str) -> None:
        """Log and show why a Crawford Start sent no job."""
        logger.warning(f"Job not sent: {reason}")
        self._scheduler(
            self._editor.notification_requested.send, self, message=message
        )

    async def _start_job(
        self,
        machine: Machine,
        job_name: str,
        final_job_action: Callable[..., Coroutine],
        on_progress: Callable[[dict], None] | None = None,
    ):
        """
        Generic, awaitable job starter that orchestrates assembly and
        execution.
        """
        handle: BaseArtifactHandle | None = None
        artifact_store = self._editor.pipeline.artifact_store

        try:
            # 1. Await the job artifact generation from the pipeline
            handle = await self._editor.pipeline.generate_job_artifact_async()

            if not handle:
                logger.warning(
                    f"{job_name.capitalize()} job has no operations."
                )
                return

            # 2. Use the safe context manager to acquire and release the
            # artifact
            with artifact_store.checkout_handle(handle) as artifact:
                if not artifact:
                    raise ValueError(
                        "Failed to retrieve artifact from handle."
                    )

                await final_job_action(artifact, machine, on_progress)

        except Exception as e:
            logger.exception(f"Failed to assemble or execute {job_name} job")
            self._editor.notification_requested.send(
                self,
                message=_("{job_name} failed: {error}").format(
                    job_name=job_name.capitalize(), error=e
                ),
            )
            # Manually release handle on error if checkout was not entered
            if handle and "artifact" not in locals():
                artifact_store.release(handle)
            raise

    async def frame_job(
        self,
        machine: Machine,
        on_progress: Callable[[dict], None] | None = None,
    ):
        """
        Asynchronously generates ops and runs a framing job.
        This is an awaitable coroutine.
        """
        await self._start_job(
            machine,
            job_name="framing",
            final_job_action=self._run_frame_action,
            on_progress=on_progress,
        )

    async def send_job(
        self,
        machine: Machine,
        on_progress: Callable[[dict], None] | None = None,
    ):
        """
        Asynchronously generates ops and sends the job to the machine.
        This is an awaitable coroutine.
        """
        await self._start_job(
            machine,
            job_name="sending",
            final_job_action=self._run_send_action,
            on_progress=on_progress,
        )

    def run_send_job(
        self,
        machine: Machine,
        on_progress: Callable[[dict], None] | None = None,
        on_done: Callable[[], None] | None = None,
        start_at: tuple[float, float] | None = None,
        premove_speed: int | None = None,
    ):
        """
        Schedules the send_job coroutine to run via the task manager.

        Refused while a job is running: a second "send-job" task would
        replace the first, cancelling it with no D8 01 while the
        controller runs on. Cancel is the only way to end a job.

        Args:
            machine: The machine to send to.
            on_progress: Optional progress callback, on the main thread.
            on_done: Optional callback, run on the main thread once the
                send finishes, is cancelled, or fails.
            start_at: Crawford mode's "last job's start position": a
                machine-space (x, y) in mm the job is anchored at. The
                head is jogged there first, in the same task, so the
                one-job rule and Stop cover the move too.
            premove_speed: That jog's speed in mm/min, the jog panel's.
        """
        if start_at is not None and premove_speed is None:
            raise ValueError("start_at needs a premove_speed")
        if self.is_job_running:
            logger.warning("Start ignored: a job is already running")
            return
        self._send_active = True
        self.job_state_changed.send(self)

        final_job_action = self._run_send_action
        if start_at is not None:
            self._premove_cancelled = False

            async def premove_then_send(artifact, machine, on_progress):
                if await self._premove_to_start(
                    artifact.ops, machine, start_at, premove_speed
                ):
                    await self._run_send_action(
                        artifact, machine, on_progress
                    )

            final_job_action = premove_then_send

        def when_done(task):
            self._send_active = False
            self.job_state_changed.send(self)
            if on_done is not None:
                on_done()

        self._editor.task_manager.add_coroutine(
            lambda ctx: self._start_job(
                machine,
                job_name="sending",
                final_job_action=final_job_action,
                on_progress=on_progress,
            ),
            key="send-job",
            when_done=when_done,
        )

    def set_hold(self, machine: Machine, is_requesting_hold: bool):
        """
        Adds a task to set the machine's hold state (pause/resume).
        """
        driver = machine.driver
        self._editor.task_manager.add_coroutine(
            lambda ctx: driver.set_hold(is_requesting_hold), key="set-hold"
        )

    def cancel_job(self, machine: Machine):
        """
        Adds a task to cancel the currently running job on the machine.

        Idempotent: the toolbar's Stop and the jog panel's both land
        here, and while one cancel is still on its way, another press
        adds nothing. A task per press used to replace the one before
        it, cancelling it mid-flight.
        """
        self._scale_cancelled = True
        self._premove_cancelled = True
        if self._cancel_in_flight:
            return
        self._cancel_in_flight = True

        def when_done(task):
            self._cancel_in_flight = False

        driver = machine.driver
        self._editor.task_manager.add_coroutine(
            lambda ctx: driver.cancel(), key="cancel-job", when_done=when_done
        )

    def focus_z(self, machine: Machine):
        """Adds a task to run the controller's Z focus routine."""
        driver = machine.driver
        self._editor.task_manager.add_coroutine(lambda ctx: driver.focus_z())

    def jog(self, machine: Machine, deltas: dict[Axis, float], speed: int):
        """
        Adds a task to jog the machine along specific axes.
        """
        # Keyed, so a step jog that has not started yet is replaced
        # by the newer one rather than stacking behind it. The hold
        # path stays unkeyed on purpose: a replaced key-up would leave
        # the head moving.
        self._editor.task_manager.add_coroutine(
            lambda ctx: machine.jog(deltas, speed), key="jog"
        )

    @property
    def has_job_ops(self) -> bool:
        """Whether the document has anything to run on the machine."""
        return self._editor.doc.has_result()

    @property
    def document_settled(self) -> Signal:
        """Signal UI can watch to re-evaluate document-driven actions."""
        return self._editor.document_settled

    def first_layer_power(self) -> float:
        """
        The power of the first step that has one, normalized 0-1.

        Used as the default for a scale cut, so the rectangle burns
        like the job it frames. Falls back to full power.
        """
        for layer in self._editor.doc.layers:
            workflow = layer.workflow
            if not workflow:
                continue
            for step in workflow.steps:
                power = getattr(step, "power", None)
                if power is not None:
                    return float(power)
        return 1.0

    def run_go_scale(
        self,
        machine: Machine,
        speed: int,
        on_done: Callable[[], None] | None = None,
    ):
        """
        Adds a task to traverse the job's bounding box, laser off.

        Pure movement, not a job: the driver moves the head around the
        outline with the jog primitive, from the start corner and back
        to it, on the same anchor Start pre-moves to. With no job, the
        door interlock does not apply and the lid may stay open.

        Args:
            machine: The machine to traverse on.
            speed: Travel speed in mm/min, the jog panel's.
            on_done: Optional callback, run on the main thread once the
                traverse finishes, is cancelled, or fails.
        """

        async def trace(width: float, height: float) -> None:
            await machine.driver.go_scale(width, height, speed)

        self._run_scale(trace, "go scale", on_done)

    def run_cut_scale(
        self,
        machine: Machine,
        speed: int,
        power: float,
        on_done: Callable[[], None] | None = None,
    ):
        """
        Adds a task to cut the job's bounding box as a rectangle.

        Args:
            machine: The machine to cut on.
            speed: Cut speed in mm/min.
            power: Cut power, normalized 0-1. Min power equals it.
            on_done: Optional callback, run on the main thread once the
                cut finishes, is cancelled, or fails.
        """

        async def cut(width: float, height: float) -> None:
            ops = _cut_scale_ops(machine, width, height, speed, power)
            encoder = _create_driver_encoder(machine)
            encoded = encoder.encode(ops, machine, self._editor.doc)
            await self._execute_monitored_job(ops, machine, encoded=encoded)

        self._run_scale(cut, "cut scale", on_done)

    def _run_scale(
        self,
        run: Callable[[float, float], Coroutine],
        job_name: str,
        on_done: Callable[[], None] | None,
    ):
        """Schedule a scale run over the current job's bounding box."""

        def when_done(task):
            if on_done is not None:
                self._scheduler(on_done)

        self._scale_cancelled = False
        self._editor.task_manager.add_coroutine(
            lambda ctx: self._scale(run, job_name),
            key=job_name.replace(" ", "-"),
            when_done=when_done,
        )

    async def _scale(
        self,
        run: Callable[[float, float], Coroutine],
        job_name: str,
    ):
        """Measure the job outline, then run the scale around it."""
        handle = await self._editor.pipeline.generate_job_artifact_async()
        if not handle:
            logger.warning(f"{job_name.capitalize()} has no operations.")
            return

        artifact_store = self._editor.pipeline.artifact_store
        with artifact_store.checkout_handle(handle) as artifact:
            if not isinstance(artifact, JobArtifact):
                raise TypeError(f"{job_name} did not produce a JobArtifact")
            min_x, min_y, max_x, max_y = artifact.ops.rect()

        if self._scale_cancelled:
            logger.info(f"{job_name.capitalize()} cancelled before it started")
            return

        await run(max_x - min_x, max_y - min_y)

    def jog_key_down(self, machine: Machine, axis: str, direction: int):
        """
        Adds a task to start a press-and-hold jog on one axis.

        These tasks are deliberately unkeyed: a keyed task replaces
        the pending one with the same key, which could swallow a
        key-up and leave the head moving. Unkeyed tasks are not
        ordered against each other either -- the task manager fires
        each one straight at the loop -- so the driver does its own
        ordering rather than relying on this layer for it.
        """
        driver = machine.driver
        if driver:
            self._editor.task_manager.add_coroutine(
                lambda ctx: driver.jog_key_down(axis, direction)
            )

    def jog_key_up(self, machine: Machine, axis: str, direction: int):
        """Adds a task to end a press-and-hold jog on one axis."""
        driver = machine.driver
        if driver:
            self._editor.task_manager.add_coroutine(
                lambda ctx: driver.jog_key_up(axis, direction)
            )

    def release_all_jog_keys(self, machine: Machine):
        """Adds a task to release every jog key still held down."""
        driver = machine.driver
        if driver:
            self._editor.task_manager.add_coroutine(
                lambda ctx: driver.release_all_jog_keys()
            )

    def set_jog_speed(self, machine: Machine, speed: int):
        """Adds a task to set the press-and-hold jog speed in mm/min."""
        driver = machine.driver
        if driver:
            self._editor.task_manager.add_coroutine(
                lambda ctx: driver.set_jog_speed(speed), key="set-jog-speed"
            )

    def set_power(
        self,
        head: Laser,
        percent: float,
        machine: Machine | None = None,
    ):
        """
        Adds a task to set the laser power to a specific percentage.

        Args:
            head: The laser head to control
            percent: Power percentage (0-1.0). 0 disables power.
        """
        if machine is None:
            config = get_context().config
            machine = config.machine
        if machine:
            self._editor.task_manager.add_coroutine(
                lambda ctx: machine.set_power(head, percent)
            )

    def set_focus_power(
        self,
        head: Laser,
        percent: float,
        machine: Machine | None = None,
    ):
        """
        Adds a task to set the laser power for focus mode.

        Args:
            head: The laser head to control
            percent: Power percentage (0-1.0). 0 disables power.
        """
        if machine is None:
            config = get_context().config
            machine = config.machine
        if machine:
            self._editor.task_manager.add_coroutine(
                lambda ctx: machine.set_focus_power(head, percent)
            )

    def home(self, machine: Machine, axis: Axis | None = None):
        """Adds a task to home a specific axis."""
        self._editor.task_manager.add_coroutine(lambda ctx: machine.home(axis))

    def move_to(self, machine: Machine, x: float, y: float):
        """Adds a task to move to an absolute position."""
        driver = machine.driver
        if driver:
            self._editor.task_manager.add_coroutine(
                lambda ctx: driver.move_to(x, y), key="move-to"
            )


def _rect_corners(width: float, height: float) -> list[tuple[float, float]]:
    """The closed bounding-box loop, starting and ending at (0, 0)."""
    return [
        (0.0, 0.0),
        (width, 0.0),
        (width, height),
        (0.0, height),
        (0.0, 0.0),
    ]


def _cut_scale_ops(
    machine: Machine,
    width: float,
    height: float,
    speed: int,
    power: float,
) -> Ops:
    """Build a one-layer job that cuts the bounding box."""
    ops = Ops()
    ops.job_start()
    ops.layer_start("cut-scale")
    head = machine.get_default_laser_head()
    if head is not None:
        ops.set_head(head.uid)
    ops.set_power(power)
    ops.set_feed_rate(speed)
    corners = _rect_corners(width, height)
    ops.move_to(corners[0][0], corners[0][1], 0.0)
    for x, y in corners[1:]:
        ops.line_to(x, y, 0.0)
    ops.layer_end("cut-scale")
    ops.job_end()
    return ops


def _create_driver_encoder(machine: Machine):
    """Instantiate the machine's driver encoder."""
    if machine.driver_name:
        try:
            driver_cls = get_driver_cls(machine.driver_name)
        except (ValueError, ImportError):
            driver_cls = NoDeviceDriver
    else:
        driver_cls = NoDeviceDriver
    return driver_cls.create_encoder(machine)

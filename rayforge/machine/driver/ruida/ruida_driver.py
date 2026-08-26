import asyncio
import inspect
import logging
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import replace
from gettext import gettext as _
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)

from ....context import RayforgeContext
from ....core.varset import HostnameVar, PortVar, VarSet
from ....core.varset.hostnamevar import is_valid_hostname_or_ip
from ....pipeline.encoder.base import EncodedOutput, OpsEncoder
from ...models.coordinate_system import CoordinateSystem
from ...models.laser import LaserHead, LaserType
from ...transport import TransportStatus
from ...transport.udp import UdpTransport
from ..driver import (
    Axis,
    DeviceStatus,
    Driver,
    DriverMaturity,
    DriverPrecheckError,
    DriverSetupError,
    Pos,
    PWMParams,
)
from .ruida_client import RuidaClient
from .ruida_encoder import RuidaEncoder, build_rd_bytes
from .ruida_transport import RuidaTransport

if TYPE_CHECKING:
    from raygeo.ops import Ops

    from ....core.doc import Doc
    from ...models.head import Head
    from ...models.laser import Laser
    from ...models.machine import Machine


logger = logging.getLogger(__name__)


class RuidaDriver(Driver):
    """
    Driver for Ruida laser controllers using UDP protocol.

    Implements the Driver interface with unit conversion (mm ↔ µm)
    and uses RuidaClient for communication with the controller.
    """

    label = _("Ruida (UDP)")
    subtitle = _("Connect to a Ruida laser controller over UDP")
    supports_settings = False
    reports_granular_progress = False
    uses_gcode = False
    maturity = DriverMaturity.KNOWN_BUGGY
    native_overscan = True
    CONNECTION_TIMEOUT = 2.0
    HOMING_TIMEOUT = 40.0
    RECONNECT_INTERVAL = 5.0
    KEEPALIVE_INTERVAL = 1.0
    POSITION_POLL_INTERVAL = 0.5
    # The connection loop wakes on this tick and lets each activity
    # own its own deadline. Sleeping a whole keepalive interval made
    # POSITION_POLL_INTERVAL unreachable.
    LOOP_TICK_INTERVAL = 0.1
    RESPONSE_PORT = 40200
    # Homing and move-to are positioning, not cutting: they run at the
    # profile's max travel speed, falling back to 200 mm/s.
    DEFAULT_TRAVEL_SPEED = 12000  # mm/min
    # Press-and-hold jog runs at the speed the panel shows. This is
    # only the seed for the moment before the UI has pushed one, and
    # it matches the jog speed row's own default so the two agree.
    DEFAULT_JOG_SPEED = 1000  # mm/min
    # Jobs default to the anchor ref point (D8 12), matching RDWorks, so
    # cuts start at the origin the user set on the panel. The WCS itself
    # stays user-selectable; this only picks the initial slot.
    DEFAULT_WCS = "REF0"
    STATUS_POLL_INTERVAL = 0.5
    # Consecutive unanswered status reads before a completion wait
    # decides the controller is gone rather than busy.
    STATUS_MISS_LIMIT = 8
    FRAME_CORNER_TOLERANCE_UM = 1000
    FRAME_CORNER_TIMEOUT = 15.0
    FRAME_POLL_INTERVAL = 0.2
    MACHINE_STATUS_ADDRESS = 0x0400
    STATUS_JOB_RUNNING_BIT = 0x00000001
    # Press-and-hold jog: one long move toward the bed limit, halted by
    # D8 01 on release. The head stops this far inside the limit so a
    # hold that runs to the end never drives into the hard stop.
    JOG_LIMIT_MARGIN_MM = 1.0
    # A single-step jog is "settled" once the head is this close to the
    # commanded target, or once the move's own travel time plus this
    # grace period has passed.
    JOG_SETTLE_TOLERANCE_UM = 500
    JOG_SETTLE_GRACE = 1.0
    JOG_SETTLE_POLL_INTERVAL = 0.05

    def __init__(self, context: RayforgeContext, machine: "Machine"):
        super().__init__(context, machine)
        self.host = None
        self.port = None
        self.jog_port = None
        self._udp_transport = None
        self._ruida_transport = None
        self._jog_udp_transport = None
        self._client = None
        self._response_received = asyncio.Event()
        self._connection_task: asyncio.Task | None = None
        self._card_info_task: asyncio.Task | None = None
        self._keep_running = False
        self._is_connected = False
        self._response_timeout = self.CONNECTION_TIMEOUT
        self._polling_suspensions = 0
        # The two axes are reported in separate replies, so they are
        # cached separately; _last_known_pos is only a position once
        # both halves are in.
        self._last_x_um: int | None = None
        self._last_y_um: int | None = None
        self._jog_keys_down: set[tuple[str, int]] = set()
        # True while any interactive motion is in flight -- a jog, a
        # single step, or a scale trace. It is the ignore interlock:
        # input that arrives while it is set is dropped, never queued.
        self._jog_busy = False
        self._jog_speed_mm_min = self.DEFAULT_JOG_SPEED
        # A job owns the wire while it uploads and runs: interactive
        # motion is refused for the duration rather than interleaved
        # into a stream whose acks are matched positionally.
        self._job_running = False
        # Every halt bumps this. A trace captures it on entry and
        # abandons itself the moment it changes, so a stop that came
        # from anywhere -- Stop button, key release, focus loss,
        # disconnect -- ends the trace too.
        self._frame_epoch = 0
        # A Stop pressed while the outline is still being measured has
        # no trace to bump the epoch on, so it is latched here and
        # consumed by the run it was aimed at.
        self._frame_cancel_pending = False

    @property
    def _last_known_pos(self) -> tuple[int, int] | None:
        """Where the head is in machine space, or None if unknown."""
        if self._last_x_um is None or self._last_y_um is None:
            return None
        return (self._last_x_um, self._last_y_um)

    @_last_known_pos.setter
    def _last_known_pos(self, value: tuple[int, int] | None) -> None:
        if value is None:
            self._last_x_um = None
            self._last_y_um = None
        else:
            self._last_x_um, self._last_y_um = value

    @property
    def _suppress_polling(self) -> bool:
        """Whether background polling is currently suspended."""
        return self._polling_suspensions > 0

    @contextmanager
    def _polling_suspended(self):
        """
        Hold off background polling for the duration of a block.

        A counter rather than a flag: a job upload and a scale trace
        can overlap, and the inner one's exit must not hand the poller
        back to the outer one mid-send.
        """
        self._polling_suspensions += 1
        try:
            yield
        finally:
            self._polling_suspensions = max(0, self._polling_suspensions - 1)

    @property
    def machine_space_wcs(self) -> str:
        return "MACHINE"

    @property
    def machine_space_wcs_display_name(self) -> str:
        return _("Machine Coordinates")

    @property
    def supported_wcs(self) -> list[str]:
        if not self._client:
            return [self.machine_space_wcs]
        return list(self._client.ref_points)

    @property
    def resource_uri(self) -> str | None:
        if self.host:
            return f"udp://{self.host}:{self.port} (jog: {self.jog_port})"
        return None

    @classmethod
    def precheck(cls, **kwargs: Any) -> None:
        host = kwargs.get("host", "")
        if not is_valid_hostname_or_ip(host):
            raise DriverPrecheckError(
                _("Invalid hostname or IP address: '{host}'").format(host=host)
            )

    @classmethod
    def get_setup_vars(cls) -> "VarSet":
        return VarSet(
            vars=[
                HostnameVar(
                    key="host",
                    label=_("Hostname"),
                    description=_(
                        "The IP address or hostname of the Ruida controller"
                    ),
                ),
                PortVar(
                    key="port",
                    label=_("Main Port"),
                    description=_(
                        "The UDP port for main commands (default: 50200)"
                    ),
                    default=50200,
                ),
                PortVar(
                    key="jog_port",
                    label=_("Jog Port"),
                    description=_(
                        "The UDP port for jog commands (default: 50207)"
                    ),
                    default=50207,
                ),
            ]
        )

    def supports_pwm(self, head: "Head") -> bool:
        return (
            isinstance(head, LaserHead) and head.laser_type != LaserType.DIODE
        )

    def get_pwm_params(self, head: "Head") -> PWMParams | None:
        if not isinstance(head, LaserHead) or not self.supports_pwm(head):
            return None
        return PWMParams(
            frequency=head.pwm_frequency,
            max_frequency=head.max_pwm_frequency,
            pulse_width=head.pulse_width,
            min_pulse_width=head.min_pulse_width,
            max_pulse_width=head.max_pulse_width,
        )

    @classmethod
    def create_encoder(cls, machine: "Machine") -> "OpsEncoder":
        return RuidaEncoder()

    def _setup_implementation(self, **kwargs: Any) -> None:
        host = kwargs.get("host", "")
        port = kwargs.get("port", 50200)
        jog_port = kwargs.get("jog_port", 50207)
        response_port = kwargs.get("response_port", self.RESPONSE_PORT)
        if not host:
            raise DriverSetupError(_("Hostname must be configured."))

        self.host = host
        self.port = port
        self.jog_port = jog_port

        self._udp_transport = UdpTransport(
            host, port, local_port=response_port
        )
        self._ruida_transport = RuidaTransport(self._udp_transport)
        self._jog_udp_transport = UdpTransport(host, jog_port)
        self._jog_ruida_transport = RuidaTransport(self._jog_udp_transport)
        self._client = RuidaClient(
            self._ruida_transport,
            jog_transport=self._jog_ruida_transport,
        )

        self._client.state_changed.connect(self._on_state_changed)
        self._ruida_transport.status_changed.connect(self._on_status_changed)
        self._client.position_updated.connect(self._on_position_updated)

        self._init_coordinate_systems()

    def _init_coordinate_systems(self) -> None:
        """
        Initialize the machine's coordinate systems to match the
        Ruida controller's ref point model (MACHINE, REF0, REF1).
        """
        m = self._machine
        supported = self.supported_wcs
        existing = m.coordinate_systems

        new_systems = {}
        for name in supported:
            if name in existing:
                new_systems[name] = existing[name]
            else:
                new_systems[name] = CoordinateSystem(name=name)

        m.coordinate_systems = new_systems
        if m.active_wcs not in new_systems:
            default = self.DEFAULT_WCS
            m.active_wcs = default if default in new_systems else supported[0]

        # The controller cannot report its ref point mode, so seed the
        # client's tracked value from the profile. Otherwise the mode
        # poller would push its "MACHINE" placeholder back onto the
        # machine within seconds of connecting.
        if self._client:
            self._client.set_tracked_ref_point_mode(m.active_wcs)

    async def cleanup(self):
        # A held jog key outlives the UI, so release before tearing the
        # transports down.
        await self.release_all_jog_keys()
        self._keep_running = False
        self._is_connected = False

        if self._connection_task:
            self._connection_task.cancel()
            try:
                await self._connection_task
            except asyncio.CancelledError:
                pass
            self._connection_task = None
        if self._card_info_task:
            self._card_info_task.cancel()
            try:
                await self._card_info_task
            except asyncio.CancelledError:
                pass
            self._card_info_task = None

        if self._ruida_transport:
            self._ruida_transport.status_changed.disconnect(
                self._on_status_changed
            )
        if self._client:
            self._client.state_changed.disconnect(self._on_state_changed)
            self._client.position_updated.disconnect(self._on_position_updated)
            await self._client.disconnect()
        if self._jog_udp_transport:
            await self._jog_udp_transport.disconnect()
        if self._ruida_transport:
            await self._ruida_transport.disconnect()
        self._jog_udp_transport = None
        self._ruida_transport = None
        self._udp_transport = None
        self._client = None
        self._update_connection_status(TransportStatus.DISCONNECTED, "")
        await super().cleanup()

    async def _connect_implementation(self) -> None:
        if not self.host:
            self._update_connection_status(
                TransportStatus.DISCONNECTED, "No host configured"
            )
            return

        if self._connection_task and not self._connection_task.done():
            logger.warning("Connect called with active connection task")
            return

        self._keep_running = True
        self._connection_task = asyncio.create_task(self._connection_loop())

    async def _connection_loop(self) -> None:
        logger.debug("Entering Ruida connection loop")
        while self._keep_running:
            self._update_connection_status(TransportStatus.CONNECTING)
            self._is_connected = False

            try:
                if not self._client:
                    raise DriverSetupError("Client not initialized")

                await self._client.connect()

                self._response_received.clear()
                await self._client.keep_alive()

                try:
                    await asyncio.wait_for(
                        self._response_received.wait(),
                        timeout=self.CONNECTION_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    self._update_connection_status(
                        TransportStatus.ERROR,
                        _("No response from controller"),
                    )
                    await self._disconnect_transports()
                    self._update_connection_status(TransportStatus.SLEEPING)
                    await asyncio.sleep(self.RECONNECT_INTERVAL)
                    continue

                self._is_connected = True
                self._update_connection_status(TransportStatus.CONNECTED, "")
                self.state.status = DeviceStatus.IDLE
                self.state_changed.send(self, state=self.state)

                logger.info(
                    f"Connected to Ruida controller "
                    f"at {self.host}:{self.port}",
                    extra=self._log_extra("MACHINE_EVENT"),
                )

                self._card_info_task = asyncio.create_task(
                    self._fetch_card_info(),
                    name="ruida-fetch-card-info",
                )

                last_poll_time = 0.0
                last_ref_poll_time = 0.0
                last_keepalive = asyncio.get_event_loop().time()

                while self._keep_running and self._is_connected:
                    current_time = asyncio.get_event_loop().time()

                    # The keepalive has to leave on its own schedule.
                    # It used to be sent once, at connect, and never
                    # again: liveness rode entirely on the position
                    # poll, which a job upload suspends.
                    if current_time - last_keepalive >= (
                        self.KEEPALIVE_INTERVAL
                    ):
                        await self._client.keep_alive()
                        last_keepalive = current_time

                    if (
                        not self._suppress_polling
                        and current_time - last_poll_time
                        >= self.POSITION_POLL_INTERVAL
                    ):
                        # The poll is its own liveness proof: it waits
                        # on the reply to the register it asked for,
                        # not on "some packet arrived", which any
                        # unrelated ack used to satisfy.
                        if not await self._poll_position():
                            logger.warning(
                                "Controller stopped responding, reconnecting",
                                extra=self._log_extra("MACHINE_EVENT"),
                            )
                            self._is_connected = False
                            await self._disconnect_transports()
                            break
                        last_poll_time = asyncio.get_event_loop().time()

                    if (
                        not self._suppress_polling
                        and current_time - last_ref_poll_time >= 2.0
                    ):
                        await self._poll_ref_point_mode()
                        last_ref_poll_time = current_time

                    await asyncio.sleep(self.LOOP_TICK_INTERVAL)

            except asyncio.CancelledError:
                logger.debug("Connection loop cancelled")
                await self._disconnect_transports()
                raise
            except Exception as e:  # noqa: BLE001 - connection loop boundary
                logger.error(f"Connection error: {e}")
                self._update_connection_status(TransportStatus.ERROR, str(e))
                await self._disconnect_transports()

            if self._keep_running:
                self._update_connection_status(TransportStatus.SLEEPING)
                await asyncio.sleep(self.RECONNECT_INTERVAL)

        logger.debug("Exiting Ruida connection loop")

    async def _disconnect_transports(self) -> None:
        # Last chance to stop a held jog key; the socket may already be
        # dead, which release_all_jog_keys tolerates.
        await self.release_all_jog_keys()
        # A reconnect must not inherit a position from before the gap.
        self._last_known_pos = None
        if self._client:
            try:
                await self._client.disconnect()
            except OSError as e:
                logger.debug(f"Error disconnecting client: {e}")
        if self._jog_udp_transport:
            try:
                await self._jog_udp_transport.disconnect()
            except OSError as e:
                logger.debug(f"Error disconnecting jog transport: {e}")
        if self._ruida_transport:
            try:
                await self._ruida_transport.disconnect()
            except OSError as e:
                logger.debug(f"Error disconnecting ruida transport: {e}")

    async def _poll_position(self) -> bool:
        """
        Poll the current position, waiting for the reply.

        Returns whether the controller answered. Going through
        read_position rather than the fire-and-forget get_position
        gives every reply an owner, so an interactive read can no
        longer be answered by the poller's request.
        """
        if not self._client or not self._is_connected:
            return True

        try:
            logger.debug("Polling position from controller")
            pos = await self._client.read_position(
                timeout=self._response_timeout
            )
            if pos is None:
                return False
            self._set_known_pos(pos)
            await self._client._read_memory_wait(
                0x0441, timeout=self._response_timeout
            )
            return True
        except (OSError, asyncio.TimeoutError) as e:
            logger.debug(f"Error polling position: {e}")
            return False

    async def _poll_ref_point_mode(self) -> None:
        """Poll current ref point mode from controller."""
        if not self._client or not self._is_connected:
            return

        try:
            mode = await self._client.get_ref_point_mode()
            if mode and mode != self._machine.active_wcs:
                logger.debug(f"Ref point mode changed: {mode}")
                self._machine.set_active_wcs(mode)
        except (OSError, asyncio.TimeoutError) as e:
            logger.debug(f"Error polling ref point mode: {e}")

    async def run(
        self,
        encoded: EncodedOutput,
        doc: "Doc",
        ops: "Ops",
        on_command_done: Callable[[int], None | Awaitable[None]] | None = None,
    ) -> None:
        # The pipeline rebuilds EncodedOutput from
        # EncodeOutput.MachineCode, which carries only text and op_map,
        # so encoded.driver_data never reaches the driver. Build the
        # blob from ops here; encoded serves UI progress mapping only.
        op_map = encoded.op_map
        num_ops = op_map.op_count if op_map else 0
        blob = build_rd_bytes(ops, self._machine, doc)

        logger.info(
            f"Job encoded: {num_ops} ops, {len(blob)} bytes",
            extra=self._log_extra("USER_COMMAND"),
        )

        if not blob or not self._client:
            reason = (
                "ops produced no machine commands"
                if not blob
                else "no client connection"
            )
            logger.warning(
                f"Job not sent: {reason}",
                extra=self._log_extra("USER_COMMAND"),
            )
            await self._report_ops_done(on_command_done, 0, num_ops)
            self.job_finished.send(self)
            return

        self._dump_job_blob(blob)

        self._job_running = True
        try:
            with self._polling_suspended():
                # The proven sender had no concurrent traffic:
                # keepalive and position polling stay suspended for
                # the whole send.
                await asyncio.sleep(0.2)
                await self._client.send_job(
                    blob,
                    on_start=self._log_send_start,
                    on_chunk=self._log_chunk_acked,
                )
                logger.info(
                    "Upload complete, waiting for job to finish",
                    extra=self._log_extra("USER_COMMAND"),
                )
                await self._report_ops_done(on_command_done, 0, num_ops)
                await self._wait_for_job_completion()
        finally:
            self._job_running = False
            self._last_known_pos = None

        logger.info("Job finished", extra=self._log_extra("USER_COMMAND"))
        self.job_finished.send(self)

    def _dump_job_blob(self, blob: bytes) -> None:
        """
        Write the blob about to be sent to a temp file, so every run
        leaves a diagnostic artifact identical to the transmission.
        """
        path = Path(tempfile.gettempdir()) / "rayforge_last_job.rd"
        try:
            path.write_bytes(blob)
        except OSError as err:
            logger.warning(f"Could not write job dump to {path}: {err}")
            return
        logger.info(
            f"Job blob written to {path}",
            extra=self._log_extra("USER_COMMAND"),
        )

    def _log_send_start(self, total_bytes: int, chunk_count: int) -> None:
        logger.info(
            f"Sending {total_bytes} bytes in {chunk_count} chunks",
            extra=self._log_extra("USER_COMMAND"),
        )

    def _log_chunk_acked(
        self, index: int, count: int, size: int, attempts: int
    ) -> None:
        logger.info(
            f"chunk {index}/{count} acked, {size} bytes, "
            f"{attempts} attempt(s)",
            extra=self._log_extra("USER_COMMAND"),
        )

    async def _report_ops_done(
        self,
        on_command_done: Callable[[int], None | Awaitable[None]] | None,
        start: int,
        end: int,
    ) -> None:
        if on_command_done is None:
            return
        for op_index in range(start, end):
            result = on_command_done(op_index)
            if inspect.isawaitable(result):
                await result

    async def _wait_for_status_idle(self, what: str) -> None:
        """
        Poll machine status until the job-running bit clears.

        Gives up after STATUS_MISS_LIMIT consecutive unanswered reads.
        A UDP socket stays "connected" when the controller is
        unplugged -- nothing fails a send and no reply ever comes --
        so waiting on is_connected alone hangs forever, and the run
        that is holding the polling suspension can never notice
        either.
        """
        misses = 0
        while self._client and self._client.is_connected:
            status = await self._client._read_memory_wait(
                self.MACHINE_STATUS_ADDRESS
            )
            if status is None:
                misses += 1
                if misses >= self.STATUS_MISS_LIMIT:
                    logger.warning(
                        f"Controller stopped answering status; "
                        f"abandoning the {what} wait",
                        extra=self._log_extra("MACHINE_EVENT"),
                    )
                    return
            else:
                misses = 0
                if not status & self.STATUS_JOB_RUNNING_BIT:
                    return
            await asyncio.sleep(self.STATUS_POLL_INTERVAL)

    async def _wait_for_job_completion(self) -> None:
        await self._wait_for_status_idle("job")

    async def run_raw(self, machine_code: str) -> None:
        """
        Ruida controllers use binary protocol, not text-based machine code.

        This method logs a warning and does nothing. Use run() with
        properly encoded Ruida binary data instead.
        """
        if machine_code and machine_code.strip():
            logger.warning(
                "Ruida controllers do not support text-based machine code. "
                "Use run() with EncodedOutput instead."
            )
        self.job_finished.send(self)

    async def set_hold(self, hold: bool = True) -> None:
        assert self._client
        if hold:
            await self._client.pause_process()
        else:
            await self._client.resume_process()

    async def cancel(self) -> None:
        """
        Stop whatever this driver started: job, trace, or jog.

        The red Stop button is the one control the user reaches for
        when anything is moving, so it cannot be a job-only command.
        Bumping the frame epoch aborts a running trace, dropping the
        held keys stops a release from restarting a hold, and
        _stop_jog_motion sends the same D8 01 a job cancel used to.
        """
        assert self._client
        self._frame_epoch += 1
        self._jog_keys_down.clear()
        await self._stop_jog_motion()

    def can_home(self, axis: Axis | None = None) -> bool:
        return True

    async def home(self, axes: Axis | None = None) -> None:
        assert self._client
        if axes is None:
            logger.info("Home All", extra=self._log_extra("MACHINE_EVENT"))
            home_xy = True
            home_z = False
        else:
            cmd_parts = []
            home_xy = bool(axes & (Axis.X | Axis.Y))
            home_z = bool(axes & Axis.Z)
            if home_xy:
                cmd_parts.append("XY")
            if home_z:
                cmd_parts.append("Z")
            cmd_name = f"Home {'/'.join(cmd_parts)}"
            logger.info(cmd_name, extra=self._log_extra("MACHINE_EVENT"))

        self._response_timeout = self.HOMING_TIMEOUT
        self._jog_busy = True
        try:
            with self._polling_suspended():
                await self._set_max_travel_speed()
                if home_xy:
                    await self._client.home_xy()
                if home_z:
                    await self._client.home_z()
                # Homing is over when the machine reports itself idle.
                # Reading Current X only reports where the head is,
                # which the background poller answers within half a
                # second whether or not the cycle has finished.
                await self._wait_for_status_idle("home")
        finally:
            self._response_timeout = self.CONNECTION_TIMEOUT
            self._jog_busy = False
            # The head is at the machine zero it just found, not where
            # the cache last saw it.
            self._last_known_pos = None

    def can_trace_frame(self) -> bool:
        return True

    async def trace_frame(self, width_mm: float, height_mm: float) -> None:
        """
        Traverse the job's bounding box as plain interactive rapids.

        This is an alignment aid, not a job: it never starts a process
        (no D8 00, no prologue) and never sends a power command, so the
        laser cannot fire and the controller's door interlock has
        nothing to gate. The corners are absolute targets built from
        the head position the trace starts at, driven by the same
        D9 10 primitive a jog uses.
        """
        assert self._client
        width_um = int(width_mm * 1000)
        height_um = int(height_mm * 1000)
        logger.info(
            f"Go Scale: tracing {width_mm:.1f} x {height_mm:.1f} mm "
            f"from the current position",
            extra=self._log_extra("USER_COMMAND"),
        )

        # Captured before anything is sent. A cancel that arrived
        # while the caller was still measuring the outline has already
        # bumped the epoch, so the trace refuses to start rather than
        # wiping the user's Stop.
        epoch = self._frame_epoch
        if self._frame_cancel_pending:
            self._frame_cancel_pending = False
            logger.info(
                "Go Scale cancelled before it started",
                extra=self._log_extra("USER_COMMAND"),
            )
            return
        if self._jog_busy or self._job_running:
            logger.info(
                "Go Scale ignored: the head is already moving",
                extra=self._log_extra("USER_COMMAND"),
            )
            return

        start = await self._jog_origin()
        if start is None:
            logger.warning(
                "Go Scale not started: the head position is unknown",
                extra=self._log_extra("USER_COMMAND"),
            )
            return
        corners = [
            (start[0] + dx, start[1] + dy)
            for dx, dy in (
                (0, 0),
                (width_um, 0),
                (width_um, height_um),
                (0, height_um),
                (0, 0),
            )
        ]
        if not self._corners_fit(corners):
            return

        self._jog_busy = True
        try:
            with self._polling_suspended():
                await self._set_travel_speed(self._frame_speed_mm_min())
                for x_um, y_um in corners:
                    if self._frame_epoch != epoch:
                        logger.info(
                            "Go Scale cancelled",
                            extra=self._log_extra("USER_COMMAND"),
                        )
                        return
                    target = await self._jog_move_to(x_um, y_um)
                    await self._wait_for_frame_corner(*target, epoch=epoch)
        finally:
            self._jog_busy = False
            self._frame_cancel_pending = False

    def _frame_speed_mm_min(self) -> int:
        """
        The trace speed, in mm/min, clamped to the profile.

        Framing is interactive motion the user watches, so it runs at
        the jog panel's own speed -- the same value the arrows use,
        pushed here by set_jog_speed -- rather than a fixed one. It is
        still never faster than the machine is configured for.
        """
        profile = self._machine.max_travel_speed or self.DEFAULT_TRAVEL_SPEED
        return int(min(self._jog_speed_mm_min, profile))

    def _corners_fit(self, corners: list[tuple[int, int]]) -> bool:
        """
        Whether every corner is reachable, warning about the ones that
        are not.

        A clamped corner would trace a rectangle that is not the job's,
        which is worse than tracing nothing: the user reads it as
        proof the job fits.
        """
        (x_lo, x_hi), (y_lo, y_hi) = (
            self._axis_range("x"),
            self._axis_range("y"),
        )
        outside = [
            c
            for c in corners
            if not (x_lo <= c[0] <= x_hi and y_lo <= c[1] <= y_hi)
        ]
        if not outside:
            return True
        logger.warning(
            f"Go Scale not started: the outline runs off the bed at "
            f"{outside[0][0] / 1000:.1f}, {outside[0][1] / 1000:.1f} mm",
            extra=self._log_extra("USER_COMMAND"),
        )
        return False

    async def cancel_frame(self) -> None:
        """
        Stop a running scale trace and resync the cached position.

        The head parks wherever the stop caught it; no further corners
        are sent. Bumping the epoch also cancels a trace that has not
        started yet, so a Stop pressed while the outline is still
        being measured is not forgotten.
        """
        self._frame_epoch += 1
        self._frame_cancel_pending = True
        if self._jog_busy:
            await self._stop_jog_motion()

    async def _wait_for_frame_corner(
        self,
        target_x: int,
        target_y: int,
        epoch: int,
    ) -> None:
        """
        Poll the head position until it reaches a corner.

        Args:
            target_x: Corner X in micrometers, absolute.
            target_y: Corner Y in micrometers, absolute.
            epoch: The frame epoch this trace was started under.
        """
        assert self._client
        deadline = asyncio.get_event_loop().time() + self.FRAME_CORNER_TIMEOUT
        while asyncio.get_event_loop().time() < deadline:
            if self._frame_epoch != epoch:
                return
            pos = self._from_controller(await self._client.read_position())
            if pos is not None:
                self._last_known_pos = pos
                if (
                    abs(pos[0] - target_x) <= self.FRAME_CORNER_TOLERANCE_UM
                    and abs(pos[1] - target_y)
                    <= self.FRAME_CORNER_TOLERANCE_UM
                ):
                    return
            await asyncio.sleep(self.FRAME_POLL_INTERVAL)

        logger.warning(
            f"Go Scale: corner ({target_x}, {target_y}) um not reached "
            f"within {self.FRAME_CORNER_TIMEOUT}s, abandoning the trace",
            extra=self._log_extra("USER_COMMAND"),
        )
        self._frame_epoch += 1

    async def move_to(self, pos_x: float, pos_y: float) -> None:
        assert self._client
        logger.info(
            f"move_to x={pos_x:.2f} y={pos_y:.2f}",
            extra=self._log_extra("MACHINE_EVENT"),
        )
        x_um = int(pos_x * 1000)
        y_um = int(pos_y * 1000)
        await self._rapid_move_to(x_um, y_um)

    async def _set_travel_speed(self, speed_mm_min: float) -> None:
        """
        Stream C9 02 at a speed given in mm/min.

        This is the only place the application's mm/min meets the
        controller's um/s: every interactive path goes through here so
        the conversion has exactly one home.
        """
        assert self._client
        await self._client.set_travel_speed(int(speed_mm_min * 1000 / 60))

    async def _set_max_travel_speed(self) -> None:
        """Stream C9 02 at the profile's max travel speed."""
        await self._set_travel_speed(
            self._machine.max_travel_speed or self.DEFAULT_TRAVEL_SPEED
        )

    async def _rapid_move_to(self, target_x: int, target_y: int) -> None:
        assert self._client
        await self._set_max_travel_speed()
        await self._client.rapid_move_xy(
            *self._to_controller(target_x, target_y)
        )
        self._last_known_pos = (target_x, target_y)

    async def select_tool(self, tool_number: int) -> None:
        pass

    async def read_settings(self) -> None:
        await asyncio.sleep(0)
        self.settings_read.send(self, settings=[])

    def get_setting_vars(self) -> list["VarSet"]:
        return [VarSet(title=_("No settings"))]

    async def write_setting(self, key: str, value: Any) -> None:
        pass

    async def clear_alarm(self) -> None:
        """
        Nothing to clear: this driver models no alarm state.

        It used to send D8 01 Stop Process, byte-identical to
        cancel(), so a "clear alarm" quietly aborted whatever was
        running. Stopping belongs to cancel().
        """
        logger.debug("Ruida reports no alarm state; nothing to clear")

    async def set_power(self, head: "Laser", percent: float) -> None:
        assert self._client
        power_percent = percent * 100
        laser_num = head.tool_number + 1
        await self._client.set_power_immediate(laser_num, power_percent)

    async def set_focus_power(self, head: "Laser", percent: float) -> None:
        await self.set_power(head, percent)

    def can_jog(self, axis: Axis | None = None) -> bool:
        """
        Z is not implemented here, so it is not advertised.

        Both jog paths speak only X and Y; a Z delta used to be
        converted and then dropped, which left the panel offering a
        button that did nothing but pin the busy interlock.
        """
        if axis is None:
            return True
        return not bool(axis & Axis.Z)

    def can_hold_jog(self) -> bool:
        return True

    async def jog_key_down(self, axis: str, direction: int) -> None:
        """
        Start a continuous jog: one long move toward the bed limit.

        Ignored while a single-step jog or a trace is still running. A
        key that joins a hold already running -- the two halves of a
        diagonal button arrive as separate presses -- stops the move
        in flight and re-issues it for the combined direction, so
        exactly one move is ever outstanding and nothing queues up
        behind the finger.
        """
        assert self._client
        key = (axis.lower(), direction)
        if key[0] not in ("x", "y"):
            logger.debug(f"Jog key ignored, axis not supported: {key[0]}")
            return
        if key in self._jog_keys_down:
            return
        holding = bool(self._jog_keys_down)
        if self._job_running or (self._jog_busy and not holding):
            return

        self._jog_keys_down.add(key)
        logger.debug(f"Jog key down: {key[0]}{direction:+d}")
        if holding:
            await self._stop_jog_motion()
        try:
            self._jog_busy = True
            await self._set_travel_speed(self._jog_speed_mm_min)
            if not await self._jog_to_limit():
                self._jog_keys_down.discard(key)
        except (OSError, RuntimeError) as e:
            logger.warning(f"Hold jog failed to start: {e}")
            self._jog_keys_down.discard(key)
        finally:
            # The flag tracks motion, not intent: if no key survived
            # the awaits, nothing is moving and the interlock must not
            # stay up. Releasing it here is what keeps a diagonal
            # whose halves were released mid-flight from bricking every
            # later jog.
            if not self._jog_keys_down:
                self._jog_busy = False

    async def jog_key_up(self, axis: str, direction: int) -> None:
        key = (axis.lower(), direction)
        if key not in self._jog_keys_down:
            return
        self._jog_keys_down.discard(key)
        logger.debug(f"Jog key up: {key[0]}{direction:+d}")
        await self._stop_jog_motion()
        if not self._jog_keys_down:
            return
        try:
            # One half of a diagonal let go: keep going on the rest.
            self._jog_busy = True
            if not await self._jog_to_limit():
                self._jog_keys_down.clear()
        except (OSError, RuntimeError) as e:
            logger.warning(f"Hold jog failed to continue: {e}")
            self._jog_keys_down.clear()
        finally:
            if not self._jog_keys_down:
                self._jog_busy = False

    async def release_all_jog_keys(self) -> None:
        keys = sorted(self._jog_keys_down)
        self._jog_keys_down.clear()
        if keys:
            logger.info(
                f"Releasing {len(keys)} held jog key(s)",
                extra=self._log_extra("MACHINE_EVENT"),
            )
        if keys or self._jog_busy:
            await self._stop_jog_motion()

    async def _stop_jog_motion(self) -> None:
        """
        Halt whatever is moving and resync the cached position.

        The stop goes out first so the head is already braking while
        the position read is in flight; whatever comes back is where
        the head actually ended up. A read that fails leaves the cache
        empty rather than holding the target the head was only ever
        commanded toward -- an unknown position is recoverable, a
        confident wrong one is not.

        Bumping the frame epoch makes this the single halt for every
        kind of interactive motion: a trace running concurrently sees
        the change at its next corner and abandons itself.

        HARDWARE NOTE: this assumes D8 01 halts an interactive rapid.
        See MOTION_AUDIT.md MOT-05 -- nothing in this repository
        confirms it, and the fallback if it is wrong is to keep the
        long move but chunk it into 25 mm relative moves, issued only
        once the polled position shows the previous chunk nearly
        consumed -- still behind the busy flag, so the queue never
        grows past one outstanding move.
        """
        self._frame_epoch += 1
        if not self._client:
            self._jog_busy = False
            return
        try:
            await self._client.stop_process()
            self._set_known_pos(await self._client.read_position())
        except (OSError, RuntimeError) as e:
            logger.warning(f"Jog stop failed: {e}")
            self._set_known_pos(None)
        finally:
            self._jog_busy = False

    async def _jog_to_limit(self) -> bool:
        """
        Move toward the bed limit along the held direction(s).

        Returns whether a move was actually commanded. A caller that
        gets False is holding the interlock over nothing and must let
        it go.
        """
        if not self._held_deltas():
            return False

        origin = await self._jog_origin()
        if origin is None:
            logger.warning(
                "Hold jog not started: the head position is unknown",
                extra=self._log_extra("USER_COMMAND"),
            )
            return False

        # Re-read the held keys after the await. A release that landed
        # while the position read was in flight must win, or the head
        # departs for the bed limit with nothing held down.
        deltas = self._held_deltas()
        if not deltas:
            return False

        margin_um = int(self.JOG_LIMIT_MARGIN_MM * 1000)
        target = tuple(
            self._axis_limit(
                origin[i], deltas[name], self._axis_range(name), margin_um
            )
            for i, name in enumerate(("x", "y"))
        )
        await self._jog_move_to(target[0], target[1])
        return True

    def _held_deltas(self) -> dict[str, int] | None:
        """The summed direction per axis, or None when nothing is held."""
        deltas = {"x": 0, "y": 0}
        for axis, direction in self._jog_keys_down:
            if axis in deltas:
                deltas[axis] += direction
        if not (deltas["x"] or deltas["y"]):
            return None
        return deltas

    def _axis_range(self, axis: str) -> tuple[int, int]:
        """
        The travel an axis has, in micrometres, in machine space.

        A reversed axis runs from -extent to 0 rather than 0 to
        extent, which is the same convention Machine.get_soft_limits
        uses, so the driver has to speak it too.
        """
        width_mm, height_mm = self._machine.axis_extents
        if axis == "x":
            extent_um = int(width_mm * 1000)
            reversed_axis = self._machine.reverse_x_axis
        else:
            extent_um = int(height_mm * 1000)
            reversed_axis = self._machine.reverse_y_axis
        if reversed_axis:
            return -extent_um, 0
        return 0, extent_um

    def _to_controller(self, x_um: int, y_um: int) -> tuple[int, int]:
        """Machine-space micrometres as the controller counts them."""
        return (
            -x_um if self._machine.reverse_x_axis else x_um,
            -y_um if self._machine.reverse_y_axis else y_um,
        )

    def _axis_um_from_controller(self, axis: str, value_um: int) -> int:
        """One controller reading in the profile's own machine space."""
        if axis == "x" and self._machine.reverse_x_axis:
            return -value_um
        if axis == "y" and self._machine.reverse_y_axis:
            return -value_um
        return value_um

    def _from_controller(
        self, pos: tuple[int, int] | None
    ) -> tuple[int, int] | None:
        """A controller position pair in the profile's machine space."""
        if pos is None:
            return None
        return (
            self._axis_um_from_controller("x", pos[0]),
            self._axis_um_from_controller("y", pos[1]),
        )

    def _set_known_pos(self, pos: tuple[int, int] | None) -> None:
        """
        Record where the head is, in controller coordinates.

        None means "no longer known", which every consumer treats as a
        reason to read again rather than to invent a zero.
        """
        self._last_known_pos = self._from_controller(pos)

    @staticmethod
    def _axis_limit(
        pos_um: int,
        direction: int,
        axis_range: tuple[int, int],
        margin_um: int,
    ) -> int:
        """The far end of the travel an axis has left, or where it is."""
        low, high = axis_range
        if direction > 0:
            return max(pos_um, high - margin_um)
        if direction < 0:
            return min(pos_um, low + margin_um)
        return pos_um

    async def set_jog_speed(self, speed: int) -> None:
        """
        Remember the press-and-hold jog speed.

        Args:
            speed: Jog speed in mm/min.
        """
        self._jog_speed_mm_min = max(1, int(speed))
        logger.info(
            f"Hold jog speed: {self._jog_speed_mm_min} mm/min",
            extra=self._log_extra("MACHINE_EVENT"),
        )

    async def jog(self, speed: int, **deltas: float) -> None:
        """
        Move one step of the step-size control and wait for it to land.

        Ignored while another jog or a trace is in flight, so clicks
        cannot queue up behind a hold or behind each other.
        """
        assert self._client
        if self._jog_busy or self._job_running:
            return

        dx_um = 0
        dy_um = 0
        for axis_name, delta in deltas.items():
            axis_lower = axis_name.lower()
            delta_um = int(delta * 1000)
            if axis_lower == "x":
                dx_um += delta_um
            elif axis_lower == "y":
                dy_um += delta_um
        if not (dx_um or dy_um):
            return

        self._jog_busy = True
        try:
            origin = await self._jog_origin()
            if origin is None:
                logger.warning(
                    "Jog not sent: the head position is unknown",
                    extra=self._log_extra("USER_COMMAND"),
                )
                return
            await self._set_travel_speed(speed)
            target = await self._jog_move_to(
                origin[0] + dx_um, origin[1] + dy_um
            )
            await self._wait_for_jog_settled(origin, target, speed)
        finally:
            self._jog_busy = False

    async def _jog_origin(self) -> tuple[int, int] | None:
        """
        The position a jog is measured from, read back if unknown.

        None when it cannot be established. Every D9 10 this driver
        sends is an absolute target, so an origin that was guessed is
        a full-bed traverse waiting to happen: callers must refuse to
        move rather than substitute a zero.
        """
        assert self._client
        if self._last_known_pos is None:
            self._set_known_pos(await self._client.read_position())
        return self._last_known_pos

    async def _jog_move_to(self, x_um: int, y_um: int) -> tuple[int, int]:
        """
        Move the head to an absolute target with the interactive D9 10
        command, clamped to the axis travel. No speed is sent; the
        caller streams it first.

        Coordinates in and out are machine space as the profile
        defines it, which a reversed axis makes negative; the
        conversion to the controller's own count happens here.

        D9 10 is the only motion form used. D9 00/01 are decoded as
        relative by ruida_server and by the reference client app, so
        an earlier attempt to use them as absolute targets drove the
        head to the wrong end of the axis.
        """
        assert self._client
        x_lo, x_hi = self._axis_range("x")
        y_lo, y_hi = self._axis_range("y")
        x_um = max(x_lo, min(x_um, x_hi))
        y_um = max(y_lo, min(y_um, y_hi))
        await self._client.rapid_move_xy(*self._to_controller(x_um, y_um))
        # Track the commanded target so back-to-back jogs do not
        # compute from a stale polled position.
        self._last_known_pos = (x_um, y_um)
        return x_um, y_um

    async def _wait_for_jog_settled(
        self,
        start: tuple[int, int],
        target: tuple[int, int],
        speed_mm_min: int,
    ) -> None:
        """
        Poll until the head reaches a single-step target, or time out.

        The timeout is the move's own travel time plus a grace period,
        so a slow jog over a long step is not cut short. The start has
        to be passed in: _jog_move_to has already overwritten the
        cached position with the commanded target by the time this
        runs.
        """
        assert self._client
        distance_um = max(abs(target[0] - start[0]), abs(target[1] - start[1]))
        speed_um_s = max(1.0, speed_mm_min * 1000.0 / 60.0)
        timeout = distance_um / speed_um_s + self.JOG_SETTLE_GRACE
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            pos = self._from_controller(await self._client.read_position())
            if pos is not None:
                self._last_known_pos = pos
                if (
                    abs(pos[0] - target[0]) <= self.JOG_SETTLE_TOLERANCE_UM
                    and abs(pos[1] - target[1]) <= self.JOG_SETTLE_TOLERANCE_UM
                ):
                    return
            await asyncio.sleep(self.JOG_SETTLE_POLL_INTERVAL)

    async def set_wcs_offset(
        self, wcs_slot: str, x: float, y: float, z: float
    ) -> None:
        """
        Set a reference point offset on the controller.

        Args:
            wcs_slot: "REF0" or "REF1"
            x, y, z: Offset in mm (z ignored, Ruida is 2D)
        """
        if wcs_slot == "MACHINE":
            return

        if not self._client:
            return

        if wcs_slot not in self._client.ref_points:
            logger.warning(f"Unknown WCS slot: {wcs_slot}")
            return

        x_um = int(x * 1000)
        y_um = int(y * 1000)

        await self._client.set_ref_point_offset(wcs_slot, x_um, y_um)
        self.wcs_updated.send(self, offsets={wcs_slot: (x, y, z)})

    async def read_wcs_offsets(self) -> dict[str, Pos]:
        """
        Read reference point offsets from the controller.

        Returns offsets for REF0 and REF1 in mm. MACHINE is always zero.
        """
        offsets: dict[str, Pos] = {"MACHINE": (0.0, 0.0, 0.0)}

        if not self._client or not self._is_connected:
            self.wcs_updated.send(self, offsets=offsets)
            return offsets

        for ref_point in self._client.ref_points:
            if ref_point == "MACHINE":
                continue
            result = await self._client.get_ref_point_offset(ref_point)
            if result is not None:
                x_um, y_um = result
                offsets[ref_point] = (x_um / 1000.0, y_um / 1000.0, 0.0)

        self.wcs_updated.send(self, offsets=offsets)
        return offsets

    async def read_parser_state(self) -> str | None:
        if not self._client or not self._is_connected:
            return None
        return await self._client.get_ref_point_mode()

    async def select_wcs(self, wcs: str) -> None:
        """
        Select a reference point mode on the controller.

        Args:
            wcs: "REF0", "REF1", or "MACHINE"
        """
        if not self._client:
            return
        await self._client.select_ref_point(wcs)

    async def run_probe_cycle(
        self, axis: Axis, max_travel: float, feed_rate: int
    ) -> Pos | None:
        self.probe_status_changed.send(self, message="Probe not supported")
        return None

    async def _fetch_card_info(self) -> None:
        if not self._client:
            return
        try:
            card_info = await self._client.get_card_info()
            if card_info:
                card_id, model_name = card_info
                device = (
                    f"{model_name or 'Ruida controller'} "
                    f"(Card ID: 0x{card_id:08X})"
                )
            else:
                device = "Ruida controller"
            logger.info(
                f"Identified: {device}",
                extra=self._log_extra("MACHINE_EVENT"),
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - background task boundary
            logger.exception("Could not fetch card info")

    def _on_state_changed(self, sender) -> None:
        self._response_received.set()

    def _on_position_updated(self, sender, axis: str, value_um: int) -> None:
        """
        Handle position update from client.

        The two axes arrive in separate replies, so the cache is only
        published once both are known. Filling the missing one with a
        zero used to hand the next jog a fabricated origin.
        """
        machine_um = self._axis_um_from_controller(axis, value_um)
        pos_mm = machine_um / 1000.0
        current_pos = self.state.machine_pos

        if axis == "x":
            new_pos = (pos_mm, current_pos[1], current_pos[2])
            self._last_x_um = machine_um
        elif axis == "y":
            new_pos = (current_pos[0], pos_mm, current_pos[2])
            self._last_y_um = machine_um
        elif axis == "z":
            new_pos = (current_pos[0], current_pos[1], pos_mm)
        else:
            return

        if new_pos != current_pos:
            self.state = replace(self.state, machine_pos=new_pos)
            logger.debug(
                f"Position update: {axis}={pos_mm:.3f}mm, "
                f"machine_pos={self.state.machine_pos}"
            )
            self.state_changed.send(self, state=self.state)

    def _on_status_changed(
        self, sender, status: TransportStatus, message: str = ""
    ) -> None:
        self._update_connection_status(status, message)

    def _update_connection_status(
        self, status: TransportStatus, message: str = ""
    ) -> None:
        self.connection_status_changed.send(
            self, status=status, message=message
        )

    @property
    def is_connected(self) -> bool:
        return self._is_connected

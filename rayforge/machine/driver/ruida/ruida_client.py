"""
Ruida Client Protocol - Client-side command generation and sending.

Handles generation of commands to send to a Ruida laser controller,
sending them via transport, and parsing of responses.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Optional

from blinker import Signal

from .ruida_maps import (
    CARD_ID_ADDRESS,
    CARD_ID_TO_MODEL,
    REF_POINT_COMMANDS,
    REF_POINT_OFFSET_ADDRESSES,
)
from .ruida_protocol import RuidaResponse, RuidaState
from .ruida_util import (
    build_swizzle_lut,
    decode35,
    encode14,
    encode35,
    unswizzle_byte,
)

if TYPE_CHECKING:
    from .ruida_transport import RuidaTransport

logger = logging.getLogger(__name__)

# Job-stream sending parameters, ported from the proven working
# sender (send_fixture_test.py).
JOB_MAGIC = 0x88
JOB_CHUNK_MAX_BYTES = 1000
JOB_ACK_TIMEOUT = 4.0
JOB_SEND_ATTEMPTS = 4

# A single-byte job-chunk reply is an ACK when the byte, raw or
# unswizzled, is 0xCC or 0xC6, and a NAK for 0xCF or 0xCD. The client
# receives transport-unswizzled bytes, so the raw-byte cases map back
# through unswizzle.
_JOB_ACK_BYTES = frozenset(
    {0xCC, 0xC6} | {unswizzle_byte(b, JOB_MAGIC) for b in (0xCC, 0xC6)}
)
_JOB_NAK_BYTES = frozenset(
    {0xCF, 0xCD} | {unswizzle_byte(b, JOB_MAGIC) for b in (0xCF, 0xCD)}
)

# Panel key stream, sent raw on the jog channel: no swizzle and no
# checksum frame, unlike normal commands. A press is a down/up pair.
#
# UNUSED. Nothing sends these, and nothing uses the jog transport the
# client opens for them either. They are kept, with jog_start /
# jog_stop / jog_move_x / jog_move_y below, because D8 KeyUp is the
# only motion stop this repository actually models: if the hardware
# check in MOTION_AUDIT.md MOT-05 shows D8 01 does not halt an
# interactive D9 10 rapid, this is the surface the fix would use.
KEY_DOWN_PREFIX = b"\xa5\x50"
KEY_UP_PREFIX = b"\xa5\x51"


def split_commands(data: bytes) -> list[bytes]:
    """
    Split an unswizzled command stream into whole commands.

    A byte with the MSB set starts a new command; payload bytes are
    all 7-bit.
    """
    commands: list[bytes] = []
    current = bytearray()
    for byte in data:
        if byte >= 0x80 and current:
            commands.append(bytes(current))
            current = bytearray()
        current.append(byte)
    if current:
        commands.append(bytes(current))
    return commands


def build_datagrams(commands: list[bytes], max_size: int) -> list[bytes]:
    """
    Group whole commands into datagrams of at most max_size bytes.

    A command is never split across datagrams.
    """
    datagrams: list[bytes] = []
    current = bytearray()
    for command in commands:
        if current and len(current) + len(command) > max_size:
            datagrams.append(bytes(current))
            current = bytearray()
        current.extend(command)
    if current:
        datagrams.append(bytes(current))
    return datagrams


class RuidaClient:
    """
    Ruida client-side protocol handler.

    Generates commands to send to a Ruida controller, sends them via
    the transport layer, and parses responses.

    Usage:
        transport = RuidaTransport(UdpTransport(host, port))
        client = RuidaClient(transport)
        await client.connect()
        await client.home_xy()
        await client.move_abs(10000, 20000)  # in micrometers
    """

    def __init__(
        self,
        transport: "RuidaTransport",
        state: RuidaState | None = None,
        jog_transport: Optional["RuidaTransport"] = None,
    ):
        self._transport = transport
        self._jog_transport = jog_transport
        self.state = state or RuidaState()
        # A FIFO of waiters per address, not one. Two overlapping
        # reads of the same register used to overwrite each other:
        # the first hung to its full timeout, and its timeout then
        # evicted the second one's future.
        self._pending_mem_reads: dict[int, list[asyncio.Future]] = {}
        self._pending_acks: list[asyncio.Future] = []
        self._pending_job_acks: list[asyncio.Future] = []
        self._send_lock = asyncio.Lock()
        self._ref_point_mode: str | None = "MACHINE"
        self.position_updated = Signal()
        self.state_changed = Signal()

        self._transport.decoded_received.connect(self._handle_response)

    @property
    def is_connected(self) -> bool:
        return self._transport.is_connected

    def _handle_response(self, sender, data: bytes) -> None:
        """
        Handle decoded data from the transport layer.

        Parses DA memory read responses and emits signals.
        Also resolves any pending synchronous memory reads.

        Args:
            sender: The signal sender (unused)
            data: The decoded response data
        """
        pending = sorted(self._pending_mem_reads)
        logger.debug(f"handle_response: {data.hex()} (pending: {pending})")
        if len(data) == 1 and self._pending_job_acks:
            if data[0] in _JOB_ACK_BYTES or data[0] in _JOB_NAK_BYTES:
                future = self._pending_job_acks.pop(0)
                if not future.done():
                    future.set_result(data[0])
        elif (
            len(data) == 1
            and data[0] in (0xCC, 0xC6, 0xCF)
            and self._pending_acks
        ):
            future = self._pending_acks.pop(0)
            if not future.done():
                future.set_result(data[0] != 0xCF)

        if len(data) >= 9 and data[0] == 0xDA and data[1] == 0x01:
            mem_address = (data[2] << 8) | data[3]
            value = decode35(data[4:9])

            waiters = self._pending_mem_reads.get(mem_address)
            while waiters:
                future = waiters.pop(0)
                if not waiters:
                    self._pending_mem_reads.pop(mem_address, None)
                if not future.done():
                    future.set_result(value)
                    break

            axis = None
            if mem_address == 0x0421:
                axis = "x"
                self.state.x = value
            elif mem_address == 0x0431:
                axis = "y"
                self.state.y = value
            elif mem_address == 0x0441:
                axis = "z"
                self.state.z = value

            if axis:
                logger.debug(
                    f"Position response: {axis}={value}um "
                    f"(mem 0x{mem_address:04X})"
                )
                self.position_updated.send(self, axis=axis, value_um=value)

        self.state_changed.send(self)

    async def connect(self) -> None:
        """Establish connection to the Ruida controller."""
        await self._transport.connect()
        if self._jog_transport:
            await self._jog_transport.connect()

    async def disconnect(self) -> None:
        """Close connection to the Ruida controller."""
        if self._jog_transport:
            await self._jog_transport.disconnect()
        await self._transport.disconnect()

    def parse_response(self, data: bytes) -> RuidaResponse:
        return RuidaResponse.from_bytes(data)

    async def send_command(self, command: bytes) -> None:
        """
        Send a raw command to the controller.

        Sends are serialized behind a lock so that ACKs elicited by
        keepalive or status commands cannot resolve a pending
        job-chunk ACK future.

        Args:
            command: Raw command bytes (will be swizzled and framed)
        """
        async with self._send_lock:
            await self._transport.send_command(command)

    async def send_command_wait_ack(
        self, command: bytes, timeout: float = 1.0
    ) -> bool | None:
        """
        Send a command and wait for the controller's acknowledgement.

        Args:
            command: Raw command bytes (will be swizzled and framed)
            timeout: Maximum time to wait for the response in seconds

        Returns:
            True on ACK (0xCC or 0xC6), False on NAK (0xCF),
            None on timeout
        """
        loop = asyncio.get_event_loop()
        async with self._send_lock:
            future: asyncio.Future = loop.create_future()
            self._pending_acks.append(future)
            try:
                await self._transport.send_command(command)
                return await asyncio.wait_for(future, timeout)
            except asyncio.TimeoutError:
                if future in self._pending_acks:
                    self._pending_acks.remove(future)
                return None

    async def send_job(
        self,
        blob: bytes,
        on_start: Callable[[int, int], None] | None = None,
        on_chunk: Callable[[int, int, int, int], None] | None = None,
    ) -> None:
        """
        Send a complete swizzled .rd job blob to the controller.

        Ported from the proven working sender: the blob is unswizzled
        to find command boundaries, whole commands are grouped into
        chunks of at most JOB_CHUNK_MAX_BYTES, and each chunk is
        swizzled and framed with a 16-bit big-endian checksum by the
        transport. The caller must suspend keepalive and position
        polling for the whole send.

        Args:
            blob: The complete job as final swizzled .rd file bytes.
            on_start: Called once before the first chunk with
                (blob_size, chunk_count).
            on_chunk: Called after each acknowledged chunk with
                (index, chunk_count, chunk_size, attempts).

        Raises:
            RuntimeError: If a chunk is not acknowledged after
                JOB_SEND_ATTEMPTS attempts.
        """
        _, unswizzle_lut = build_swizzle_lut(JOB_MAGIC)
        commands = split_commands(bytes(unswizzle_lut[b] for b in blob))
        chunks = build_datagrams(commands, JOB_CHUNK_MAX_BYTES)
        if on_start:
            on_start(len(blob), len(chunks))
        for i, chunk in enumerate(chunks):
            attempts = await self._send_job_chunk(chunk)
            if not attempts:
                raise RuntimeError(
                    f"Controller did not acknowledge job chunk "
                    f"{i + 1}/{len(chunks)} after "
                    f"{JOB_SEND_ATTEMPTS} attempts"
                )
            if on_chunk:
                on_chunk(i + 1, len(chunks), len(chunk), attempts)

    async def _send_job_chunk(self, chunk: bytes) -> int:
        """
        Send one job chunk and wait for its ACK, retrying on NAK or
        timeout up to JOB_SEND_ATTEMPTS times.

        Returns:
            The number of attempts used once the chunk is
            acknowledged, or 0 if it never was.
        """
        loop = asyncio.get_event_loop()
        for attempt in range(1, JOB_SEND_ATTEMPTS + 1):
            async with self._send_lock:
                future: asyncio.Future = loop.create_future()
                self._pending_job_acks.append(future)
                try:
                    await self._transport.send_command(chunk)
                    reply = await asyncio.wait_for(future, JOB_ACK_TIMEOUT)
                except asyncio.TimeoutError:
                    if future in self._pending_job_acks:
                        self._pending_job_acks.remove(future)
                    logger.debug(
                        f"job chunk attempt {attempt}/"
                        f"{JOB_SEND_ATTEMPTS}: no reply in "
                        f"{JOB_ACK_TIMEOUT}s"
                    )
                    continue
            if reply in _JOB_ACK_BYTES:
                logger.debug(
                    f"job chunk attempt {attempt}/{JOB_SEND_ATTEMPTS}: "
                    f"ack 0x{reply:02x}"
                )
                return attempt
            logger.debug(
                f"job chunk attempt {attempt}/{JOB_SEND_ATTEMPTS}: "
                f"nak 0x{reply:02x}"
            )
        return 0

    async def send_jog_command(self, command: bytes) -> None:
        """
        Send a jog command to the controller via the main channel.

        Jog commands are swizzled and framed with checksum, sent on
        the main command channel (port 50200).

        Args:
            command: Raw command bytes
        """
        await self.send_command(command)

    async def move_abs(self, x: int, y: int) -> None:
        """
        Move to absolute position (traversal, laser off).

        Args:
            x: X coordinate in micrometers
            y: Y coordinate in micrometers
        """
        await self.send_command(self._build_move_abs(x, y))

    async def move_rel(self, dx: int, dy: int) -> None:
        """
        Move by relative offset (traversal, laser off).

        Args:
            dx: X offset in micrometers
            dy: Y offset in micrometers
        """
        await self.send_command(self._build_move_rel(dx, dy))

    async def cut_abs(self, x: int, y: int) -> None:
        """
        Move to absolute position (cutting, laser on).

        Args:
            x: X coordinate in micrometers
            y: Y coordinate in micrometers
        """
        await self.send_command(self._build_cut_abs(x, y))

    async def cut_rel(self, dx: int, dy: int) -> None:
        """
        Move by relative offset (cutting, laser on).

        Args:
            dx: X offset in micrometers
            dy: Y offset in micrometers
        """
        await self.send_command(self._build_cut_rel(dx, dy))

    async def move_rel_x(self, dx: int) -> None:
        """
        Move X axis by relative offset (traversal, laser off).

        Args:
            dx: X offset in micrometers
        """
        await self.send_command(self._build_move_rel_x(dx))

    async def move_rel_y(self, dy: int) -> None:
        """
        Move Y axis by relative offset (traversal, laser off).

        Args:
            dy: Y offset in micrometers
        """
        await self.send_command(self._build_move_rel_y(dy))

    async def cut_rel_x(self, dx: int) -> None:
        """
        Move X axis by relative offset (cutting, laser on).

        Args:
            dx: X offset in micrometers
        """
        await self.send_command(self._build_cut_rel_x(dx))

    async def cut_rel_y(self, dy: int) -> None:
        """
        Move Y axis by relative offset (cutting, laser on).

        Args:
            dy: Y offset in micrometers
        """
        await self.send_command(self._build_cut_rel_y(dy))

    async def rapid_move_xy(
        self, x_um: int, y_um: int, light: bool = False
    ) -> None:
        """
        Rapid move to an absolute position (D9 10).

        This is the interactive motion command used by real Ruida
        hardware; job streams use move_abs (0x88) instead. The move is
        a traversal: the laser never fires.

        UNVERIFIED, see MOTION_AUDIT.md MOT-38: the option byte sent
        is 0x00, which ruida_server names "Origin", yet the driver
        feeds this method absolute machine coordinates read back from
        0x0421/0x0431. Those two readings coincide whenever the
        selected ref point offset is zero, which is why nothing has
        caught it. The RDWorks fixture contains no D9 at all, so the
        repository cannot settle which frame the controller uses --
        the hardware check is written up in the audit. Do not change
        the option byte without that capture.

        Args:
            x_um: X coordinate in micrometers
            y_um: Y coordinate in micrometers
            light: Switch the red pointer on for the move
        """
        opts = self._build_move_opts(origin=True, light=light)
        await self.send_command(self._build_rapid_move_xy(x_um, y_um, opts))

    async def rapid_move_axis(
        self,
        axis: int,
        coord: int,
        origin: bool = False,
        light: bool = False,
    ) -> None:
        """
        Rapid move on a single axis.

        Args:
            axis: Sub-opcode: 0x00=X, 0x01=Y, 0x02=Z, 0x03=U. It is
                masked to four bits, so the 0x10-0x13 spelling maps
                to the same commands.
            coord: Coordinate in micrometers
            origin: Move relative to stored origin point
            light: Enable laser pointer during move
        """
        await self.send_command(
            self._build_rapid_move_axis(axis, coord, origin, light)
        )

    async def home_xy(self) -> None:
        """Home the X and Y axes."""
        await self.send_command(self._build_home_xy())

    async def home_z(self) -> None:
        """Home the Z axis."""
        await self.send_command(self._build_home_z())

    async def home_u(self) -> None:
        """Home the U axis."""
        await self.send_command(self._build_home_u())

    async def start_process(self) -> None:
        """Start the laser cutting process."""
        await self.send_command(self._build_start_process())

    async def stop_process(self) -> None:
        """Stop the laser cutting process."""
        await self.send_command(self._build_stop_process())

    async def pause_process(self) -> None:
        """Pause the laser cutting process."""
        await self.send_command(self._build_pause_process())

    async def resume_process(self) -> None:
        """Resume the paused laser cutting process."""
        await self.send_command(self._build_resume_process())

    async def set_ref_point_0(self) -> None:
        """Set reference point 0 (current position)."""
        await self.send_command(self._build_ref_point_0())

    async def set_ref_point_1(self) -> None:
        """Set reference point 1 (current position)."""
        await self.send_command(self._build_ref_point_1())

    async def set_ref_point_2(self) -> None:
        """Set reference point 2 (machine zero/absolute position)."""
        await self.send_command(self._build_ref_point_2())

    async def set_absolute_mode(self) -> None:
        """Set absolute coordinate mode."""
        await self.send_command(b"\xe6\x01")

    async def commit_ref_point(self) -> None:
        """Commit the current reference point setting."""
        await self.send_command(b"\xf0")

    async def jog_start(self, axis: str, direction: int) -> None:
        """
        Start continuous jog on an axis.

        Args:
            axis: Axis name ('x', 'y', 'z', or 'u')
            direction: Direction (1 for positive, -1 for negative)
        """
        await self.send_command(self._build_jog_keydown(axis, direction))

    async def jog_stop(self, axis: str, direction: int) -> None:
        """
        Stop continuous jog on an axis.

        UNUSED; see the note on KEY_DOWN_PREFIX. Kept because D8
        KeyUp is the only motion stop this repository models.

        Args:
            axis: Axis name ('x', 'y', 'z', or 'u')
            direction: Direction the matching key-down used
        """
        await self.send_command(self._build_jog_keyup(axis, direction))

    async def jog_move_x(self, target_x: int) -> None:
        """
        Rapid move the X axis by a relative offset (D9 00).

        UNUSED, and UNVERIFIED. Both in-repo references decode D9 00
        as relative (ruida_server accumulates, s.x += coord), and the
        driver's own bench note says feeding it an absolute
        coordinate drove the head to the wrong end of the axis, which
        is what a relative form would do. The driver uses D9 10 for
        every interactive move instead.

        Args:
            target_x: X offset in micrometers
        """
        await self.send_command(self._build_rapid_move_axis(0x00, target_x))

    async def jog_move_y(self, target_y: int) -> None:
        """
        Rapid move the Y axis by a relative offset (D9 01).

        UNUSED and UNVERIFIED; see jog_move_x.

        Args:
            target_y: Y offset in micrometers
        """
        await self.send_command(self._build_rapid_move_axis(0x01, target_y))

    async def set_power_immediate(
        self, laser: int, power_percent: float
    ) -> None:
        """
        Set laser power immediately (takes effect right away).

        Args:
            laser: Laser number (1-4)
            power_percent: Power level (0.0 to 100.0)
        """
        await self.send_command(
            self._build_power_immediate(laser, power_percent)
        )

    async def set_power_end(self, laser: int, power_percent: float) -> None:
        """
        Set laser power at end of move (takes effect after current move).

        Args:
            laser: Laser number (1-4)
            power_percent: Power level (0.0 to 100.0)
        """
        await self.send_command(self._build_power_end(laser, power_percent))

    async def set_frequency(self, laser: int, layer: int, hz: int) -> None:
        """
        Set laser PWM frequency for a layer.

        Args:
            laser: Laser number (1-based)
            layer: Layer index
            hz: Frequency in Hz
        """
        await self.send_command(self._build_frequency(laser, hz, layer))

    async def set_pulse_width(self, pulse_width_us: int) -> None:
        """
        Set laser pulse width.

        Args:
            pulse_width_us: Pulse width in microseconds
        """
        await self.send_command(self._build_pulse_width(pulse_width_us))

    async def set_travel_speed(self, um_per_s: int) -> None:
        """
        Set interactive travel speed (C9 02, speed_laser_1).

        Streamed immediately before an interactive rapid move; real
        hardware has no persistent jog-speed register. This is the
        only authority for C9 02: the mm/s wrappers below convert and
        delegate rather than encoding the opcode a second time.

        Args:
            um_per_s: Speed in micrometers per second
        """
        await self.send_command(self._build_travel_speed(um_per_s))

    async def set_speed(self, speed_mm_s: float) -> None:
        """
        Set movement speed.

        Args:
            speed_mm_s: Speed in millimeters per second
        """
        await self.send_command(self._build_speed(speed_mm_s))

    async def set_axis_speed(self, speed_mm_s: float) -> None:
        """
        Set axis-specific speed.

        Args:
            speed_mm_s: Speed in millimeters per second
        """
        await self.send_command(self._build_axis_speed(speed_mm_s))

    async def end_of_file(self) -> None:
        """Send end-of-file marker."""
        await self.send_command(self._build_end_of_file())

    async def keep_alive(self) -> None:
        """Send keep-alive packet to maintain connection."""
        await self.send_command(self._build_keep_alive())

    def _build_move_abs(self, x: int, y: int) -> bytes:
        return b"\x88" + encode35(x) + encode35(y)

    def _build_move_rel(self, dx: int, dy: int) -> bytes:
        return b"\x89" + encode14(dx) + encode14(dy)

    def _build_cut_abs(self, x: int, y: int) -> bytes:
        return b"\xa8" + encode35(x) + encode35(y)

    def _build_cut_rel(self, dx: int, dy: int) -> bytes:
        return b"\xa9" + encode14(dx) + encode14(dy)

    def _build_move_rel_x(self, dx: int) -> bytes:
        return b"\x8a" + encode14(dx)

    def _build_move_rel_y(self, dy: int) -> bytes:
        return b"\x8b" + encode14(dy)

    def _build_cut_rel_x(self, dx: int) -> bytes:
        return b"\xaa" + encode14(dx)

    def _build_cut_rel_y(self, dy: int) -> bytes:
        return b"\xab" + encode14(dy)

    def _build_rapid_move_xy(self, x: int, y: int, opts: int = 0x00) -> bytes:
        return b"\xd9\x10" + bytes([opts]) + encode35(x) + encode35(y)

    def _build_rapid_move_axis(
        self,
        axis: int,
        coord: int,
        origin: bool = False,
        light: bool = False,
    ) -> bytes:
        opts = self._build_move_opts(origin, light)
        return b"\xd9" + bytes([axis & 0x0F]) + bytes([opts]) + encode35(coord)

    def _build_move_opts(self, origin: bool, light: bool) -> int:
        """
        The D9 option byte: bit 0 is Light, bit 1 is not-Origin.

        UNVERIFIED. This mapping matches ruida_server's own decoder
        and nothing else -- there is no capture of a D9 command
        anywhere in this repository. See MOTION_AUDIT.md MOT-47.
        """
        if origin and light:
            return 0x01
        elif origin:
            return 0x00
        elif light:
            return 0x03
        return 0x02

    def _build_home_xy(self) -> bytes:
        return b"\xd8\x2a"

    def _build_home_z(self) -> bytes:
        return b"\xd8\x2c"

    def _build_home_u(self) -> bytes:
        return b"\xd8\x2d"

    def _build_start_process(self) -> bytes:
        return b"\xd8\x00"

    def _build_stop_process(self) -> bytes:
        return b"\xd8\x01"

    def _build_pause_process(self) -> bytes:
        return b"\xd8\x02"

    def _build_resume_process(self) -> bytes:
        return b"\xd8\x03"

    def _build_ref_point_0(self) -> bytes:
        return b"\xd8\x12"

    def _build_ref_point_1(self) -> bytes:
        return b"\xd8\x11"

    def _build_ref_point_2(self) -> bytes:
        return b"\xd8\x10"

    def _build_jog_keydown(self, axis: str, direction: int) -> bytes:
        axis_map = {
            ("x", -1): 0x20,
            ("x", 1): 0x21,
            ("y", 1): 0x22,
            ("y", -1): 0x23,
            ("z", 1): 0x24,
            ("z", -1): 0x25,
            ("u", 1): 0x26,
            ("u", -1): 0x27,
        }
        key = (axis.lower(), direction)
        if key not in axis_map:
            raise ValueError(f"Invalid axis/direction: {axis}, {direction}")
        return b"\xd8" + bytes([axis_map[key]])

    def _build_jog_keyup(self, axis: str, direction: int) -> bytes:
        """
        D8 key-up, which is the key-down opcode plus 0x10.

        The map used to be keyed by axis alone and always produced the
        negative-direction opcode, so a positive-direction key could
        never have been released.
        """
        key = (axis.lower(), direction)
        keydown = self._build_jog_keydown(*key)
        return b"\xd8" + bytes([keydown[1] + 0x10])

    def _build_power_immediate(
        self, laser: int, power_percent: float
    ) -> bytes:
        power_val = int(power_percent / 100.0 * 16383.0)
        laser_map = {1: 0xC7, 2: 0xC0, 3: 0xC2, 4: 0xC3}
        if laser not in laser_map:
            raise ValueError(f"Invalid laser: {laser}")
        return bytes([laser_map[laser]]) + encode14(power_val)

    def _build_power_end(self, laser: int, power_percent: float) -> bytes:
        power_val = int(power_percent / 100.0 * 16383.0)
        laser_map = {1: 0xC8, 2: 0xC1, 3: 0xC4, 4: 0xC5}
        if laser not in laser_map:
            raise ValueError(f"Invalid laser: {laser}")
        return bytes([laser_map[laser]]) + encode14(power_val)

    def _build_travel_speed(self, um_per_s: int) -> bytes:
        """C9 02 + encode35, in micrometres per second."""
        return b"\xc9\x02" + encode35(um_per_s)

    def _build_speed(self, speed_mm_s: float) -> bytes:
        """C9 02 from mm/s. Delegates so one place owns the opcode."""
        return self._build_travel_speed(int(speed_mm_s * 1000))

    def _build_frequency(
        self, laser: int, frequency: int, layer: int = 0
    ) -> bytes:
        """C6 60 <laser index, zero-based> <layer & 0x7F> + encode35."""
        laser_index = min(max(laser - 1, 0), 5)
        return (
            b"\xc6\x60"
            + bytes([laser_index, layer & 0x7F])
            + encode35(frequency)
        )

    def _build_pulse_width(self, pulse_width_us: int) -> bytes:
        """C6 10 + encode35 (7 bytes total)."""
        return b"\xc6\x10" + encode35(pulse_width_us)

    def _build_axis_speed(self, speed_mm_s: float) -> bytes:
        """C9 03, the per-axis speed, from mm/s."""
        return b"\xc9\x03" + encode35(int(speed_mm_s * 1000))

    def _build_end_of_file(self) -> bytes:
        return b"\xd7"

    def _build_keep_alive(self) -> bytes:
        return b"\xce"

    def _build_ack(self) -> bytes:
        return b"\xcc"

    def _build_error(self) -> bytes:
        return b"\xcd"

    async def air_assist_on(self) -> None:
        """Enable air assist."""
        await self.send_command(b"\xca\x01\x13")

    async def air_assist_off(self) -> None:
        """Disable air assist."""
        await self.send_command(b"\xca\x01\x12")

    async def select_layer(self, layer_index: int) -> None:
        """
        Select layer by index (0-15).

        Args:
            layer_index: Layer index (0-15).
        """
        if not 0 <= layer_index <= 15:
            raise ValueError(f"Layer index must be 0-15, got {layer_index}")
        await self.send_command(bytes([0xCA, layer_index]))

    async def send_raw(self, data: bytes) -> None:
        """
        Send raw binary data (already framed/swizzled).

        Args:
            data: Raw binary data to send.
        """
        await self._transport.send(data)

    def _build_read_memory(self, mem_address: int) -> bytes:
        """
        Build command to read from controller memory.

        Args:
            mem_address: Memory address (e.g., 0x0421 for Current X)

        Returns:
            Command bytes to send
        """
        mem_high = (mem_address >> 8) & 0xFF
        mem_low = mem_address & 0xFF
        return bytes([0xDA, 0x00, mem_high, mem_low])

    async def _read_memory(self, mem_address: int) -> None:
        """
        Send a memory read request to the controller.

        Args:
            mem_address: Memory address to read (e.g., 0x0421 for Current X)
        """
        await self.send_command(self._build_read_memory(mem_address))

    async def get_position(self) -> tuple[int, int, int]:
        """
        Request current X, Y, Z position from controller.

        Sends memory read commands for position registers.
        Position values will be returned asynchronously via the
        decoded_received signal.

        Returns:
            Tuple of (x, y, z) in micrometers
            (may be stale until response received)
        """
        await self._read_memory(0x0421)
        await self._read_memory(0x0431)
        await self._read_memory(0x0441)
        return (self.state.x, self.state.y, self.state.z)

    async def read_position(
        self, timeout: float = 2.0
    ) -> tuple[int, int] | None:
        """
        Read current X and Y from the controller, waiting for both.

        Unlike get_position(), this does not return stale cached state.

        Args:
            timeout: Maximum time to wait per register, in seconds.

        Returns:
            Tuple of (x_um, y_um), or None if either read timed out.
        """
        x_um = await self._read_memory_wait(0x0421, timeout)
        y_um = await self._read_memory_wait(0x0431, timeout)
        if x_um is None or y_um is None:
            return None
        return (x_um, y_um)

    def _build_write_memory(self, mem_address: int, value: int) -> bytes:
        """
        Build command to write to controller memory.

        Args:
            mem_address: Memory address (e.g., 0x0224 for Position Point 0 X)
            value: Value to write in micrometers

        Returns:
            Command bytes to send
        """
        mem_high = (mem_address >> 8) & 0xFF
        mem_low = mem_address & 0xFF
        encoded_value = encode35(value)
        return (
            bytes([0xDA, 0x01, mem_high, mem_low])
            + encoded_value
            + encoded_value
        )

    async def _write_memory(self, mem_address: int, value: int) -> None:
        """
        Write a value to controller memory.

        Args:
            mem_address: Memory address to write
            value: Value to write (will be encoded as 35-bit signed)
        """
        await self.send_command(self._build_write_memory(mem_address, value))

    async def _read_memory_wait(
        self, mem_address: int, timeout: float = 2.0
    ) -> int | None:
        """
        Read a value from controller memory and wait for response.

        Args:
            mem_address: Memory address to read
            timeout: Maximum time to wait for response in seconds

        Returns:
            Decoded value or None if timeout
        """
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        waiters = self._pending_mem_reads.setdefault(mem_address, [])
        waiters.append(future)

        try:
            await self._read_memory(mem_address)
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            # Remove by identity: popping the address would evict
            # whichever waiter happens to be at the head, which may
            # belong to somebody else entirely.
            waiters = self._pending_mem_reads.get(mem_address)
            if waiters and future in waiters:
                waiters.remove(future)
            if waiters is not None and not waiters:
                self._pending_mem_reads.pop(mem_address, None)
            logger.warning(f"Timeout reading memory 0x{mem_address:04X}")
            return None

    async def set_ref_point_offset(
        self, ref_point: str, x_um: int, y_um: int
    ) -> None:
        """
        Set the offset for a reference point.

        Args:
            ref_point: "REF0" or "REF1"
            x_um: X offset in micrometers
            y_um: Y offset in micrometers
        """
        if ref_point not in REF_POINT_OFFSET_ADDRESSES:
            raise ValueError(f"Unknown reference point: {ref_point}")

        x_addr, y_addr = REF_POINT_OFFSET_ADDRESSES[ref_point]
        await self._write_memory(x_addr, x_um)
        await self._write_memory(y_addr, y_um)

    async def get_ref_point_offset(
        self, ref_point: str
    ) -> tuple[int, int] | None:
        """
        Get the offset for a reference point.

        Args:
            ref_point: "REF0" or "REF1"

        Returns:
            Tuple of (x_um, y_um) or None if read failed
        """
        if ref_point not in REF_POINT_OFFSET_ADDRESSES:
            raise ValueError(f"Unknown reference point: {ref_point}")

        x_addr, y_addr = REF_POINT_OFFSET_ADDRESSES[ref_point]
        x_um = await self._read_memory_wait(x_addr)
        y_um = await self._read_memory_wait(y_addr)

        if x_um is None or y_um is None:
            return None
        return (x_um, y_um)

    @property
    def ref_points(self) -> tuple[str, ...]:
        """Return tuple of valid reference point names including MACHINE."""
        return ("MACHINE",) + tuple(REF_POINT_OFFSET_ADDRESSES.keys())

    async def select_ref_point(self, ref_point: str) -> None:
        """
        Select a reference point mode on the controller.

        Args:
            ref_point: "MACHINE", "REF0", or "REF1"
        """
        if ref_point not in REF_POINT_COMMANDS:
            raise ValueError(f"Unknown reference point: {ref_point}")
        await self.send_command(REF_POINT_COMMANDS[ref_point])
        self._ref_point_mode = ref_point

    def set_tracked_ref_point_mode(self, mode: str | None) -> None:
        """
        Seed the locally tracked reference point mode.

        The controller cannot report its mode, so the driver seeds it
        from the machine profile rather than assuming MACHINE.

        Args:
            mode: "MACHINE", "REF0", "REF1", or None.
        """
        self._ref_point_mode = mode

    async def get_ref_point_mode(self) -> str | None:
        """
        Get the current reference point mode.

        The ref point mode cannot be read back from the controller
        (no valid DA memory address exists for it), so this returns
        the locally tracked mode set via select_ref_point.

        Returns:
            "MACHINE", "REF0", "REF1", or None if not yet set
        """
        return self._ref_point_mode

    async def get_card_id(self) -> int | None:
        """
        Get the card ID from the controller.

        Returns:
            Card ID (e.g., 0x65106510) or None if read failed
        """
        return await self._read_memory_wait(CARD_ID_ADDRESS)

    async def get_model_name(self) -> str | None:
        """
        Get the controller model name.

        Returns:
            Model name (e.g., "RDC6442S") or None if unknown/read failed
        """
        card_id = await self.get_card_id()
        if card_id is None:
            return None

        return CARD_ID_TO_MODEL.get(card_id, f"Unknown (0x{card_id:08X})")

    async def get_card_info(
        self,
    ) -> tuple[int | None, str | None] | None:
        """
        Get card ID and model name from the controller.

        Returns:
            Tuple of (card_id, model_name) or None if read failed.
            model_name may be None if card_id is unknown.
        """
        card_id = await self.get_card_id()
        if card_id is None:
            return None

        model_name = CARD_ID_TO_MODEL.get(card_id)
        return (card_id, model_name)

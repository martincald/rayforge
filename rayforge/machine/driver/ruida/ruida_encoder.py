"""
Ruida Encoder - Converts Ops commands to Ruida binary protocol.

Produces both binary output for the controller and human-readable
text representation for UI display.
"""

import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING

from raygeo.geo.types import Point3D
from raygeo.ops import Ops
from raygeo.ops.state import AirAssistMode
from raygeo.ops.types import CommandType

from ....pipeline.encoder.base import (
    EncodedOutput,
    MachineCodeOpMap,
    OpsEncoder,
)
from ..driver import acceleration_run_up_mm
from .ruida_maps import REF_POINT_COMMANDS
from .ruida_util import build_swizzle_lut, encode14, encode35

if TYPE_CHECKING:
    from ....core.doc import Doc
    from ....machine.models.machine import Machine

logger = logging.getLogger(__name__)

# Constant payloads replayed verbatim from the RDWorks ground-truth
# file (tests/machine/driver/ruida/fixtures/rdworks_reference.rd).
# Their meaning is unknown; they are emitted only when
# follow_reference is enabled.
_REF_E7_32 = bytes.fromhex("e73201502024100150202410")
_REF_E7_3B = b"\xe7\x3b\x41"
_REF_C6_65_VALUE = b"\x3d"
_REF_CA_03 = b"\xca\x03\x3d"
_REF_DA_01_0620 = b"\xda\x01\x06\x20" + encode35(73) + encode35(73)

_LASER_DEVICE_CMDS = {1: b"\xca\x01\x10", 2: b"\xca\x01\x11"}

# Immediate power opcode per laser, used for scanline modulation.
_IMD_POWER_CMDS = {1: 0xC7, 2: 0xC0, 3: 0xC2, 4: 0xC3}

# Relative motion commands carry signed 14-bit two's complement
# deltas; both |dx| and |dy| must stay below this to use them.
_REL_LIMIT_UM = 0x2000

# Swizzle magic used for complete .rd job files.
RD_MAGIC = 0x88

# Jobs always select the anchor reference point (D8 12), matching the
# RDWorks ground-truth file, so a cut starts where the operator set the
# origin. The stored machine WCS never picks the job's reference point.
JOB_REF_POINT = "REF0"


# The work mode a part declares, in the header's CA 41 <part> <mode>
# and again in the body's CA 01 <mode>. The RDWorks ground-truth file
# holds a single contour part and carries 0 in both places, so 0 is
# right for a cut part and is what every part gets.
# TODO: a scan part's mode is unverified. The fixtures that would
# settle it -- fixtures/rdworks_scan.rd and
# fixtures/rdworks_scan_plus_cut.rd -- are not in this repository.
# See docs/process-ordering-audit.md PRO-09; when one arrives, this
# is the only value that changes.
_DEFAULT_PART_MODE = 0


def _no_settings() -> dict:
    """The settings a part falls back to when it has none at all."""
    return {
        "uid": None,
        "speed": 0.0,
        "travel": 0.0,
        "power": 0.0,
        "min_power": 0.0,
        "air": False,
        "mode": _DEFAULT_PART_MODE,
    }


def commands_to_rd_bytes(commands: list[bytes]) -> bytes:
    """
    Swizzle a complete command list into final .rd file bytes.

    Args:
        commands: The complete unswizzled command list, including the
            E5 05 checksum and D7 end-of-file marker.

    Returns:
        The whole command stream swizzled with RD_MAGIC.
    """
    swizzle_lut, _ = build_swizzle_lut(RD_MAGIC)
    return bytes(swizzle_lut[b] for b in b"".join(commands))


def build_rd_bytes(ops: Ops, machine: "Machine", doc: "Doc") -> bytes:
    """
    Encode ops into a complete swizzled Ruida .rd job blob.

    The unswizzled command list remains available via
    RuidaEncoder.encode() (driver_data["commands"]).
    """
    encoded = RuidaEncoder().encode(ops, machine, doc)
    return commands_to_rd_bytes(encoded.driver_data["commands"])


def export_rd(
    ops: Ops, machine: "Machine", doc: "Doc", path: Path | str
) -> None:
    """
    Write ops as a Ruida .rd file.

    The file contains exactly the blob RuidaClient.send_job would
    transmit for the same ops.
    """
    Path(path).write_bytes(build_rd_bytes(ops, machine, doc))


class RuidaEncoder(OpsEncoder):
    """
    Converts Ops commands to Ruida binary protocol.

    This encoder produces:
    - Binary data for transmission to Ruida controllers
    - Human-readable text for UI display

    Coordinates are converted from mm to micrometers (µm) internally.
    Power is converted from normalized (0.0-1.0) to percentage (0-100)
    and then to the 14-bit value expected by Ruida (0-16383).
    """

    UM_PER_MM = 1000.0
    SECONDS_PER_MINUTE = 60.0
    POWER_SCALE = 16383.0

    def __init__(self, follow_reference: bool = True):
        self.follow_reference = follow_reference
        self.power: float | None = None
        self.cut_speed: float | None = None
        self.travel_speed: float | None = None
        self.air_assist: bool = False
        self.current_pos: Point3D = (0.0, 0.0, 0.0)
        self.active_laser: int = 1
        self.origin_um: tuple[int, int] = (0, 0)
        self._doc: Doc | None = None
        self._layers: list[dict] = []
        self._part_opens: dict[int, int] = {}
        self._planned: bool = False
        self._in_part: bool = False
        self._part: int = -1
        self._laser_selected: int | None = None
        self._last_pos_um: tuple[int, int] | None = None
        self._imd_power: int | None = None
        self._min_power: float | None = None

    def encode(
        self, ops: Ops, machine: "Machine", doc: "Doc"
    ) -> EncodedOutput:
        """
        Encode Ops commands to Ruida binary format.

        Args:
            ops: The Ops object containing commands to encode
            machine: The machine configuration
            doc: The document being processed

        Returns:
            EncodedOutput with one complete command per entry in
            driver_data["commands"], text representation, and op_map
        """
        self._reset_state()
        self._doc = doc

        binary_chunks: list[bytes] = []
        text_lines: list[str] = []
        line_spans: list[tuple[int, int]] = []

        for i in range(ops.len()):
            start_line = len(text_lines)
            self._handle_command(ops, i, machine, binary_chunks, text_lines)
            end_line = len(text_lines)
            line_spans.append((start_line, end_line - start_line))

        if text_lines and not text_lines[-1]:
            text_lines = text_lines[:-1]

        machine_code_to_op = [-1] * len(text_lines)
        for i, (start_line, line_count) in enumerate(line_spans):
            for line_num in range(start_line, start_line + line_count):
                if line_num < len(machine_code_to_op):
                    machine_code_to_op[line_num] = i
        op_map = MachineCodeOpMap.from_lists(line_spans, machine_code_to_op)

        return EncodedOutput(
            text="\n".join(text_lines),
            op_map=op_map,
            driver_data={"commands": binary_chunks},
        )

    def _reset_state(self) -> None:
        """Reset encoder state for a new encoding pass."""
        self.current_pos = (0.0, 0.0, 0.0)
        self.active_laser = 1
        self.origin_um = (0, 0)
        self._doc = None
        self._layers = []
        self._part_opens = {}
        self._planned = False
        self._in_part = False
        self._part = -1
        self._reset_emission_state()

    def _reset_emission_state(self) -> None:
        """
        Forget everything the encoder remembers having emitted.

        Every one of these fields suppresses a command when it already
        matches, so a stale value silently drops a command a layer
        needs. Cleared at the start of each layer, so no setting can
        bleed from the layer before it.
        """
        self.power = None
        self.cut_speed = None
        self.travel_speed = None
        self.air_assist = False
        self._laser_selected = None
        self._last_pos_um = None
        self._imd_power = None
        self._min_power = None

    def _mm_to_um(self, mm: float) -> int:
        """Convert millimeters to micrometers."""
        return int(mm * self.UM_PER_MM)

    def _speed_to_um_s(self, mm_min: float) -> int:
        """
        Convert a stored speed to the micrometers per second the wire
        wants.

        Speeds reach the encoder in the application base unit, mm/min.
        This is the only place they are converted, so a speed set in the
        UI arrives on the controller unchanged.
        """
        return int(mm_min * self.UM_PER_MM / self.SECONDS_PER_MINUTE)

    def _power_to_ruida(self, power_normalized: float) -> int:
        """Convert normalized power (0.0-1.0) to Ruida 14-bit value."""
        return int(power_normalized * self.POWER_SCALE)

    def _handle_command(
        self,
        ops: Ops,
        idx: int,
        machine: "Machine",
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Dispatch command to appropriate handler."""
        ct = ops.command_type(idx)

        # The job pre-scan is the only thing that decides where a part
        # begins; this walk just does what it was told, at the index it
        # was told. A stream encoded with no job prologue was never
        # planned, so there a marker still opens its own part.
        part = self._part_opens.get(idx)
        if (
            part is None
            and not self._planned
            and ct == CommandType.LAYER_START
        ):
            part = self._part + 1
        if part is not None:
            self._open_part(part, binary)

        if ct == CommandType.SET_POWER:
            self._handle_set_power(ops, idx, binary, text)
        elif ct == CommandType.SET_FEED_RATE:
            self._handle_set_cut_speed(ops, idx, binary, text)
        elif ct == CommandType.SET_RAPID_RATE:
            self._handle_set_travel_speed(ops, idx, binary, text)
        elif ct == CommandType.SET_FREQUENCY:
            self._handle_set_frequency(ops, idx, binary, text)
        elif ct == CommandType.SET_PULSE_WIDTH:
            self._handle_set_pulse_width(ops, idx, binary, text)
        elif ct == CommandType.SET_AIR_ASSIST:
            self._handle_air_assist(ops, idx, binary, text)
        elif ct == CommandType.SET_COOLANT:
            self._handle_coolant(ops, idx, binary, text)
        elif ct == CommandType.SET_HEAD:
            self._handle_set_laser(ops, idx, machine, binary, text)
        elif ct == CommandType.MOVE_TO:
            self._handle_move_to(ops, idx, binary, text)
            self.current_pos = ops.endpoint(idx)
        elif ct == CommandType.LINE_TO:
            self._handle_line_to(ops, idx, binary, text)
            self.current_pos = ops.endpoint(idx)
        elif ct == CommandType.ARC_TO:
            self._handle_arc_to(ops, idx, binary, text)
            self.current_pos = ops.endpoint(idx)
        elif ct == CommandType.SCAN_LINE:
            self._handle_scan_line(ops, idx, binary, text)
            self.current_pos = ops.endpoint(idx)
        elif ct == CommandType.JOB_START:
            self._handle_job_start(ops, machine, binary, text)
        elif ct == CommandType.JOB_END:
            self._handle_job_end(binary, text)
        elif ct == CommandType.LAYER_START:
            self._handle_layer_start(ops, idx, binary, text)
        elif ct == CommandType.LAYER_END:
            self._handle_layer_end(ops, idx, binary, text)
        elif ct == CommandType.WORKPIECE_START:
            self._handle_workpiece_start(ops, idx, text)
        elif ct == CommandType.WORKPIECE_END:
            self._handle_workpiece_end(ops, idx, text)

    def _handle_set_power(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle SetPowerCommand - set min/max power for active laser."""
        power = ops.power(idx)
        power_percent = power * 100.0
        if self._in_part:
            # The part's own block already stated this. A change the
            # block could not have covered opened a part of its own,
            # so nothing is left here to override inline.
            text.append(f"POWER {power_percent:.1f}")
            return
        if self.power is not None and power == self.power:
            text.append(f"POWER {power_percent:.1f}")
            return
        self.power = power
        min14 = encode14(self._power_to_ruida(self._min_power_for(power)))
        max14 = encode14(self._power_to_ruida(power))

        laser_cmds = {
            1: (b"\xc6\x01", b"\xc6\x02"),
            2: (b"\xc6\x21", b"\xc6\x22"),
            3: (b"\xc6\x05", b"\xc6\x06"),
            4: (b"\xc6\x07", b"\xc6\x08"),
        }
        min_cmd, max_cmd = laser_cmds.get(self.active_laser, laser_cmds[1])
        binary.append(min_cmd + min14)
        binary.append(max_cmd + max14)
        text.append(f"POWER {power_percent:.1f}")

    def _min_power_for(self, max_power: float) -> float:
        """
        The floor to pair with a max power, never above it.

        Falls back to the max power, which is what the reference file
        emits and what a document without the field means.
        """
        if self._min_power is None:
            return max_power
        return min(self._min_power, max_power)

    def _layer_min_power(self, uid: str | None, max_power: float) -> float:
        """
        The Min Power configured for a part, normalized 0-1.

        The controller applies Min Power below its start speed, so a
        floor left at zero never fires the tube on a slow cut. Ops carry
        a single power channel, so the floor is read from the document
        by the uid the layer marker carries.

        Job ops mark by step uid, which is what owns the floor. A layer
        uid is still accepted, for ops assembled outside the job
        aggregate, and answers with the first step that has a floor.
        Anything else falls back to min == max, loudly.
        """
        if uid is None or self._doc is None:
            return max_power

        for step in self._doc_steps():
            # getattr, like min_power below: the encoder reads only the
            # fields it needs off a step, never the whole model.
            if getattr(step, "uid", None) != uid:
                continue
            min_power = getattr(step, "min_power", None)
            if min_power is None:
                return max_power
            return min(float(min_power), max_power)

        for layer in self._doc.layers:
            if layer.uid != uid:
                continue
            workflow = layer.workflow
            if workflow is None:
                break
            for step in workflow.steps:
                min_power = getattr(step, "min_power", None)
                if min_power is not None:
                    return min(float(min_power), max_power)
            break
        else:
            self._warn_unresolved_uid(uid, "min power")
        return max_power

    def _doc_steps(self) -> list:
        """Every step of every layer the document has, in order."""
        if self._doc is None:
            return []
        return [
            step
            for layer in self._doc.layers
            if layer.workflow
            for step in layer.workflow.steps
        ]

    def _warn_unresolved_uid(self, uid: str | None, what: str) -> None:
        """
        Report a settings lookup that found nothing and fell back.

        Silence here is what let a whole job run on one step's
        settings, so the uid and both uid spaces it was matched
        against are named.
        """
        layer_uids = (
            [layer.uid for layer in self._doc.layers] if self._doc else []
        )
        step_uids = [getattr(step, "uid", None) for step in self._doc_steps()]
        logger.warning(
            f"Ruida: no {what} for uid {uid!r}; falling back. "
            f"Known layer uids: {layer_uids}. "
            f"Known step uids: {step_uids}."
        )

    def _handle_set_cut_speed(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle SetCutSpeedCommand - set cutting speed in mm/min."""
        speed = ops.rate(idx)
        if self._in_part or (
            self.cut_speed is not None and speed == self.cut_speed
        ):
            text.append(f"SPEED {speed:.1f}")
            return
        self.cut_speed = speed
        binary.append(b"\xc9\x02" + encode35(self._speed_to_um_s(speed)))
        text.append(f"SPEED {speed:.1f}")

    def _handle_set_travel_speed(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """
        Handle SetTravelSpeedCommand - track state only.

        The part's own body block emits its C9 03 from the travel
        speed in force when the part opened, so nothing is emitted
        per primitive here; that would overwrite the part's axis
        speed mid-cut.
        """
        speed = ops.rate(idx)
        self.travel_speed = speed
        text.append(f"TRAVEL_SPEED {speed:.1f}")

    def _handle_set_frequency(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle SetFrequencyCommand - emit 0xC6 0x60 frequency.

        Layout: C6 60 <laser index, zero-based> <layer & 0x7F> +
        encode35(freq). Emitted only when a frequency is explicitly
        configured; the reference file contains no C6 60.
        """
        freq = ops.frequency(idx)
        text.append(f"FREQUENCY {freq}")
        if not freq:
            return
        laser = self.active_laser - 1
        layer = max(self._part, 0) & 0x7F
        binary.append(b"\xc6\x60" + bytes([laser, layer]) + encode35(freq))

    def _handle_set_pulse_width(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle SetPulseWidthCommand - emit 0xC6 0x10 interval.

        Wire format: C6 10 + encode35 (7 bytes total). Emitted only
        when a pulse width is explicitly configured; the reference
        file contains no C6 10.
        """
        pw = ops.pulse_width(idx)
        pulse_us = int(pw)
        text.append(f"PULSE_WIDTH {pw:.1f}")
        if not pulse_us:
            return
        binary.append(b"\xc6\x10" + encode35(pulse_us))

    def _handle_air_assist(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle SetAirAssistCommand - update air assist state."""
        mode = ops.air_assist(idx)
        if self._in_part:
            # Stated by the part's block, like speed and power.
            return
        if mode == AirAssistMode.ON:
            if not self.air_assist:
                self.air_assist = True
                binary.append(b"\xca\x01\x13")
                text.append("AIR_ASSIST ON")
        else:
            if self.air_assist:
                self.air_assist = False
                binary.append(b"\xca\x01\x12")
                text.append("AIR_ASSIST OFF")

    def _handle_coolant(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle SetCoolantCommand - coolant not used on laser cutters."""

    def _handle_set_laser(
        self,
        ops: Ops,
        idx: int,
        machine: "Machine",
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle SetLaserCommand - select active laser head."""
        laser_uid = ops.head_uid(idx)
        laser_head = next(
            (head for head in machine.heads if head.uid == laser_uid),
            None,
        )

        if laser_head is None:
            logger.warning(
                f"Could not find laser with UID '{laser_uid}'. "
                "Using default laser 1."
            )
            self.active_laser = 1
        else:
            # A head's tool_number counts from 0, as T0 does on every
            # other driver, and Ruida numbers its lasers from 1.
            # set_power makes the same +1, so a job and a test fire
            # select the same laser. Read as-is, the model default
            # was laser 0, and the second part of every job died on
            # CA 10 <laser - 1>.
            self.active_laser = laser_head.tool_number + 1

        if self._laser_selected != self.active_laser:
            self._laser_selected = self.active_laser
            binary.append(
                _LASER_DEVICE_CMDS.get(self.active_laser, b"\xca\x01\x10")
            )
        text.append(f"LASER {self.active_laser}")

    def _job_local_um(self, ops: Ops, idx: int) -> tuple[int, int]:
        """Command endpoint in job-local micrometers."""
        end = ops.endpoint(idx)
        return (
            self._mm_to_um(end[0]) - self.origin_um[0],
            self._mm_to_um(end[1]) - self.origin_um[1],
        )

    def _rel_deltas(self, x_um: int, y_um: int) -> tuple[int, int] | None:
        """Deltas from the last emitted position, if encodable as
        signed 14-bit relative motion; None forces an absolute move."""
        if self._last_pos_um is None:
            return None
        dx = x_um - self._last_pos_um[0]
        dy = y_um - self._last_pos_um[1]
        if abs(dx) < _REL_LIMIT_UM and abs(dy) < _REL_LIMIT_UM:
            return dx, dy
        return None

    def _handle_move_to(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle MoveToCommand - rapid move with laser off.

        Coordinates are translated to job-local space (job minimum
        maps to 0,0), matching the RDWorks reference file. Short
        moves are emitted relative (89/8A/8B, encode14 two's
        complement deltas); anything else is an absolute 88.
        """
        x_um, y_um = self._job_local_um(ops, idx)
        deltas = self._rel_deltas(x_um, y_um)
        if deltas is not None:
            dx, dy = deltas
            if dx == 0 and dy == 0:
                binary.append(b"\x89" + encode14(0) + encode14(0))
            elif dx == 0:
                binary.append(b"\x8b" + encode14(dy))
            elif dy == 0:
                binary.append(b"\x8a" + encode14(dx))
            else:
                binary.append(b"\x89" + encode14(dx) + encode14(dy))
            text.append(
                f"MOVE_REL dX:{dx / self.UM_PER_MM:.3f} "
                f"dY:{dy / self.UM_PER_MM:.3f}"
            )
        else:
            binary.append(b"\x88" + encode35(x_um) + encode35(y_um))
            text.append(
                f"MOVE_ABS X:{x_um / self.UM_PER_MM:.3f} "
                f"Y:{y_um / self.UM_PER_MM:.3f}"
            )
        self._last_pos_um = (x_um, y_um)

    def _handle_line_to(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle LineToCommand - cutting move with laser on.

        Coordinates are translated to job-local space (job minimum
        maps to 0,0), matching the RDWorks reference file. Short
        cuts are emitted relative (A9/AA/AB, encode14 two's
        complement deltas); anything else is an absolute A8. A
        zero-delta cut emits nothing.
        """
        x_um, y_um = self._job_local_um(ops, idx)
        deltas = self._rel_deltas(x_um, y_um)
        if deltas is not None:
            dx, dy = deltas
            if dx == 0 and dy == 0:
                text.append("CUT_REL dX:0.000 dY:0.000")
                return
            if dx == 0:
                binary.append(b"\xab" + encode14(dy))
            elif dy == 0:
                binary.append(b"\xaa" + encode14(dx))
            else:
                binary.append(b"\xa9" + encode14(dx) + encode14(dy))
            text.append(
                f"CUT_REL dX:{dx / self.UM_PER_MM:.3f} "
                f"dY:{dy / self.UM_PER_MM:.3f}"
            )
        else:
            binary.append(b"\xa8" + encode35(x_um) + encode35(y_um))
            text.append(
                f"CUT_ABS X:{x_um / self.UM_PER_MM:.3f} "
                f"Y:{y_um / self.UM_PER_MM:.3f}"
            )
        self._last_pos_um = (x_um, y_um)

    def _handle_arc_to(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle ArcToCommand - linearize arc to series of cuts."""
        end = ops.endpoint(idx)
        _i_val, _j_val, cw = ops.arc_params(idx)
        text.append(
            f"; ARC to ({end[0]:.3f}, {end[1]:.3f}) {'CW' if cw else 'CCW'}"
        )

        sub_ops = ops.linearize(idx, self.current_pos)
        for j in range(sub_ops.len()):
            sub_ct = sub_ops.command_type(j)
            if sub_ct == CommandType.LINE_TO:
                self._handle_line_to(sub_ops, j, binary, text)
            elif sub_ct == CommandType.SET_POWER:
                self._handle_set_power(sub_ops, j, binary, text)

    def _handle_scan_line(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle ScanLinePowerCommand - linearize to power/line segments.

        Per-sample power uses a single immediate-power command
        (C7 for laser 1) instead of the C6 01 + C6 02 min/max pair;
        the layer-start C6 01/02 min/max stay unchanged.
        """
        end = ops.endpoint(idx)
        power_mv = ops.scanline_data(idx)
        text.append(
            f"; SCAN_LINE to ({end[0]:.3f}, {end[1]:.3f}) "
            f"({len(power_mv)} samples)"
        )

        sub_ops = ops.linearize(idx, self.current_pos)
        for j in range(sub_ops.len()):
            sub_ct = sub_ops.command_type(j)
            if sub_ct == CommandType.LINE_TO:
                self._handle_line_to(sub_ops, j, binary, text)
            elif sub_ct == CommandType.SET_POWER:
                self._emit_immediate_power(sub_ops, j, binary, text)

    def _emit_immediate_power(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Emit a single immediate-power command for the active laser."""
        power = ops.power(idx)
        text.append(f"POWER {power * 100.0:.1f}")
        power_val = self._power_to_ruida(power)
        if self._imd_power == power_val:
            return
        self._imd_power = power_val
        opcode = _IMD_POWER_CMDS.get(self.active_laser, 0xC7)
        binary.append(bytes([opcode]) + encode14(power_val))

    @staticmethod
    def _grow(
        box: list[float] | None, points: list[tuple[float, float]]
    ) -> list[float]:
        """Extend an [min_x, min_y, max_x, max_y] box over points."""
        for px, py in points:
            if box is None:
                box = [px, py, px, py]
            else:
                box[0] = min(box[0], px)
                box[1] = min(box[1], py)
                box[2] = max(box[2], px)
                box[3] = max(box[3], py)
        assert box is not None
        return box

    @staticmethod
    def _overscan_points(
        points: list[tuple[float, float]],
        speed_mm_min: float | None,
        acceleration: float,
    ) -> list[tuple[float, float]]:
        """
        Extend a scan row by the overscan the controller will add.

        Ruida performs its own overscan (the driver reports
        native_overscan), so the ramp never appears in the op stream --
        yet the head really does travel it, and a job whose declared
        bounds stop at the content is rejected for exceeding them. The
        allowance is the distance needed to reach the scan speed,
        v^2 / 2a, applied past both ends along the scan direction.
        """
        if not speed_mm_min or len(points) < 2:
            return points
        distance = acceleration_run_up_mm(speed_mm_min, acceleration)
        if distance <= 0.0:
            return points
        (x0, y0), (x1, y1) = points[0], points[-1]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length == 0.0:
            return points
        pad_x = distance * dx / length
        pad_y = distance * dy / length
        return points + [
            (x0 - pad_x, y0 - pad_y),
            (x1 + pad_x, y1 + pad_y),
        ]

    def _collect_job_info(
        self, ops: Ops, machine: "Machine"
    ) -> tuple[tuple[int, int, int, int], list[dict], dict[int, int]]:
        """
        Pre-scan ops for the job prologue.

        This is the only site that decides where a part begins. It
        returns the job bounds in job-local micrometers (job minimum
        maps to 0,0), one entry per part, and the map from ops index
        to the part that opens there -- which the body walk obeys
        rather than counting for itself. Two walks with two sets of
        rules is how geometry came to be bound to another part's
        settings; see docs/process-ordering-audit.md PRO-02.

        A part is a settings combination, not a marker: a marker opens
        one, and so does a feed/power/air change that arrives after
        the current part has already cut something. A change that
        arrives before the part's first cut belongs to that part, so
        the last value before the first cut is the part's value.

        The bounds cover every motion the controller will make, not
        just the cutting geometry: travel moves count (``ops.rect()``
        excludes them), and raster rows carry the controller's own
        overscan. Under-declaring either makes the controller reject
        the job for exceeding its stated limits.
        """
        ox, oy = self.origin_um
        acceleration = float(machine.acceleration or 0)

        cutting = (
            CommandType.LINE_TO,
            CommandType.ARC_TO,
            CommandType.SCAN_LINE,
        )
        motion = cutting + (CommandType.MOVE_TO,)
        settings = (
            CommandType.SET_FEED_RATE,
            CommandType.SET_POWER,
            CommandType.SET_AIR_ASSIST,
        )

        parts: list[dict] = []
        opens: dict[int, int] = {}
        current: dict | None = None
        cur_uid: str | None = None
        cur_speed: float | None = None
        cur_travel: float | None = None
        cur_power: float | None = None
        cur_air: bool = False
        pos: tuple[float, float] | None = None
        job_box: list[float] | None = None

        def open_part(index: int) -> dict:
            """Start a part here, and record where the body must too."""
            nonlocal current
            current = {
                "uid": cur_uid,
                "speed": cur_speed,
                "travel": cur_travel,
                "power": cur_power,
                "air": cur_air,
                "bounds": None,
                "has_cut": False,
            }
            opens[index] = len(parts)
            parts.append(current)
            return current

        for i in range(ops.len()):
            ct = ops.command_type(i)
            if ct == CommandType.LAYER_START:
                cur_uid = ops.layer_uid(i)
                open_part(i)
            elif ct == CommandType.LAYER_END:
                current = None
                cur_uid = None
            elif ct in settings:
                if ct == CommandType.SET_FEED_RATE:
                    cur_speed = ops.rate(i)
                elif ct == CommandType.SET_POWER:
                    cur_power = ops.power(i)
                else:
                    cur_air = ops.air_assist(i) == AirAssistMode.ON
                if current is None:
                    continue
                if current["has_cut"]:
                    # The part below has already cut at its own
                    # settings; these are somebody else's.
                    open_part(i)
                else:
                    current["speed"] = cur_speed
                    current["power"] = cur_power
                    current["air"] = cur_air
            elif ct == CommandType.SET_RAPID_RATE:
                cur_travel = ops.rate(i)
                # Rapids are not a settings combination of their own:
                # a travel change never opens a part, it just joins
                # the one being built.
                if current is not None and not current["has_cut"]:
                    current["travel"] = cur_travel
            elif ct in motion:
                end = ops.endpoint(i)
                points = [(end[0], end[1])]
                if pos is not None:
                    points.insert(0, pos)
                if ct == CommandType.SCAN_LINE:
                    points = self._overscan_points(
                        points, cur_speed, acceleration
                    )
                job_box = self._grow(job_box, points)
                if current is not None:
                    current["bounds"] = self._grow(current["bounds"], points)
                    if ct in cutting:
                        current["has_cut"] = True
                pos = (end[0], end[1])

        if job_box is None:
            job_box = [0.0, 0.0, 0.0, 0.0]
        bounds = (
            self._mm_to_um(job_box[0]) - ox,
            self._mm_to_um(job_box[1]) - oy,
            self._mm_to_um(job_box[2]) - ox,
            self._mm_to_um(job_box[3]) - oy,
        )

        parts, opens = self._drop_empty_parts(parts, opens)

        if not parts:
            parts.append(
                {
                    "uid": None,
                    "speed": cur_speed,
                    "travel": cur_travel,
                    "power": cur_power,
                    "air": cur_air,
                    "bounds": None,
                }
            )

        result = []
        for part in parts:
            pb = part["bounds"]
            if pb is None:
                part_bounds = bounds
            else:
                part_bounds = (
                    self._mm_to_um(pb[0]) - ox,
                    self._mm_to_um(pb[1]) - oy,
                    self._mm_to_um(pb[2]) - ox,
                    self._mm_to_um(pb[3]) - oy,
                )
            power = part["power"] or 0.0
            result.append(
                {
                    "uid": part["uid"],
                    "speed": part["speed"] or 0.0,
                    "travel": part["travel"] or 0.0,
                    "power": power,
                    "min_power": self._layer_min_power(part["uid"], power),
                    "air": part["air"],
                    "mode": _DEFAULT_PART_MODE,
                    "bounds": part_bounds,
                }
            )
        return bounds, result, opens

    @staticmethod
    def _drop_empty_parts(
        parts: list[dict], opens: dict[int, int]
    ) -> tuple[list[dict], dict[int, int]]:
        """
        Forget the parts that have no motion at all, and renumber.

        A marker the assembler emitted but never filled would
        otherwise get a header block, a body block and a seat in the
        CA 22 count -- a part the controller selects, sets up, and
        finds nothing in.
        """
        keep = [n for n, part in enumerate(parts) if part["bounds"]]
        if len(keep) == len(parts):
            return parts, opens
        renumbered = {old: new for new, old in enumerate(keep)}
        return (
            [parts[old] for old in keep],
            {
                index: renumbered[old]
                for index, old in opens.items()
                if old in renumbered
            },
        )

    def _handle_job_start(
        self,
        ops: Ops,
        machine: "Machine",
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """
        Handle JobStartCommand - emit the Ruida job prologue.

        The prologue structurally matches the RDWorks ground-truth
        file for this controller: reference point selection, process
        start, job-local bounds (job minimum maps to 0,0), then
        per-layer part settings. Commands with unknown meaning are
        replayed with the reference file's constant payloads when
        follow_reference is enabled.

        The reference point is always the anchor (D8 12), independent
        of the machine's stored WCS.
        """
        ref_point_cmd = REF_POINT_COMMANDS[JOB_REF_POINT]
        logger.info(
            f"Job ref point: {JOB_REF_POINT} (D8 {ref_point_cmd[1]:02X})"
        )

        rect = ops.rect()
        # Job-local (0, 0) is the start corner of the bounding box --
        # the corner the operator says the head is standing on -- so
        # the job lands where the head already is.
        dx, dy = machine.job_placement_offset(
            rect[2] - rect[0], rect[3] - rect[1]
        )
        self.origin_um = (
            self._mm_to_um(rect[0] - dx),
            self._mm_to_um(rect[1] - dy),
        )
        bounds, layers, opens = self._collect_job_info(ops, machine)
        min_x, min_y, max_x, max_y = bounds
        self._layers = layers
        self._part_opens = opens
        self._planned = True
        self._part = -1

        z5 = encode35(0)
        binary.append(ref_point_cmd)
        if self.follow_reference:
            binary.append(_REF_E7_32)
        binary.append(b"\xf0")
        binary.append(b"\xf1\x02\x00")
        if self.follow_reference:
            binary.append(_REF_E7_3B)
        binary.append(b"\xd8\x00")
        binary.append(b"\xe7\x06" + z5 + z5)
        binary.append(b"\xe7\x38\x00")
        binary.append(b"\xe7\x03" + encode35(min_x) + encode35(min_y))
        binary.append(b"\xe7\x07" + encode35(max_x) + encode35(max_y))
        binary.append(b"\xe7\x50" + encode35(min_x) + encode35(min_y))
        binary.append(b"\xe7\x51" + encode35(max_x) + encode35(max_y))
        binary.append(
            b"\xe7\x04" + encode14(1) + encode14(1) + encode14(0) * 5
        )
        binary.append(b"\xe7\x05\x00")

        for part, layer in enumerate(layers):
            part_b = bytes([part])
            speed_um = self._speed_to_um_s(layer["speed"])
            min14 = encode14(self._power_to_ruida(layer["min_power"]))
            max14 = encode14(self._power_to_ruida(layer["power"]))
            lmin_x, lmin_y, lmax_x, lmax_y = layer["bounds"]
            binary.append(b"\xc9\x04" + part_b + encode35(speed_um))
            if self.follow_reference:
                binary.append(b"\xc6\x65" + part_b + _REF_C6_65_VALUE)
            binary.append(b"\xc6\x31" + part_b + min14)
            binary.append(b"\xc6\x32" + part_b + max14)
            binary.append(b"\xc6\x41" + part_b + min14)
            binary.append(b"\xc6\x42" + part_b + max14)
            binary.append(b"\xca\x06" + part_b + z5)
            # CA 41 declares the part's work mode, whose shape is
            # known -- unlike the payloads above it, which are
            # replayed verbatim because their meaning is not. It is a
            # property of the job, so it is not gated on the replay.
            binary.append(b"\xca\x41" + part_b + bytes([layer["mode"]]))
            binary.append(
                b"\xe7\x52" + part_b + encode35(lmin_x) + encode35(lmin_y)
            )
            binary.append(
                b"\xe7\x53" + part_b + encode35(lmax_x) + encode35(lmax_y)
            )
            if self.follow_reference:
                binary.append(
                    b"\xe7\x61" + part_b + encode35(lmin_x) + encode35(lmin_y)
                )
                binary.append(
                    b"\xe7\x62" + part_b + encode35(lmax_x) + encode35(lmax_y)
                )

        binary.append(b"\xca\x22" + bytes([len(layers) - 1]))
        binary.append(b"\xe7\x54\x00" + z5)
        binary.append(b"\xe7\x54\x01" + z5)
        binary.append(b"\xe7\x55\x00" + z5)
        binary.append(b"\xe7\x55\x01" + z5)

        if self.follow_reference:
            one14 = encode14(1)
            w35 = encode35(max_x)
            h35 = encode35(max_y)
            neg_w35 = encode35(-max_x)
            binary.append(b"\xf1\x03" + z5 + z5)
            binary.append(b"\xf1\x00\x00")
            binary.append(b"\xf1\x01\x00")
            binary.append(b"\xf2\x00\x00")
            binary.append(b"\xf2\x03" + z5 + z5)
            binary.append(b"\xf2\x04" + w35 + h35)
            binary.append(b"\xf2\x05" + one14 + one14 + neg_w35 + h35)
            binary.append(b"\xf2\x06" + z5 + z5)
            binary.append(b"\xf2\x07\x00")
            binary.append(b"\xf2\x08" + neg_w35 + h35)
            binary.append(b"\xe7\x0a" + z5)
            binary.append(b"\xea\x00")
            binary.append(b"\xe7\x60\x00\x00")
            binary.append(b"\xe3\x00")
            binary.append(b"\xe7\x0b\x00")
            binary.append(b"\xe7\x13" + z5 + z5)
            binary.append(b"\xe7\x17" + w35 + h35)
            binary.append(b"\xe7\x23" + z5 + z5)
            binary.append(b"\xe7\x24\x00")
            binary.append(b"\xe7\x37" + neg_w35 + h35)
            binary.append(b"\xe7\x08" + one14 + one14 + neg_w35 + h35)

        text.append(f"; Job Start - Ref Point: {JOB_REF_POINT}")

    def _handle_job_end(
        self,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """
        Handle JobEndCommand - emit the Ruida job tail.

        Matches the RDWorks ground-truth file: EB, E7 00, then the
        E5 05 file checksum (sum of every payload byte of every
        command before the E5 05 command itself, plus 0xD7), then the
        D7 end-of-file marker.
        """
        if self.follow_reference:
            binary.append(b"\xe4")
        binary.append(b"\xeb")
        binary.append(b"\xe7\x00")
        if self.follow_reference:
            binary.append(_REF_DA_01_0620)
        running_sum = sum(sum(chunk) for chunk in binary)
        binary.append(b"\xe5\x05" + encode35(running_sum + 0xD7))
        binary.append(b"\xd7")
        text.append("; Job End")

    def _settings_for(self, part: int) -> dict:
        """
        The pre-scanned settings for one part, by index.

        The pre-scan nominated this index, so it always has an entry.
        A miss means the plan and the walk have come apart, which is
        how a whole job came to run on one step's settings, so it is
        reported rather than papered over.
        """
        if 0 <= part < len(self._layers):
            return self._layers[part]

        self._warn_unresolved_part(part)
        return _no_settings()

    def _warn_unresolved_part(self, part: int) -> None:
        """Report a part the job prologue never declared."""
        logger.warning(
            f"Ruida: no settings for part {part}; falling back to none. "
            f"The prologue declared {len(self._layers)} part(s), "
            f"opening at ops indices {sorted(self._part_opens)}."
        )

    def _open_part(self, part: int, binary: list[bytes]) -> None:
        """
        Emit one part's body block, at an index the pre-scan chose.

        Matches the RDWorks ground-truth file: work mode, part index,
        laser device, air assist, speeds, delays and powers, then
        CA 03 / CA 10 before the first motion command. Every setting
        the part needs is restated here, so the geometry that follows
        cannot inherit anything from the part before it.
        """
        self._part = part
        layer = self._settings_for(part)
        part_b = bytes([part & 0xFF])
        speed_um = self._speed_to_um_s(layer["speed"])
        min14 = encode14(self._power_to_ruida(layer["min_power"]))
        max14 = encode14(self._power_to_ruida(layer["power"]))

        # Nothing this part emits may still be suppressed by what the
        # part before it emitted. Clearing _last_pos_um is what makes
        # the first move after the CA 02 absolute, which the DLL does
        # by calling RD_SetFirstMove from RD_wSetLayerNum.
        self._reset_emission_state()

        binary.append(b"\xca\x01" + bytes([layer["mode"]]))
        binary.append(b"\xca\x02" + part_b)
        binary.append(b"\xca\x01\x30")
        binary.append(
            _LASER_DEVICE_CMDS.get(self.active_laser, b"\xca\x01\x10")
        )
        binary.append(b"\xca\x01\x13" if layer["air"] else b"\xca\x01\x12")
        binary.append(b"\xc9\x02" + encode35(speed_um))
        if layer["travel"]:
            # The part's rapids, so a job no longer inherits the axis
            # speed the job before it left on the controller.
            binary.append(
                b"\xc9\x03" + encode35(self._speed_to_um_s(layer["travel"]))
            )
        binary.append(b"\xc6\x12" + encode35(0))
        binary.append(b"\xc6\x13" + encode35(0))
        binary.append(b"\xc6\x50" + encode14(0x1FFF))
        binary.append(b"\xc6\x51" + encode14(0x1FFF))
        binary.append(b"\xc6\x01" + min14)
        binary.append(b"\xc6\x02" + max14)
        binary.append(b"\xc6\x21" + min14)
        binary.append(b"\xc6\x22" + max14)
        binary.append(_REF_CA_03)
        binary.append(b"\xca\x10" + bytes([self.active_laser - 1]))

        # Record what the block just emitted, so nothing in the part
        # body repeats it.
        self.cut_speed = layer["speed"]
        self.travel_speed = layer["travel"]
        self.power = layer["power"]
        self._min_power = layer["min_power"]
        self.air_assist = layer["air"]
        self._laser_selected = self.active_laser
        self._in_part = True
        logger.info(
            f"Part {part} ({layer['uid']}): "
            f"speed {layer['speed'] / self.SECONDS_PER_MINUTE:.1f} mm/s "
            f"power {layer['min_power'] * 100:.0f}/"
            f"{layer['power'] * 100:.0f}% "
            f"mode {layer['mode']}"
        )

    def _handle_layer_start(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle LayerStartCommand - text marker only.

        The body block itself is emitted by _open_part, at whichever
        indices the job pre-scan nominated -- a marker is one of them,
        but no longer the only one.
        """
        text.append(f"; --- Layer {ops.layer_uid(idx)[:8]} ---")

    def _handle_layer_end(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle LayerEndCommand - text marker only.

        The reference file has no command between a layer's last cut
        and the next layer's body block (or the job tail).
        """
        self._in_part = False
        text.append("; --- End Layer ---")

    def _handle_workpiece_start(
        self,
        ops: Ops,
        idx: int,
        text: list[str],
    ) -> None:
        """Handle WorkpieceStartCommand - mark workpiece beginning."""
        uid = ops.workpiece_uid(idx)
        text.append(f"; --- Workpiece {uid[:8]} ---")

    def _handle_workpiece_end(
        self,
        ops: Ops,
        idx: int,
        text: list[str],
    ) -> None:
        """Handle WorkpieceEndCommand - mark workpiece end."""
        text.append("; --- End Workpiece ---")

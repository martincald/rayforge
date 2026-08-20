"""
Ruida Encoder - Converts Ops commands to Ruida binary protocol.

Produces both binary output for the controller and human-readable
text representation for UI display.
"""

import logging
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
        self._layers: list[dict] = []
        self._part: int = -1
        self._laser_selected: int | None = None
        self._last_pos_um: tuple[int, int] | None = None
        self._imd_power: int | None = None

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
        self.power = None
        self.cut_speed = None
        self.travel_speed = None
        self.air_assist = False
        self.current_pos = (0.0, 0.0, 0.0)
        self.active_laser = 1
        self.origin_um = (0, 0)
        self._layers = []
        self._part = -1
        self._laser_selected = None
        self._last_pos_um = None
        self._imd_power = None

    def _mm_to_um(self, mm: float) -> int:
        """Convert millimeters to micrometers."""
        return int(mm * self.UM_PER_MM)

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
        if self.power is not None and power == self.power:
            text.append(f"POWER {power_percent:.1f}")
            return
        self.power = power
        power14 = encode14(self._power_to_ruida(power))

        laser_cmds = {
            1: (b"\xc6\x01", b"\xc6\x02"),
            2: (b"\xc6\x21", b"\xc6\x22"),
            3: (b"\xc6\x05", b"\xc6\x06"),
            4: (b"\xc6\x07", b"\xc6\x08"),
        }
        min_cmd, max_cmd = laser_cmds.get(self.active_laser, laser_cmds[1])
        binary.append(min_cmd + power14)
        binary.append(max_cmd + power14)
        text.append(f"POWER {power_percent:.1f}")

    def _handle_set_cut_speed(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """Handle SetCutSpeedCommand - set cutting speed in mm/s."""
        speed = ops.rate(idx)
        if self.cut_speed is not None and speed == self.cut_speed:
            text.append(f"SPEED {speed:.1f}")
            return
        self.cut_speed = speed
        speed_um = self._mm_to_um(speed)
        binary.append(b"\xc9\x02" + encode35(speed_um))
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

        Travel speed is a controller-side setting (G0 velocity); no
        command is emitted so the cut speed is not overwritten.
        Per-primitive C9 03/C9 05 travel speed was audited and is
        intentionally not emitted: the RDWorks reference file
        contains neither.
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
            self.active_laser = laser_head.tool_number

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

    def _collect_job_info(
        self, ops: Ops
    ) -> tuple[tuple[int, int, int, int], list[dict]]:
        """
        Pre-scan ops for the job prologue.

        Returns job bounds in job-local micrometers (job minimum maps
        to 0,0) and one entry per layer with the layer's speed (mm/s),
        power (normalized), air assist state and bounds (um).
        Jobs without layer markers yield a single implicit layer.
        """
        min_x, min_y, max_x, max_y = ops.rect()
        ox, oy = self.origin_um
        bounds = (
            self._mm_to_um(min_x) - ox,
            self._mm_to_um(min_y) - oy,
            self._mm_to_um(max_x) - ox,
            self._mm_to_um(max_y) - oy,
        )

        cutting = (
            CommandType.LINE_TO,
            CommandType.ARC_TO,
            CommandType.SCAN_LINE,
        )
        motion = cutting + (CommandType.MOVE_TO,)

        layers: list[dict] = []
        current: dict | None = None
        cur_speed: float | None = None
        cur_power: float | None = None
        cur_air: bool = False
        pos: tuple[float, float] | None = None

        for i in range(ops.len()):
            ct = ops.command_type(i)
            if ct == CommandType.LAYER_START:
                current = {
                    "speed": cur_speed,
                    "power": cur_power,
                    "air": cur_air,
                    "bounds": None,
                    "explicit_speed": False,
                    "explicit_power": False,
                    "explicit_air": False,
                }
                layers.append(current)
            elif ct == CommandType.LAYER_END:
                current = None
            elif ct == CommandType.SET_FEED_RATE:
                cur_speed = ops.rate(i)
                if current is not None and not current["explicit_speed"]:
                    current["speed"] = cur_speed
                    current["explicit_speed"] = True
            elif ct == CommandType.SET_POWER:
                cur_power = ops.power(i)
                if current is not None and not current["explicit_power"]:
                    current["power"] = cur_power
                    current["explicit_power"] = True
            elif ct == CommandType.SET_AIR_ASSIST:
                cur_air = ops.air_assist(i) == AirAssistMode.ON
                if current is not None and not current["explicit_air"]:
                    current["air"] = cur_air
                    current["explicit_air"] = True
            elif ct in motion:
                end = ops.endpoint(i)
                if ct in cutting and current is not None:
                    points = [end] if pos is None else [pos, end]
                    lb = current["bounds"]
                    for px, py in ((p[0], p[1]) for p in points):
                        if lb is None:
                            lb = [px, py, px, py]
                        else:
                            lb[0] = min(lb[0], px)
                            lb[1] = min(lb[1], py)
                            lb[2] = max(lb[2], px)
                            lb[3] = max(lb[3], py)
                    current["bounds"] = lb
                pos = (end[0], end[1])

        if not layers:
            layers.append(
                {
                    "speed": cur_speed,
                    "power": cur_power,
                    "air": cur_air,
                    "bounds": None,
                }
            )

        result = []
        for layer in layers:
            lb = layer["bounds"]
            if lb is None:
                layer_bounds = bounds
            else:
                layer_bounds = (
                    self._mm_to_um(lb[0]) - ox,
                    self._mm_to_um(lb[1]) - oy,
                    self._mm_to_um(lb[2]) - ox,
                    self._mm_to_um(lb[3]) - oy,
                )
            result.append(
                {
                    "speed": layer["speed"] or 0.0,
                    "power": layer["power"] or 0.0,
                    "air": layer["air"],
                    "bounds": layer_bounds,
                }
            )
        return bounds, result

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

        Raises:
            ValueError: If active_wcs is not a valid Ruida reference point
        """
        active_wcs = machine.active_wcs
        if active_wcs not in REF_POINT_COMMANDS:
            raise ValueError(
                f"Unknown WCS slot '{active_wcs}'. "
                f"Valid options: {', '.join(REF_POINT_COMMANDS.keys())}"
            )

        rect = ops.rect()
        self.origin_um = (
            self._mm_to_um(rect[0]),
            self._mm_to_um(rect[1]),
        )
        bounds, layers = self._collect_job_info(ops)
        min_x, min_y, max_x, max_y = bounds
        self._layers = layers
        self._part = -1

        z5 = encode35(0)
        binary.append(REF_POINT_COMMANDS[active_wcs])
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
            speed_um = self._mm_to_um(layer["speed"])
            power14 = encode14(self._power_to_ruida(layer["power"]))
            lmin_x, lmin_y, lmax_x, lmax_y = layer["bounds"]
            binary.append(b"\xc9\x04" + part_b + encode35(speed_um))
            if self.follow_reference:
                binary.append(b"\xc6\x65" + part_b + _REF_C6_65_VALUE)
            binary.append(b"\xc6\x31" + part_b + power14)
            binary.append(b"\xc6\x32" + part_b + power14)
            binary.append(b"\xc6\x41" + part_b + power14)
            binary.append(b"\xc6\x42" + part_b + power14)
            binary.append(b"\xca\x06" + part_b + z5)
            if self.follow_reference:
                binary.append(b"\xca\x41" + part_b + b"\x00")
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

        text.append(f"; Job Start - Ref Point: {active_wcs}")

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

    def _handle_layer_start(
        self,
        ops: Ops,
        idx: int,
        binary: list[bytes],
        text: list[str],
    ) -> None:
        """
        Handle LayerStartCommand - emit the per-layer body block.

        Matches the RDWorks ground-truth file: layer prop commands,
        part index, laser device, air assist, speed, delays and
        powers, then CA 03 / CA 10 before the first motion command.
        Layer settings come from the job pre-scan so the block is
        complete before any motion.
        """
        uid = ops.layer_uid(idx)
        self._part += 1
        part = self._part
        if part < len(self._layers):
            layer = self._layers[part]
        else:
            layer = {"speed": 0.0, "power": 0.0, "air": False}
        part_b = bytes([part & 0xFF])
        speed_um = self._mm_to_um(layer["speed"])
        power14 = encode14(self._power_to_ruida(layer["power"]))

        binary.append(b"\xca\x01\x00")
        binary.append(b"\xca\x02" + part_b)
        binary.append(b"\xca\x01\x30")
        binary.append(
            _LASER_DEVICE_CMDS.get(self.active_laser, b"\xca\x01\x10")
        )
        binary.append(b"\xca\x01\x13" if layer["air"] else b"\xca\x01\x12")
        binary.append(b"\xc9\x02" + encode35(speed_um))
        binary.append(b"\xc6\x12" + encode35(0))
        binary.append(b"\xc6\x13" + encode35(0))
        binary.append(b"\xc6\x50" + encode14(0x1FFF))
        binary.append(b"\xc6\x51" + encode14(0x1FFF))
        binary.append(b"\xc6\x01" + power14)
        binary.append(b"\xc6\x02" + power14)
        binary.append(b"\xc6\x21" + power14)
        binary.append(b"\xc6\x22" + power14)
        binary.append(_REF_CA_03)
        binary.append(b"\xca\x10" + bytes([self.active_laser - 1]))

        self.cut_speed = layer["speed"]
        self.power = layer["power"]
        self.air_assist = layer["air"]
        self._laser_selected = self.active_laser
        # Layer boundary: first motion of a layer must be absolute
        # and immediate power must be re-emitted.
        self._last_pos_um = None
        self._imd_power = None
        text.append(f"; --- Layer {uid[:8]} ---")

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

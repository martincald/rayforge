"""
Extensive test suite for the RuidaEncoder.

Tests cover:
- Individual command encoding
- Binary output verification
- Text representation generation
- Op map correctness
- Edge cases and error handling
- Serialization of EncodedOutput
"""

from pathlib import Path

import pytest
from raygeo.ops import Ops
from raygeo.ops.state import AirAssistMode

from rayforge.core.doc import Doc
from rayforge.machine.driver.ruida.ruida_encoder import (
    RuidaEncoder,
    build_rd_bytes,
    commands_to_rd_bytes,
    export_rd,
)
from rayforge.machine.driver.ruida.ruida_util import encode14, encode35
from rayforge.machine.models.laser import Laser
from rayforge.pipeline.encoder.base import EncodedOutput, MachineCodeOpMap

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "rdworks_reference.rd"


@pytest.fixture
def encoder():
    """Provides a fresh RuidaEncoder instance."""
    return RuidaEncoder()


@pytest.fixture
def mock_machine(isolated_machine):
    """Provides a machine with multiple laser heads for testing."""
    laser1 = Laser()
    laser1.uid = "laser-1"
    laser1.tool_number = 0

    laser2 = Laser()
    laser2.uid = "laser-2"
    laser2.tool_number = 1

    isolated_machine.heads.clear()
    isolated_machine.add_head(laser1)
    isolated_machine.add_head(laser2)

    isolated_machine.active_wcs = "MACHINE"

    return isolated_machine


@pytest.fixture
def doc():
    """Provides a fresh Doc instance."""
    return Doc()


class TestRuidaEncoderBasics:
    """Basic encoder functionality tests."""

    def test_encode_returns_encoded_output(self, encoder, mock_machine, doc):
        """Verify encode() returns an EncodedOutput instance."""
        ops = Ops()
        result = encoder.encode(ops, mock_machine, doc)

        assert isinstance(result, EncodedOutput)
        assert isinstance(result.text, str)
        assert isinstance(result.op_map, MachineCodeOpMap)
        assert isinstance(result.driver_data, dict)

    def test_empty_ops_produces_empty_output(self, encoder, mock_machine, doc):
        """Empty Ops should produce empty commands and text."""
        ops = Ops()
        result = encoder.encode(ops, mock_machine, doc)

        assert result.driver_data["commands"] == []
        assert result.text == ""
        assert result.op_map.op_count == 0
        assert result.op_map.line_count == 0

    def test_commands_in_driver_data(self, encoder, mock_machine, doc):
        """Commands should be stored in driver_data['commands']."""
        ops = Ops()
        ops.set_power(0.5)
        result = encoder.encode(ops, mock_machine, doc)

        assert "commands" in result.driver_data
        assert isinstance(result.driver_data["commands"], list)
        assert all(
            isinstance(cmd, bytes) for cmd in result.driver_data["commands"]
        )
        assert len(result.driver_data["commands"]) > 0

    def test_encoder_state_resets_between_encodes(
        self, encoder, mock_machine, doc
    ):
        """Each encode() call should reset internal state."""
        ops1 = Ops()
        ops1.set_power(0.5)
        encoder.encode(ops1, mock_machine, doc)

        assert encoder.power == 0.5

        ops2 = Ops()
        ops2.set_power(0.8)
        result2 = encoder.encode(ops2, mock_machine, doc)

        assert encoder.power == 0.8
        assert result2.op_map.span_for_op(0) == (0, 1)


class TestSetPowerCommand:
    """Tests for SetPowerCommand encoding."""

    def test_power_zero(self, encoder, mock_machine, doc):
        """Zero power should encode to 0."""
        ops = Ops()
        ops.set_power(0.0)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary == (
            b"\xc6\x01" + encode14(0) + b"\xc6\x02" + encode14(0)
        )
        assert "POWER 0.0" in result.text

    def test_power_half(self, encoder, mock_machine, doc):
        """50% power should encode to 8191 (half of 16383)."""
        ops = Ops()
        ops.set_power(0.5)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        power14 = encode14(int(0.5 * 16383))
        assert binary == b"\xc6\x01" + power14 + b"\xc6\x02" + power14
        assert "POWER 50.0" in result.text

    def test_power_full(self, encoder, mock_machine, doc):
        """100% power should encode to 16383 (max 14-bit value)."""
        ops = Ops()
        ops.set_power(1.0)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        power14 = encode14(16383)
        assert binary == b"\xc6\x01" + power14 + b"\xc6\x02" + power14
        assert "POWER 100.0" in result.text

    def test_power_precision(self, encoder, mock_machine, doc):
        """Power should maintain precision in text output."""
        ops = Ops()
        ops.set_power(0.123)
        result = encoder.encode(ops, mock_machine, doc)

        assert "POWER 12.3" in result.text

    def test_power_with_different_lasers(self, encoder, mock_machine, doc):
        """Power command should use correct byte for active laser."""
        ops = Ops()
        ops.set_head("laser-2")
        ops.set_power(0.5)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        lines = result.text.split("\n")

        assert b"\xc6\x21" in binary
        assert b"\xc6\x22" in binary
        assert "LASER 2" in lines[0]
        assert "POWER 50.0" in lines[1]


class TestSetCutSpeedCommand:
    """Tests for SetCutSpeedCommand encoding."""

    def test_speed_encoding(self, encoder, mock_machine, doc):
        """Cut speed is stored in mm/min and encoded as um/s."""
        ops = Ops()
        ops.set_feed_rate(6000)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary == b"\xc9\x02" + encode35(100000)
        assert "SPEED 6000.0" in result.text

    def test_speed_fractional(self, encoder, mock_machine, doc):
        """A speed that does not divide evenly still converts once."""
        ops = Ops()
        ops.set_feed_rate(50)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary == b"\xc9\x02" + encode35(833)
        assert "SPEED 50.0" in result.text

    def test_speed_zero(self, encoder, mock_machine, doc):
        """Zero speed should encode correctly."""
        ops = Ops()
        ops.set_feed_rate(0)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary == b"\xc9\x02" + encode35(0)
        assert "SPEED 0.0" in result.text


class TestSetTravelSpeedCommand:
    """Tests for SetTravelSpeedCommand encoding."""

    def test_travel_speed_emits_no_command(self, encoder, mock_machine, doc):
        """Travel speed must not overwrite the cut speed (C9 02)."""
        ops = Ops()
        ops.set_rapid_rate(500)
        result = encoder.encode(ops, mock_machine, doc)

        assert result.driver_data["commands"] == []
        assert "TRAVEL_SPEED 500.0" in result.text

    def test_travel_speed_updates_state(self, encoder, mock_machine, doc):
        """Travel speed should update encoder state."""
        ops = Ops()
        ops.set_rapid_rate(300)
        encoder.encode(ops, mock_machine, doc)

        assert encoder.travel_speed == 300


class TestAirAssistCommands:
    """Tests for air assist commands."""

    def test_enable_air_assist(self, encoder, mock_machine, doc):
        """Enable air assist should send correct command."""
        ops = Ops()
        ops.set_air_assist(AirAssistMode.ON)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert b"\xca\x01\x13" in binary
        assert "AIR_ASSIST ON" in result.text

    def test_disable_air_assist(self, encoder, mock_machine, doc):
        """Disable air assist should send correct command."""
        ops = Ops()
        ops.set_air_assist(AirAssistMode.ON)
        ops.set_air_assist(AirAssistMode.OFF)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert b"\xca\x01\x13" in binary
        assert b"\xca\x01\x12" in binary
        lines = result.text.split("\n")
        assert "AIR_ASSIST ON" in lines[0]
        assert "AIR_ASSIST OFF" in lines[1]

    def test_air_assist_no_redundant_commands(
        self, encoder, mock_machine, doc
    ):
        """Should not emit redundant air assist commands."""
        ops = Ops()
        ops.set_air_assist(AirAssistMode.ON)
        ops.set_air_assist(AirAssistMode.ON)
        ops.set_air_assist(AirAssistMode.ON)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        on_count = binary.count(b"\xca\x01\x13")
        assert on_count == 1

    def test_air_assist_state_tracking(self, encoder, mock_machine, doc):
        """Air assist state should be tracked correctly."""
        ops = Ops()
        ops.set_air_assist(AirAssistMode.ON)
        ops.set_air_assist(AirAssistMode.ON)
        ops.set_air_assist(AirAssistMode.OFF)
        ops.set_air_assist(AirAssistMode.OFF)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary.count(b"\xca\x01\x13") == 1
        assert binary.count(b"\xca\x01\x12") == 1


class TestSetLaserCommand:
    """Tests for laser selection command."""

    def test_select_laser_1(self, encoder, mock_machine, doc):
        """Select laser 1 should emit correct command."""
        ops = Ops()
        ops.set_head("laser-1")
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary == b"\xca\x01\x10"
        assert "LASER 1" in result.text

    def test_select_laser_2(self, encoder, mock_machine, doc):
        """Select laser 2 should emit correct command."""
        ops = Ops()
        ops.set_head("laser-2")
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary == b"\xca\x01\x11"
        assert "LASER 2" in result.text

    def test_select_unknown_laser_defaults_to_1(
        self, encoder, mock_machine, doc
    ):
        """Unknown laser UID should default to laser 1."""
        ops = Ops()
        ops.set_head("nonexistent-laser")
        result = encoder.encode(ops, mock_machine, doc)

        assert encoder.active_laser == 1
        assert "LASER 1" in result.text


class TestMoveToCommand:
    """Tests for rapid move (travel) command."""

    def test_move_to_origin(self, encoder, mock_machine, doc):
        """Move to origin should encode correctly."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        x_um = int(0.0 * 1000)
        y_um = int(0.0 * 1000)
        assert binary == b"\x88" + encode35(x_um) + encode35(y_um)
        assert "MOVE_ABS X:0.000 Y:0.000" in result.text

    def test_move_to_positive_coords(self, encoder, mock_machine, doc):
        """Move to positive coordinates should encode correctly."""
        ops = Ops()
        ops.move_to(100.5, 200.25, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        x_um = int(100.5 * 1000)
        y_um = int(200.25 * 1000)
        assert binary == b"\x88" + encode35(x_um) + encode35(y_um)
        assert "MOVE_ABS X:100.500 Y:200.250" in result.text

    def test_move_to_updates_position(self, encoder, mock_machine, doc):
        """Move command should update current position."""
        ops = Ops()
        ops.move_to(50.0, 75.0, 0.0)
        encoder.encode(ops, mock_machine, doc)

        assert encoder.current_pos == (50.0, 75.0, 0.0)


class TestLineToCommand:
    """Tests for cutting move command."""

    def test_line_to_simple(self, encoder, mock_machine, doc):
        """Simple line cut should encode correctly."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(50.0, 100.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        lines = result.text.split("\n")
        assert "MOVE_ABS X:0.000 Y:0.000" in lines[0]
        assert "CUT_ABS X:50.000 Y:100.000" in lines[1]

    def test_line_to_updates_position(self, encoder, mock_machine, doc):
        """Line command should update current position."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(25.0, 50.0, 0.0)
        encoder.encode(ops, mock_machine, doc)

        assert encoder.current_pos == (25.0, 50.0, 0.0)

    def test_multiple_line_commands(self, encoder, mock_machine, doc):
        """Multiple consecutive line commands should encode correctly."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(10.0, 0.0, 0.0)
        ops.line_to(10.0, 10.0, 0.0)
        ops.line_to(0.0, 10.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        lines = result.text.split("\n")
        assert len(lines) == 4
        assert "MOVE_ABS X:0.000 Y:0.000" in lines[0]
        assert "CUT_ABS X:10.000 Y:0.000" in lines[1]
        assert "CUT_ABS X:10.000 Y:10.000" in lines[2]
        assert "CUT_ABS X:0.000 Y:10.000" in lines[3]


class TestArcToCommand:
    """Tests for arc command (linearized to line segments)."""

    def test_arc_linearizes_to_lines(self, encoder, mock_machine, doc):
        """Arc should be linearized into line segments."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        ops.arc_to(10.0, 0.0, 5.0, 0.0, clockwise=True)
        result = encoder.encode(ops, mock_machine, doc)

        lines = result.text.split("\n")
        assert any("; ARC" in line for line in lines)
        cut_lines = [line for line in lines if "CUT_" in line]
        assert len(cut_lines) >= 1

    def test_arc_updates_position(self, encoder, mock_machine, doc):
        """Arc command should update current position."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        ops.arc_to(10.0, 0.0, 5.0, 0.0, clockwise=True)
        encoder.encode(ops, mock_machine, doc)

        assert encoder.current_pos == (10.0, 0.0, 0.0)


class TestScanLinePowerCommand:
    """Tests for scan line (raster) command."""

    def test_scan_line_linearizes(self, encoder, mock_machine, doc):
        """Scan line should linearize into power and line commands."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        power_values = bytearray([0, 128, 255, 128, 0])
        ops.scan_to(5.0, 0.0, 0.0, power_values)
        result = encoder.encode(ops, mock_machine, doc)

        lines = result.text.split("\n")
        assert any("; SCAN_LINE" in line for line in lines)
        assert any("POWER" in line for line in lines)

    def test_scan_line_updates_position(self, encoder, mock_machine, doc):
        """Scan line command should update current position."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        power_values = bytearray([128, 128])
        ops.scan_to(2.0, 0.0, 0.0, power_values)
        encoder.encode(ops, mock_machine, doc)

        assert encoder.current_pos == (2.0, 0.0, 0.0)

    def test_scan_line_emits_immediate_power(self, encoder, mock_machine, doc):
        """Per-sample power uses C7 immediate power, not C6 01/02."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        power_values = bytearray([0, 128, 255])
        ops.scan_to(3.0, 0.0, 0.0, power_values)
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        imd = [c for c in commands if c[0] == 0xC7]
        assert imd
        assert all(len(c) == 3 for c in imd)
        assert not any(c[:2] in (b"\xc6\x01", b"\xc6\x02") for c in commands)


class TestJobMarkers:
    """Tests for job start/end markers."""

    def test_job_start(self, encoder, mock_machine, doc):
        """Job start should emit the job prologue."""
        ops = Ops()
        ops.job_start()
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        assert commands[0] == b"\xd8\x12"
        assert commands[1] == bytes.fromhex("e73201502024100150202410")
        assert commands[2] == b"\xf0"
        assert commands[3] == b"\xf1\x02\x00"
        assert commands[4] == b"\xe7\x3b\x41"
        assert commands[5] == b"\xd8\x00"
        assert commands[-1] == (
            b"\xe7\x08" + encode14(1) + encode14(1) + encode35(0) + encode35(0)
        )
        assert "; Job Start - Ref Point: REF0" in result.text

    def test_job_end(self, encoder, mock_machine, doc):
        """Job end should emit the tail with checksum and EOF marker."""
        ops = Ops()
        ops.job_end()
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        assert commands[0] == b"\xe4"
        assert commands[1] == b"\xeb"
        assert commands[2] == b"\xe7\x00"
        assert commands[3][:4] == b"\xda\x01\x06\x20"
        prior_sum = sum(sum(c) for c in commands[:4])
        assert commands[4] == b"\xe5\x05" + encode35(prior_sum + 0xD7)
        assert commands[-1] == b"\xd7"
        assert "; Job End" in result.text

    def test_full_job_structure(self, encoder, mock_machine, doc):
        """Full job should have proper structure."""
        ops = Ops()
        ops.job_start()
        ops.set_power(0.5)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(10.0, 10.0, 0.0)
        ops.job_end()
        result = encoder.encode(ops, mock_machine, doc)

        lines = result.text.split("\n")
        assert "Job Start" in lines[0]
        assert lines[-1] == "; Job End"
        assert b"".join(result.driver_data["commands"]).startswith(b"\xd8\x12")
        assert b"".join(result.driver_data["commands"]).endswith(b"\xd7")


class TestLayerMarkers:
    """Tests for layer start/end markers."""

    def test_layer_start(self, encoder, mock_machine, doc):
        """Layer start should emit the body block and text marker."""
        ops = Ops()
        ops.layer_start("test-layer-123")
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        assert commands[0] == b"\xca\x01\x00"
        assert commands[1] == b"\xca\x02\x00"
        binary = b"".join(commands)
        assert b"\xc9\x02" in binary
        assert b"\xca\x10\x00" in binary
        assert "; --- Layer test-lay ---" in result.text

    def test_layer_end(self, encoder, mock_machine, doc):
        """Layer end should emit a text marker only."""
        ops = Ops()
        ops.layer_end("test-layer-456")
        result = encoder.encode(ops, mock_machine, doc)

        assert result.driver_data["commands"] == []
        assert "; --- End Layer ---" in result.text


class TestWorkpieceMarkers:
    """Tests for workpiece start/end markers."""

    def test_workpiece_start(self, encoder, mock_machine, doc):
        """Workpiece start should emit text marker only."""
        ops = Ops()
        ops.workpiece_start("workpiece-abc")
        result = encoder.encode(ops, mock_machine, doc)

        assert b"".join(result.driver_data["commands"]) == b""
        assert "; --- Workpiece workpiec ---" in result.text

    def test_workpiece_end(self, encoder, mock_machine, doc):
        """Workpiece end should emit text marker only."""
        ops = Ops()
        ops.workpiece_end("workpiece-xyz")
        result = encoder.encode(ops, mock_machine, doc)

        assert b"".join(result.driver_data["commands"]) == b""
        assert "; --- End Workpiece ---" in result.text


class TestOpMapGeneration:
    """Tests for MachineCodeOpMap generation."""

    def test_single_command_mapping(self, encoder, mock_machine, doc):
        """Single command should have correct op_map."""
        ops = Ops()
        ops.set_power(0.5)
        result = encoder.encode(ops, mock_machine, doc)

        assert result.op_map.span_for_op(0) == (0, 1)
        assert result.op_map.op_for_line(0) == 0

    def test_multi_line_command_mapping(self, encoder, mock_machine, doc):
        """Command producing multiple lines should map correctly."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        ops.arc_to(10.0, 0.0, 5.0, 0.0, clockwise=True)
        result = encoder.encode(ops, mock_machine, doc)

        assert result.op_map.op_count == 2
        assert result.op_map.span_for_op(0)[1] >= 1
        assert result.op_map.span_for_op(1)[1] >= 1

    def test_marker_command_has_text_mapping(self, encoder, mock_machine, doc):
        """Marker commands with text output should map to line."""
        ops = Ops()
        ops.job_start()
        result = encoder.encode(ops, mock_machine, doc)

        # Job start produces a text line, so op_map should have (0, 1)
        assert result.op_map.span_for_op(0) == (0, 1)

    def test_sequential_commands_mapping(self, encoder, mock_machine, doc):
        """Sequential commands should have sequential line numbers."""
        ops = Ops()
        ops.set_power(0.5)
        ops.set_feed_rate(100)
        ops.move_to(0.0, 0.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        assert result.op_map.span_for_op(0) == (0, 1)
        assert result.op_map.span_for_op(1) == (1, 1)
        assert result.op_map.span_for_op(2) == (2, 1)

        for line_num in range(3):
            assert result.op_map.op_for_line(line_num) == line_num


class TestComplexJobs:
    """Tests for complex job scenarios."""

    def test_square_cut(self, encoder, mock_machine, doc):
        """A simple square cut should encode correctly."""
        ops = Ops()
        ops.job_start()
        ops.set_power(0.8)
        ops.set_feed_rate(200)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(10.0, 0.0, 0.0)
        ops.line_to(10.0, 10.0, 0.0)
        ops.line_to(0.0, 10.0, 0.0)
        ops.line_to(0.0, 0.0, 0.0)
        ops.job_end()
        result = encoder.encode(ops, mock_machine, doc)

        lines = result.text.split("\n")
        assert len(lines) >= 9
        assert "Job Start" in lines[0]
        assert lines[-1] == "; Job End"

        cut_lines = [line for line in lines if "CUT_ABS" in line]
        assert len(cut_lines) == 4

    def test_multi_layer_job(self, encoder, mock_machine, doc):
        """Multi-layer job should encode correctly."""
        ops = Ops()
        ops.job_start()

        ops.layer_start("layer-1")
        ops.set_power(0.5)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(10.0, 0.0, 0.0)
        ops.layer_end("layer-1")

        ops.layer_start("layer-2")
        ops.set_power(1.0)
        ops.move_to(0.0, 10.0, 0.0)
        ops.line_to(10.0, 10.0, 0.0)
        ops.layer_end("layer-2")

        ops.job_end()
        result = encoder.encode(ops, mock_machine, doc)

        text = result.text
        assert "; --- Layer layer-1 ---" in text
        assert "; --- Layer layer-2 ---" in text
        assert text.count("; --- End Layer ---") == 2

    def test_air_assist_toggle(self, encoder, mock_machine, doc):
        """Air assist toggle during job should work correctly."""
        ops = Ops()
        ops.set_air_assist(AirAssistMode.ON)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(10.0, 0.0, 0.0)
        ops.set_air_assist(AirAssistMode.OFF)
        ops.move_to(20.0, 0.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        lines = result.text.split("\n")
        assert "AIR_ASSIST ON" in lines[0]
        on_idx = lines.index(
            next(line for line in lines if "AIR_ASSIST ON" in line)
        )
        off_idx = lines.index(
            next(line for line in lines if "AIR_ASSIST OFF" in line)
        )
        assert on_idx < off_idx


class TestCoordinateConversion:
    """Tests for coordinate conversion (mm to µm)."""

    def test_mm_to_um_conversion(self, encoder, mock_machine, doc):
        """Coordinates should be converted from mm to µm."""
        ops = Ops()
        ops.move_to(1.0, 1.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        x_um = int(1.0 * 1000)
        y_um = int(1.0 * 1000)
        assert encode35(x_um) in binary
        assert encode35(y_um) in binary

    def test_large_coordinates(self, encoder, mock_machine, doc):
        """Large coordinates should encode correctly."""
        ops = Ops()
        ops.move_to(1000.0, 2000.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        x_um = int(1000.0 * 1000)
        y_um = int(2000.0 * 1000)
        assert encode35(x_um) in binary
        assert encode35(y_um) in binary

    def test_fractional_coordinates(self, encoder, mock_machine, doc):
        """Fractional coordinates should maintain precision."""
        ops = Ops()
        ops.move_to(0.001, 0.001, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        x_um = int(0.001 * 1000)
        y_um = int(0.001 * 1000)
        assert encode35(x_um) in binary
        assert encode35(y_um) in binary


class TestBinaryCommandStructure:
    """Tests for verifying binary command structure."""

    def test_move_command_structure(self, encoder, mock_machine, doc):
        """Move command should have 0x88 prefix + 10 bytes of coords."""
        ops = Ops()
        ops.move_to(100.0, 200.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary[0] == 0x88
        assert len(binary) == 11

    def test_cut_command_structure(self, encoder, mock_machine, doc):
        """Cut command should have 0xA8 prefix + 10 bytes of coords."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(50.0, 75.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        cut_cmd = binary[11:]
        assert cut_cmd[0] == 0xA8
        assert len(cut_cmd) == 11

    def test_speed_command_structure(self, encoder, mock_machine, doc):
        """Speed command should have 0xC9 0x02 prefix."""
        ops = Ops()
        ops.set_feed_rate(100)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary[0:2] == b"\xc9\x02"

    def test_power_command_structure(self, encoder, mock_machine, doc):
        """Power emits C6 min/max pair, 4 bytes each."""
        ops = Ops()
        ops.set_power(0.5)
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        assert len(commands) == 2
        assert commands[0][:2] == b"\xc6\x01"
        assert commands[1][:2] == b"\xc6\x02"
        assert all(len(cmd) == 4 for cmd in commands)


class TestRelativeMotionEncoding:
    """Golden tests for relative/absolute motion command selection."""

    def test_signed14_matches_fixture_example(self):
        """Fixture ground truth: a9 7b 4f 00 15 has dx=-561um."""
        assert encode14(-561) == b"\x7b\x4f"

    def test_small_square_uses_relative_cuts(self, encoder, mock_machine, doc):
        """A <8mm square yields AA/AB axis cuts and A9 diagonals."""
        ops = Ops()
        ops.move_to(10.0, 10.0, 0.0)
        ops.line_to(15.0, 10.0, 0.0)
        ops.line_to(15.0, 15.0, 0.0)
        ops.line_to(10.0, 10.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        assert commands[0] == b"\x88" + encode35(10000) + encode35(10000)
        assert commands[1] == b"\xaa" + encode14(5000)
        assert commands[2] == b"\xab" + encode14(5000)
        assert commands[3] == b"\xa9" + encode14(-5000) + encode14(-5000)

    def test_long_segment_uses_absolute_cut(self, encoder, mock_machine, doc):
        """A segment over 8.192mm falls back to absolute A8."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(8.3, 0.0, 0.0)
        ops.line_to(8.3, 1.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        assert commands[1] == b"\xa8" + encode35(8300) + encode35(0)
        # After the absolute emission, relative tracking resumes.
        assert commands[2] == b"\xab" + encode14(1000)

    def test_relative_travel_moves(self, encoder, mock_machine, doc):
        """Short travels use 89/8A/8B; zero-delta is 89 with zeros."""
        ops = Ops()
        ops.move_to(0.0, 0.0, 0.0)
        ops.move_to(5.0, 0.0, 0.0)
        ops.move_to(5.0, 3.0, 0.0)
        ops.move_to(2.0, 1.0, 0.0)
        ops.move_to(2.0, 1.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        assert commands[0] == b"\x88" + encode35(0) + encode35(0)
        assert commands[1] == b"\x8a" + encode14(5000)
        assert commands[2] == b"\x8b" + encode14(3000)
        assert commands[3] == b"\x89" + encode14(-3000) + encode14(-2000)
        assert commands[4] == b"\x89" + encode14(0) + encode14(0)

    def test_zero_delta_cut_emits_nothing(self, encoder, mock_machine, doc):
        """A cut to the current position emits no binary command."""
        ops = Ops()
        ops.move_to(1.0, 1.0, 0.0)
        ops.line_to(1.0, 1.0, 0.0)
        result = encoder.encode(ops, mock_machine, doc)

        assert result.driver_data["commands"] == [
            b"\x88" + encode35(1000) + encode35(1000)
        ]

    def test_layer_start_forces_absolute_motion(
        self, encoder, mock_machine, doc
    ):
        """The first motion of every layer is absolute."""
        ops = Ops()
        ops.job_start()
        ops.layer_start("layer-1")
        ops.set_power(0.5)
        ops.set_feed_rate(100)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(1.0, 0.0, 0.0)
        ops.layer_end("layer-1")
        ops.layer_start("layer-2")
        ops.set_power(1.0)
        ops.set_feed_rate(50)
        ops.move_to(1.0, 1.0, 0.0)
        ops.line_to(2.0, 1.0, 0.0)
        ops.layer_end("layer-2")
        ops.job_end()
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        moves = [c for c in commands if c[0] in (0x88, 0x89, 0x8A, 0x8B)]
        assert [c[0] for c in moves] == [0x88, 0x88]

    def test_mixed_abs_rel_checksum(self, encoder, mock_machine, doc):
        """E5 05 stays correct with mixed abs/rel motion streams."""
        ops = Ops()
        ops.job_start()
        ops.layer_start("layer-1")
        ops.set_power(0.5)
        ops.set_feed_rate(100)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(5.0, 0.0, 0.0)
        ops.line_to(5.0, 9.0, 0.0)
        ops.line_to(4.0, 8.0, 0.0)
        ops.layer_end("layer-1")
        ops.job_end()
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        opcodes = [c[0] for c in commands]
        assert 0xAA in opcodes
        assert 0xA8 in opcodes
        assert 0xA9 in opcodes
        e5_idx = next(
            i for i, c in enumerate(commands) if c[:2] == b"\xe5\x05"
        )
        stored = _decode_u35(commands[e5_idx][2:7])
        sum_before = sum(sum(c) for c in commands[:e5_idx])
        assert stored == sum_before + 0xD7
        assert commands[-1] == b"\xd7"


class TestSetFrequencyCommand:
    """Tests for SetFrequencyCommand encoding."""

    def test_frequency_encoding(self, encoder, mock_machine, doc):
        ops = Ops()
        ops.set_frequency(1000)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary[:2] == b"\xc6\x60"
        assert binary[2] == 0  # laser 1, zero-based
        assert binary[3] == 0  # layer 0
        assert binary[4:] == encode35(1000)
        assert "FREQUENCY 1000" in result.text

    def test_frequency_with_laser_2(self, encoder, mock_machine, doc):
        ops = Ops()
        ops.set_head("laser-2")
        ops.set_frequency(5000)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        freq_cmd = binary[binary.index(b"\xc6\x60") :]
        assert freq_cmd[2] == 1  # laser 2, zero-based
        assert "FREQUENCY 5000" in result.text

    def test_frequency_command_structure(self, encoder, mock_machine, doc):
        ops = Ops()
        ops.set_frequency(2000)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary[0] == 0xC6
        assert binary[1] == 0x60
        assert len(binary) == 9

    def test_frequency_zero_emits_nothing(self, encoder, mock_machine, doc):
        """An unconfigured (zero) frequency emits no C6 60."""
        ops = Ops()
        ops.set_frequency(0)
        result = encoder.encode(ops, mock_machine, doc)

        assert result.driver_data["commands"] == []


class TestSetPulseWidthCommand:
    """Tests for SetPulseWidthCommand encoding."""

    def test_pulse_width_encoding(self, encoder, mock_machine, doc):
        ops = Ops()
        ops.set_pulse_width(50)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary[:2] == b"\xc6\x10"
        assert binary[2:] == encode35(50)
        assert "PULSE_WIDTH 50.0" in result.text

    def test_pulse_width_command_structure(self, encoder, mock_machine, doc):
        ops = Ops()
        ops.set_pulse_width(25)
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert binary[0] == 0xC6
        assert binary[1] == 0x10
        assert len(binary) == 7

    def test_pulse_width_zero_emits_nothing(self, encoder, mock_machine, doc):
        """An unconfigured (zero) pulse width emits no C6 10."""
        ops = Ops()
        ops.set_pulse_width(0)
        result = encoder.encode(ops, mock_machine, doc)

        assert result.driver_data["commands"] == []


class TestJobPrologue:
    """Golden-bytes tests for the job prologue."""

    def test_one_layer_job_prologue_bytes(self, encoder, mock_machine, doc):
        """The prologue for a minimal one-layer job is byte-exact."""
        ops = Ops()
        ops.job_start()
        ops.layer_start("layer-1")
        ops.set_power(0.5)
        ops.set_feed_rate(100)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(10.0, 20.0, 0.0)
        ops.layer_end("layer-1")
        ops.job_end()
        result = encoder.encode(ops, mock_machine, doc)

        z5 = encode35(0)
        one14 = encode14(1)
        power14 = encode14(int(0.5 * 16383))
        w35 = encode35(10000)
        h35 = encode35(20000)
        neg_w35 = encode35(-10000)
        expected = [
            b"\xd8\x12",
            bytes.fromhex("e73201502024100150202410"),
            b"\xf0",
            b"\xf1\x02\x00",
            b"\xe7\x3b\x41",
            b"\xd8\x00",
            b"\xe7\x06" + z5 + z5,
            b"\xe7\x38\x00",
            b"\xe7\x03" + z5 + z5,
            b"\xe7\x07" + w35 + h35,
            b"\xe7\x50" + z5 + z5,
            b"\xe7\x51" + w35 + h35,
            b"\xe7\x04" + one14 + one14 + encode14(0) * 5,
            b"\xe7\x05\x00",
            b"\xc9\x04\x00" + encode35(1666),
            b"\xc6\x65\x00\x3d",
            b"\xc6\x31\x00" + power14,
            b"\xc6\x32\x00" + power14,
            b"\xc6\x41\x00" + power14,
            b"\xc6\x42\x00" + power14,
            b"\xca\x06\x00" + z5,
            b"\xca\x41\x00\x00",
            b"\xe7\x52\x00" + z5 + z5,
            b"\xe7\x53\x00" + w35 + h35,
            b"\xe7\x61\x00" + z5 + z5,
            b"\xe7\x62\x00" + w35 + h35,
            b"\xca\x22\x00",
            b"\xe7\x54\x00" + z5,
            b"\xe7\x54\x01" + z5,
            b"\xe7\x55\x00" + z5,
            b"\xe7\x55\x01" + z5,
            b"\xf1\x03" + z5 + z5,
            b"\xf1\x00\x00",
            b"\xf1\x01\x00",
            b"\xf2\x00\x00",
            b"\xf2\x03" + z5 + z5,
            b"\xf2\x04" + w35 + h35,
            b"\xf2\x05" + one14 + one14 + neg_w35 + h35,
            b"\xf2\x06" + z5 + z5,
            b"\xf2\x07\x00",
            b"\xf2\x08" + neg_w35 + h35,
            b"\xe7\x0a" + z5,
            b"\xea\x00",
            b"\xe7\x60\x00\x00",
            b"\xe3\x00",
            b"\xe7\x0b\x00",
            b"\xe7\x13" + z5 + z5,
            b"\xe7\x17" + w35 + h35,
            b"\xe7\x23" + z5 + z5,
            b"\xe7\x24\x00",
            b"\xe7\x37" + neg_w35 + h35,
            b"\xe7\x08" + one14 + one14 + neg_w35 + h35,
        ]

        commands = result.driver_data["commands"]
        assert commands[: len(expected)] == expected
        assert commands[-1] == b"\xd7"

    def test_multi_layer_prologue_has_one_part_per_layer(
        self, encoder, mock_machine, doc
    ):
        """Each layer gets its own part settings in the prologue."""
        ops = Ops()
        ops.job_start()
        ops.layer_start("layer-1")
        ops.set_power(0.5)
        ops.set_feed_rate(100)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(10.0, 0.0, 0.0)
        ops.layer_end("layer-1")
        ops.layer_start("layer-2")
        ops.set_power(1.0)
        ops.set_feed_rate(50)
        ops.move_to(0.0, 10.0, 0.0)
        ops.line_to(10.0, 10.0, 0.0)
        ops.layer_end("layer-2")
        ops.job_end()
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        speeds = [c for c in commands if c.startswith(b"\xc9\x04")]
        assert speeds == [
            b"\xc9\x04\x00" + encode35(1666),
            b"\xc9\x04\x01" + encode35(833),
        ]
        assert b"\xca\x22\x01" in commands


def _unswizzle_byte(b: int) -> int:
    """Unswizzle one byte with magic 0x88 (independent of ruida_util)."""
    b = (b - 1) & 0xFF
    b ^= 0x88
    b ^= b >> 7
    b ^= (b << 7) & 0xFF
    b ^= b >> 7
    return b


def _split_commands(data: bytes) -> list[bytes]:
    """Split a decoded stream into commands (MSB-set byte starts one)."""
    cmds: list[bytes] = []
    cur = bytearray()
    for b in data:
        if b >= 0x80 and cur:
            cmds.append(bytes(cur))
            cur = bytearray()
        cur.append(b)
    if cur:
        cmds.append(bytes(cur))
    return cmds


def _reference_commands() -> list[bytes]:
    """Decode the RDWorks ground-truth file into a command list."""
    raw = FIXTURE_PATH.read_bytes()
    return _split_commands(bytes(_unswizzle_byte(b) for b in raw))


def _decode_u35(data: bytes) -> int:
    value = 0
    for b in data:
        value = (value << 7) | (b & 0x7F)
    return value


_MOVE_OPS = {0x88, 0x89, 0x8A, 0x8B}
_CUT_OPS = {0xA8, 0xA9, 0xAA, 0xAB}
_SUB_OPS = {0xC6, 0xC9, 0xCA, 0xD8, 0xDA, 0xE5, 0xE7, 0xF1, 0xF2}


def _command_tokens(cmds: list[bytes]) -> list[str]:
    """
    Map commands to type tokens (opcode + sub-opcode).

    Motion commands are normalized to MOVE/CUT and consecutive runs
    collapsed, since the fixture's geometry differs from the test
    job's; everything else keeps opcode and sub-opcode (plus the
    argument byte for CA 01 prop commands).
    """
    tokens: list[str] = []
    for cmd in cmds:
        op = cmd[0]
        if op in _MOVE_OPS:
            token = "MOVE"
        elif op in _CUT_OPS:
            token = "CUT"
        elif op == 0xCA and len(cmd) >= 3 and cmd[1] == 0x01:
            token = f"CA 01 {cmd[2]:02X}"
        elif op in _SUB_OPS and len(cmd) >= 2:
            token = f"{op:02X} {cmd[1]:02X}"
        else:
            token = f"{op:02X}"
        if token in ("MOVE", "CUT") and tokens and tokens[-1] == token:
            continue
        tokens.append(token)
    return tokens


def _equivalent_job_ops() -> Ops:
    """A one-layer job equivalent to the fixture: ~20x20mm square,
    10 mm/s, 60% power, air assist on, offset from the origin so the
    job-local translation is exercised."""
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.6)
    ops.set_feed_rate(10)
    ops.set_air_assist(AirAssistMode.ON)
    ops.move_to(60.0, 40.0, 0.0)
    ops.line_to(80.0, 40.0, 0.0)
    ops.line_to(80.0, 60.0, 0.0)
    ops.line_to(60.0, 60.0, 0.0)
    ops.line_to(60.0, 40.0, 0.0)
    ops.layer_end("layer-1")
    ops.job_end()
    return ops


class TestRDWorksGroundTruth:
    """Golden tests against the RDWorks reference file."""

    def test_fixture_checksum_formula(self):
        """The fixture's E5 05 equals byte-sum-before plus 0xD7."""
        cmds = _reference_commands()
        e5_idx = next(i for i, c in enumerate(cmds) if c[:2] == b"\xe5\x05")
        stored = _decode_u35(cmds[e5_idx][2:7])
        sum_before = sum(sum(c) for c in cmds[:e5_idx])
        assert stored == sum_before + 0xD7
        assert cmds[-1] == b"\xd7"

    def test_command_type_sequence_matches_fixture(
        self, encoder, mock_machine, doc
    ):
        """Encoder output has the fixture's command-type sequence."""
        mock_machine.active_wcs = "REF0"
        result = encoder.encode(_equivalent_job_ops(), mock_machine, doc)
        ours = _command_tokens(result.driver_data["commands"])
        reference = _command_tokens(_reference_commands())
        assert ours == reference

    def test_job_local_bounds(self, encoder, mock_machine, doc):
        """Bounds and motion are translated so the job min is 0,0."""
        result = encoder.encode(_equivalent_job_ops(), mock_machine, doc)
        commands = result.driver_data["commands"]

        e7_03 = next(c for c in commands if c[:2] == b"\xe7\x03")
        e7_07 = next(c for c in commands if c[:2] == b"\xe7\x07")
        assert e7_03[2:] == encode35(0) + encode35(0)
        assert e7_07[2:] == encode35(20000) + encode35(20000)

        e7_52 = next(c for c in commands if c[:2] == b"\xe7\x52")
        e7_53 = next(c for c in commands if c[:2] == b"\xe7\x53")
        assert e7_52[2:] == b"\x00" + encode35(0) + encode35(0)
        assert e7_53[2:] == b"\x00" + encode35(20000) + encode35(20000)

        move = next(c for c in commands if c[0] == 0x88)
        assert move[1:] == encode35(0) + encode35(0)

    def test_own_stream_checksum(self, encoder, mock_machine, doc):
        """E5 05 arithmetic holds on the encoder's own stream."""
        result = encoder.encode(_equivalent_job_ops(), mock_machine, doc)
        commands = result.driver_data["commands"]
        e5_idx = next(
            i for i, c in enumerate(commands) if c[:2] == b"\xe5\x05"
        )
        stored = _decode_u35(commands[e5_idx][2:7])
        sum_before = sum(sum(c) for c in commands[:e5_idx])
        assert stored == sum_before + 0xD7
        assert commands[e5_idx + 1] == b"\xd7"
        assert commands[-1] == b"\xd7"

    def test_multi_layer_checksum(self, encoder, mock_machine, doc):
        """Independent sum matches E5 05 for a multi-layer job."""
        ops = Ops()
        ops.job_start()
        ops.layer_start("layer-1")
        ops.set_power(0.5)
        ops.set_feed_rate(100)
        ops.set_air_assist(AirAssistMode.ON)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(10.0, 0.0, 0.0)
        ops.layer_end("layer-1")
        ops.layer_start("layer-2")
        ops.set_power(1.0)
        ops.set_feed_rate(50)
        ops.set_air_assist(AirAssistMode.OFF)
        ops.move_to(0.0, 10.0, 0.0)
        ops.line_to(10.0, 10.0, 0.0)
        ops.layer_end("layer-2")
        ops.job_end()
        result = encoder.encode(ops, mock_machine, doc)

        commands = result.driver_data["commands"]
        e5_cmds = [c for c in commands if c[:2] == b"\xe5\x05"]
        assert len(e5_cmds) == 1
        e5_idx = commands.index(e5_cmds[0])
        stored = _decode_u35(e5_cmds[0][2:7])
        sum_before = sum(sum(c) for c in commands[:e5_idx])
        assert stored == sum_before + 0xD7
        assert commands[-1] == b"\xd7"


def _square_job_ops() -> Ops:
    """A one-layer square job for whole-blob tests."""
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.8)
    ops.set_feed_rate(200)
    ops.move_to(0.0, 0.0, 0.0)
    ops.line_to(10.0, 0.0, 0.0)
    ops.line_to(10.0, 10.0, 0.0)
    ops.line_to(0.0, 10.0, 0.0)
    ops.line_to(0.0, 0.0, 0.0)
    ops.layer_end("layer-1")
    ops.job_end()
    return ops


class TestBuildRdBytes:
    """Tests for the complete swizzled .rd blob builder."""

    def test_blob_is_swizzled_command_stream(self, mock_machine, doc):
        """The blob is the encoder's command stream, swizzled whole."""
        ops = _square_job_ops()
        blob = build_rd_bytes(ops, mock_machine, doc)
        encoded = RuidaEncoder().encode(ops, mock_machine, doc)
        commands = encoded.driver_data["commands"]

        assert blob == commands_to_rd_bytes(commands)
        unswizzled = bytes(_unswizzle_byte(b) for b in blob)
        assert unswizzled == b"".join(commands)

    def test_one_layer_square_structure_and_checksum(self, mock_machine, doc):
        """Unswizzled blob has the fixture structure; E5 05 matches an
        independently computed sum."""
        blob = build_rd_bytes(_square_job_ops(), mock_machine, doc)
        cmds = _split_commands(bytes(_unswizzle_byte(b) for b in blob))

        assert cmds[0] == b"\xd8\x12"
        assert cmds[-1] == b"\xd7"
        e5_idx = next(i for i, c in enumerate(cmds) if c[:2] == b"\xe5\x05")
        stored = _decode_u35(cmds[e5_idx][2:7])
        sum_before = sum(sum(c) for c in cmds[:e5_idx])
        assert stored == sum_before + 0xD7
        assert cmds[e5_idx + 1] == b"\xd7"

    def test_command_type_sequence_matches_fixture(self, mock_machine, doc):
        """Unswizzled blob keeps the fixture's command-type sequence."""
        mock_machine.active_wcs = "REF0"
        blob = build_rd_bytes(_equivalent_job_ops(), mock_machine, doc)
        cmds = _split_commands(bytes(_unswizzle_byte(b) for b in blob))
        assert _command_tokens(cmds) == _command_tokens(_reference_commands())

    def test_export_rd_writes_send_job_blob(self, tmp_path, mock_machine, doc):
        """export_rd writes exactly the blob send_job would transmit."""
        ops = _square_job_ops()
        path = tmp_path / "job.rd"
        export_rd(ops, mock_machine, doc, path)

        assert path.read_bytes() == build_rd_bytes(ops, mock_machine, doc)


class TestFrequencyAndPulseWidthInJob:
    """Tests for frequency/pulse_width within a full job."""

    def test_full_job_with_pwm(self, encoder, mock_machine, doc):
        ops = Ops()
        ops.job_start()
        ops.set_power(0.8)
        ops.set_feed_rate(200)
        ops.set_frequency(1000)
        ops.set_pulse_width(50)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(10.0, 10.0, 0.0)
        ops.job_end()
        result = encoder.encode(ops, mock_machine, doc)

        binary = b"".join(result.driver_data["commands"])
        assert b"\xc6\x60" in binary
        assert b"\xc6\x10" in binary
        text = result.text
        assert "FREQUENCY 1000" in text
        assert "PULSE_WIDTH 50.0" in text


def _raster_job_ops() -> Ops:
    """A one-layer raster job: two 20mm scan rows at 100 mm/s."""
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.5)
    ops.set_feed_rate(6000)  # 100 mm/s
    ops.move_to(10.0, 10.0, 0.0)
    ops.scan_to(30.0, 10.0, 0.0, bytearray([128] * 8))
    ops.move_to(10.0, 11.0, 0.0)
    ops.scan_to(30.0, 11.0, 0.0, bytearray([128] * 8))
    ops.layer_end("layer-1")
    ops.job_end()
    return ops


def _travelling_job_ops() -> Ops:
    """A cut job whose travel reaches past the cutting geometry."""
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.5)
    ops.set_feed_rate(600)
    ops.move_to(10.0, 10.0, 0.0)
    ops.line_to(20.0, 10.0, 0.0)
    ops.move_to(50.0, 40.0, 0.0)  # travel well outside the cut bbox
    ops.move_to(10.0, 10.0, 0.0)
    ops.layer_end("layer-1")
    ops.job_end()
    return ops


def _decode_s35(data: bytes) -> int:
    """A 35-bit Ruida value, read as signed."""
    value = _decode_u35(data)
    return value - (1 << 35) if value >= (1 << 34) else value


def _bounds(commands: list[bytes]) -> tuple[int, int, int, int]:
    """The declared doc bounds, job-local micrometers."""
    e7_03 = next(c for c in commands if c[:2] == b"\xe7\x03")
    e7_07 = next(c for c in commands if c[:2] == b"\xe7\x07")
    return (
        _decode_s35(e7_03[2:7]),
        _decode_s35(e7_03[7:12]),
        _decode_s35(e7_07[2:7]),
        _decode_s35(e7_07[7:12]),
    )


class TestDeclaredMotionExtent:
    """The declared bounds cover every motion, not just the content."""

    def test_raster_bounds_exceed_the_content_bbox(
        self, encoder, mock_machine, doc
    ):
        """
        The controller adds its own overscan to a scan row, so the
        declaration has to leave room for it or the job is rejected
        for exceeding its stated limits.
        """
        mock_machine.acceleration = 1000
        commands = encoder.encode(
            _raster_job_ops(), mock_machine, doc
        ).driver_data["commands"]

        min_x, min_y, max_x, max_y = _bounds(commands)
        # 100 mm/s at 1000 mm/s^2 needs 5 mm to reach speed, both ends.
        assert min_x == -5000
        assert max_x == 25000
        # The scan axis alone grows; across the rows nothing changes.
        assert (min_y, max_y) == (0, 1000)

    def test_raster_bounds_scale_with_the_profile_acceleration(
        self, encoder, mock_machine, doc
    ):
        """A machine that accelerates harder needs less run-up."""
        mock_machine.acceleration = 4000
        commands = encoder.encode(
            _raster_job_ops(), mock_machine, doc
        ).driver_data["commands"]

        min_x, _, max_x, _ = _bounds(commands)
        assert (min_x, max_x) == (-1250, 21250)

    def test_per_part_bounds_carry_the_overscan_too(
        self, encoder, mock_machine, doc
    ):
        mock_machine.acceleration = 1000
        commands = encoder.encode(
            _raster_job_ops(), mock_machine, doc
        ).driver_data["commands"]

        e7_52 = next(c for c in commands if c[:2] == b"\xe7\x52")
        e7_53 = next(c for c in commands if c[:2] == b"\xe7\x53")
        assert _decode_s35(e7_52[3:8]) == -5000
        assert _decode_s35(e7_53[3:8]) == 25000

    def test_checksum_still_holds_over_the_grown_bounds(
        self, encoder, mock_machine, doc
    ):
        mock_machine.acceleration = 1000
        commands = encoder.encode(
            _raster_job_ops(), mock_machine, doc
        ).driver_data["commands"]

        e5_idx = next(
            i for i, c in enumerate(commands) if c[:2] == b"\xe5\x05"
        )
        running = sum(sum(c) for c in commands[:e5_idx])
        assert commands[e5_idx][2:] == encode35(running + 0xD7)

    def test_travel_moves_count_toward_the_bounds(
        self, encoder, mock_machine, doc
    ):
        """ops.rect() drops travels; the head still goes there."""
        commands = encoder.encode(
            _travelling_job_ops(), mock_machine, doc
        ).driver_data["commands"]

        assert _bounds(commands) == (0, 0, 40000, 30000)

    def test_vector_only_bounds_are_unchanged(
        self, encoder, mock_machine, doc
    ):
        """A job whose travel stays inside the cuts declares the cuts."""
        commands = encoder.encode(
            _equivalent_job_ops(), mock_machine, doc
        ).driver_data["commands"]

        assert _bounds(commands) == (0, 0, 20000, 20000)

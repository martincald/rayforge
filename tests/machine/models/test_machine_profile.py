from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
import yaml
from raygeo.ops import Ops

from rayforge.config import BUILTIN_DEVICES_DIR
from rayforge.core.doc import Doc
from rayforge.machine.device.profile import DeviceProfile
from rayforge.machine.driver import get_driver_cls
from rayforge.machine.models.machine import Machine
from rayforge.shared import tasker

if TYPE_CHECKING:
    from rayforge.context import RayforgeContext


def _encode(ops, machine, doc):
    """Encode ops via the driver encoder (bypasses deleted encode_ops)."""
    driver_cls = get_driver_cls(machine.driver_name)
    encoder = driver_cls.create_encoder(machine)
    return encoder.encode(ops, machine, doc)


# The Carvera Air device profile (a Smoothieware/GRBL device) was removed
# along with the non-Ruida drivers. Its dialect is reconstructed here,
# using NoDeviceDriver, so the G-code generation behaviour it exercised
# stays covered.
_CARVERA_AIR_DEVICE_YAML = {
    "api_version": 1,
    "device": {"name": "Carvera Air"},
    "machine": {
        "driver": "NoDeviceDriver",
        "gcode_precision": 4,
        "axis_extents": [300.0, 200.0],
        "origin": "bottom_left",
        "max_travel_speed": 3000,
        "max_cut_speed": 3000,
        "home_on_start": True,
        "heads": [
            {
                "tool_number": 8888,
                "max_power": 1.0,
                "frame_power_percent": 1.0,
                "focus_power_percent": 1.0,
                "spot_size_mm": [0.1, 0.1],
            }
        ],
    },
}

_CARVERA_AIR_DIALECT_YAML = {
    "laser_on": "",
    "laser_off": "G1 S0",
    "focus_laser_on": "M3 S{power:.0f}",
    "tool_change": "T{tool_number}",
    "set_speed": "",
    "travel_move": "G0 X{x} Y{y} Z{z}{extra_cmd}",
    "linear_move": "G1 X{x} Y{y} Z{z}{extra_cmd}{s_command}{f_command}",
    "arc_cw": "G2 X{x} Y{y} Z{z}{extra_cmd} I{i} J{j}{s_command}{f_command}",
    "arc_ccw": "G3 X{x} Y{y} Z{z}{extra_cmd} I{i} J{j}{s_command}{f_command}",
    "bezier_cubic": "",
    "air_assist_on": "M8",
    "air_assist_off": "M9",
    "home_all": "$H",
    "home_axis": "G28 {axis_letter}0",
    "move_to": "G90 G0 X{x} Y{y}",
    "jog": "G91 G0 F{speed}",
    "clear_alarm": "M999",
    "set_wcs_offset": "G10 L20 P{p_num} X{x} Y{y} Z{z}",
    "probe_cycle": "G38.2 {axis_letter}{max_travel} F{feed_rate}",
    "dwell": "G4 P{seconds:.3f}",
    "preamble": [
        "M321",
        "G0Z0",
        "G00 {machine.active_wcs}",
        "M3",
        "G21 ; Set units to mm",
        "G90 ; Absolute positioning",
    ],
    "postscript": [
        "M5 ; Ensure laser is off",
        "G0 X0 Y0 ; Return to origin",
        ";USER END SCRIPT",
        "M322",
        ";USER END SCRIPT",
        "M2",
    ],
    "inject_wcs_after_preamble": False,
    "can_g0_with_speed": True,
    "omit_unchanged_coords": True,
    "continuous_laser_mode": False,
    "modal_feedrate": False,
}


@pytest_asyncio.fixture
async def carvera_air_machine(
    context_initializer: "RayforgeContext", tmp_path: Path
) -> "Machine":
    """Provides a Machine configured like the (removed) Carvera Air
    device profile."""
    device_dir = tmp_path / "carvera-air"
    device_dir.mkdir()
    (device_dir / "device.yaml").write_text(
        yaml.safe_dump(_CARVERA_AIR_DEVICE_YAML, sort_keys=False)
    )
    (device_dir / "dialect.yaml").write_text(
        yaml.safe_dump(_CARVERA_AIR_DIALECT_YAML, sort_keys=False)
    )
    pkg = DeviceProfile.from_path(device_dir)
    machine = pkg.create_machine(context_initializer)
    tasker.task_mgr.wait_until_settled(5000)
    return machine


@pytest.mark.asyncio
async def test_carvera_air_gcode_generation(carvera_air_machine: "Machine"):
    """
    Tests that a simple line move operation generates the correct G-code
    for the Carvera Air profile, including its custom dialect settings for
    preamble, postscript, and command templates.
    """
    # --- Arrange ---
    machine = carvera_air_machine
    ops = Ops()
    ops.job_start()
    ops.set_feed_rate(600)
    ops.set_power(0.5)
    ops.line_to(10.123, 20.456, 0)
    ops.job_end()
    doc = Doc()

    # --- Act ---
    gcode_str = _encode(ops, machine, doc).text

    # --- Assert ---
    # The Carvera profile specifies gcode_precision=4.
    # The dialect definition in the profile dictates the command format.
    expected_gcode = [
        # Preamble from profile's dialect_definition
        "M321",
        "G0Z0",
        "G00 G54",
        "M3",
        "G21 ; Set units to mm",
        "G90 ; Absolute positioning",
        # WCS is NOT emitted because inject_wcs_after_preamble=False
        # linear_move: "G1 X{x} Y{y} Z{z}{s_command}{f_command}"
        # The profile's laser head has max_power=1.0, so 50% power is S0.5.
        "G1 X10.123 Y20.456 Z0 S0.5 F600",
        # JobEndCommand triggers _laser_off, which is "G1 S0" for Carvera
        "G1 S0",
        # Postscript from profile's dialect_definition
        "M5 ; Ensure laser is off",
        "G0 X0 Y0 ; Return to origin",
        ";USER END SCRIPT",
        "M322",
        ";USER END SCRIPT",
        "M2",
        "",  # Final newline from G-code encoder's _finalize method
    ]

    assert gcode_str == "\n".join(expected_gcode)


@pytest.mark.asyncio
async def test_inject_wcs_after_preamble_flag(carvera_air_machine: "Machine"):
    """
    Tests that inject_wcs_after_preamble flag controls whether
    WCS is injected after the preamble.
    """
    from rayforge.machine.models.dialect import GcodeDialect

    # --- Arrange ---
    machine = carvera_air_machine
    ops = Ops()
    ops.job_start()
    ops.set_feed_rate(600)
    ops.set_power(0.5)
    ops.line_to(10.123, 20.456, 0)
    ops.job_end()
    doc = Doc()

    # --- Act: With inject_wcs_after_preamble=True (default) ---
    gcode_str = _encode(ops, machine, doc).text
    gcode_lines = gcode_str.split("\n")

    # --- Assert: WCS should be present ---
    # Carvera Air profile has "G00 G54" in preamble
    assert "G00 G54" in gcode_lines

    # --- Act: With inject_wcs_after_preamble=False ---
    # Create a custom dialect with the flag disabled
    custom_dialect = GcodeDialect(
        label="No WCS Dialect",
        description="Dialect without WCS injection",
        laser_on="",
        laser_off="",
        focus_laser_on="",
        tool_change="",
        set_speed="",
        travel_move="",
        linear_move="",
        arc_cw="",
        arc_ccw="",
        bezier_cubic="",
        air_assist_on="",
        air_assist_off="",
        home_all="",
        home_axis="",
        move_to="",
        jog="",
        clear_alarm="",
        set_wcs_offset="",
        probe_cycle="",
        preamble=["G21", "G90"],
        postscript=["M5"],
        inject_wcs_after_preamble=False,
    )
    machine.context.dialect_mgr.register(custom_dialect)
    machine.set_dialect_uid(custom_dialect.uid)

    gcode_str = _encode(ops, machine, doc).text
    gcode_lines = gcode_str.split("\n")

    # --- Assert: WCS should NOT be present ---
    assert "G54" not in gcode_lines


@pytest.mark.asyncio
async def test_builtin_devices_all_load():
    """All bundled device profiles can be loaded."""
    for d in sorted(BUILTIN_DEVICES_DIR.iterdir()):
        if d.is_dir():
            pkg = DeviceProfile.from_path(d)
            assert pkg.name
            if pkg.machine_config.driver:
                driver_cls = get_driver_cls(pkg.machine_config.driver)
                if driver_cls.uses_gcode:
                    assert pkg.dialect_config


@pytest.mark.asyncio
async def test_device_without_rotary_modules(
    context_initializer: "RayforgeContext",
):
    """Devices without rotary_modules create machines with none."""
    pkg = DeviceProfile.from_path(BUILTIN_DEVICES_DIR / "omtech-polar")
    machine = pkg.create_machine(context_initializer)
    tasker.task_mgr.wait_until_settled(5000)
    assert machine.rotary_modules == {}

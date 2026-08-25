"""One conversion, end to end, for every speed the Ruida encoder emits.

The model stores speeds in mm/min. The UI boundary converts once, and
the encoder converts once more into the micrometers per second the wire
carries. A speed set in mm/s must arrive on the controller unchanged.
"""

import pytest
from raygeo.ops import Ops

from rayforge.core.doc import Doc
from rayforge.machine.driver.ruida.ruida_encoder import RuidaEncoder
from rayforge.machine.driver.ruida.ruida_util import decode35
from rayforge.machine.models.laser import Laser
from rayforge.shared.units.definitions import get_unit


@pytest.fixture
def machine(isolated_machine):
    laser = Laser()
    laser.uid = "laser-1"
    laser.tool_number = 1
    isolated_machine.heads.clear()
    isolated_machine.add_head(laser)
    isolated_machine.active_wcs = "MACHINE"
    return isolated_machine


def _store_mm_s(speed_mm_s: float) -> int:
    """Put a speed through the single UI boundary conversion."""
    unit = get_unit("mm/s")
    assert unit is not None
    return int(unit.to_base(speed_mm_s))


def _one_layer_job(speed_mm_min: int) -> Ops:
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.5)
    ops.set_feed_rate(speed_mm_min)
    ops.move_to(0.0, 0.0, 0.0)
    ops.line_to(10.0, 0.0, 0.0)
    ops.layer_end("layer-1")
    ops.job_end()
    return ops


def _speeds(commands, opcode: bytes, payload_at: int) -> list[int]:
    return [
        decode35(c[payload_at : payload_at + 5])
        for c in commands
        if c.startswith(opcode)
    ]


@pytest.mark.parametrize(
    "display_mm_s, expected_um_s",
    [(10.0, 10000), (1.0, 1000), (20.0, 20000)],
)
def test_ui_speed_reaches_the_wire_unchanged(
    machine, display_mm_s, expected_um_s
):
    ops = _one_layer_job(_store_mm_s(display_mm_s))

    result = RuidaEncoder().encode(ops, machine, Doc())
    commands = result.driver_data["commands"]

    assert _speeds(commands, b"\xc9\x02", 2) == [expected_um_s]
    assert _speeds(commands, b"\xc9\x04", 3) == [expected_um_s]


def test_stored_unit_is_mm_per_minute(machine):
    """10 mm/s is stored as 600, and still lands as 10000 um/s."""
    assert _store_mm_s(10.0) == 600

    result = RuidaEncoder().encode(_one_layer_job(600), machine, Doc())
    commands = result.driver_data["commands"]

    assert _speeds(commands, b"\xc9\x02", 2) == [10000]


def test_body_speed_change_converts_once(machine):
    """A mid-layer speed change takes the same single conversion."""
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.5)
    ops.set_feed_rate(_store_mm_s(10.0))
    ops.move_to(0.0, 0.0, 0.0)
    ops.line_to(10.0, 0.0, 0.0)
    ops.set_feed_rate(_store_mm_s(40.0))
    ops.line_to(20.0, 0.0, 0.0)
    ops.layer_end("layer-1")
    ops.job_end()

    result = RuidaEncoder().encode(ops, machine, Doc())
    commands = result.driver_data["commands"]

    assert _speeds(commands, b"\xc9\x02", 2) == [10000, 40000]


@pytest.mark.parametrize("speed_mm_s", [0.1, 1000.0])
def test_speed_range_ends_survive_the_mm_min_boundary(machine, speed_mm_s):
    """
    The cut speed range is 0.1 - 1000 mm/s. Both ends have to reach the
    controller intact: mm/s to mm/min is the one lossy hop, and 0.1 mm/s
    is exactly 6 mm/min, so nothing gets rounded away.
    """
    stored = _store_mm_s(speed_mm_s)
    assert stored == round(speed_mm_s * 60)

    result = RuidaEncoder().encode(_one_layer_job(stored), machine, Doc())
    commands = result.driver_data["commands"]

    expected = round(speed_mm_s * 1000)
    assert _speeds(commands, b"\xc9\x02", 2) == [expected]
    assert _speeds(commands, b"\xc9\x04", 3) == [expected]

"""What the Go Scale and Cut Scale actions put on the wire.

Go Scale is plain interactive rapids: a speed and five moves, nothing
else, so no process starts and the laser cannot fire. Cut Scale is an
ordinary one-layer job around the same rectangle, and stays one.
"""

import pytest
import pytest_asyncio
from blinker import Signal

from rayforge.core.doc import Doc
from rayforge.machine.cmd import _cut_scale_ops
from rayforge.machine.driver.ruida.ruida_driver import RuidaDriver
from rayforge.machine.driver.ruida.ruida_encoder import RuidaEncoder
from rayforge.machine.driver.ruida.ruida_util import decode35, encode35
from rayforge.machine.models.laser import Laser
from rayforge.machine.models.machine import Machine

# Opcodes that cut, and the power commands a layer body emits.
CUT_OPCODES = (b"\xa8", b"\xa9", b"\xaa", b"\xab")
BODY_POWER = (b"\xc6\x01", b"\xc6\x02")


@pytest.fixture
def machine(isolated_machine):
    laser = Laser()
    laser.uid = "laser-1"
    isolated_machine.heads.clear()
    isolated_machine.add_head(laser)
    isolated_machine.active_wcs = "MACHINE"
    return isolated_machine


def _commands(ops, machine):
    return RuidaEncoder().encode(ops, machine, Doc()).driver_data["commands"]


class _ScaleClientSpy:
    """Records everything a Go Scale run sends."""

    def __init__(self, position=(0, 0)):
        self.commands: list[bytes] = []
        self.position = position
        self.state_changed = Signal()
        self.position_updated = Signal()

    async def disconnect(self):
        pass

    async def set_travel_speed(self, um_per_s: int):
        self.commands.append(b"\xc9\x02" + encode35(um_per_s))

    async def rapid_move_xy(self, x_um: int, y_um: int, light: bool = False):
        self.commands.append(b"\xd9\x10\x00" + encode35(x_um) + encode35(y_um))
        self.position = (x_um, y_um)

    async def stop_process(self):
        self.commands.append(b"\xd8\x01")

    async def read_position(self, timeout: float = 2.0):
        return self.position


def _corners(commands: list[bytes]) -> list[tuple[int, int]]:
    return [
        (decode35(c[3:8]), decode35(c[8:13]))
        for c in commands
        if c[:2] == b"\xd9\x10"
    ]


@pytest_asyncio.fixture
async def ruida_driver(lite_context):
    """A RuidaDriver with no transports; tests inject a client spy."""
    machine = Machine(lite_context)
    machine.driver_name = "RuidaDriver"
    lite_context.machine_mgr.add_machine(machine)
    driver = RuidaDriver(lite_context, machine)

    yield driver

    driver._client = None
    await driver.cleanup()
    await machine.shutdown()


class TestGoScale:
    """Go Scale traverses the outline with interactive rapids."""

    @pytest.mark.asyncio
    async def test_emits_one_speed_and_five_moves_only(self, ruida_driver):
        spy = _ScaleClientSpy(position=(0, 0))
        ruida_driver._client = spy

        await ruida_driver.trace_frame(100.0, 50.0)

        # The trace runs at the jog panel's speed but never exceeds
        # the profile's max travel speed.
        expected_mm_min = min(
            ruida_driver._jog_speed_mm_min,
            ruida_driver._machine.max_travel_speed
            or ruida_driver.DEFAULT_TRAVEL_SPEED,
        )
        assert spy.commands[0] == b"\xc9\x02" + encode35(
            int(expected_mm_min * 1000 / 60)
        )
        assert len(_corners(spy.commands)) == 5
        # A speed and five moves: nothing starts a process, and no
        # power command is ever sent.
        assert len(spy.commands) == 6
        assert b"\xd8\x00" not in spy.commands

    @pytest.mark.asyncio
    async def test_traces_at_the_jog_panel_speed(self, ruida_driver):
        """The panel's jog speed drives the trace, not a fixed one."""
        spy = _ScaleClientSpy(position=(0, 0))
        ruida_driver._client = spy
        # 40 mm/s, in the mm/min base units the jog panel pushes.
        await ruida_driver.set_jog_speed(40 * 60)

        await ruida_driver.trace_frame(100.0, 50.0)

        assert spy.commands[0] == b"\xc9\x02" + encode35(40000)

    @pytest.mark.asyncio
    async def test_corners_are_offset_from_the_start_position(
        self, ruida_driver
    ):
        spy = _ScaleClientSpy(position=(60000, 40000))
        ruida_driver._client = spy

        await ruida_driver.trace_frame(100.0, 50.0)

        assert _corners(spy.commands) == [
            (60000, 40000),
            (160000, 40000),
            (160000, 90000),
            (60000, 90000),
            (60000, 40000),
        ]

    @pytest.mark.asyncio
    async def test_cancel_stops_the_motion_and_resyncs(self, ruida_driver):
        spy = _ScaleClientSpy(position=(0, 0))
        ruida_driver._client = spy
        original = spy.rapid_move_xy

        async def cancel_after_second(x_um, y_um, light=False):
            await original(x_um, y_um, light=light)
            if len(_corners(spy.commands)) == 2:
                await ruida_driver.cancel_frame()

        spy.rapid_move_xy = cancel_after_second

        await ruida_driver.trace_frame(100.0, 50.0)

        assert _corners(spy.commands) == [(0, 0), (100000, 0)]
        assert b"\xd8\x01" in spy.commands
        assert ruida_driver._jog_busy is False


def test_cut_scale_cuts_four_segments(machine):
    ops = _cut_scale_ops(machine, 100.0, 50.0, 1200, 0.8)

    commands = _commands(ops, machine)

    cuts = [c for c in commands if c[:1] in CUT_OPCODES]
    assert len(cuts) == 4


def test_cut_scale_uses_one_layer(machine):
    ops = _cut_scale_ops(machine, 100.0, 50.0, 1200, 0.8)

    commands = _commands(ops, machine)

    assert b"\xca\x22\x00" in commands


def test_cut_scale_still_starts_a_process(machine):
    """Cut Scale fires, so the interlock must still apply to it."""
    ops = _cut_scale_ops(machine, 100.0, 50.0, 1200, 0.8)

    commands = _commands(ops, machine)

    assert b"\xd8\x00" in commands


def test_cut_scale_min_power_equals_max_power(machine):
    ops = _cut_scale_ops(machine, 100.0, 50.0, 1200, 0.8)

    commands = _commands(ops, machine)

    mins = [c[2:] for c in commands if c[:2] == b"\xc6\x01"]
    maxes = [c[2:] for c in commands if c[:2] == b"\xc6\x02"]
    assert mins and mins == maxes

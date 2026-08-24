"""The Ruida blobs the Go Scale and Cut Scale actions produce.

Go Scale must be incapable of firing the laser: the stream carries
travel moves and no power command at all. Cut Scale is an ordinary
one-layer job around the same rectangle.
"""

import pytest

from rayforge.core.doc import Doc
from rayforge.machine.cmd import _cut_scale_ops, _go_scale_ops
from rayforge.machine.driver.ruida.ruida_encoder import RuidaEncoder
from rayforge.machine.models.laser import Laser

# Opcodes that cut, and the power commands a layer body emits.
CUT_OPCODES = (b"\xa8", b"\xa9", b"\xaa", b"\xab")
BODY_POWER = (b"\xc6\x01", b"\xc6\x02")


@pytest.fixture
def machine(isolated_machine):
    laser = Laser()
    laser.uid = "laser-1"
    laser.tool_number = 1
    isolated_machine.heads.clear()
    isolated_machine.add_head(laser)
    isolated_machine.active_wcs = "MACHINE"
    return isolated_machine


def _commands(ops, machine):
    return RuidaEncoder().encode(ops, machine, Doc()).driver_data["commands"]


def _body(commands):
    """Everything after the prologue's last part-settings command."""
    starts = [
        i
        for i, c in enumerate(commands)
        if c.startswith((b"\xe7\x55", b"\xe7\x08"))
    ]
    return commands[max(starts) + 1 :] if starts else commands


def test_go_scale_body_has_no_cut_opcode(machine):
    commands = _commands(_go_scale_ops(machine, 100.0, 50.0), machine)

    cuts = [c for c in commands if c[:1] in CUT_OPCODES]
    assert cuts == []


def test_go_scale_body_has_no_power_command(machine):
    commands = _commands(_go_scale_ops(machine, 100.0, 50.0), machine)

    powers = [c for c in _body(commands) if c[:2] in BODY_POWER]
    assert powers == []


def test_go_scale_traverses_the_four_corners(machine):
    commands = _commands(_go_scale_ops(machine, 100.0, 50.0), machine)

    moves = [
        c for c in commands if c[:1] in (b"\x88", b"\x89", b"\x8a", b"\x8b")
    ]
    assert len(moves) == 5


def test_go_scale_anchors_at_the_ref_point(machine):
    commands = _commands(_go_scale_ops(machine, 100.0, 50.0), machine)

    assert commands[0] == b"\xd8\x12"


def test_cut_scale_cuts_four_segments(machine):
    ops = _cut_scale_ops(machine, 100.0, 50.0, 1200, 0.8)

    commands = _commands(ops, machine)

    cuts = [c for c in commands if c[:1] in CUT_OPCODES]
    assert len(cuts) == 4


def test_cut_scale_uses_one_layer(machine):
    ops = _cut_scale_ops(machine, 100.0, 50.0, 1200, 0.8)

    commands = _commands(ops, machine)

    assert b"\xca\x22\x00" in commands


def test_cut_scale_min_power_equals_max_power(machine):
    ops = _cut_scale_ops(machine, 100.0, 50.0, 1200, 0.8)

    commands = _commands(ops, machine)

    mins = [c[2:] for c in commands if c[:2] == b"\xc6\x01"]
    maxes = [c[2:] for c in commands if c[:2] == b"\xc6\x02"]
    assert mins and mins == maxes

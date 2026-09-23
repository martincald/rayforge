"""What the Go Scale and Cut Scale actions put on the wire.

Both are ordinary one-layer jobs around the job's bounding box, sent
through build_rd_bytes and send_job like any other. Go Scale's layer
has power 0 and nothing in it cuts: every corner is a travel move, at
the jog panel's speed, so the laser cannot fire. Cut Scale burns the
same rectangle.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from raygeo.ops import Ops

from swiftcut.core.doc import Doc
from swiftcut.machine.cmd import MachineCmd, _cut_scale_ops, _go_scale_ops
from swiftcut.machine.driver.ruida.ruida_encoder import RuidaEncoder
from swiftcut.machine.driver.ruida.ruida_util import (
    decode35,
    encode14,
    encode35,
)
from swiftcut.machine.models.laser import Laser
from swiftcut.pipeline.artifact import JobArtifact

# Opcodes that cut, and every command that carries a power.
CUT_OPCODES = (b"\xa8", b"\xa9", b"\xaa", b"\xab")
POWER_COMMANDS = (
    b"\xc6\x01",
    b"\xc6\x02",
    b"\xc6\x21",
    b"\xc6\x22",
)
PART_POWER_COMMANDS = (
    b"\xc6\x31",
    b"\xc6\x32",
    b"\xc6\x41",
    b"\xc6\x42",
)
TRAVEL_OPCODES = (b"\x88", b"\x89", b"\x8a", b"\x8b")

# 40 mm/s on the jog panel, in the mm/min base unit it hands over.
JOG_SPEED = 40 * 60


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


def _go_scale(machine):
    return _commands(_go_scale_ops(machine, 100.0, 50.0, JOG_SPEED), machine)


class TestGoScaleBlob:
    """Go Scale is a valid job that only travels."""

    def test_is_a_complete_job(self, machine):
        commands = _go_scale(machine)

        assert commands[0] == b"\xd8\x12"
        assert b"\xd8\x00" in commands
        assert b"\xeb" in commands
        assert commands[-2].startswith(b"\xe5\x05")
        assert commands[-1] == b"\xd7"

    def test_has_one_part(self, machine):
        commands = _go_scale(machine)

        assert b"\xca\x22\x00" in commands

    def test_has_no_cut_opcode(self, machine):
        commands = _go_scale(machine)

        cuts = [c for c in commands if c[:1] in CUT_OPCODES]
        assert cuts == []

    def test_every_power_is_zero(self, machine):
        commands = _go_scale(machine)

        body = [c[2:] for c in commands if c[:2] in POWER_COMMANDS]
        part = [c[3:] for c in commands if c[:2] in PART_POWER_COMMANDS]
        assert len(body) == 4 and len(part) == 4
        assert set(body) == set(part) == {encode14(0)}

    def test_travels_at_the_jog_panel_speed(self, machine):
        """The layer speed and its rapids are both the panel's."""
        commands = _go_scale(machine)

        um_per_s = encode35(40000)
        assert b"\xc9\x02" + um_per_s in commands
        assert b"\xc9\x03" + um_per_s in commands
        assert b"\xc9\x04\x00" + um_per_s in commands

    def test_traverses_the_four_corners(self, machine):
        commands = _go_scale(machine)

        moves = [
            (decode35(c[1:6]), decode35(c[6:11]))
            for c in commands
            if c[:1] in TRAVEL_OPCODES
        ]
        assert moves == [
            (0, 0),
            (100000, 0),
            (100000, 50000),
            (0, 50000),
            (0, 0),
        ]

    def test_declares_the_outline_as_its_bounds(self, machine):
        """Travel counts: the controller checks the head's real path."""
        commands = _go_scale(machine)

        high = next(c for c in commands if c.startswith(b"\xe7\x07"))
        assert (decode35(high[2:7]), decode35(high[7:12])) == (100000, 50000)


def _editor_with_outline(width: float, height: float):
    """An editor whose job artifact is a width x height rectangle."""
    ops = Ops()
    ops.move_to(0.0, 0.0, 0.0)
    ops.line_to(width, height, 0.0)
    artifact = JobArtifact(ops=ops, distance=ops.distance(), generation_id=1)
    editor = MagicMock()
    editor.pipeline.generate_job_artifact_async = AsyncMock(
        return_value=MagicMock()
    )
    store = editor.pipeline.artifact_store
    store.checkout_handle.return_value.__enter__.return_value = artifact
    return editor


async def _run_scheduled(editor):
    """Await the coroutine the last add_coroutine call scheduled."""
    factory = editor.task_manager.add_coroutine.call_args.args[0]
    await factory(None)


class TestGoScaleRunsAsAJob:
    """MachineCmd sends Go Scale down the ordinary job path."""

    @pytest.mark.asyncio
    async def test_the_outline_goes_out_as_a_travel_only_job(self, machine):
        machine.driver_name = "RuidaDriver"
        editor = _editor_with_outline(100.0, 50.0)
        cmd = MachineCmd(editor)

        with patch.object(
            MachineCmd, "_execute_monitored_job", new=AsyncMock()
        ) as execute:
            cmd.run_go_scale(machine, JOG_SPEED)
            await _run_scheduled(editor)

        assert execute.await_args is not None
        ops = execute.await_args.args[0]
        assert ops.rect(include_travel=True) == (0.0, 0.0, 100.0, 50.0)
        commands = _commands(ops, machine)
        assert [c for c in commands if c[:1] in CUT_OPCODES] == []

    @pytest.mark.asyncio
    async def test_a_stop_while_measuring_cancels_it(self, machine):
        """MOT-02: a Stop pressed before the job exists must hold."""
        machine.driver_name = "RuidaDriver"
        editor = _editor_with_outline(100.0, 50.0)
        cmd = MachineCmd(editor)
        measure = editor.pipeline.generate_job_artifact_async

        async def stop_mid_measure():
            cmd.cancel_job(machine)
            return MagicMock()

        measure.side_effect = stop_mid_measure

        with patch.object(
            MachineCmd, "_execute_monitored_job", new=AsyncMock()
        ) as execute:
            cmd.run_go_scale(machine, JOG_SPEED)
            await _run_scheduled(editor)

        execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_earlier_stop_does_not_block_the_next(self, machine):
        """Only a Stop aimed at this scale cancels it."""
        machine.driver_name = "RuidaDriver"
        editor = _editor_with_outline(100.0, 50.0)
        cmd = MachineCmd(editor)
        cmd.cancel_job(machine)

        with patch.object(
            MachineCmd, "_execute_monitored_job", new=AsyncMock()
        ) as execute:
            cmd.run_go_scale(machine, JOG_SPEED)
            await _run_scheduled(editor)

        execute.assert_awaited_once()


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

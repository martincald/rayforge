"""What the Go Scale and Cut Scale actions run.

Both work on the job's bounding box. Go Scale is pure movement: the
outline goes to the driver's go_scale, which traces it with rapids at
the jog panel's speed and sends no job, so the laser cannot fire and
the door interlock does not apply (its wire bytes are tested in
test_ruida_start_corner.py). Cut Scale is an ordinary one-layer job,
sent through build_rd_bytes and send_job, that burns the rectangle.
"""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from raygeo.ops import Ops

from swiftcut.core.doc import Doc
from swiftcut.machine.cmd import MachineCmd, _cut_scale_ops
from swiftcut.machine.driver.ruida.ruida_encoder import RuidaEncoder
from swiftcut.machine.models.laser import Laser
from swiftcut.pipeline.artifact import JobArtifact

# Opcodes that cut.
CUT_OPCODES = (b"\xa8", b"\xa9", b"\xaa", b"\xab")

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


def _with_driver(machine):
    """Give the machine a driver whose go_scale is recorded."""
    driver = MagicMock()
    driver.go_scale = AsyncMock()
    return patch.object(
        type(machine), "driver", new_callable=PropertyMock, return_value=driver
    )


class TestGoScaleIsMovement:
    """MachineCmd hands Go Scale's outline to the driver, not a job."""

    @pytest.mark.asyncio
    async def test_the_outline_goes_to_the_driver(self, machine):
        machine.driver_name = "RuidaDriver"
        editor = _editor_with_outline(100.0, 50.0)
        cmd = MachineCmd(editor)

        with (
            _with_driver(machine) as driver,
            patch.object(
                MachineCmd, "_execute_monitored_job", new=AsyncMock()
            ) as execute,
        ):
            cmd.run_go_scale(machine, JOG_SPEED)
            await _run_scheduled(editor)

        driver.return_value.go_scale.assert_awaited_once_with(
            100.0, 50.0, JOG_SPEED
        )
        execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_stop_while_measuring_cancels_it(self, machine):
        """MOT-02: a Stop pressed before the trace starts must hold."""
        machine.driver_name = "RuidaDriver"
        editor = _editor_with_outline(100.0, 50.0)
        cmd = MachineCmd(editor)
        measure = editor.pipeline.generate_job_artifact_async

        with _with_driver(machine) as driver:

            async def stop_mid_measure():
                cmd.cancel_job(machine)
                return MagicMock()

            measure.side_effect = stop_mid_measure
            cmd.run_go_scale(machine, JOG_SPEED)
            await _run_scheduled(editor)

        driver.return_value.go_scale.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_earlier_stop_does_not_block_the_next(self, machine):
        """Only a Stop aimed at this scale cancels it."""
        machine.driver_name = "RuidaDriver"
        editor = _editor_with_outline(100.0, 50.0)
        cmd = MachineCmd(editor)

        with _with_driver(machine) as driver:
            cmd.cancel_job(machine)
            cmd.run_go_scale(machine, JOG_SPEED)
            await _run_scheduled(editor)

        driver.return_value.go_scale.assert_awaited_once()


class TestCutScaleRunsAsAJob:
    """Cut Scale still goes down the ordinary job path."""

    @pytest.mark.asyncio
    async def test_the_rectangle_goes_out_as_a_job(self, machine):
        machine.driver_name = "RuidaDriver"
        editor = _editor_with_outline(100.0, 50.0)
        cmd = MachineCmd(editor)

        with patch.object(
            MachineCmd, "_execute_monitored_job", new=AsyncMock()
        ) as execute:
            cmd.run_cut_scale(machine, 1200, 0.8)
            await _run_scheduled(editor)

        assert execute.await_args is not None
        ops = execute.await_args.args[0]
        assert ops.rect() == (0.0, 0.0, 100.0, 50.0)
        commands = _commands(ops, machine)
        assert [c for c in commands if c[:1] in CUT_OPCODES]


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

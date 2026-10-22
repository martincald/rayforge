"""
After a switch from ilab-614 (1400 x 900 mm) to ilab-626 (900 x 900
mm), every consumer of the bed reads the active machine's extents:
the Ruida driver's jog clamp, the job overrun check, and the bed that
import placement, Auto Layout and moves keep items on. The canvas is
covered in tests/ui_gtk/canvas2d/test_surface_follows_machine.py.
"""

import asyncio
import copy
from types import SimpleNamespace

import pytest
import pytest_asyncio
from blinker import Signal
from raygeo.ops import Ops

from swiftcut.core.bed_bounds import bed_rect
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.doceditor.layout.nest import NestLayoutStrategy
from swiftcut.machine.cmd import MachineCmd
from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.machine.models.default_profile import (
    ILAB_614_PROFILE,
    ILAB_626_PROFILE,
)
from swiftcut.machine.models.machine import Machine
from swiftcut.shared.tasker.manager import TaskManager


@pytest_asyncio.fixture
async def switch(lite_context, task_mgr: TaskManager, monkeypatch):
    """
    Both bundled profiles, on UDP to a documentation address with the
    Ruida connect faked so nothing dials out, ilab-614 active and
    connected as at launch. Calling the result switches to ilab-626
    the way the machine menu does.
    """

    async def fake_connect(driver):
        pass

    monkeypatch.setattr(RuidaDriver, "_connect_implementation", fake_connect)
    manager = lite_context.machine_mgr
    machines = []
    for profile in (ILAB_614_PROFILE, ILAB_626_PROFILE):
        data = copy.deepcopy(profile)
        data["machine"]["driver_args"]["connection"] = "udp"
        data["machine"]["driver_args"]["host"] = "192.0.2.1"
        machine = Machine.from_dict(data, context=lite_context)
        manager.add_machine(machine)
        machines.append(machine)
    ilab_614, ilab_626 = machines
    lite_context.config.set_machine(ilab_614)
    # Launch: the active machine gets its driver and connects.
    manager.initialize_connections()
    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)

    async def to_626():
        assert manager.set_active_machine(ilab_626) is True
        await asyncio.to_thread(task_mgr.wait_until_settled, 5000)
        assert lite_context.config.machine is ilab_626

    yield ilab_614, ilab_626, to_626
    for controller in list(manager.controllers.values()):
        await controller.shutdown()


@pytest.mark.asyncio
async def test_the_jog_clamp_is_the_active_machines_bed(lite_context, switch):
    _ilab_614, _ilab_626, to_626 = switch
    before = lite_context.config.machine.driver
    assert isinstance(before, RuidaDriver)
    assert before._axis_range("x") == (0, 1_400_000)

    await to_626()

    driver = lite_context.config.machine.driver
    assert isinstance(driver, RuidaDriver)
    assert driver is not before
    assert driver._axis_range("x") == (0, 900_000)
    assert driver._axis_range("y") == (0, 900_000)


def _job_1000_mm_wide() -> Ops:
    ops = Ops()
    ops.move_to(0, 0, 0)
    ops.line_to(1000, 10, 0)
    return ops


@pytest.mark.asyncio
async def test_the_overrun_check_is_the_active_machines_bed(
    lite_context, task_mgr, switch
):
    """
    Start hands the check config.machine (MainWindow.on_send_clicked)
    or the jog panel's machine, which follows config.machine; a 1000
    mm job fits ilab-614 and runs past ilab-626.
    """
    _ilab_614, _ilab_626, to_626 = switch
    # The check needs only the editor's notices.
    editor = SimpleNamespace(
        task_manager=task_mgr, notification_requested=Signal()
    )
    machine_cmd = MachineCmd(editor)
    seen = []
    editor.notification_requested.connect(
        lambda sender, message="", **kwargs: seen.append(message),
        weak=False,
    )
    machine_cmd._warn_if_job_overruns_bed(
        _job_1000_mm_wide(), lite_context.config.machine
    )
    assert seen == []

    await to_626()
    machine_cmd._warn_if_job_overruns_bed(
        _job_1000_mm_wide(), lite_context.config.machine
    )
    assert len(seen) == 1
    assert "would run past the bed" in seen[0]


@pytest.mark.asyncio
async def test_placement_and_auto_layout_keep_to_the_active_bed(
    lite_context, task_mgr, switch
):
    """
    Import placement, moves and Auto Layout all take the bed from
    bed_rect(the active machine) when they run; nothing keeps the
    ilab-614 bed.
    """
    _ilab_614, _ilab_626, to_626 = switch
    editor = DocEditor(task_manager=task_mgr, context=lite_context)
    try:
        piece = WorkPiece(name="piece")
        piece.set_size(50.0, 50.0)
        piece.pos = (1000.0, 100.0)
        editor.doc.active_layer.add_child(piece)
        assert bed_rect(lite_context.machine) == (0.0, 0.0, 1400.0, 900.0)
        assert editor.file.off_bed_workpieces() == []
        assert NestLayoutStrategy([piece])._boundary == (
            0.0,
            0.0,
            1400.0,
            900.0,
        )

        await to_626()

        assert bed_rect(lite_context.machine) == (0.0, 0.0, 900.0, 900.0)
        assert editor.file.off_bed_workpieces() == [piece]
        assert NestLayoutStrategy([piece])._boundary == (
            0.0,
            0.0,
            900.0,
            900.0,
        )
        assert editor.machine_dimensions == (900.0, 900.0)
    finally:
        editor.cleanup()
        # The piece set the pipeline going; it must be done by teardown.
        await asyncio.to_thread(task_mgr.wait_until_settled, 5000)

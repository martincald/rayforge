"""
Nothing outlives what started it: threads and asyncio tasks are
counted before and after a driver connects and disconnects, a machine
switch goes back and forth, and a document's pipeline is shut down.
"""

import asyncio
import copy
import threading

import pytest
from driver.ruida.test_ruida_driver import (  # noqa: F401 - fixtures
    driver,
    ruida_simulator,
    wait_for_connection,
)

from swiftcut.core.doc import Doc
from swiftcut.machine.models.default_profile import BUNDLED_PROFILES
from swiftcut.machine.models.machine import Machine
from swiftcut.pipeline.pipeline import Pipeline


async def _settle():
    """Let cancelled tasks and joined threads finish going away."""
    for _ in range(20):
        await asyncio.sleep(0.05)


def _threads() -> list[str]:
    return sorted(t.name for t in threading.enumerate())


def _tasks(loop=None) -> int:
    current = asyncio.current_task()
    return len(
        [
            t
            for t in asyncio.all_tasks(loop)
            if t is not current and not t.done()
        ]
    )


async def _loop_tasks(task_mgr) -> int:
    """The task manager's own loop, counted on that loop."""

    async def count():
        return _tasks()

    future = asyncio.run_coroutine_threadsafe(count(), task_mgr.loop)
    return await asyncio.wrap_future(future)


@pytest.mark.asyncio
async def test_a_disconnect_leaves_no_task_or_thread(driver):  # noqa: F811
    await _settle()
    threads, tasks = _threads(), _tasks()

    assert await wait_for_connection(driver)
    await asyncio.sleep(0.5)
    assert _tasks() > tasks
    # What MachineController.disconnect does.
    await driver.cleanup()
    await _settle()

    assert _threads() == threads
    assert _tasks() == tasks


@pytest.fixture
def shop_machines(lite_context):
    """Both bundled machines, never connecting; the 614 is active."""
    machines = []
    for profile in BUNDLED_PROFILES:
        data = copy.deepcopy(profile)
        data["machine"]["auto_connect"] = False
        machine = Machine.from_dict(data, context=lite_context)
        lite_context.machine_mgr.add_machine(machine)
        machines.append(machine)
    lite_context.config.set_machine(machines[0])
    return machines


async def _switch(context, task_mgr, machine):
    assert context.machine_mgr.set_active_machine(machine)
    assert await asyncio.to_thread(task_mgr.wait_until_settled, 5000)
    assert context.config.machine is machine


@pytest.mark.asyncio
async def test_switching_machines_leaves_no_task_or_thread(
    lite_context, task_mgr, shop_machines
):
    ilab_614, ilab_626 = shop_machines
    await _switch(lite_context, task_mgr, ilab_626)
    await _switch(lite_context, task_mgr, ilab_614)
    await _settle()
    threads = _threads()
    tasks = await _loop_tasks(task_mgr)

    for _ in range(5):
        await _switch(lite_context, task_mgr, ilab_626)
        await _switch(lite_context, task_mgr, ilab_614)
    await _settle()

    assert _threads() == threads
    assert await _loop_tasks(task_mgr) == tasks
    await lite_context.machine_mgr.shutdown()


@pytest.mark.asyncio
async def test_closing_a_document_leaves_no_thread(
    context_initializer, task_mgr, test_machine_and_config
):
    machine, _config = test_machine_and_config

    async def open_and_close():
        pipeline = Pipeline(
            Doc(), task_mgr, context_initializer.artifact_store, machine
        )
        await asyncio.to_thread(task_mgr.wait_until_settled, 5000)
        pipeline.shutdown()

    await open_and_close()
    await _settle()
    threads = _threads()

    for _ in range(5):
        await open_and_close()
    await _settle()

    assert _threads() == threads

"""
Machine signals sent from the task thread reach their listeners on the
main thread, through the scheduler.

The UI listens to these signals and touches widgets, which only the
GTK main thread may do. The task thread here is a worker thread with
its own event loop, as the TaskManager's is.
"""

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from swiftcut.machine.models.controller import MachineController
from swiftcut.machine.models.machine import Machine
from swiftcut.machine.transport import TransportStatus


class _MainThreadQueue:
    """A main thread scheduler that holds each call until drained."""

    def __init__(self):
        self.calls = []

    def __call__(self, func, *args, **kwargs):
        self.calls.append((func, args, kwargs))

    def drain(self):
        """Runs the held calls, on the calling thread."""
        calls, self.calls = self.calls, []
        for func, args, kwargs in calls:
            func(*args, **kwargs)


def _run_in_worker(func, *args):
    """
    Calls func on a worker thread, and runs the coroutine it returns
    in that thread's own event loop. What it raised is raised here.
    """
    errors = []

    def target():
        try:
            result = func(*args)
            if asyncio.iscoroutine(result):
                asyncio.run(result)
        except BaseException as e:  # noqa: BLE001 - re-raised below
            errors.append(e)

    worker = threading.Thread(target=target)
    worker.start()
    worker.join()
    if errors:
        raise errors[0]


def _listener_threads(signal) -> list[threading.Thread]:
    """The thread each send of signal reached a listener on."""
    threads = []

    def on_send(sender, **kwargs):
        threads.append(threading.current_thread())

    signal.connect(on_send, weak=False)
    return threads


@pytest.fixture
def machine(lite_context):
    machine = Machine(lite_context)
    lite_context.machine_mgr.add_machine(machine)
    return machine


@pytest.mark.parametrize("method", ["set_power", "set_focus_power"])
def test_a_laser_power_change_reaches_listeners_on_the_main_thread(
    lite_context, machine, method
):
    queue = _MainThreadQueue()
    controller = MachineController(machine, lite_context, queue)
    queue.calls.clear()
    threads = _listener_threads(controller.laser_power_changed)

    _run_in_worker(getattr(controller, method), None, 0.5)

    assert threads == []
    queue.drain()
    assert threads == [threading.main_thread()]


def test_the_active_wcs_read_from_the_device_is_announced_on_the_main_thread(
    lite_context, machine, monkeypatch
):
    queue = _MainThreadQueue()
    monkeypatch.setattr(machine, "_scheduler", queue)
    controller = MachineController(machine, lite_context, queue)
    machine.connection_status = TransportStatus.CONNECTED
    monkeypatch.setattr(
        controller.driver,
        "read_parser_state",
        AsyncMock(return_value="G55"),
    )
    assert machine.active_wcs != "G55"
    queue.calls.clear()
    threads = _listener_threads(machine.changed)

    _run_in_worker(controller.sync_active_wcs_from_device)

    assert machine.active_wcs == "G55"
    assert threads == []
    queue.drain()
    assert threads == [threading.main_thread()]


def test_an_active_wcs_set_on_the_main_thread_is_announced_at_once(
    machine, monkeypatch
):
    queue = _MainThreadQueue()
    monkeypatch.setattr(machine, "_scheduler", queue)
    threads = _listener_threads(machine.changed)

    machine.set_active_wcs("G55")

    assert threads == [threading.main_thread()]
    assert queue.calls == []


def test_job_hours_added_on_the_task_thread_reach_listeners_on_the_main_one(
    machine, monkeypatch
):
    queue = _MainThreadQueue()
    monkeypatch.setattr(machine, "_scheduler", queue)
    hours = machine.machine_hours
    before = hours.total_hours
    threads = _listener_threads(hours.changed)

    _run_in_worker(machine.add_machine_hours, 0.5)

    assert threads == []
    queue.drain()
    assert threads == [threading.main_thread()]
    assert hours.total_hours == pytest.approx(before + 0.5)

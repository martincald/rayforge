"""
A dropped connection in a real window on the bundled ilab-614 profile,
its Ruida driver's connection stubbed out: nothing reaches a device.
The statuses arrive on machine.connection_status_changed, as the
controller forwards them.
"""

import asyncio
import time
from contextlib import contextmanager
from unittest.mock import PropertyMock, patch

import pytest
from gi.repository import Adw, GLib, Gtk

from swiftcut.context import get_context
from swiftcut.machine.cmd import MachineCmd
from swiftcut.machine.driver.driver import DeviceStatus
from swiftcut.machine.transport import TransportStatus
from swiftcut.pipeline.pipeline import Pipeline
from swiftcut.shared.tasker import task_mgr

pytestmark = pytest.mark.ui


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    context = GLib.main_context_default()
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def _wait_for(condition, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        _pump(0.05)


def _settled() -> bool:
    return not task_mgr.has_tasks()


def _send(machine, status: TransportStatus) -> None:
    machine.set_connection_status(status)
    machine.connection_status_changed.send(machine, status=status)


@pytest.fixture
def ilab_614(tmp_path, monkeypatch, ui_task_mgr):
    """
    A context on the bundled profiles, ilab-614 active, whose drivers
    never connect: no device, no network.
    """
    from swiftcut import config
    from swiftcut import context as context_module
    from swiftcut.machine.driver.driver import Driver
    from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
    from swiftcut.shared import tasker

    async def no_connection(self):
        pass

    monkeypatch.setattr(Driver, "connect", no_connection)
    monkeypatch.setattr(RuidaDriver, "_connect_implementation", no_connection)
    folder = tmp_path / "config"
    monkeypatch.setattr(config, "CONFIG_DIR", folder)
    monkeypatch.setattr(config, "DIALECT_DIR", folder / "dialects")
    monkeypatch.setattr(config, "MACHINE_DIR", folder / "machines")
    monkeypatch.setattr(config, "ADDONS_DIR", folder / "addons")
    monkeypatch.setattr(config, "CONFIG_FILE", folder / "config.yaml")
    monkeypatch.setattr(config, "AI_CONFIG_FILE", folder / "ai.yaml")
    monkeypatch.setattr(tasker.task_mgr, "_instance", ui_task_mgr)

    # No placeholder machine: an empty machine folder gets the bundled
    # profiles.
    context = get_context()
    _ = context.addon_mgr
    context.machine_mgr.initialize_connections()
    yield context

    asyncio.run_coroutine_threadsafe(
        context.shutdown(), ui_task_mgr.loop
    ).result(timeout=10)
    context_module._context_instance = None


@pytest.fixture
def win(ilab_614, request):
    from swiftcut.ui_gtk.mainwindow import MainWindow

    class App(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)
            self.win.set_default_size(1280, 800)

    test_name = request.node.name.replace("_", "-")
    app = App(application_id=f"org.swiftcut.swiftcut.test.{test_name}")
    app.register(None)
    app.activate()
    window = app.win
    window.present()
    _pump(0.5)
    _wait_for(_settled)
    yield window
    for toplevel in Gtk.Window.list_toplevels():
        if toplevel.get_transient_for() is window:
            toplevel.destroy()
    window.doc_editor.cleanup()
    window.destroy()
    app.quit()
    _pump(0.2)


@contextmanager
def _a_job_ready(win):
    """A job with ops, current and idle, so only the link gates Start."""
    with (
        patch.object(
            MachineCmd,
            "has_job_ops",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch.object(
            Pipeline,
            "is_data_stale",
            new_callable=PropertyMock,
            return_value=False,
        ),
        patch.object(
            type(win.doc_editor.doc), "has_result", return_value=True
        ),
        patch.object(win.machine_cmd, "set_jog_speed"),
    ):
        yield


def test_a_drop_disables_jog_start_and_both_scales(win):
    machine = get_context().config.machine
    assert (machine.name, machine.driver_name) == ("ilab-614", "RuidaDriver")
    jog = win.bottom_panel.jog_widget
    controls = {
        "east": jog.east_btn,
        "west": jog.west_btn,
        "north": jog.north_btn,
        "south": jog.south_btn,
        "north-east": jog.north_east_btn,
        "north-west": jog.north_west_btn,
        "south-east": jog.south_east_btn,
        "south-west": jog.south_west_btn,
        "start": jog.start_btn,
        "go scale": jog.go_scale_btn,
        "cut scale": jog.cut_scale_btn,
    }
    actions = ("machine-send", "machine-go-scale", "machine-cut-scale")
    am = win.action_manager
    machine.device_state.status = DeviceStatus.IDLE

    with _a_job_ready(win):
        _send(machine, TransportStatus.CONNECTED)

        assert [n for n, b in controls.items() if not b.get_sensitive()] == []
        assert [a for a in actions if not am.get_action(a).get_enabled()] == []

        _send(machine, TransportStatus.SLEEPING)

        assert [n for n, b in controls.items() if b.get_sensitive()] == []
        assert [a for a in actions if am.get_action(a).get_enabled()] == []


def test_the_banner_follows_the_active_machine(win):
    context = get_context()
    ilab_614 = context.config.machine
    ilab_626 = next(
        m
        for m in context.machine_mgr.machines.values()
        if m.name == "ilab-626"
    )
    banner = win.reconnect_banner.banner
    assert win.reconnect_banner.machine is ilab_614
    assert banner.get_prev_sibling() is win.header_bar
    assert ilab_614.controller.connect_requested

    _send(ilab_614, TransportStatus.CONNECTING)
    assert not banner.get_revealed()
    _send(ilab_614, TransportStatus.ERROR)
    assert banner.get_revealed()
    _send(ilab_614, TransportStatus.DISCONNECTED)
    _send(ilab_614, TransportStatus.SLEEPING)
    assert banner.get_revealed()

    # A switch is refused while a task runs.
    _wait_for(_settled)
    win._update_actions_and_ui()
    win.activate_action(
        "win.select-machine", GLib.Variant.new_string(ilab_626.id)
    )
    _wait_for(lambda: context.config.machine is ilab_626 and _settled())

    assert win.reconnect_banner.machine is ilab_626
    assert not banner.get_revealed()
    _send(ilab_614, TransportStatus.ERROR)
    assert not banner.get_revealed()


def test_a_disconnect_hides_the_banner(win, ui_task_mgr):
    """
    The driver's statuses take the controller's path to the window; a
    disconnect with auto-connect off leaves nothing retrying.
    """
    machine = get_context().config.machine
    banner = win.reconnect_banner.banner
    driver = machine.driver
    for status in (TransportStatus.ERROR, TransportStatus.SLEEPING):
        driver.connection_status_changed.send(driver, status=status)
    _pump(0.2)
    assert banner.get_revealed()

    machine.auto_connect = False
    asyncio.run_coroutine_threadsafe(
        machine.disconnect(), ui_task_mgr.loop
    ).result(timeout=10)
    _wait_for(_settled)
    _pump(0.2)

    assert machine.connection_status == TransportStatus.DISCONNECTED
    assert not machine.controller.connect_requested
    assert not banner.get_revealed()

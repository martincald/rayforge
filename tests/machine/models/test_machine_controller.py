"""
Tests for the MachineController class.

This module tests the MachineController which handles:
- Driver lifecycle management (connect/disconnect/shutdown)
- Command execution (jog, home, run_raw, etc.)
- Signal emissions for state changes

The MachineController is the logic layer that owns and manages the driver.
"""

import asyncio
import logging
from unittest.mock import call, patch

import pytest

from swiftcut.machine.driver.driver import ResourceBusyError
from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.machine.models.controller import MachineController
from swiftcut.machine.models.machine import Machine
from swiftcut.machine.transport import TransportStatus
from swiftcut.shared.tasker import task_mgr


@pytest.mark.usefixtures("lite_context")
class TestMachineController:
    """Test suite for the MachineController class."""

    def test_controller_initialization(self, lite_context):
        """Test that MachineController can be initialized."""
        machine = Machine(lite_context)
        lite_context.machine_mgr.add_machine(machine)
        controller = MachineController(
            machine, lite_context, task_mgr.schedule_on_main_thread
        )
        assert controller is not None
        assert controller.machine == machine
        assert controller.context == lite_context
        assert controller.driver is not None

    def test_controller_driver_property(self, lite_context):
        """Test that the controller has a driver property."""
        machine = Machine(lite_context)
        lite_context.machine_mgr.add_machine(machine)
        controller = machine.controller
        assert controller.driver is not None

    def test_controller_signals_exist(self, lite_context):
        """Test that controller has all required signals."""
        machine = Machine(lite_context)
        lite_context.machine_mgr.add_machine(machine)
        controller = machine.controller
        assert hasattr(controller, "connection_status_changed")
        assert hasattr(controller, "state_changed")
        assert hasattr(controller, "job_finished")
        assert hasattr(controller, "command_status_changed")
        assert hasattr(controller, "wcs_updated")

    @pytest.mark.asyncio
    async def test_rebuild_driver_logs_the_resolved_driver_and_profile(
        self, lite_context, caplog
    ):
        """
        Driver resolution has to be provable from the log alone: a
        future triage on a misbehaving profile needs to see which
        driver class a machine's driver_name actually resolved to.
        """
        machine = Machine(lite_context)
        lite_context.machine_mgr.add_machine(machine)
        controller = MachineController(
            machine, lite_context, task_mgr.schedule_on_main_thread
        )

        machine.name = "ilab-614"
        machine.driver_name = "RuidaDriver"
        # Never let a test dial out to a real machine.
        machine.auto_connect = False

        with caplog.at_level(logging.INFO):
            await controller.rebuild_driver()

        assert (
            "Driver resolved: RuidaDriver for profile ilab-614"
            in caplog.text
        )


def _ruida_controller(lite_context):
    """
    A controller for a UDP Ruida profile that never connects. It is
    built before the driver is named, so it schedules no rebuild of
    its own.
    """
    machine = Machine(lite_context)
    lite_context.machine_mgr.add_machine(machine)
    controller = MachineController(
        machine, lite_context, task_mgr.schedule_on_main_thread
    )
    machine.driver_name = "RuidaDriver"
    machine.driver_args = {"host": "192.168.1.100"}
    # Never let a test dial out to a real machine.
    machine.auto_connect = False
    return machine, controller


class TestRebuildForTheLiveSettings:
    """
    One settings change asks for two rebuilds. The second finds the
    live driver set up from those settings and keeps it; anything
    that does need a new driver still gets one.
    """

    @pytest.mark.asyncio
    async def test_the_same_settings_keep_the_live_driver(self, lite_context):
        _machine, controller = _ruida_controller(lite_context)
        await controller.rebuild_driver()
        driver = controller.driver

        await controller.rebuild_driver()

        assert controller.driver is driver

    @pytest.mark.asyncio
    async def test_new_driver_args_build_a_new_driver(self, lite_context):
        machine, controller = _ruida_controller(lite_context)
        await controller.rebuild_driver()
        driver = controller.driver

        machine.driver_args = {"host": "192.168.1.101"}
        await controller.rebuild_driver()

        assert controller.driver is not driver
        assert controller.driver.host == "192.168.1.101"

    @pytest.mark.asyncio
    async def test_new_driver_config_builds_a_new_driver(self, lite_context):
        """A profile applies driver_config after set_driver has
        already asked for its rebuilds; the later one must apply it."""
        machine, controller = _ruida_controller(lite_context)
        await controller.rebuild_driver()
        driver = controller.driver

        machine.driver_config = {"note": "from the profile"}
        await controller.rebuild_driver()

        assert controller.driver is not driver
        assert controller.driver.config == {"note": "from the profile"}

    @pytest.mark.asyncio
    async def test_a_cleaned_up_driver_is_rebuilt(self, lite_context):
        """disconnect() cleans the driver up, then asks for a rebuild
        with unchanged settings: that one must not be skipped."""
        _machine, controller = _ruida_controller(lite_context)
        await controller.rebuild_driver()
        driver = controller.driver

        await driver.cleanup()
        await controller.rebuild_driver()

        assert controller.driver is not driver
        assert controller.driver.did_setup


class TestRelease:
    """
    Another machine becoming active releases this one's driver for
    good: disconnect() would rebuild and reconnect it.
    """

    @pytest.mark.asyncio
    async def test_release_disconnects_and_schedules_no_rebuild(
        self, lite_context
    ):
        machine, controller = _ruida_controller(lite_context)
        await controller.rebuild_driver()
        driver = controller.driver
        machine.set_connection_status(TransportStatus.CONNECTED)

        with patch(
            "swiftcut.machine.models.controller.task_mgr"
        ) as controller_tasks:
            await controller.release()

        assert controller_tasks.cancel_task.call_args_list == [
            call((machine.id, "driver-connect")),
            call((machine.id, "rebuild-driver")),
            call((machine.id, "rebuild-driver-on-change")),
            call((machine.id, "rebuild-driver-on-init")),
            call((machine.id, "initial-connect")),
        ]
        controller_tasks.add_coroutine.assert_not_called()
        assert controller.driver is driver
        assert not driver.did_setup
        assert machine.connection_status == TransportStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_a_released_controller_shuts_down_cleanly(
        self, lite_context
    ):
        """Quitting after a switch cleans the released driver up again."""
        _machine, controller = _ruida_controller(lite_context)
        await controller.rebuild_driver()
        await controller.release()

        await controller.shutdown()

    @pytest.mark.asyncio
    async def test_a_released_controller_rebuilds_when_active_again(
        self, lite_context
    ):
        """Switching back builds a new driver, as rebuild_driver does."""
        _machine, controller = _ruida_controller(lite_context)
        await controller.rebuild_driver()
        driver = controller.driver
        await controller.release()

        await controller.rebuild_driver()

        assert controller.driver is not driver
        assert controller.driver.did_setup

    @pytest.mark.asyncio
    async def test_a_released_controller_rebuilds_but_never_connects(
        self, lite_context, monkeypatch
    ):
        """
        A settings edit on a released machine builds a driver with the
        new settings and connects nothing. Once the flag is cleared (the
        manager does that on a switch back), a rebuild connects.
        """
        connects = []

        async def fake_connect(driver):
            connects.append(driver.host)

        monkeypatch.setattr(
            RuidaDriver, "_connect_implementation", fake_connect
        )
        machine, controller = _ruida_controller(lite_context)
        machine.auto_connect = True
        await controller.rebuild_driver()
        await controller.release()

        machine.driver_args = {"host": "192.168.1.101"}
        await controller.rebuild_driver()
        await controller.rebuild_driver()

        assert controller.driver.host == "192.168.1.101"
        assert connects == ["192.168.1.100"]

        controller._released = False
        await controller.rebuild_driver()

        assert connects == ["192.168.1.100", "192.168.1.101"]


class TestConnectOnce:
    """
    A driver's connection loop retries by itself, so the controller
    asks each driver to connect once, until a disconnect, release or
    shutdown forgets it.
    """

    @pytest.mark.asyncio
    async def test_connect_requested_follows_the_live_driver(
        self, lite_context, task_mgr, monkeypatch
    ):
        connects = []

        async def fake_connect(driver):
            connects.append(driver)

        monkeypatch.setattr(
            RuidaDriver, "_connect_implementation", fake_connect
        )
        machine, controller = _ruida_controller(lite_context)
        await controller.rebuild_driver()
        assert not controller.connect_requested

        await controller.connect()
        await controller.connect()
        assert controller.connect_requested
        assert connects == [controller.driver]

        await controller.disconnect()
        assert not controller.connect_requested
        await asyncio.to_thread(task_mgr.wait_until_settled, 5000)
        assert not controller.connect_requested

        await controller.connect()
        assert controller.connect_requested
        machine.driver_args = {"host": "192.168.1.101"}
        await controller.rebuild_driver()
        assert not controller.connect_requested

        await controller.connect()
        await controller.release()
        assert not controller.connect_requested
        assert len(connects) == 3
        await controller.shutdown()

    @pytest.mark.asyncio
    async def test_a_refused_connect_can_be_asked_again(
        self, lite_context, monkeypatch
    ):
        connects = []

        async def busy_once(driver):
            connects.append(driver)
            if len(connects) == 1:
                raise ResourceBusyError("udp://192.168.1.100", "ilab-626")

        monkeypatch.setattr(RuidaDriver, "_connect_implementation", busy_once)
        _machine, controller = _ruida_controller(lite_context)
        await controller.rebuild_driver()

        with pytest.raises(ResourceBusyError):
            await controller.connect()
        assert not controller.connect_requested
        await controller.connect()

        assert controller.connect_requested
        assert connects == [controller.driver, controller.driver]
        await controller.shutdown()


class TestConnectedMeansTheControllerAnswered:
    """
    A transport says CONNECTED once its port or socket opens, before
    the controller has answered. The machine is connected only once
    the driver is: until then jog, Start and both scales stay off.
    """

    @pytest.mark.asyncio
    async def test_an_open_port_with_a_silent_controller_is_connecting(
        self, lite_context
    ):
        machine, controller = _ruida_controller(lite_context)
        await controller.rebuild_driver()
        driver = controller.driver
        assert isinstance(driver, RuidaDriver)
        assert not driver.is_connected

        driver._on_status_changed(None, TransportStatus.CONNECTING)
        driver._on_status_changed(None, TransportStatus.CONNECTED)

        assert machine.connection_status == TransportStatus.CONNECTING
        assert not machine.is_connected()
        await controller.shutdown()
        await asyncio.to_thread(task_mgr.wait_until_settled, 5000)

    @pytest.mark.asyncio
    async def test_the_handshake_answered_connects_the_machine(
        self, lite_context
    ):
        machine, controller = _ruida_controller(lite_context)
        await controller.rebuild_driver()
        driver = controller.driver
        driver._on_status_changed(None, TransportStatus.CONNECTING)
        driver._on_status_changed(None, TransportStatus.CONNECTED)

        # What the connection loop does once the controller answered.
        driver._is_connected = True
        driver._update_connection_status(TransportStatus.CONNECTED, "")

        assert machine.connection_status == TransportStatus.CONNECTED
        assert machine.is_connected()
        await controller.shutdown()
        await asyncio.to_thread(task_mgr.wait_until_settled, 5000)

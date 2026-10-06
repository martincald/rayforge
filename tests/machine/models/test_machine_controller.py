"""
Tests for the MachineController class.

This module tests the MachineController which handles:
- Driver lifecycle management (connect/disconnect/shutdown)
- Command execution (jog, home, run_raw, etc.)
- Signal emissions for state changes

The MachineController is the logic layer that owns and manages the driver.
"""

import logging

import pytest

from swiftcut.machine.models.controller import MachineController
from swiftcut.machine.models.machine import Machine
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

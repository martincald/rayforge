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

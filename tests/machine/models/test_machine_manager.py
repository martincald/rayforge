"""
Tests for the MachineManager class.

This module tests the MachineManager which handles:
- Machine lifecycle (loading/saving machine configurations)
- Active machine management
- Machine file persistence

The MachineManager is responsible for managing the collection of
machines and coordinating their lifecycle.
"""

import asyncio

import pytest

from swiftcut.machine.models.machine import Machine
from swiftcut.machine.models.manager import MachineManager
from swiftcut.shared.tasker.manager import TaskManager


@pytest.mark.usefixtures("lite_context")
class TestMachineManager:
    """Test suite for the MachineManager class."""

    def test_manager_initialization(self, tmp_path):
        """Test that MachineManager can be initialized."""
        manager = MachineManager(tmp_path)
        assert manager is not None
        assert manager.base_dir == tmp_path
        assert isinstance(manager.machines, dict)

    def test_manager_add_machine(self, lite_context, tmp_path):
        """Test adding a machine to the manager."""
        manager = MachineManager(tmp_path)
        machine = Machine(lite_context)

        manager.add_machine(machine)
        assert len(manager.machines) == 1
        assert manager.machines[machine.id] == machine

    def test_manager_get_machine_by_id(self, lite_context, tmp_path):
        """Test getting a machine by its ID."""
        manager = MachineManager(tmp_path)
        machine = Machine(lite_context)

        manager.add_machine(machine)
        found = manager.get_machine_by_id(machine.id)
        assert found == machine

    def test_manager_get_machine_by_id_not_found(self, tmp_path):
        """Test getting a non-existent machine by ID."""
        manager = MachineManager(tmp_path)
        found = manager.get_machine_by_id("non-existent-id")
        assert found is None

    def test_manager_signals_exist(self, tmp_path):
        """Test that manager has all required signals."""
        manager = MachineManager(tmp_path)
        assert hasattr(manager, "machine_added")
        assert hasattr(manager, "machine_removed")
        assert hasattr(manager, "machine_updated")

    def test_load_machine_logs_the_file_path(
        self, lite_context, tmp_path, caplog
    ):
        """
        Loading a machine must log which file it came from, so the
        owner (or a log dump) can tell which on-disk profile is
        actually live -- e.g. to catch a stale/duplicate machine
        directory left over from a package rename.
        """
        manager = MachineManager(tmp_path)
        machine = Machine(lite_context)
        machine.name = "ilab-614"
        manager.add_machine(machine)
        manager.save_machine(machine)
        expected_file = manager.filename_from_id(machine.id)

        with caplog.at_level("INFO"):
            reloaded_manager = MachineManager(tmp_path)

        assert str(expected_file) in caplog.text
        assert "ilab-614" in caplog.text
        assert reloaded_manager.machines[machine.id].name == "ilab-614"

    def test_load_new_machines_picks_up_files_added_out_of_band(
        self, lite_context, tmp_path
    ):
        """
        load_new_machines is what lets a running MachineManager pick up
        a machine file dropped into base_dir after startup (e.g. by the
        "Import settings from Rayforge" action), without disturbing any
        machine already loaded and possibly connected.
        """
        manager = MachineManager(tmp_path)
        existing = Machine(lite_context)
        manager.add_machine(existing)

        added = manager.load_new_machines()
        assert added == []
        assert len(manager.machines) == 1

        imported = Machine(lite_context)
        manager.save_machine(imported)  # write the file, but don't add()

        received = []

        def on_machine_added(sender, machine_id):
            received.append(machine_id)

        manager.machine_added.connect(on_machine_added)

        added = manager.load_new_machines()

        assert [m.id for m in added] == [imported.id]
        assert imported.id in manager.machines
        assert existing.id in manager.machines
        # The already-loaded machine must be left as the same object.
        assert manager.machines[existing.id] is existing
        assert received == [imported.id]

    def test_load_machine_warns_on_non_default_ruida_ports(
        self, lite_context, tmp_path, caplog
    ):
        """
        A2.3: loading a Ruida profile whose ports drifted from the
        ilab-614 defaults must log a WARNING. See
        test_loading_a_wrong_port_profile_does_not_modify_the_file
        for the "never silently rewrite" half of this requirement.
        """
        manager = MachineManager(tmp_path)
        machine = Machine(lite_context)
        machine.driver_name = "RuidaDriver"
        machine.driver_args = {
            "host": "192.168.1.100",
            "port": 50201,
            "jog_port": 50207,
        }
        manager.add_machine(machine)

        with caplog.at_level("WARNING"):
            MachineManager(tmp_path)

        assert "non-default Ruida ports" in caplog.text
        assert "50201" in caplog.text

    def test_load_machine_does_not_warn_for_correct_ruida_ports(
        self, lite_context, tmp_path, caplog
    ):
        manager = MachineManager(tmp_path)
        machine = Machine(lite_context)
        machine.driver_name = "RuidaDriver"
        machine.driver_args = {
            "host": "192.168.1.100",
            "port": 50200,
            "jog_port": 50207,
        }
        manager.add_machine(machine)

        with caplog.at_level("WARNING"):
            MachineManager(tmp_path)

        assert "non-default Ruida ports" not in caplog.text

    def test_load_machine_does_not_warn_for_a_non_ruida_driver(
        self, lite_context, tmp_path, caplog
    ):
        """The check must not fire for a non-Ruida driver."""
        manager = MachineManager(tmp_path)
        machine = Machine(lite_context)
        machine.driver_name = "NoDeviceDriver"
        machine.driver_args = {"port": 50201}
        manager.add_machine(machine)

        with caplog.at_level("WARNING"):
            MachineManager(tmp_path)

        assert "non-default Ruida ports" not in caplog.text

    def test_loading_a_wrong_port_profile_does_not_modify_the_file(
        self, lite_context, tmp_path
    ):
        """The hard constraint: sanity checking on load never writes."""
        manager = MachineManager(tmp_path)
        machine = Machine(lite_context)
        machine.driver_name = "RuidaDriver"
        machine.driver_args = {
            "host": "192.168.1.100",
            "port": 50201,
            "jog_port": 50207,
        }
        # A real Ruida profile has dialect_uid: None (RuidaDriver
        # doesn't use gcode); this avoids the unrelated builtin ->
        # per-machine-copy dialect migration triggering its own
        # resave, which would otherwise mask what this test checks.
        machine.dialect_uid = None
        manager.add_machine(machine)
        machine_file = manager.filename_from_id(machine.id)
        before = machine_file.read_bytes()

        MachineManager(tmp_path)

        assert machine_file.read_bytes() == before

    def test_has_controller_does_not_lazily_create(
        self, lite_context, tmp_path
    ):
        """has_controller reports existence without lazily creating one."""
        manager = MachineManager(tmp_path)
        machine = Machine(lite_context)
        manager.add_machine(machine)

        # No controller has been instantiated yet.
        assert manager.has_controller(machine.id) is False
        assert machine.id not in manager.controllers

        # It must also be safe (no raise) for unknown ids.
        assert manager.has_controller("non-existent-id") is False

        # Instantiating the controller flips the flag to True.
        manager.get_controller(machine.id)
        assert manager.has_controller(machine.id) is True

    @pytest.mark.asyncio
    async def test_removed_machine_reports_no_controller(
        self, machine: Machine, task_mgr: TaskManager
    ):
        """
        Regression for #280: removing the currently selected machine must
        leave it without a live controller. Accessing ``machine.controller``
        on a removed machine raises ValueError (the source of the crash), so
        ``has_controller`` is what lets the UI safely skip the disconnect of
        the controller's signals.
        """
        manager = machine.context.machine_mgr

        # Force the controller into existence, mirroring the active machine
        # whose laser_power_changed signal the UI has connected to.
        manager.get_controller(machine.id)
        assert machine.has_controller is True

        manager.remove_machine(machine.id)
        # Let the scheduled controller shutdown settle.
        await asyncio.to_thread(task_mgr.wait_until_settled, 2000)

        assert manager.has_controller(machine.id) is False
        assert machine.has_controller is False
        with pytest.raises(ValueError):
            _ = machine.controller

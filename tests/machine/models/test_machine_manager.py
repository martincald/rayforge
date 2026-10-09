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
import copy
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.machine.models.default_profile import (
    ILAB_614_PROFILE,
    ILAB_626_PROFILE,
)
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


def _bundled_pair(context):
    """
    Both bundled profiles in the context's manager, beside its inert
    placeholder. Building a machine creates no controller, so nothing
    connects unless a test asks for a controller.
    """
    manager = context.machine_mgr
    ilab_614 = manager.create_default_machine(ILAB_614_PROFILE)
    ilab_626 = manager.create_default_machine(ILAB_626_PROFILE)
    return manager, ilab_614, ilab_626


@pytest.mark.asyncio
async def test_only_the_active_machine_connects_at_launch(
    lite_context, task_mgr: TaskManager
):
    """
    Both bundled profiles reach the same controller, so launch
    connects the active one only; the other never gets a controller.
    """
    manager, ilab_614, ilab_626 = _bundled_pair(lite_context)
    lite_context.config.set_machine(ilab_626)

    with patch.object(
        manager, "_rebuild_and_connect_machine", new=AsyncMock()
    ) as connect:
        manager.initialize_connections()
        await asyncio.to_thread(task_mgr.wait_until_settled, 2000)

    connect.assert_awaited_once_with(ilab_626)
    assert not manager.has_controller(ilab_614.id)
    assert not manager.has_controller(ilab_626.id)


def _other_machine(context, name="Other Laser"):
    """A machine that is not bundled, on the inert NoDeviceDriver."""
    machine = Machine(context)
    machine.name = name
    machine.driver_name = "NoDeviceDriver"
    return machine


def test_switchable_machines_are_the_bundled_ones_in_order(lite_context):
    """
    The switcher lists ilab-614 then ilab-626, whatever order they
    were added in, and never a driverless or a non-bundled machine.
    """
    manager = lite_context.machine_mgr
    driverless = Machine(lite_context)
    manager.add_machine(driverless)
    manager.add_machine(_other_machine(lite_context))
    ilab_626 = manager.create_default_machine(ILAB_626_PROFILE)
    ilab_614 = manager.create_default_machine(ILAB_614_PROFILE)

    assert manager.switchable_machines() == [ilab_614, ilab_626]
    assert not manager.has_controller(ilab_614.id)
    assert not manager.has_controller(ilab_626.id)


def test_a_bundled_machine_cannot_be_removed(lite_context):
    """
    Removing a bundled machine is refused: the machine and its file
    stay, and nothing is told it was removed.
    """
    manager, _ilab_614, ilab_626 = _bundled_pair(lite_context)
    machine_file = manager.filename_from_id(ilab_626.id)
    removed = []

    def on_removed(sender, machine_id):
        removed.append(machine_id)

    manager.machine_removed.connect(on_removed)

    assert manager.remove_machine(ilab_626.id) is False

    assert manager.get_machine_by_id(ilab_626.id) is ilab_626
    assert machine_file.exists()
    assert removed == []


def test_a_second_machine_with_a_bundled_name_cannot_be_added(lite_context):
    """
    A machine named like a bundled one is refused; a machine that is
    not bundled is still added and removed as before.
    """
    manager, _ilab_614, ilab_626 = _bundled_pair(lite_context)
    impostor = _other_machine(lite_context, name="ilab-626")

    manager.add_machine(impostor)

    assert impostor.id not in manager.machines
    assert not manager.filename_from_id(impostor.id).exists()
    assert manager.switchable_machines()[1] is ilab_626

    other = _other_machine(lite_context)
    manager.add_machine(other)
    assert manager.get_machine_by_id(other.id) is other
    assert manager.remove_machine(other.id) is True
    assert other.id not in manager.machines
    assert not manager.filename_from_id(other.id).exists()


def test_switching_to_a_machine_that_is_not_bundled_is_refused(
    lite_context, task_mgr: TaskManager
):
    manager, ilab_614, _ilab_626 = _bundled_pair(lite_context)
    other = _other_machine(lite_context)
    manager.add_machine(other)
    lite_context.config.set_machine(ilab_614)

    assert manager.set_active_machine(other) is False
    assert manager.set_active_machine(ilab_614) is False

    assert not task_mgr.has_tasks()
    assert lite_context.config.machine is ilab_614


@pytest.mark.asyncio
async def test_a_second_switch_is_refused_while_one_runs(
    lite_context, task_mgr: TaskManager
):
    """
    Two quick clicks make one switch: a second request would replace
    (cancel) the switch in flight, so it is refused instead.
    """
    manager, ilab_614, ilab_626 = _bundled_pair(lite_context)
    lite_context.config.set_machine(ilab_614)
    old, new = AsyncMock(), AsyncMock()
    manager.controllers[ilab_614.id] = old
    manager.controllers[ilab_626.id] = new

    assert manager.set_active_machine(ilab_626) is True
    assert manager.set_active_machine(ilab_626) is False
    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)

    old.release.assert_awaited_once()
    new.rebuild_driver.assert_awaited_once()
    assert lite_context.config.machine is ilab_626


@pytest.mark.asyncio
async def test_a_failed_connect_after_a_switch_is_logged(
    lite_context, task_mgr: TaskManager, caplog
):
    """The switch has landed; a driver error is logged, like
    _safe_connect's, and is no failed task."""
    manager, ilab_614, ilab_626 = _bundled_pair(lite_context)
    lite_context.config.set_machine(ilab_614)
    new = AsyncMock()
    new.rebuild_driver.side_effect = RuntimeError("no such device")
    manager.controllers[ilab_614.id] = AsyncMock()
    manager.controllers[ilab_626.id] = new

    with caplog.at_level("ERROR"):
        assert manager.set_active_machine(ilab_626) is True
        await asyncio.to_thread(task_mgr.wait_until_settled, 5000)

    assert lite_context.config.machine is ilab_626
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert errors == [
        "Failed to connect machine 'ilab-626' after the switch: no such device"
    ]


@pytest.mark.asyncio
async def test_a_released_machine_never_reconnects(
    lite_context, task_mgr: TaskManager, monkeypatch
):
    """
    After a switch to ilab-626, a Machine Settings dialog still open on
    ilab-614 edits its driver args: ilab-614's driver is rebuilt with
    them but never connects, so two connection loops never share the
    device. Switching back connects ilab-614 exactly once.
    """
    connects = []

    async def fake_connect(driver):
        connects.append(driver._machine.name)

    monkeypatch.setattr(RuidaDriver, "_connect_implementation", fake_connect)
    manager = lite_context.machine_mgr
    machines = []
    for profile in (ILAB_614_PROFILE, ILAB_626_PROFILE):
        data = copy.deepcopy(profile)
        # Never let a test dial out to a real machine.
        data["machine"]["driver_args"]["connection"] = "udp"
        data["machine"]["driver_args"]["host"] = "192.0.2.1"
        machine = Machine.from_dict(data, context=lite_context)
        manager.add_machine(machine)
        machines.append(machine)
    ilab_614, ilab_626 = machines
    assert ilab_614.auto_connect and ilab_626.auto_connect
    lite_context.config.set_machine(ilab_614)
    manager.get_controller(ilab_614.id)
    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)
    assert manager.set_active_machine(ilab_626) is True
    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)
    assert connects == ["ilab-614", "ilab-626"]
    released_driver = manager.controllers[ilab_614.id].driver

    ilab_614.set_driver_args({**ilab_614.driver_args, "host": "192.0.2.2"})
    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)

    assert connects == ["ilab-614", "ilab-626"]
    driver = manager.controllers[ilab_614.id].driver
    assert driver is not released_driver
    assert driver.host == "192.0.2.2"

    assert manager.set_active_machine(ilab_614) is True
    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)

    assert connects == ["ilab-614", "ilab-626", "ilab-614"]
    for controller in list(manager.controllers.values()):
        await controller.shutdown()


def _udp_pair(context, monkeypatch, connects):
    """
    Both bundled profiles on UDP to a documentation address, with the
    Ruida connect faked to record which machine connected.
    """

    async def fake_connect(driver):
        connects.append(driver._machine.name)

    monkeypatch.setattr(RuidaDriver, "_connect_implementation", fake_connect)
    manager = context.machine_mgr
    machines = []
    for profile in (ILAB_614_PROFILE, ILAB_626_PROFILE):
        data = copy.deepcopy(profile)
        # Never let a test dial out to a real machine.
        data["machine"]["driver_args"]["connection"] = "udp"
        data["machine"]["driver_args"]["host"] = "192.0.2.1"
        machine = Machine.from_dict(data, context=context)
        manager.add_machine(machine)
        machines.append(machine)
    return manager, machines[0], machines[1]


async def _settle(task_mgr: TaskManager):
    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)


@pytest.mark.asyncio
async def test_a_switch_that_fails_to_land_reconnects_the_active_machine(
    lite_context, task_mgr: TaskManager, monkeypatch
):
    """
    A config.changed receiver raises while switching back to ilab-614:
    ilab-614 is the active machine, so it gets its driver back and
    connects, instead of staying released and silent.
    """
    connects = []
    manager, ilab_614, ilab_626 = _udp_pair(
        lite_context, monkeypatch, connects
    )
    lite_context.config.set_machine(ilab_614)
    manager.get_controller(ilab_614.id)
    await _settle(task_mgr)
    assert manager.set_active_machine(ilab_626) is True
    await _settle(task_mgr)
    armed = [True]

    def bad_receiver(sender, **kwargs):
        if armed:
            armed.clear()
            raise RuntimeError("a UI handler failed")

    lite_context.config.changed.connect(bad_receiver, weak=False)
    try:
        assert manager.set_active_machine(ilab_614) is True
        await _settle(task_mgr)
    finally:
        lite_context.config.changed.disconnect(bad_receiver)

    assert lite_context.config.machine is ilab_614
    assert manager.controllers[ilab_614.id]._released is False
    assert connects == ["ilab-614", "ilab-626", "ilab-614"]
    for controller in list(manager.controllers.values()):
        await controller.shutdown()


@pytest.mark.asyncio
async def test_a_release_that_fails_keeps_the_old_machine_connected(
    lite_context, task_mgr: TaskManager, monkeypatch
):
    """
    The old driver's cleanup raises: the switch never lands, ilab-614
    stays active and is connected again, and ilab-626 never connects.
    """
    connects = []
    manager, ilab_614, ilab_626 = _udp_pair(
        lite_context, monkeypatch, connects
    )
    lite_context.config.set_machine(ilab_614)
    manager.get_controller(ilab_614.id)
    await _settle(task_mgr)
    real_cleanup = RuidaDriver.cleanup
    armed = [True]

    async def failing_cleanup(driver):
        if armed:
            armed.clear()
            raise OSError("the port did not close")
        await real_cleanup(driver)

    monkeypatch.setattr(RuidaDriver, "cleanup", failing_cleanup)

    assert manager.set_active_machine(ilab_626) is True
    await _settle(task_mgr)

    assert lite_context.config.machine is ilab_614
    assert manager.controllers[ilab_614.id]._released is False
    assert connects == ["ilab-614", "ilab-614"]
    for controller in list(manager.controllers.values()):
        await controller.shutdown()


@pytest.mark.asyncio
async def test_an_inactive_machine_never_connects_when_its_driver_is_used(
    lite_context, task_mgr: TaskManager, monkeypatch
):
    """
    Asking the inactive bundled machine for its driver builds a
    controller for it; that controller starts released, so nothing
    but the active machine connects.
    """
    connects = []
    manager, ilab_614, ilab_626 = _udp_pair(
        lite_context, monkeypatch, connects
    )
    lite_context.config.set_machine(ilab_614)
    manager.get_controller(ilab_614.id)
    await _settle(task_mgr)

    ilab_626.supports_pwm()
    await _settle(task_mgr)
    await manager.get_controller(ilab_626.id).connect()

    assert manager.controllers[ilab_626.id]._released is True
    assert connects == ["ilab-614"]

    assert manager.set_active_machine(ilab_626) is True
    await _settle(task_mgr)
    assert connects == ["ilab-614", "ilab-626"]
    for controller in list(manager.controllers.values()):
        await controller.shutdown()


@pytest.mark.asyncio
async def test_a_switch_releases_the_old_machine_before_the_new_connects(
    lite_context, task_mgr: TaskManager
):
    """
    Both profiles reach the same controller. The switch releases the
    old machine's driver for good, then makes the new machine active
    (saved in config.yaml), then builds and connects the new driver.
    The old driver is never rebuilt or reconnected.
    """
    manager, ilab_614, ilab_626 = _bundled_pair(lite_context)
    for machine in (ilab_614, ilab_626):
        machine.auto_connect = False
    lite_context.config.set_machine(ilab_614)
    events = []
    old, new = AsyncMock(), AsyncMock()
    old.release.side_effect = lambda: events.append("release ilab-614")
    new.rebuild_driver.side_effect = lambda: events.append(
        "rebuild ilab-626"
    )
    manager.controllers[ilab_614.id] = old
    manager.controllers[ilab_626.id] = new

    def on_config_changed(sender, **kwargs):
        events.append(f"active {lite_context.config.machine.name}")

    lite_context.config.changed.connect(on_config_changed)

    assert manager.set_active_machine(ilab_626) is True
    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)

    assert events == [
        "release ilab-614",
        "active ilab-626",
        "rebuild ilab-626",
    ]
    assert lite_context.config.machine is ilab_626
    old.rebuild_driver.assert_not_awaited()
    old.connect.assert_not_awaited()
    old.disconnect.assert_not_awaited()
    saved = await asyncio.to_thread(lite_context.config_mgr.filepath.read_text)
    assert yaml.safe_load(saved)["machine"] == ilab_626.id


@pytest.mark.asyncio
async def test_a_switch_swaps_per_machine_settings_and_keeps_shared_ones(
    lite_context, task_mgr: TaskManager
):
    """
    Per machine, in each profile's own file: the bed, the Cut Scale
    values, the connection and USB device, the start corner, the
    machine hours and the last job's start. Shared, in config.yaml and
    the materials and recipes dirs: everything else. A switch changes
    which profile is active and nothing else; no value is copied
    between profiles.
    """
    from swiftcut import config as config_module
    from swiftcut.machine.models.machine import StartCorner

    manager, ilab_614, ilab_626 = _bundled_pair(lite_context)
    for machine in (ilab_614, ilab_626):
        machine.auto_connect = False
    ilab_626.driver_args = {**ilab_626.driver_args, "usb_serial": "BBB"}
    ilab_626.cut_scale_speed_mm_s = 15.0
    ilab_626.start_corner = StartCorner.BOTTOM_RIGHT
    ilab_626.set_last_job_start((120.0, 80.0))
    manager.save_machine(ilab_626)
    config = lite_context.config
    config.set_machine(ilab_614)
    config.set_theme("dark")
    config.set_unit_preference("speed", "mm/min")
    ilab_614_file = manager.filename_from_id(ilab_614.id)
    ilab_614_bytes = ilab_614_file.read_bytes()
    shared_before = yaml.safe_load(
        await asyncio.to_thread(lite_context.config_mgr.filepath.read_text)
    )
    manager.controllers[ilab_614.id] = AsyncMock()
    manager.controllers[ilab_626.id] = AsyncMock()

    manager.set_active_machine(ilab_626)
    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)

    active = config.machine
    assert active is ilab_626
    assert active.axis_extents == (900.0, 900.0)
    assert active.cut_scale_speed_mm_s == 15.0
    assert active.cut_scale_power_pct == 30.0
    assert active.driver_args["connection"] == "usb"
    assert active.driver_args["usb_serial"] == "BBB"
    assert active.start_corner == StartCorner.BOTTOM_RIGHT
    assert active.machine_hours.total_hours == 0.0
    assert active.last_job_start == (120.0, 80.0)
    assert ilab_614.axis_extents == (1400.0, 900.0)
    assert ilab_614.last_job_start is None
    assert "usb_serial" not in ilab_614.driver_args
    assert ilab_614.start_corner == StartCorner.TOP_LEFT
    assert ilab_614.machine_hours.total_hours > 0
    assert ilab_614_file.read_bytes() == ilab_614_bytes

    shared_after = yaml.safe_load(
        await asyncio.to_thread(lite_context.config_mgr.filepath.read_text)
    )
    assert shared_before.pop("machine") == ilab_614.id
    assert shared_after.pop("machine") == ilab_626.id
    assert shared_after == shared_before
    assert shared_after["theme"] == "dark"
    assert shared_after["unit_preferences"]["speed"] == "mm/min"
    for shared_dir in (
        config_module.USER_MATERIALS_DIR,
        config_module.USER_RECIPES_DIR,
    ):
        assert config_module.MACHINE_DIR not in shared_dir.parents

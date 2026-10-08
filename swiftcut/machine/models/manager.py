import asyncio
import copy
import logging
from pathlib import Path
from typing import Optional

import yaml
from blinker import Signal

from ...context import get_context
from ...shared.tasker import task_mgr
from ..driver import RuidaDriver, get_driver_cls
from ..driver.driver import ResourceBusyError
from .controller import MachineController
from .default_profile import BUNDLED_NAMES, BUNDLED_PROFILES
from .machine import Machine

logger = logging.getLogger(__name__)

# The task key of a machine switch: one switch at a time.
SWITCH_TASK_KEY = "switch-machine"


class MachineManager:
    def __init__(self, base_dir: Path):
        base_dir.mkdir(parents=True, exist_ok=True)
        self.base_dir = base_dir
        self.controllers: dict[str, MachineController] = {}
        self.machines: dict[str, Machine] = {}
        self.machine_added = Signal()
        self.machine_removed = Signal()
        self.machine_updated = Signal()
        self.load()

    def initialize_connections(self):
        """
        Triggers the initial connection of the active machine, if it has
        auto_connect enabled. The other profiles never connect: both
        bundled machines reach the same controller. This is called after
        the UI is fully initialized to ensure proper signal handling
        during connection attempts.
        """
        machine = get_context().config.machine
        if machine and machine.auto_connect and not machine.is_connected():
            task_mgr.add_coroutine(
                lambda ctx: self._rebuild_and_connect_machine(machine),
                key=(machine.id, "initial-connect"),
            )

    async def shutdown(self):
        """
        Shuts down all managed machine controllers and their drivers
        gracefully.
        """
        logger.info("Shutting down all machine controllers.")
        tasks = [
            controller.shutdown() for controller in self.controllers.values()
        ]
        if tasks:
            await asyncio.gather(*tasks)
        logger.info("All machine controllers shut down.")

    def get_controller(self, machine_id: str) -> "MachineController":
        """
        Gets the controller for a machine, creating it if it doesn't exist.
        This enables lazy instantiation of controllers.
        """
        if machine_id in self.controllers:
            return self.controllers[machine_id]

        machine = self.get_machine_by_id(machine_id)
        if not machine:
            raise ValueError(f"No machine found with ID {machine_id}")

        logger.debug(
            f"Creating controller for machine '{machine.name}' on first use."
        )
        # A bundled machine that is not the active one shares the
        # active machine's device: its driver is built, never connected.
        active = get_context().config.machine
        released = (
            active is not None
            and active is not machine
            and machine in self.switchable_machines()
        )
        controller = MachineController(
            machine,
            get_context(),
            task_mgr.schedule_on_main_thread,
            released=released,
        )

        # Wire up the machine's signal proxies to the new controller
        machine._connect_controller_signals(controller)

        self.controllers[machine_id] = controller
        return controller

    def has_controller(self, machine_id: str) -> bool:
        """
        Returns whether a controller has already been instantiated for the
        given machine. Unlike ``get_controller``, this never lazily creates
        a controller and never raises, so it is safe to call for machines
        that have already been removed.
        """
        return machine_id in self.controllers

    async def _rebuild_and_connect_machine(self, machine: "Machine"):
        """
        A single, sequenced task that rebuilds a machine's driver and then
        connects if auto_connect is on.
        """
        controller = self.get_controller(machine.id)
        # Only rebuild if not already connected to avoid disconnecting
        if not machine.is_connected():
            await controller.rebuild_driver()
        if machine.auto_connect and not machine.is_connected():
            await self._safe_connect(machine)

    async def _safe_connect(self, machine: "Machine"):
        """
        Attempts to connect a machine, suppressing ResourceBusyErrors.
        """
        try:
            await machine.connect()
        except ResourceBusyError:
            context = get_context()
            if machine is context.config.machine:
                logger.warning(
                    f"Active machine '{machine.name}' could not connect "
                    "because resource is busy."
                )
            else:
                logger.debug(
                    f"Inactive machine '{machine.name}' deferred connection: "
                    "resource busy."
                )
        except Exception as e:  # noqa: BLE001 - async auto-connect task
            logger.error(
                f"Failed to auto-connect machine '{machine.name}': {e}"
            )

    def set_active_machine(self, new_machine: Machine) -> bool:
        """
        Makes a bundled machine the active one, handling the connection
        lifecycle for the controller both profiles share. Returns False
        when the switch is refused.
        """
        context = get_context()
        old_machine = context.config.machine

        if old_machine and old_machine.id == new_machine.id:
            return False  # No change
        if new_machine not in self.switchable_machines():
            logger.warning(
                f"Not switching to '{new_machine.name}': "
                "not a bundled machine"
            )
            return False
        # A second request would replace (cancel) the switch in flight.
        if task_mgr.get_task(SWITCH_TASK_KEY) is not None:
            logger.warning(
                f"Not switching to '{new_machine.name}': "
                "a machine switch is in progress"
            )
            return False

        logger.info(f"Switching active machine to '{new_machine.name}'")

        async def switch_routine(ctx):
            try:
                # 1. Release the old machine's driver. Unlike
                #    disconnect(), release() never rebuilds or
                #    reconnects it, so the port is free for the new one.
                if old_machine and self.has_controller(old_machine.id):
                    logger.info(
                        f"Releasing previous machine '{old_machine.name}'"
                    )
                    await self.controllers[old_machine.id].release()
                    # Add a small delay for the OS to release the port
                    await asyncio.sleep(0.2)

                # 2. Update the global config. This triggers UI updates,
                #    so it must run on the main thread (GTK is not
                #    thread-safe).
                await task_mgr.run_on_main_thread(
                    context.config.set_machine, new_machine
                )
            except Exception as e:  # noqa: BLE001 - async switch task
                logger.error(
                    f"Switching to machine '{new_machine.name}' failed: {e}"
                )

            # 3. Whichever machine is active now gets its driver back:
            #    the new one, or the old one when the switch failed
            #    before it landed. It connects if set to auto-connect.
            await self._connect_active_machine()

        task_mgr.add_coroutine(switch_routine, key=SWITCH_TASK_KEY)
        return True

    async def _connect_active_machine(self):
        """
        Builds the active machine's driver, released or not, and
        connects it if it is set to auto-connect.
        """
        machine = get_context().config.machine
        if machine is None:
            return
        logger.info(f"Connecting active machine '{machine.name}'")
        try:
            controller = self.get_controller(machine.id)
            controller._released = False
            await controller.rebuild_driver()
        except ResourceBusyError:
            logger.warning(
                f"Active machine '{machine.name}' could not connect "
                "because resource is busy."
            )
        except Exception as e:  # noqa: BLE001 - async switch task
            logger.error(
                f"Failed to connect machine '{machine.name}' "
                f"after the switch: {e}"
            )

    def filename_from_id(self, machine_id: str) -> Path:
        return self.base_dir / f"{machine_id}.yaml"

    def add_machine(self, machine: Machine):
        if machine.id in self.machines:
            return
        if any(m.name == machine.name for m in self.switchable_machines()):
            logger.warning(
                f"Not adding machine '{machine.name}': a bundled machine "
                "has that name"
            )
            return
        self.machines[machine.id] = machine
        machine.changed.connect(self.on_machine_changed)
        self.save_machine(machine)
        self.machine_added.send(self, machine_id=machine.id)

    def remove_machine(self, machine_id: str) -> bool:
        machine = self.machines.get(machine_id)
        if not machine:
            return False
        if machine in self.switchable_machines():
            logger.warning(
                f"Not removing machine '{machine.name}': it is bundled"
            )
            return False

        # Shut down and remove the associated controller if it exists
        if machine_id in self.controllers:
            controller = self.controllers.pop(machine_id)
            # Shutdown is async, so schedule it
            task_mgr.add_coroutine(lambda ctx: controller.shutdown())

        machine.changed.disconnect(self.on_machine_changed)
        machine.context.dialect_mgr.dialects_changed.disconnect(
            machine._on_dialects_changed
        )
        del self.machines[machine_id]

        machine_file = self.filename_from_id(machine_id)
        try:
            machine_file.unlink()
            logger.info(f"Removed machine file: {machine_file}")
        except OSError as e:
            logger.error(f"Error removing machine file {machine_file}: {e}")

        self.machine_removed.send(self, machine_id=machine_id)
        return True

    def get_machine_by_id(self, machine_id):
        return self.machines.get(machine_id)

    def get_machines(self) -> list["Machine"]:
        """Returns a list of all managed machines, sorted by name."""
        return sorted(self.machines.values(), key=lambda m: m.name)

    def create_default_machine(self, profile: dict) -> Machine:
        """Adds a machine built from a bundled profile."""
        machine = Machine.from_dict(
            copy.deepcopy(profile), context=get_context()
        )
        self.add_machine(machine)
        return machine

    @staticmethod
    def has_driver(machine) -> bool:
        name = machine.driver_name or ""
        return get_driver_cls(name, default=None) is not None

    def ensure_default_machine(self) -> list[Machine]:
        """
        Seeds the bundled profiles and returns the machines it added.
        With no profile that has a resolvable driver, every bundled
        profile is seeded. When a bundled machine already exists, only
        the bundled names still missing are added; existing files are
        never rewritten. Otherwise nothing is seeded. Driverless
        profiles are left on disk untouched.
        """
        for m in self.machines.values():
            if not self.has_driver(m):
                logger.warning(
                    "Machine '%s' (%s) has no resolvable driver %r; "
                    "kept, never auto-selected",
                    m.name,
                    m.id,
                    m.driver_name,
                )
        drivered = [m for m in self.machines.values() if self.has_driver(m)]
        if drivered and not self.switchable_machines():
            return []
        present = {m.name for m in drivered}
        return [
            self.create_default_machine(profile)
            for profile in BUNDLED_PROFILES
            if profile["machine"]["name"] not in present
        ]

    def switchable_machines(self) -> list[Machine]:
        """
        The bundled machines, in bundled order: for each bundled name,
        the machine of that name with a resolvable driver (the lowest
        id if there are several). Reads names and ids only, so it never
        creates a controller.
        """
        by_name: dict[str, Machine] = {}
        for m in sorted(self.machines.values(), key=lambda m: m.id):
            if m.name in BUNDLED_NAMES and self.has_driver(m):
                by_name.setdefault(m.name, m)
        return [by_name[name] for name in BUNDLED_NAMES if name in by_name]

    def pick_auto_machine(self) -> Machine | None:
        """
        Returns the first bundled machine, else the min-by-id machine
        with a driver, or None.
        """
        switchable = self.switchable_machines()
        if switchable:
            return switchable[0]
        candidates = [m for m in self.machines.values() if self.has_driver(m)]
        return min(candidates, key=lambda m: m.id, default=None)

    def save_machine(self, machine):
        logger.debug(f"Saving machine {machine.id}")
        machine_file = self.filename_from_id(machine.id)
        try:
            data = machine.to_dict(include_frozen_dialect=False)
            content = yaml.safe_dump(data)
        except Exception as e:
            logger.error(f"Failed to serialize machine {machine.id}: {e}")
            raise
        with open(machine_file, "w") as f:
            f.write(content)

    def load_machine(self, machine_id: str) -> Optional["Machine"]:
        machine_file = self.filename_from_id(machine_id)
        if not machine_file.exists():
            raise FileNotFoundError(f"Machine file {machine_file} not found")
        with open(machine_file, "r") as f:
            data = yaml.safe_load(f)
            if not data:
                msg = f"skipping invalid machine file {f.name}"
                logger.warning(msg)
                return None
        machine = Machine.from_dict(data, context=get_context())
        machine.id = machine_id
        self.machines[machine.id] = machine
        machine.changed.connect(self.on_machine_changed)
        logger.info(f"Loaded machine '{machine.name}' from {machine_file}")

        # Profile sanity check: flags a Ruida profile whose ports
        # drifted from the ilab-614 defaults (see the silent-timeout
        # investigation this closes). Logging only -- the file is
        # never rewritten here; only the Diagnostics "Reset ports to
        # defaults" button does that, on an explicit click.
        if machine.driver_name == "RuidaDriver":
            port_mismatches = RuidaDriver.port_mismatches(
                machine.driver_args
            )
            if port_mismatches:
                logger.warning(
                    "Machine '%s' has non-default Ruida ports: %s "
                    "(Device > Diagnostics can reset them)",
                    machine.name,
                    port_mismatches,
                )

        if machine.dialect_migrated:
            logger.info(
                f"Saving machine '{machine.name}' after dialect migration."
            )
            self.save_machine(machine)
            machine.dialect_migrated = False

        return machine

    def on_machine_changed(self, machine, **kwargs):
        self.save_machine(machine)
        self.machine_updated.send(self, machine_id=machine.id)

    def load(self):
        for file in self.base_dir.glob("*.yaml"):
            try:
                self.load_machine(file.stem)
            except (OSError, ValueError, TypeError, yaml.YAMLError) as e:
                logger.error(f"Failed to load machine from {file}: {e}")

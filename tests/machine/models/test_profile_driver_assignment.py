from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

from swiftcut.config import BUILTIN_DEVICES_DIR
from swiftcut.machine.device.profile import DeviceProfile
from swiftcut.machine.driver.dummy import NoDeviceDriver
from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.shared import tasker

if TYPE_CHECKING:
    from swiftcut.context import RayforgeContext
    from swiftcut.machine.models.machine import Machine


@pytest_asyncio.fixture
async def omtech_polar_machine(
    context_initializer: "RayforgeContext",
) -> "Machine":
    """Provides a Machine instance from the OMTech Polar device."""
    pkg = DeviceProfile.from_path(BUILTIN_DEVICES_DIR / "omtech-polar")
    machine = pkg.create_machine(context_initializer)
    context_initializer.machine_mgr.add_machine(machine)

    tasker.task_mgr.wait_until_settled(5000)

    return machine


@pytest.mark.asyncio
async def test_omtech_polar_driver_assignment(
    omtech_polar_machine: "Machine",
):
    """
    Tests that creating a machine from the OMTech Polar device
    correctly assigns the RuidaDriver instead of NoDeviceDriver.
    """
    machine = omtech_polar_machine

    assert machine.driver_name == "RuidaDriver", (
        f"Expected driver_name to be 'RuidaDriver', "
        f"got '{machine.driver_name}'"
    )

    controller = machine.controller
    tasker.task_mgr.wait_until_settled(5000)

    assert not isinstance(controller.driver, NoDeviceDriver), (
        "Driver should not be NoDeviceDriver after device creation"
    )

    assert isinstance(controller.driver, RuidaDriver), (
        f"Expected driver to be RuidaDriver, "
        f"got {type(controller.driver).__name__}"
    )

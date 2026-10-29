"""
Backend entry point for laser-essentials addon.

Registers steps with the main application.
"""

from swiftcut.core.hooks import hookimpl

from .steps import (
    ContourStep,
    EngraveStep,
    FrameStep,
    MaterialTestStep,
    ScanStep,
)

ADDON_NAME = "laser_essentials"


@hookimpl
def register_steps(step_registry):
    """Register steps with the step registry.

    The order is the order of the add-step menu.
    """
    step_registry.register(ContourStep, addon_name=ADDON_NAME)
    step_registry.register(EngraveStep, addon_name=ADDON_NAME)
    step_registry.register(ScanStep, addon_name=ADDON_NAME)
    step_registry.register(FrameStep, addon_name=ADDON_NAME)
    step_registry.register(MaterialTestStep, addon_name=ADDON_NAME)

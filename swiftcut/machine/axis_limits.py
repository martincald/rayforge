"""
The controller's own axis limits, beside the profile's bed.

A profile copied from another machine can carry the wrong bed: the
Ruida driver clamps every jog target to the profile's extents, so a
controller that travels further than the profile says can never reach
the rest of its bed. This reads what the controller itself reports,
for the Device page's Diagnostics group.

Register addresses are from ruida_maps.py: X is axis 1 (base 0x20)
and Y axis 2 (base 0x30), the range at base + 6 and the home offset
at base + 0xA; the current position is at 0x0421 / 0x0431.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from gettext import gettext as _
from typing import TYPE_CHECKING

from .driver.ruida.ruida_driver import RuidaDriver

if TYPE_CHECKING:
    from .driver.driver import Driver
    from .models.machine import Machine

logger = logging.getLogger(__name__)

# (axis, range, home offset, current position)
_REGISTERS = (
    ("X", 0x0026, 0x002A, 0x0421),
    ("Y", 0x0036, 0x003A, 0x0431),
)
_ADDRESSES = {address for _axis, *regs in _REGISTERS for address in regs}

# How long each read waits for its reply, in seconds.
READ_TIMEOUT = 2.0
# A controller range this close to the profile's extent agrees with it.
RANGE_TOLERANCE_MM = 0.5


class AxisLimitsRefused(Exception):
    """The limits were not read; the message says why."""


def _mm(value_um: int | None) -> float | None:
    return None if value_um is None else value_um / 1000


def _format_mm(value_um: int | None) -> str:
    value_mm = _mm(value_um)
    if value_mm is None:
        return _("no reply")
    return _("{value:.1f} mm").format(value=value_mm)


@dataclass(frozen=True)
class AxisLimits:
    """
    One axis as the controller reports it, in micrometres (None where
    a read got no reply), beside the profile's extent for it in mm.
    """

    axis: str
    range_um: int | None
    home_offset_um: int | None
    position_um: int | None
    profile_mm: float

    @property
    def range_mm(self) -> float | None:
        return _mm(self.range_um)

    @property
    def home_offset_mm(self) -> float | None:
        return _mm(self.home_offset_um)

    @property
    def position_mm(self) -> float | None:
        return _mm(self.position_um)

    @property
    def range_differs(self) -> bool:
        range_mm = self.range_mm
        return (
            range_mm is not None
            and abs(range_mm - self.profile_mm) > RANGE_TOLERANCE_MM
        )

    @property
    def has_home_offset(self) -> bool:
        return bool(self.home_offset_um)

    @property
    def mismatch(self) -> bool:
        return self.range_differs or self.has_home_offset

    def describe(self) -> str:
        """The values, and what to do about a mismatch, one per line."""
        lines = [
            _(
                "Controller: range {range}, home offset {offset}, "
                "position {position}"
            ).format(
                range=_format_mm(self.range_um),
                offset=_format_mm(self.home_offset_um),
                position=_format_mm(self.position_um),
            ),
            _("Profile: {extent:.1f} mm").format(extent=self.profile_mm),
        ]
        if self.range_differs:
            lines.append(
                _(
                    "Profile {axis} {profile:.1f} mm, controller "
                    "{controller:.1f} mm: set {axis} Extent (Hardware "
                    "page) to {controller:.1f} mm"
                ).format(
                    axis=self.axis,
                    profile=self.profile_mm,
                    controller=self.range_mm,
                )
            )
        if self.has_home_offset:
            lines.append(
                _(
                    "Home offset {offset:.1f} mm is set on the "
                    "controller; SwiftCut does not apply it"
                ).format(offset=self.home_offset_mm)
            )
        return "\n".join(lines)


def refusal(driver: Driver, job_running: bool = False) -> str | None:
    """
    Why the limits cannot be read now, or None when they can.

    A read interleaved with a job or with interactive motion would
    break the busy interlock (MOTION_AUDIT.md), so both refuse it.
    """
    if not isinstance(driver, RuidaDriver):
        return _("Only a Ruida controller reports its axis limits.")
    if driver._client is None or not driver._is_connected:
        return _("Not read: the controller is not connected.")
    if job_running or driver._job_running:
        return _("Not read: a job is running. Wait for it to finish.")
    if driver._jog_busy:
        return _("Not read: the head is moving. Wait for it to stop.")
    return None


async def read_axis_limits(
    machine: Machine, job_running: bool = False
) -> list[AxisLimits]:
    """
    Read range, home offset and position for X and Y from the
    machine's controller, beside the machine's own axis extents.

    Every DA 01 reply for those registers that arrives meanwhile is
    logged raw, then one summary line per axis.

    Raises:
        AxisLimitsRefused: The machine is not a connected, idle Ruida
            controller; nothing was sent.
    """
    driver = machine.driver
    reason = refusal(driver, job_running)
    if reason is not None:
        raise AxisLimitsRefused(reason)
    assert isinstance(driver, RuidaDriver) and driver._client is not None
    client = driver._client

    def log_reply(sender, data: bytes) -> None:
        if (
            len(data) >= 9
            and data[:2] == b"\xda\x01"
            and int.from_bytes(data[2:4], "big") in _ADDRESSES
        ):
            logger.info(f"Axis limits reply: {data.hex(' ')}")

    received = client._transport.decoded_received
    received.connect(log_reply, weak=False)
    try:
        values = []
        for _axis, *registers in _REGISTERS:
            values.append(
                [
                    await client._read_memory_wait(address, READ_TIMEOUT)
                    for address in registers
                ]
            )
    finally:
        received.disconnect(log_reply)

    limits = [
        AxisLimits(axis, *axis_values, profile_mm=float(extent))
        for (axis, *_registers), axis_values, extent in zip(
            _REGISTERS, values, machine.axis_extents
        )
    ]
    for limit in limits:
        logger.info(
            f"Axis limits {limit.axis}: range {limit.range_um} um, "
            f"home offset {limit.home_offset_um} um, position "
            f"{limit.position_um} um (None: no reply); profile "
            f"{limit.profile_mm} mm; range differs: "
            f"{limit.range_differs}, home offset set: "
            f"{limit.has_home_offset}"
        )
    return limits

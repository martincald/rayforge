"""
Reading the controller's own axis limits beside the profile's bed
(swiftcut/machine/axis_limits.py), against the in-repo Ruida
simulator behind a RuidaClient on an in-memory transport.
"""

import logging

import pytest
from blinker import Signal

from swiftcut.machine import axis_limits
from swiftcut.machine.axis_limits import (
    AxisLimits,
    AxisLimitsRefused,
    read_axis_limits,
)
from swiftcut.machine.driver.dummy import NoDeviceDriver
from swiftcut.machine.driver.ruida.ruida_client import RuidaClient
from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.machine.driver.ruida.ruida_simulator import RuidaSimulator
from swiftcut.machine.models.machine import Machine


class SimulatorTransport:
    """
    A RuidaTransport stand-in answered by the simulator: an ACK, then
    the reply, the way the controller answers a DA read. Reads of the
    silent addresses go unanswered.
    """

    def __init__(self, simulator: RuidaSimulator, silent=()):
        self.decoded_received = Signal()
        self.status_changed = Signal()
        self.is_connected = True
        self.sent: list[bytes] = []
        self._simulator = simulator
        self._silent = set(silent)

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def send_command(self, command: bytes):
        self.sent.append(command)
        if int.from_bytes(command[2:4], "big") in self._silent:
            return
        reply = self._simulator.process_commands(command)
        self.decoded_received.send(self, data=b"\xcc")
        if reply:
            self.decoded_received.send(self, data=reply)


@pytest.fixture
def simulator():
    """A controller with a 1300 x 900 mm range, X homed 5 mm in."""
    sim = RuidaSimulator()
    sim.state.bed_x = 1_300_000
    sim.state.bed_y = 900_000
    sim.state.memory_values[0x002A] = 5000
    sim.x = 412_500
    sim.y = 100_000
    return sim


def _connect(lite_context, monkeypatch, simulator, silent=()):
    """An ilab-626-sized machine whose Ruida driver is connected."""
    machine = Machine(lite_context)
    machine.set_axis_extents(900.0, 900.0)
    driver = RuidaDriver(lite_context, machine)
    transport = SimulatorTransport(simulator, silent)
    driver._client = RuidaClient(transport)
    driver._is_connected = True
    monkeypatch.setattr(Machine, "driver", property(lambda self: driver))
    return machine, driver, transport


@pytest.mark.asyncio
async def test_reads_range_home_offset_and_position_per_axis(
    lite_context, monkeypatch, simulator
):
    machine, _driver, transport = _connect(
        lite_context, monkeypatch, simulator
    )

    x, y = await read_axis_limits(machine)

    assert x == AxisLimits("X", 1_300_000, 5000, 412_500, 900.0)
    assert y == AxisLimits("Y", 900_000, 0, 100_000, 900.0)
    assert (x.range_mm, x.home_offset_mm, x.position_mm) == (
        1300.0,
        5.0,
        412.5,
    )
    assert x.range_differs and x.has_home_offset and x.mismatch
    assert not (y.range_differs or y.has_home_offset or y.mismatch)
    assert transport.sent == [
        bytes([0xDA, 0x00, address >> 8, address & 0xFF])
        for address in (0x0026, 0x002A, 0x0421, 0x0036, 0x003A, 0x0431)
    ]


@pytest.mark.asyncio
async def test_the_profile_extent_is_the_machines_own(
    lite_context, monkeypatch, simulator
):
    machine, _driver, _transport = _connect(
        lite_context, monkeypatch, simulator
    )
    machine.set_axis_extents(1300.2, 600.0)

    x, y = await read_axis_limits(machine)

    assert (x.profile_mm, y.profile_mm) == (1300.2, 600.0)
    assert not x.range_differs  # within the 0.5 mm tolerance
    assert y.range_differs


@pytest.mark.asyncio
async def test_a_read_that_times_out_is_no_reply(
    lite_context, monkeypatch, simulator
):
    monkeypatch.setattr(axis_limits, "READ_TIMEOUT", 0.05)
    machine, _driver, _transport = _connect(
        lite_context, monkeypatch, simulator, silent={0x003A}
    )

    x, y = await read_axis_limits(machine)

    assert x.home_offset_um == 5000
    assert y.home_offset_um is None
    assert y.home_offset_mm is None
    assert not y.has_home_offset
    assert y.range_um == 900_000
    assert "home offset no reply" in y.describe()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state, message",
    [
        ({"_job_running": True}, "a job is running"),
        ({"_jog_busy": True}, "the head is moving"),
        ({"_is_connected": False}, "not connected"),
        ({"_client": None}, "not connected"),
    ],
)
async def test_refused_while_busy_or_offline_and_nothing_is_sent(
    lite_context, monkeypatch, simulator, state, message
):
    machine, driver, transport = _connect(lite_context, monkeypatch, simulator)
    for name, value in state.items():
        setattr(driver, name, value)

    with pytest.raises(AxisLimitsRefused, match=message):
        await read_axis_limits(machine)

    assert transport.sent == []


@pytest.mark.asyncio
async def test_refused_while_a_start_prepares_a_job(
    lite_context, monkeypatch, simulator
):
    """MachineCmd.is_job_running, before the driver has the job."""
    machine, _driver, transport = _connect(
        lite_context, monkeypatch, simulator
    )

    with pytest.raises(AxisLimitsRefused, match="a job is running"):
        await read_axis_limits(machine, job_running=True)

    assert transport.sent == []


@pytest.mark.asyncio
async def test_refused_for_a_driver_that_is_not_ruida(
    lite_context, monkeypatch
):
    machine = Machine(lite_context)
    driver = NoDeviceDriver(lite_context, machine)
    monkeypatch.setattr(Machine, "driver", property(lambda self: driver))

    with pytest.raises(AxisLimitsRefused, match="Only a Ruida"):
        await read_axis_limits(machine)


@pytest.mark.asyncio
async def test_raw_replies_and_a_summary_per_axis_are_logged(
    lite_context, monkeypatch, simulator, caplog
):
    machine, _driver, transport = _connect(
        lite_context, monkeypatch, simulator
    )
    caplog.set_level(logging.INFO, logger=axis_limits.__name__)

    await read_axis_limits(machine)

    messages = [
        r.getMessage()
        for r in caplog.records
        if r.name == axis_limits.__name__ and r.levelno == logging.INFO
    ]
    replies = [m for m in messages if m.startswith("Axis limits reply: ")]
    assert [m.split(": ")[1][:11] for m in replies] == [
        "da 01 00 26",
        "da 01 00 2a",
        "da 01 04 21",
        "da 01 00 36",
        "da 01 00 3a",
        "da 01 04 31",
    ]
    # The whole frame, value included: 1300000 um as five 7-bit bytes.
    assert replies[0] == "Axis limits reply: da 01 00 26 00 00 4f 2c 20"
    summaries = [m for m in messages if m.startswith("Axis limits X")]
    assert len(summaries) == 1
    assert "range 1300000 um" in summaries[0]
    assert "range differs: True" in summaries[0]
    assert any(m.startswith("Axis limits Y") for m in messages)
    # The listener is gone afterwards: a later reply is not logged.
    caplog.clear()
    transport.decoded_received.send(
        transport, data=bytes.fromhex("da01002600004f2c20")
    )
    assert not [r for r in caplog.records if r.name == axis_limits.__name__]


def test_the_text_says_which_profile_value_to_set():
    limit = AxisLimits("X", 1_300_000, 0, 412_500, 900.0)

    assert limit.describe() == (
        "Controller: range 1300.0 mm, home offset 0.0 mm, "
        "position 412.5 mm\n"
        "Profile: 900.0 mm\n"
        "Profile X 900.0 mm, controller 1300.0 mm: set X Extent "
        "(Hardware page) to 1300.0 mm"
    )


def test_the_text_says_a_home_offset_is_not_applied():
    limit = AxisLimits("Y", 900_000, -2500, None, 900.0)

    assert limit.describe() == (
        "Controller: range 900.0 mm, home offset -2.5 mm, "
        "position no reply\n"
        "Profile: 900.0 mm\n"
        "Home offset -2.5 mm is set on the controller; SwiftCut does "
        "not apply it"
    )
    assert limit.mismatch and not limit.range_differs

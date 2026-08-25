"""
Tests for RuidaDriver using real RuidaSimulator.

This test suite runs against a real RuidaSimulator instance via UDP,
not mocks, ensuring end-to-end protocol compliance.
"""

import asyncio
import logging
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest
import pytest_asyncio
from blinker import Signal
from raygeo.ops import Ops

from rayforge.core.doc import Doc
from rayforge.machine.driver.driver import Axis
from rayforge.machine.driver.ruida import ruida_driver as driver_mod
from rayforge.machine.driver.ruida.ruida_client import (
    RuidaClient,
    build_datagrams,
)
from rayforge.machine.driver.ruida.ruida_driver import RuidaDriver
from rayforge.machine.driver.ruida.ruida_encoder import (
    RuidaEncoder,
    build_rd_bytes,
    commands_to_rd_bytes,
    export_rd,
)
from rayforge.machine.driver.ruida.ruida_simulator import RuidaSimulator
from rayforge.machine.driver.ruida.ruida_transport import (
    RuidaServerTransport,
    RuidaTransport,
)
from rayforge.machine.driver.ruida.ruida_util import decode35, encode35
from rayforge.machine.models.laser import Laser, LaserType
from rayforge.machine.models.machine import Machine
from rayforge.machine.transport.transport import TransportStatus
from rayforge.machine.transport.udp_server import UdpServerTransport
from rayforge.pipeline.encoder.base import EncodedOutput, MachineCodeOpMap

logger = logging.getLogger(__name__)


async def wait_for_connection(
    driver: RuidaDriver, timeout: float = 2.0
) -> bool:
    """Wait for driver to establish connection."""
    await driver.connect()
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if driver.is_connected:
            return True
        await asyncio.sleep(0.05)
    return False


async def wait_for_cached_position(
    driver: RuidaDriver,
    x_um: int | None = None,
    y_um: int | None = None,
    timeout: float = 10.0,
) -> bool:
    """Wait for the driver's polled position cache to match."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        pos = driver.state.machine_pos
        x_ok = x_um is None or int((pos[0] or 0.0) * 1000) == x_um
        y_ok = y_um is None or int((pos[1] or 0.0) * 1000) == y_um
        if x_ok and y_ok:
            return True
        await asyncio.sleep(0.05)
    return False


@pytest_asyncio.fixture
async def ruida_simulator():
    """
    Provides a running RuidaSimulator with UDP transport.

    The simulator runs in a background task and is automatically
    stopped after each test.
    """
    sim = RuidaSimulator()
    host = "127.0.0.1"

    main_udp = UdpServerTransport(host, 0)
    main_transport = RuidaServerTransport(main_udp, magic=0x88)
    jog_transport = UdpServerTransport(host, 0)

    async def handle_main_decoded(sender, data: bytes, addr):
        response = sim.process_commands(data)
        if response == b"\xcc" or not response:
            await main_transport.send_response(b"\xcc", addr)
        else:
            await main_transport.send_response(b"\xcc", addr)
            await main_transport.send_response(response, addr)

    async def handle_jog(sender, data: bytes, addr):
        logger.debug(f"Jog received: {data.hex()} from {addr}")
        response = sim.handle_jog_packet(data)
        if response:
            await jog_transport.send_to(response, addr)

    def on_main_decoded(sender, data: bytes, addr):
        asyncio.create_task(handle_main_decoded(sender, data, addr))

    def on_jog_received(sender, data: bytes, addr):
        asyncio.create_task(handle_jog(sender, data, addr))

    main_transport.decoded_received.connect(on_main_decoded)
    jog_transport.received.connect(on_jog_received)

    await main_transport.connect()
    await jog_transport.connect()

    port = main_udp.port
    jog_port = jog_transport.port

    yield sim, host, port, jog_port

    await main_transport.disconnect()
    await jog_transport.disconnect()


@pytest_asyncio.fixture
async def driver(
    lite_context, ruida_simulator
) -> AsyncGenerator[RuidaDriver, None]:
    """
    Provides a configured RuidaDriver connected to the simulator.

    Uses the host/port from the running simulator fixture.
    """
    _sim, host, port, jog_port = ruida_simulator

    machine = Machine(lite_context)
    machine.driver_name = "RuidaDriver"
    lite_context.machine_mgr.add_machine(machine)

    driver = RuidaDriver(lite_context, machine)
    driver._setup_implementation(
        host=host, port=port, jog_port=jog_port, response_port=0
    )

    yield driver

    await driver.cleanup()
    await machine.shutdown()


@pytest.mark.asyncio
async def test_setup_with_valid_config(driver):
    """Test that driver setup succeeds with valid configuration."""
    assert driver.host is not None
    assert driver.port is not None
    assert driver._udp_transport is not None
    assert driver._ruida_transport is not None
    assert driver._client is not None


@pytest.mark.asyncio
async def test_connect_to_simulator(driver, ruida_simulator):
    """Test that driver can connect to the simulator."""
    assert await wait_for_connection(driver)
    assert driver.is_connected

    await driver.cleanup()


@pytest.mark.asyncio
async def test_move_to_updates_position(driver, ruida_simulator):
    """Test that move_to command updates simulator position."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 0
    sim.y = 0

    await driver.move_to(10.0, 20.0)
    await asyncio.sleep(0.2)

    assert sim.x == 10000
    assert sim.y == 20000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_move_to_negative_position(driver, ruida_simulator):
    """Test that move_to works with negative coordinates."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 0
    sim.y = 0

    await driver.move_to(-5.5, -3.2)
    await asyncio.sleep(0.2)

    assert sim.x == -5500
    assert sim.y == -3200

    await driver.cleanup()


@pytest.mark.asyncio
async def test_home_xy_resets_position(driver, ruida_simulator):
    """Test that home_xy command resets position to zero."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 50000
    sim.y = 100000

    await driver.home()
    await asyncio.sleep(0.2)

    assert sim.x == 0
    assert sim.y == 0

    await driver.cleanup()


@pytest.mark.asyncio
async def test_home_z_axis(driver, ruida_simulator):
    """Test that home command with Z only homes the Z axis."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 100000
    sim.z = 30000

    await driver.home(Axis.Z)
    await asyncio.sleep(0.2)

    assert sim.z == 0
    assert sim.x == 100000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_home_all_axes(driver, ruida_simulator):
    """Test that home with None moves to origin (soft home)."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 100000
    sim.y = 200000
    sim.z = 50000

    await driver.home(None)
    await asyncio.sleep(0.2)

    assert sim.x == 0
    assert sim.y == 0
    assert sim.z == 50000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_home_xy_only(driver, ruida_simulator):
    """Test that home can target only XY axes."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 100000
    sim.y = 200000
    sim.z = 50000

    await driver.home(Axis.X | Axis.Y)
    await asyncio.sleep(0.2)

    assert sim.x == 0
    assert sim.y == 0
    assert sim.z == 50000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_set_power(driver, ruida_simulator):
    """Test that set_power command works correctly."""
    _sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    test_head = Laser()
    test_head.uid = "test-head-1"
    test_head.tool_number = 0

    await driver.set_power(test_head, 0.5)
    await asyncio.sleep(0.2)

    await driver.cleanup()


@pytest.mark.asyncio
async def test_set_power_zero(driver, ruida_simulator):
    """Test that set_power(0) disables power."""
    _sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    test_head = Laser()
    test_head.uid = "test-head-2"
    test_head.tool_number = 1

    await driver.set_power(test_head, 0.0)
    await asyncio.sleep(0.2)

    await driver.cleanup()


@pytest.mark.asyncio
async def test_jog_x_axis(driver, ruida_simulator):
    """Test that jog command works for X axis."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 0
    sim.y = 0
    assert await wait_for_cached_position(driver, x_um=0, y_um=0)

    await driver.jog(5000, x=10.0)
    await asyncio.sleep(0.2)

    assert sim.x == 10000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_jog_y_axis(driver, ruida_simulator):
    """Test that jog command works for Y axis."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 0
    sim.y = 0
    assert await wait_for_cached_position(driver, x_um=0, y_um=0)

    await driver.jog(3000, y=5.0)
    await asyncio.sleep(0.2)

    assert sim.y == 5000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_jog_both_axes(driver, ruida_simulator):
    """Test that jog can move both axes simultaneously."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 10000
    sim.y = 20000
    assert await wait_for_cached_position(driver, x_um=10000, y_um=20000)

    await driver.jog(4000, x=-10.0, y=5.0)
    await asyncio.sleep(0.2)

    assert sim.x == 0
    assert sim.y == 25000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_jog_negative_direction(driver, ruida_simulator):
    """Test that jog works in negative direction."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 100000
    assert await wait_for_cached_position(driver, x_um=100000)

    await driver.jog(6000, x=-50.0)
    await asyncio.sleep(0.2)

    assert sim.x == 50000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_move_to_is_absolute(driver, ruida_simulator):
    """Test that move_to reaches the target regardless of start position."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 99000
    sim.y = 88000

    await driver.move_to(10.0, 20.0)
    await asyncio.sleep(0.2)

    assert sim.x == 10000
    assert sim.y == 20000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_move_to_sends_single_rapid_move(driver, ruida_simulator):
    """Test that move_to streams C9 02 then one absolute D9 10."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    commands: list[tuple[str, bytes]] = []
    sim._server.on_command = lambda desc, data: commands.append((desc, data))

    await driver.move_to(10.0, 20.0)
    await asyncio.sleep(0.2)

    moves = [d for desc, d in commands if desc.startswith("Move Abs")]
    speeds = [
        (i, d)
        for i, (desc, d) in enumerate(commands)
        if desc.startswith("Speed Laser 1")
    ]
    rapids = [
        (i, d)
        for i, (desc, d) in enumerate(commands)
        if desc.startswith("Rapid move")
    ]
    assert not moves
    assert len(speeds) == 1
    assert len(rapids) == 1
    speed_index, speed = speeds[0]
    rapid_index, rapid = rapids[0]
    assert speed_index < rapid_index
    assert speed[:2] == b"\xc9\x02"
    # Machine default is 3000 mm/min = 50000 um/s.
    assert decode35(speed[2:7]) == 50000
    assert rapid[:3] == b"\xd9\x10\x00"
    assert decode35(rapid[3:8]) == 10000
    assert decode35(rapid[8:13]) == 20000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_jog_sends_single_rapid_move_xy(driver, ruida_simulator):
    """Test that jog emits one D9 10 datagram with the absolute target."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 30000
    sim.y = 40000
    assert await wait_for_cached_position(driver, x_um=30000, y_um=40000)

    motion: list[bytes] = []

    def on_command(desc: str, data: bytes) -> None:
        if desc.startswith(("Rapid move", "Move Abs")):
            motion.append(data)

    sim._server.on_command = on_command

    await driver.jog(4000, x=-10.0, y=5.0)
    await asyncio.sleep(0.2)

    assert len(motion) == 1
    assert motion[0][:3] == b"\xd9\x10\x00"
    assert decode35(motion[0][3:8]) == 20000
    assert decode35(motion[0][8:13]) == 45000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_home_sends_home_xy_command(driver, ruida_simulator):
    """Test that home() sends the D8 2A Home XY command."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    commands: list[str] = []
    sim._server.on_command = lambda desc, data: commands.append(desc)

    await driver.home()
    await asyncio.sleep(0.2)

    assert "Home XY" in commands
    assert "Home Z" not in commands

    await driver.cleanup()


@pytest.mark.asyncio
async def test_home_z_sends_home_z_command(driver, ruida_simulator):
    """Test that home(Axis.Z) sends the D8 2C Home Z command."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    commands: list[str] = []
    sim._server.on_command = lambda desc, data: commands.append(desc)

    await driver.home(Axis.Z)
    await asyncio.sleep(0.2)

    assert "Home Z" in commands
    assert "Home XY" not in commands

    await driver.cleanup()


@pytest.mark.asyncio
async def test_home_restores_response_timeout(driver, ruida_simulator):
    """Test that home() restores the response timeout afterwards."""
    assert await wait_for_connection(driver)

    await driver.home()

    assert driver._response_timeout == driver.CONNECTION_TIMEOUT

    await driver.cleanup()


@pytest.mark.asyncio
async def test_jog_single_axis_streams_speed_then_absolute(
    driver, ruida_simulator
):
    """Test single-axis jog: C9 02 speed, then absolute D9 10."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 30000
    sim.y = 0
    assert await wait_for_cached_position(driver, x_um=30000, y_um=0)

    commands: list[tuple[str, bytes]] = []
    sim._server.on_command = lambda desc, data: commands.append((desc, data))

    await driver.jog(6000, x=10.0)
    await asyncio.sleep(0.2)

    speeds = [
        (i, d)
        for i, (desc, d) in enumerate(commands)
        if desc.startswith("Speed Laser 1")
    ]
    rapids = [
        (i, d)
        for i, (desc, d) in enumerate(commands)
        if desc.startswith("Rapid move")
    ]
    assert len(speeds) == 1
    assert len(rapids) == 1
    speed_index, speed = speeds[0]
    rapid_index, rapid = rapids[0]
    assert speed_index < rapid_index
    assert speed[:2] == b"\xc9\x02"
    # 6000 mm/min = 100000 um/s.
    assert decode35(speed[2:7]) == 100000
    assert rapid[:3] == b"\xd9\x10\x00"
    assert decode35(rapid[3:8]) == 40000
    assert decode35(rapid[8:13]) == 0
    assert sim.x == 40000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_jog_never_writes_speed_register(driver, ruida_simulator):
    """Test that jog streams C9 02 each time, no register writes."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    commands: list[str] = []
    sim._server.on_command = lambda desc, data: commands.append(desc)

    await driver.jog(3000, x=1.0)
    await driver.jog(3000, y=1.0)
    await asyncio.sleep(0.2)

    writes = [c for c in commands if "Manual Fast Speed" in c]
    assert not writes
    speeds = [c for c in commands if c.startswith("Speed Laser 1")]
    assert len(speeds) == 2

    await driver.cleanup()


@pytest.mark.asyncio
async def test_set_hold(driver, ruida_simulator):
    """Test that set_hold pauses the process."""
    _sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    await driver.set_hold(True)
    await asyncio.sleep(0.2)

    await driver.set_hold(False)
    await asyncio.sleep(0.2)

    await driver.cleanup()


@pytest.mark.asyncio
async def test_cancel(driver, ruida_simulator):
    """Test that cancel stops the process."""
    _sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    await driver.cancel()
    await asyncio.sleep(0.2)

    await driver.cleanup()


@pytest.mark.asyncio
async def test_clear_alarm(driver, ruida_simulator):
    """Test that clear_alarm works."""
    _sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    await driver.clear_alarm()
    await asyncio.sleep(0.2)

    await driver.cleanup()


@pytest.mark.asyncio
async def test_select_tool_noop(driver):
    """Test that select_tool does nothing (no-op)."""
    await driver.connect()

    await driver.select_tool(1)

    await driver.cleanup()


@pytest.mark.asyncio
async def test_read_settings_sends_signal(driver):
    """Test that read_settings sends the settings_read signal."""
    await driver.connect()

    settings_received = []

    def on_settings_read(sender, settings):
        settings_received.append(settings)

    driver.settings_read.connect(on_settings_read)

    await driver.read_settings()

    assert len(settings_received) == 1
    assert settings_received[0] == []

    await driver.cleanup()


@pytest.mark.asyncio
async def test_write_setting_noop(driver):
    """Test that write_setting does nothing (no-op)."""
    await driver.connect()

    await driver.write_setting("test_key", "test_value")

    await driver.cleanup()


@pytest.mark.asyncio
async def test_set_wcs_offset_noop(driver):
    """Test that set_wcs_offset does nothing (no-op)."""
    await driver.connect()

    await driver.set_wcs_offset("G54", 10.0, 20.0, 30.0)

    await driver.cleanup()


@pytest.mark.asyncio
async def test_read_wcs_offsets(driver, ruida_simulator):
    """Test that read_wcs_offsets returns ref point offsets."""
    _sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    offsets = await driver.read_wcs_offsets()

    assert "MACHINE" in offsets
    assert offsets["MACHINE"] == (0.0, 0.0, 0.0)
    assert "REF0" in offsets
    assert "REF1" in offsets

    await driver.cleanup()


@pytest.mark.asyncio
async def test_read_parser_state_returns_none(driver):
    """Test that read_parser_state returns None."""
    await driver.connect()

    state = await driver.read_parser_state()

    assert state is None

    await driver.cleanup()


@pytest.mark.asyncio
async def test_run_probe_cycle_not_supported(driver):
    """Test that run_probe_cycle indicates not supported."""
    await driver.connect()

    probe_messages = []

    def on_probe_status_changed(sender, message):
        probe_messages.append(message)

    driver.probe_status_changed.connect(on_probe_status_changed)

    result = await driver.run_probe_cycle(Axis.Z, -10, 100)

    assert result is None
    assert len(probe_messages) > 0
    assert "not supported" in probe_messages[0].lower()

    await driver.cleanup()


@pytest.mark.asyncio
async def test_run_with_machine_code(driver, ruida_simulator):
    """Test that run method executes encoded commands on the simulator."""
    sim, _host, _port, _jog_port = ruida_simulator

    doc = Doc()
    ops = Ops()
    ops.move_to(10.0, 20.0)
    ops.line_to(30.0, 40.0)

    encoded = driver.get_encoder().encode(ops, driver._machine, doc)

    assert await wait_for_connection(driver)

    sim.x = 0
    sim.y = 0

    await driver.run(encoded, doc, ops)
    await asyncio.sleep(0.2)

    assert sim.x == 30000
    assert sim.y == 40000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_run_raw_warns_and_finishes(driver):
    """Test that run_raw logs warning and sends job_finished signal."""
    await driver.connect()

    finished_events = []

    def on_job_finished(sender):
        finished_events.append(True)

    driver.job_finished.connect(on_job_finished)

    await driver.run_raw("G0 X10")

    assert len(finished_events) == 1

    await driver.cleanup()


@pytest.mark.asyncio
async def test_connection_status_signals(driver, ruida_simulator):
    """Test that connection status signals are emitted correctly."""
    status_changes = []

    def on_connection_status_changed(sender, status, message):
        status_changes.append((status, message))

    driver.connection_status_changed.connect(on_connection_status_changed)

    assert await wait_for_connection(driver)

    await driver.cleanup()

    await asyncio.sleep(0.05)

    assert len(status_changes) >= 2


@pytest.mark.asyncio
async def test_unit_conversion_mm_to_um(driver, ruida_simulator):
    """Test that mm values are correctly converted to µm."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 0
    sim.y = 0

    await driver.move_to(123.456, 789.012)
    await asyncio.sleep(0.2)

    assert sim.x == 123456
    assert sim.y == 789012

    await driver.cleanup()


@pytest.mark.asyncio
async def test_unit_conversion_small_values(driver, ruida_simulator):
    """Test unit conversion with sub-millimeter values."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 0
    sim.y = 0

    await driver.move_to(0.123, 0.456)
    await asyncio.sleep(0.2)

    assert sim.x == 123
    assert sim.y == 456

    await driver.cleanup()


@pytest.mark.asyncio
async def test_multiple_moves_in_sequence(driver, ruida_simulator):
    """Test that multiple move commands work in sequence."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 0
    sim.y = 0

    await driver.move_to(10.0, 10.0)
    await asyncio.sleep(0.2)

    await driver.move_to(20.0, 20.0)
    await asyncio.sleep(0.2)

    await driver.move_to(30.0, 30.0)
    await asyncio.sleep(0.2)

    assert sim.x == 30000
    assert sim.y == 30000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_home_then_move(driver, ruida_simulator):
    """Test that home followed by move works correctly."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 100000
    sim.y = 200000

    await driver.home()
    await asyncio.sleep(0.2)

    assert sim.x == 0
    assert sim.y == 0

    await driver.move_to(50.0, 75.0)
    await asyncio.sleep(0.2)

    assert sim.x == 50000
    assert sim.y == 75000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_multiple_jogs_in_sequence(driver, ruida_simulator):
    """Test that multiple jog commands work in sequence."""
    sim, _host, _port, _jog_port = ruida_simulator

    assert await wait_for_connection(driver)

    sim.x = 0
    sim.y = 0
    assert await wait_for_cached_position(driver, x_um=0, y_um=0)

    await driver.jog(5000, x=10.0)
    await asyncio.sleep(0.2)

    await driver.jog(5000, y=10.0)
    await asyncio.sleep(0.2)

    await driver.jog(5000, x=-5.0)
    await asyncio.sleep(0.2)

    assert sim.x == 5000
    assert sim.y == 10000

    await driver.cleanup()


@pytest.mark.asyncio
async def test_power_settings_with_different_heads(driver, ruida_simulator):
    """Test that set_power works with different laser heads."""
    assert await wait_for_connection(driver)

    head1 = Laser()
    head1.uid = "head-1"
    head1.tool_number = 0

    head2 = Laser()
    head2.uid = "head-2"
    head2.tool_number = 1

    await driver.set_power(head1, 0.75)
    await asyncio.sleep(0.2)

    await driver.set_power(head2, 0.50)
    await asyncio.sleep(0.2)

    await driver.cleanup()


@pytest.mark.asyncio
async def test_get_encoder_returns_correct_type(driver):
    """Test that get_encoder returns RuidaEncoder."""
    encoder = driver.get_encoder()

    assert isinstance(encoder, RuidaEncoder)


@pytest.mark.asyncio
async def test_resource_uri_property(driver):
    """Test that resource_uri returns correct format."""
    driver.host = "192.168.1.100"
    driver.port = 50200
    driver.jog_port = 50207

    uri = driver.resource_uri

    assert uri == "udp://192.168.1.100:50200 (jog: 50207)"


@pytest.mark.asyncio
async def test_machine_space_wcs_properties(driver):
    """Test that machine space WCS properties return correct values."""
    wcs = driver.machine_space_wcs
    display_name = driver.machine_space_wcs_display_name

    assert wcs == "MACHINE"
    assert display_name != ""


@pytest.mark.asyncio
async def test_can_home_returns_true(driver):
    """Test that can_home returns True for all axes."""
    assert driver.can_home()
    assert driver.can_home(Axis.X)
    assert driver.can_home(Axis.Y)
    assert driver.can_home(Axis.Z)
    assert driver.can_home(Axis.X | Axis.Y)


@pytest.mark.asyncio
async def test_can_jog_returns_true(driver):
    """Test that can_jog returns True."""
    assert driver.can_jog()
    assert driver.can_jog(Axis.X)
    assert driver.can_jog(Axis.Y)


@pytest.mark.asyncio
async def test_driver_label_and_subtitle(driver):
    """Test that driver has correct label and subtitle."""
    assert "Ruida" in driver.label
    assert "UDP" in driver.label
    assert driver.subtitle != ""
    assert driver.supports_settings is False
    assert driver.reports_granular_progress is False


@pytest.mark.asyncio
async def test_disconnect_when_not_connected(driver):
    """Test that disconnect works even when not connected."""
    await driver.cleanup()

    assert not driver.is_connected


@pytest.mark.asyncio
async def test_cleanup_resets_transport(driver, ruida_simulator):
    """Test that cleanup properly resets transport objects."""
    _, host, port, _jog_port = ruida_simulator
    driver._setup_implementation(host=host, port=port, response_port=0)

    await driver.cleanup()

    assert driver._udp_transport is None
    assert driver._ruida_transport is None
    assert driver._client is None


@pytest.mark.asyncio
async def test_reconnect_after_disconnect(driver, ruida_simulator):
    """Test that driver can reconnect after disconnect."""
    _, host, port, jog_port = ruida_simulator
    assert await wait_for_connection(driver)

    assert driver.is_connected

    await driver.cleanup()

    assert not driver.is_connected

    driver._setup_implementation(
        host=host, port=port, jog_port=jog_port, response_port=0
    )
    assert await wait_for_connection(driver)

    assert driver.is_connected

    await driver.cleanup()


@pytest.mark.asyncio
async def test_keepalive_maintains_connection(driver, ruida_simulator):
    """Test that periodic keepalive maintains the connection."""
    assert await wait_for_connection(driver)

    for _ in range(3):
        await asyncio.sleep(driver.KEEPALIVE_INTERVAL + 0.2)
        assert driver.is_connected, (
            "Connection should remain active with keepalive"
        )

    await driver.cleanup()


@pytest.mark.asyncio
async def test_connection_status_on_connect(driver, ruida_simulator):
    """Test that CONNECTED status is emitted after successful connection."""
    status_changes = []

    def on_status(sender, status, message):
        status_changes.append((status, message))

    driver.connection_status_changed.connect(on_status)

    assert await wait_for_connection(driver)

    statuses = [s for s, _ in status_changes]
    assert TransportStatus.CONNECTED in statuses

    await driver.cleanup()


@pytest.mark.asyncio
async def test_keepalive_timeout_behavior(driver, ruida_simulator):
    """Test that driver handles connection lifecycle correctly."""
    assert await wait_for_connection(driver)

    await asyncio.sleep(driver.KEEPALIVE_INTERVAL * 2)

    assert driver.is_connected, (
        "Connection should remain active with keepalive"
    )

    await driver.cleanup()


@pytest.mark.asyncio
async def test_position_polling_updates_state(driver, ruida_simulator):
    """Test that position polling reads current position from controller."""
    sim, _host, _port, _jog_port = ruida_simulator

    sim.x = 50000
    sim.y = 75000

    assert await wait_for_connection(driver)

    await asyncio.sleep(driver.POSITION_POLL_INTERVAL + 0.5)

    assert driver.state.machine_pos[0] == 50.0
    assert driver.state.machine_pos[1] == 75.0

    await driver.cleanup()


@pytest.mark.asyncio
async def test_multiple_keepalive_cycles(driver, ruida_simulator):
    """Test connection stability over multiple keepalive cycles."""
    assert await wait_for_connection(driver)

    cycle_count = 0
    max_cycles = 5

    for i in range(max_cycles):
        await asyncio.sleep(driver.KEEPALIVE_INTERVAL)
        if driver.is_connected:
            cycle_count += 1

    assert cycle_count >= max_cycles - 1, (
        f"Expected {max_cycles - 1}+ successful cycles, got {cycle_count}"
    )

    await driver.cleanup()


def test_supports_pwm_false_for_diode():
    driver = RuidaDriver.__new__(RuidaDriver)
    laser = Laser()
    laser.laser_type = LaserType.DIODE

    assert driver.supports_pwm(laser) is False
    assert driver.get_pwm_params(laser) is None


def test_supports_pwm_true_for_co2():
    driver = RuidaDriver.__new__(RuidaDriver)
    laser = Laser()
    laser.laser_type = LaserType.CO2
    laser.pwm_frequency = 1000
    laser.max_pwm_frequency = 5000
    laser.pulse_width = 50
    laser.min_pulse_width = 5
    laser.max_pulse_width = 500

    assert driver.supports_pwm(laser) is True
    params = driver.get_pwm_params(laser)
    assert params is not None
    assert params.frequency == 1000
    assert params.max_frequency == 5000
    assert params.pulse_width == 50
    assert params.min_pulse_width == 5
    assert params.max_pulse_width == 500


def test_supports_pwm_true_for_fiber():
    driver = RuidaDriver.__new__(RuidaDriver)
    laser = Laser()
    laser.laser_type = LaserType.FIBER

    assert driver.supports_pwm(laser) is True
    assert driver.get_pwm_params(laser) is not None


def test_supports_pwm_co2_with_zero_frequency():
    driver = RuidaDriver.__new__(RuidaDriver)
    laser = Laser()
    laser.laser_type = LaserType.CO2
    laser.pwm_frequency = 0
    laser.max_pwm_frequency = 0
    laser.pulse_width = 0
    laser.min_pulse_width = 0

    assert driver.supports_pwm(laser) is True
    assert driver.get_pwm_params(laser) is not None


def test_build_datagrams_respects_max_size():
    commands = [b"\x88" + bytes(10)] * 200
    datagrams = build_datagrams(commands, 1000)

    assert all(len(d) <= 1000 for d in datagrams)
    assert b"".join(datagrams) == b"".join(commands)
    assert all(len(d) % 11 == 0 for d in datagrams)


def test_build_datagrams_boundaries_align_with_commands():
    commands = [bytes([i % 256]) * (7 + i % 13) for i in range(300)]
    datagrams = build_datagrams(commands, 1000)

    assert b"".join(datagrams) == b"".join(commands)
    it = iter(commands)
    for datagram in datagrams:
        consumed = b""
        while len(consumed) < len(datagram):
            consumed += next(it)
        assert consumed == datagram


def test_build_datagrams_never_splits_oversized_command():
    commands = [bytes(1500), b"\x88" + bytes(10)]
    datagrams = build_datagrams(commands, 1000)

    assert datagrams[0] == commands[0]
    assert datagrams[1] == commands[1]


class StubRuidaTransport:
    """Minimal in-memory stand-in for RuidaTransport."""

    def __init__(self):
        self.decoded_received = Signal()
        self.status_changed = Signal()
        self.sent: list[bytes] = []
        self.is_connected = True

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def send_command(self, command: bytes):
        self.sent.append(command)


def make_encoded() -> EncodedOutput:
    """An EncodedOutput as the pipeline delivers it: no driver_data."""
    return EncodedOutput(
        text="",
        op_map=MachineCodeOpMap.from_lists([], []),
        driver_data={},
    )


def stub_job_blob(monkeypatch, commands: list[bytes]) -> bytes:
    """Force run() to build the given commands as its job blob."""
    blob = commands_to_rd_bytes(commands)
    monkeypatch.setattr(
        driver_mod, "build_rd_bytes", lambda ops, machine, doc: blob
    )
    return blob


def square_job_ops() -> Ops:
    """A small closed square job with power and feed rate set."""
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.8)
    ops.set_feed_rate(200)
    ops.move_to(0.0, 0.0, 0.0)
    ops.line_to(10.0, 0.0, 0.0)
    ops.line_to(10.0, 10.0, 0.0)
    ops.line_to(0.0, 10.0, 0.0)
    ops.line_to(0.0, 0.0, 0.0)
    ops.layer_end("layer-1")
    ops.job_end()
    return ops


class StubJobClient:
    """Captures the blob run() hands to send_job."""

    def __init__(self):
        self.blobs: list[bytes] = []
        self.is_connected = False
        self.state_changed = Signal()
        self.position_updated = Signal()

    async def disconnect(self):
        pass

    async def send_job(self, blob, on_start=None, on_chunk=None):
        self.blobs.append(blob)
        if on_start:
            on_start(len(blob), 1)
        if on_chunk:
            on_chunk(1, 1, len(blob), 1)


async def wait_for_sent(
    transport: StubRuidaTransport, count: int, timeout: float = 2.0
) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while len(transport.sent) < count:
        assert asyncio.get_event_loop().time() < deadline
        await asyncio.sleep(0.02)


STATUS_IDLE_REPLY = b"\xda\x01\x04\x00" + encode35(22)
STATUS_RUNNING_REPLY = b"\xda\x01\x04\x00" + encode35(21)


@pytest.mark.asyncio
async def test_ack_pacing_no_second_datagram_before_ack(driver, monkeypatch):
    """The next datagram must not be sent before the first is ACKed."""
    transport = StubRuidaTransport()
    driver._client = RuidaClient(cast(RuidaTransport, transport))

    stub_job_blob(monkeypatch, [b"\x88" + bytes(10)] * 100)
    encoded = make_encoded()

    task = asyncio.create_task(driver.run(encoded, Doc(), Ops()))
    await wait_for_sent(transport, 1)
    await asyncio.sleep(0.2)
    assert len(transport.sent) == 1

    transport.decoded_received.send(transport, data=b"\xcc")
    await wait_for_sent(transport, 2)

    transport.decoded_received.send(transport, data=b"\xcc")
    await wait_for_sent(transport, 3)
    assert transport.sent[2] == b"\xda\x00\x04\x00"

    transport.decoded_received.send(transport, data=STATUS_IDLE_REPLY)
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_nak_triggers_datagram_retry(driver, monkeypatch):
    """A NAK response must trigger a resend of the same datagram."""
    transport = StubRuidaTransport()
    driver._client = RuidaClient(cast(RuidaTransport, transport))

    stub_job_blob(monkeypatch, [b"\x88" + bytes(10)])
    encoded = make_encoded()

    task = asyncio.create_task(driver.run(encoded, Doc(), Ops()))
    await wait_for_sent(transport, 1)

    transport.decoded_received.send(transport, data=b"\xcf")
    await wait_for_sent(transport, 2)
    assert transport.sent[1] == transport.sent[0]

    transport.decoded_received.send(transport, data=b"\xcc")
    await wait_for_sent(transport, 3)
    transport.decoded_received.send(transport, data=STATUS_IDLE_REPLY)
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_persistent_nak_aborts_job(driver, monkeypatch):
    """Persistent NAKs must abort the job with an error."""
    transport = StubRuidaTransport()
    client = RuidaClient(cast(RuidaTransport, transport))
    driver._client = client

    finished = []

    def on_finished(sender):
        finished.append(True)

    driver.job_finished.connect(on_finished)

    stub_job_blob(monkeypatch, [b"\x88" + bytes(10)])
    encoded = make_encoded()

    async def nak_all():
        while True:
            transport.decoded_received.send(transport, data=b"\xcf")
            await asyncio.sleep(0.05)

    nak_task = asyncio.create_task(nak_all())
    try:
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(
                driver.run(encoded, Doc(), Ops()), timeout=5.0
            )
    finally:
        nak_task.cancel()

    assert not finished


@pytest.mark.asyncio
async def test_job_finished_only_after_status_clears(driver, monkeypatch):
    """job_finished must not fire while the job-running bit is set."""
    transport = StubRuidaTransport()
    driver._client = RuidaClient(cast(RuidaTransport, transport))

    finished = []

    def on_finished(sender):
        finished.append(True)

    driver.job_finished.connect(on_finished)

    stub_job_blob(monkeypatch, [b"\x88" + bytes(10)])
    encoded = make_encoded()

    task = asyncio.create_task(driver.run(encoded, Doc(), Ops()))
    await wait_for_sent(transport, 1)

    transport.decoded_received.send(transport, data=b"\xcc")
    await wait_for_sent(transport, 2)
    assert transport.sent[1] == b"\xda\x00\x04\x00"

    transport.decoded_received.send(transport, data=STATUS_RUNNING_REPLY)
    await asyncio.sleep(0.2)
    assert not finished

    await wait_for_sent(transport, 3)
    transport.decoded_received.send(transport, data=STATUS_IDLE_REPLY)
    await asyncio.wait_for(task, timeout=2.0)
    assert finished


@pytest.mark.asyncio
async def test_run_square_job_end_to_end(driver, ruida_simulator):
    """A full square job runs against the simulator to completion."""
    sim, _host, _port, _jog_port = ruida_simulator

    doc = Doc()
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.8)
    ops.set_feed_rate(200)
    ops.move_to(0.0, 0.0, 0.0)
    ops.line_to(10.0, 0.0, 0.0)
    ops.line_to(10.0, 10.0, 0.0)
    ops.line_to(0.0, 10.0, 0.0)
    ops.line_to(0.0, 0.0, 0.0)
    ops.layer_end("layer-1")
    ops.job_end()

    encoded = driver.get_encoder().encode(ops, driver._machine, doc)

    assert await wait_for_connection(driver)

    finished = []

    def on_finished(sender):
        finished.append(True)

    driver.job_finished.connect(on_finished)

    await driver.run(encoded, doc, ops)

    assert sim.x == 0
    assert sim.y == 0
    assert sim.program_mode is False
    assert sim.machine_status == 22
    assert finished

    await driver.cleanup()


@pytest.mark.asyncio
async def test_run_builds_blob_from_ops_when_driver_data_empty(driver):
    """
    The pipeline strips driver_data, so run() must build the job from
    ops. An empty driver_data must still produce a real transmission.
    """
    client = StubJobClient()
    driver._client = cast(RuidaClient, client)

    doc = Doc()
    ops = square_job_ops()

    await driver.run(make_encoded(), doc, ops)

    assert client.blobs
    assert client.blobs[0]


@pytest.mark.asyncio
async def test_run_blob_matches_encoder_and_export(driver, tmp_path):
    """The sent blob equals build_rd_bytes and what export_rd writes."""
    client = StubJobClient()
    driver._client = cast(RuidaClient, client)

    doc = Doc()
    ops = square_job_ops()
    expected = build_rd_bytes(ops, driver._machine, doc)
    exported = tmp_path / "job.rd"
    export_rd(ops, driver._machine, doc, exported)

    await driver.run(make_encoded(), doc, ops)

    assert client.blobs[0] == expected
    assert client.blobs[0] == exported.read_bytes()


@pytest.mark.asyncio
async def test_run_dumps_sent_blob_to_temp_file(driver):
    """Every run leaves the exact sent blob in the temp directory."""
    client = StubJobClient()
    driver._client = cast(RuidaClient, client)

    doc = Doc()
    ops = square_job_ops()

    await driver.run(make_encoded(), doc, ops)

    dump = Path(tempfile.gettempdir()) / "rayforge_last_job.rd"
    assert dump.read_bytes() == client.blobs[0]


@pytest.mark.asyncio
async def test_run_warns_and_finishes_on_empty_ops(driver, caplog):
    """Genuinely empty ops must warn and send nothing."""
    client = StubJobClient()
    driver._client = cast(RuidaClient, client)

    finished = []

    def on_finished(sender):
        finished.append(True)

    driver.job_finished.connect(on_finished)

    with caplog.at_level(logging.WARNING):
        await driver.run(make_encoded(), Doc(), Ops())

    assert not client.blobs
    assert finished
    assert "no machine commands" in caplog.text


def _origin_job_ops() -> Ops:
    """A minimal one-layer job for prologue inspection."""
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    ops.set_power(0.8)
    ops.set_feed_rate(200)
    ops.move_to(0.0, 0.0, 0.0)
    ops.line_to(10.0, 0.0, 0.0)
    ops.line_to(10.0, 10.0, 0.0)
    ops.layer_end("layer-1")
    ops.job_end()
    return ops


class TestDefaultRefPoint:
    """The default WCS anchors jobs at the user-set panel origin."""

    def test_setup_defaults_active_wcs_to_anchor(self, driver):
        """A freshly set up driver selects REF0, not machine space."""
        assert driver._machine.active_wcs == "REF0"
        assert RuidaDriver.DEFAULT_WCS == "REF0"

    def test_job_first_command_is_d8_12(self, driver):
        """With the default WCS the job opens with the D8 12 ref point."""
        encoded = RuidaEncoder().encode(
            _origin_job_ops(), driver._machine, Doc()
        )

        assert encoded.driver_data["commands"][0] == b"\xd8\x12"

    def test_stale_machine_wcs_still_emits_d8_12(self, driver):
        """A profile stuck on MACHINE must not put D8 10 in the job."""
        driver._machine.active_wcs = "MACHINE"
        encoded = RuidaEncoder().encode(
            _origin_job_ops(), driver._machine, Doc()
        )

        assert encoded.driver_data["commands"][0] == b"\xd8\x12"

    def test_setup_seeds_the_clients_tracked_ref_point_mode(self, driver):
        """The mode poller must not push MACHINE back onto the profile."""
        assert driver._client._ref_point_mode == "REF0"

    def test_setup_preserves_a_saved_wcs(self, lite_context, ruida_simulator):
        """A machine that already names a valid slot keeps it."""
        _sim, host, port, jog_port = ruida_simulator
        machine = Machine(lite_context)
        machine.driver_name = "RuidaDriver"
        machine.active_wcs = "REF1"
        lite_context.machine_mgr.add_machine(machine)

        drv = RuidaDriver(lite_context, machine)
        drv._setup_implementation(
            host=host, port=port, jog_port=jog_port, response_port=0
        )

        assert machine.active_wcs == "REF1"


class _JogClientSpy:
    """Records the interactive motion a jog produces."""

    def __init__(self, position=(0, 0)):
        self.commands: list[bytes] = []
        self.position = position
        self.reads = 0
        self.state_changed = Signal()
        self.position_updated = Signal()

    async def disconnect(self):
        pass

    async def set_travel_speed(self, um_per_s: int):
        self.commands.append(b"\xc9\x02" + encode35(um_per_s))

    async def rapid_move_xy(self, x_um: int, y_um: int, light: bool = False):
        self.commands.append(b"\xd9\x10\x00" + encode35(x_um) + encode35(y_um))
        self.position = (x_um, y_um)

    async def stop_process(self):
        self.commands.append(b"\xd8\x01")

    async def read_position(self, timeout: float = 2.0):
        self.reads += 1
        return self.position


def _motion(commands: list[bytes]) -> list[bytes]:
    """The D9 motion commands out of a recorded stream."""
    return [c for c in commands if c[:1] == b"\xd9"]


class TestHoldJog:
    """A hold is one long move, halted by D8 01 on release."""

    @pytest.mark.asyncio
    async def test_driver_reports_hold_jog_support(self, driver):
        assert driver.can_hold_jog() is True

    @pytest.mark.asyncio
    async def test_press_emits_speed_then_one_long_move(self, driver):
        spy = _JogClientSpy()
        driver._client = spy
        driver._last_known_pos = (100000, 100000)
        driver._machine.set_axis_extents(400.0, 300.0)
        await driver.set_jog_speed(1200)  # 20 mm/s

        await driver.jog_key_down("x", 1)

        assert spy.commands[0] == b"\xc9\x02" + encode35(20000)
        moves = _motion(spy.commands)
        assert len(moves) == 1
        assert moves[0][:3] == b"\xd9\x10\x00"
        # 400 mm bed, 1 mm margin, Y unchanged.
        assert decode35(moves[0][3:8]) == 399000
        assert decode35(moves[0][8:13]) == 100000

    @pytest.mark.asyncio
    async def test_negative_direction_runs_to_the_near_limit(self, driver):
        spy = _JogClientSpy()
        driver._client = spy
        driver._last_known_pos = (100000, 100000)
        driver._machine.set_axis_extents(400.0, 300.0)

        await driver.jog_key_down("y", -1)

        moves = _motion(spy.commands)
        assert decode35(moves[0][3:8]) == 100000
        assert decode35(moves[0][8:13]) == 1000

    @pytest.mark.asyncio
    async def test_diagonal_hold_runs_both_axes_to_their_limits(self, driver):
        """The two halves of a diagonal arrive as separate presses."""
        spy = _JogClientSpy(position=(100000, 100000))
        driver._client = spy
        driver._last_known_pos = (100000, 100000)
        driver._machine.set_axis_extents(400.0, 300.0)

        await driver.jog_key_down("x", -1)
        spy.position = (100000, 100000)
        await driver.jog_key_down("y", 1)

        # The second press stops the first move before re-issuing, so
        # only one move is ever outstanding.
        moves = _motion(spy.commands)
        assert len(moves) == 2
        assert spy.commands.index(b"\xd8\x01") < spy.commands.index(moves[1])
        assert decode35(moves[1][3:8]) == 1000
        assert decode35(moves[1][8:13]) == 299000

    @pytest.mark.asyncio
    async def test_release_stops_and_resyncs(self, driver):
        spy = _JogClientSpy()
        driver._client = spy
        driver._last_known_pos = (100000, 100000)

        await driver.jog_key_down("x", 1)
        spy.position = (222000, 100000)
        reads_before = spy.reads
        await driver.jog_key_up("x", 1)

        assert spy.commands[-1] == b"\xd8\x01"
        assert spy.reads == reads_before + 1
        assert driver._last_known_pos == (222000, 100000)
        assert driver._jog_busy is False
        assert driver._jog_keys_down == set()

    @pytest.mark.asyncio
    async def test_click_during_a_hold_emits_nothing(self, driver):
        spy = _JogClientSpy()
        driver._client = spy
        driver._last_known_pos = (100000, 100000)

        await driver.jog_key_down("x", 1)
        emitted = len(spy.commands)
        await driver.jog(6000, x=10.0)

        assert len(spy.commands) == emitted
        assert driver._jog_keys_down == {("x", 1)}

    @pytest.mark.asyncio
    async def test_input_while_a_step_settles_emits_nothing(self, driver):
        spy = _JogClientSpy()
        driver._client = spy
        driver._last_known_pos = (100000, 100000)
        driver._jog_busy = True  # a single step is still settling

        await driver.jog_key_down("x", 1)
        await driver.jog(6000, y=10.0)

        assert spy.commands == []
        assert driver._jog_keys_down == set()

    @pytest.mark.asyncio
    async def test_release_all_stops_and_resyncs(self, driver):
        """Focus loss and disconnect both land here."""
        spy = _JogClientSpy()
        driver._client = spy
        driver._last_known_pos = (100000, 100000)

        await driver.jog_key_down("x", 1)
        await driver.release_all_jog_keys()

        assert spy.commands[-1] == b"\xd8\x01"
        assert driver._jog_keys_down == set()
        assert driver._jog_busy is False

    @pytest.mark.asyncio
    async def test_disconnect_stops_the_motion(self, driver):
        spy = _JogClientSpy()
        driver._client = spy
        driver._last_known_pos = (100000, 100000)

        await driver.jog_key_down("x", -1)
        await driver._disconnect_transports()

        assert b"\xd8\x01" in spy.commands
        assert driver._jog_keys_down == set()
        assert driver._jog_busy is False

    @pytest.mark.asyncio
    async def test_single_step_is_busy_until_it_settles(self, driver):
        spy = _JogClientSpy(position=(100000, 100000))
        driver._client = spy
        driver._last_known_pos = (100000, 100000)

        await driver.jog(6000, x=10.0)

        moves = _motion(spy.commands)
        assert len(moves) == 1
        assert decode35(moves[0][3:8]) == 110000
        assert spy.reads >= 1
        assert driver._jog_busy is False

    @pytest.mark.asyncio
    async def test_single_step_gives_up_after_the_timeout(self, driver):
        """A head that never arrives must not pin the busy flag."""
        spy = _JogClientSpy(position=(100000, 100000))
        driver._client = spy
        driver._last_known_pos = (100000, 100000)

        async def frozen(x_um, y_um, light=False):
            spy.commands.append(
                b"\xd9\x10\x00" + encode35(x_um) + encode35(y_um)
            )

        spy.rapid_move_xy = frozen
        driver.JOG_SETTLE_GRACE = 0.05
        driver.JOG_SETTLE_POLL_INTERVAL = 0.01

        await driver.jog(60000, x=1.0)

        assert driver._jog_busy is False

    @pytest.mark.asyncio
    async def test_set_jog_speed_stores_mm_min(self, driver):
        await driver.set_jog_speed(6000)

        assert driver._jog_speed_mm_min == 6000

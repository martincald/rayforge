"""
Tests for RuidaClient command generation and sending.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from blinker import Signal

from rayforge.machine.driver.ruida.ruida_client import (
    JOB_MAGIC,
    RuidaClient,
)
from rayforge.machine.driver.ruida.ruida_encoder import commands_to_rd_bytes
from rayforge.machine.driver.ruida.ruida_util import (
    encode35,
    swizzle_byte,
    unswizzle_byte,
)


class TestRuidaClient:
    """Tests for RuidaClient methods."""

    def setup_method(self):
        self.mock_transport = MagicMock(
            spec=[
                "connect",
                "disconnect",
                "send",
                "send_command",
                "is_connected",
                "received",
                "decoded_received",
                "status_changed",
            ]
        )
        self.mock_transport.connect = AsyncMock()
        self.mock_transport.disconnect = AsyncMock()
        self.mock_transport.send = AsyncMock()
        self.mock_transport.send_command = AsyncMock()
        self.mock_transport.is_connected = False
        self.mock_transport.received = MagicMock()
        self.mock_transport.received.connect = MagicMock()
        self.mock_transport.decoded_received = MagicMock()
        self.mock_transport.decoded_received.connect = MagicMock()
        self.mock_transport.status_changed = MagicMock()
        self.mock_transport.status_changed.connect = MagicMock()

        self.client = RuidaClient(self.mock_transport)

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test connect delegates to transport."""
        await self.client.connect()
        self.mock_transport.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnect delegates to transport."""
        await self.client.disconnect()
        self.mock_transport.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_command(self):
        """Test send_command delegates to transport."""
        command = b"\xda\x00"
        await self.client.send_command(command)
        self.mock_transport.send_command.assert_called_once_with(command)

    @pytest.mark.asyncio
    async def test_move_abs(self):
        """Test move_abs builds correct command."""
        await self.client.move_abs(10000, 20000)
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent[0] == 0x88

    @pytest.mark.asyncio
    async def test_cut_abs(self):
        """Test cut_abs builds correct command."""
        await self.client.cut_abs(10000, 20000)
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent[0] == 0xA8

    @pytest.mark.asyncio
    async def test_home_xy(self):
        """Test home_xy builds correct command."""
        await self.client.home_xy()
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == b"\xd8\x2a"

    @pytest.mark.asyncio
    async def test_start_process(self):
        """Test start_process builds correct command."""
        await self.client.start_process()
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == b"\xd8\x00"

    @pytest.mark.asyncio
    async def test_stop_process(self):
        """Test stop_process builds correct command."""
        await self.client.stop_process()
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == b"\xd8\x01"

    @pytest.mark.asyncio
    async def test_pause_process(self):
        """Test pause_process builds correct command."""
        await self.client.pause_process()
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == b"\xd8\x02"

    @pytest.mark.asyncio
    async def test_resume_process(self):
        """Test resume_process builds correct command."""
        await self.client.resume_process()
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == b"\xd8\x03"


class TestRuidaClientAirAssist:
    """Tests for air assist commands."""

    def setup_method(self):
        self.mock_transport = MagicMock(
            spec=[
                "connect",
                "disconnect",
                "send",
                "send_command",
                "is_connected",
                "received",
                "decoded_received",
                "status_changed",
            ]
        )
        self.mock_transport.connect = AsyncMock()
        self.mock_transport.disconnect = AsyncMock()
        self.mock_transport.send = AsyncMock()
        self.mock_transport.send_command = AsyncMock()
        self.mock_transport.is_connected = False
        self.mock_transport.received = MagicMock()
        self.mock_transport.received.connect = MagicMock()
        self.mock_transport.decoded_received = MagicMock()
        self.mock_transport.decoded_received.connect = MagicMock()
        self.mock_transport.status_changed = MagicMock()
        self.mock_transport.status_changed.connect = MagicMock()

        self.client = RuidaClient(self.mock_transport)

    @pytest.mark.asyncio
    async def test_air_assist_on(self):
        """Test air_assist_on sends correct command."""
        await self.client.air_assist_on()
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == b"\xca\x13"

    @pytest.mark.asyncio
    async def test_air_assist_off(self):
        """Test air_assist_off sends correct command."""
        await self.client.air_assist_off()
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == b"\xca\x12"


class TestRuidaClientSelectLayer:
    """Tests for layer selection commands."""

    def setup_method(self):
        self.mock_transport = MagicMock(
            spec=[
                "connect",
                "disconnect",
                "send",
                "send_command",
                "is_connected",
                "received",
                "decoded_received",
                "status_changed",
            ]
        )
        self.mock_transport.connect = AsyncMock()
        self.mock_transport.disconnect = AsyncMock()
        self.mock_transport.send = AsyncMock()
        self.mock_transport.send_command = AsyncMock()
        self.mock_transport.is_connected = False
        self.mock_transport.received = MagicMock()
        self.mock_transport.received.connect = MagicMock()
        self.mock_transport.decoded_received = MagicMock()
        self.mock_transport.decoded_received.connect = MagicMock()
        self.mock_transport.status_changed = MagicMock()
        self.mock_transport.status_changed.connect = MagicMock()

        self.client = RuidaClient(self.mock_transport)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("layer_index", [0, 5, 10, 15])
    async def test_select_layer_valid(self, layer_index):
        """Test select_layer with valid indices."""
        await self.client.select_layer(layer_index)
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == bytes([0xCA, layer_index])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("layer_index", [-1, 16, 100])
    async def test_select_layer_invalid(self, layer_index):
        """Test select_layer with invalid indices raises error."""
        with pytest.raises(ValueError, match="Layer index must be 0-15"):
            await self.client.select_layer(layer_index)


class TestRuidaClientSendRaw:
    """Tests for send_raw command."""

    def setup_method(self):
        self.mock_transport = MagicMock(
            spec=[
                "connect",
                "disconnect",
                "send",
                "send_command",
                "is_connected",
                "received",
                "decoded_received",
                "status_changed",
            ]
        )
        self.mock_transport.connect = AsyncMock()
        self.mock_transport.disconnect = AsyncMock()
        self.mock_transport.send = AsyncMock()
        self.mock_transport.send_command = AsyncMock()
        self.mock_transport.is_connected = False
        self.mock_transport.received = MagicMock()
        self.mock_transport.received.connect = MagicMock()
        self.mock_transport.decoded_received = MagicMock()
        self.mock_transport.decoded_received.connect = MagicMock()
        self.mock_transport.status_changed = MagicMock()
        self.mock_transport.status_changed.connect = MagicMock()

        self.client = RuidaClient(self.mock_transport)

    @pytest.mark.asyncio
    async def test_send_raw(self):
        """Test send_raw sends data directly to transport."""
        data = b"\xda\x00\x05\x7e"
        await self.client.send_raw(data)
        self.mock_transport.send.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_send_raw_empty(self):
        """Test send_raw with empty data."""
        await self.client.send_raw(b"")
        self.mock_transport.send.assert_called_once_with(b"")


class TestRuidaClientJogCommands:
    """Tests for jog commands via main transport."""

    def setup_method(self):
        self.mock_transport = MagicMock(
            spec=[
                "connect",
                "disconnect",
                "send",
                "send_command",
                "is_connected",
                "received",
                "decoded_received",
                "status_changed",
            ]
        )
        self.mock_transport.connect = AsyncMock()
        self.mock_transport.disconnect = AsyncMock()
        self.mock_transport.send = AsyncMock()
        self.mock_transport.send_command = AsyncMock()
        self.mock_transport.is_connected = False
        self.mock_transport.received = MagicMock()
        self.mock_transport.received.connect = MagicMock()
        self.mock_transport.decoded_received = MagicMock()
        self.mock_transport.decoded_received.connect = MagicMock()
        self.mock_transport.status_changed = MagicMock()
        self.mock_transport.status_changed.connect = MagicMock()

        self.client = RuidaClient(self.mock_transport)

    @pytest.mark.asyncio
    async def test_jog_move_x(self):
        """Test jog_move_x sends rapid move X via main transport."""
        await self.client.jog_move_x(10000)
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent[0] == 0xD9
        assert sent[1] == 0x00
        assert sent[2] == 0x02

    @pytest.mark.asyncio
    async def test_jog_move_y(self):
        """Test jog_move_y sends rapid move Y via main transport."""
        await self.client.jog_move_y(20000)
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent[0] == 0xD9
        assert sent[1] == 0x01
        assert sent[2] == 0x02


class TestRuidaClientPowerCommands:
    """Tests for power commands."""

    def setup_method(self):
        self.mock_transport = MagicMock(
            spec=[
                "connect",
                "disconnect",
                "send",
                "send_command",
                "is_connected",
                "received",
                "decoded_received",
                "status_changed",
            ]
        )
        self.mock_transport.connect = AsyncMock()
        self.mock_transport.disconnect = AsyncMock()
        self.mock_transport.send = AsyncMock()
        self.mock_transport.send_command = AsyncMock()
        self.mock_transport.is_connected = False
        self.mock_transport.received = MagicMock()
        self.mock_transport.received.connect = MagicMock()
        self.mock_transport.decoded_received = MagicMock()
        self.mock_transport.decoded_received.connect = MagicMock()
        self.mock_transport.status_changed = MagicMock()
        self.mock_transport.status_changed.connect = MagicMock()

        self.client = RuidaClient(self.mock_transport)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("laser", [1, 2, 3, 4])
    async def test_set_power_immediate_valid_laser(self, laser):
        """Test set_power_immediate with valid laser numbers."""
        await self.client.set_power_immediate(laser, 50.0)
        self.mock_transport.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_power_immediate_invalid_laser(self):
        """Test set_power_immediate with invalid laser number."""
        with pytest.raises(ValueError, match="Invalid laser"):
            await self.client.set_power_immediate(5, 50.0)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("laser", [1, 2, 3, 4])
    async def test_set_power_end_valid_laser(self, laser):
        """Test set_power_end with valid laser numbers."""
        await self.client.set_power_end(laser, 50.0)
        self.mock_transport.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_power_end_invalid_laser(self):
        """Test set_power_end with invalid laser number."""
        with pytest.raises(ValueError, match="Invalid laser"):
            await self.client.set_power_end(5, 50.0)


class TestRuidaClientSpeedCommands:
    """Tests for speed commands."""

    def setup_method(self):
        self.mock_transport = MagicMock(
            spec=[
                "connect",
                "disconnect",
                "send",
                "send_command",
                "is_connected",
                "received",
                "decoded_received",
                "status_changed",
            ]
        )
        self.mock_transport.connect = AsyncMock()
        self.mock_transport.disconnect = AsyncMock()
        self.mock_transport.send = AsyncMock()
        self.mock_transport.send_command = AsyncMock()
        self.mock_transport.is_connected = False
        self.mock_transport.received = MagicMock()
        self.mock_transport.received.connect = MagicMock()
        self.mock_transport.decoded_received = MagicMock()
        self.mock_transport.decoded_received.connect = MagicMock()
        self.mock_transport.status_changed = MagicMock()
        self.mock_transport.status_changed.connect = MagicMock()

        self.client = RuidaClient(self.mock_transport)

    @pytest.mark.asyncio
    async def test_set_speed(self):
        """Test set_speed builds correct command."""
        await self.client.set_speed(100.0)
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent[0:2] == b"\xc9\x02"

    @pytest.mark.asyncio
    async def test_set_axis_speed(self):
        """Test set_axis_speed builds correct command."""
        await self.client.set_axis_speed(100.0)
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent[0:2] == b"\xc9\x03"

    @pytest.mark.asyncio
    async def test_set_travel_speed(self):
        """Test set_travel_speed emits C9 02 with um/s value."""
        await self.client.set_travel_speed(100000)
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == b"\xc9\x02" + encode35(100000)

    @pytest.mark.asyncio
    async def test_rapid_move_xy(self):
        """Test rapid_move_xy emits absolute D9 10 with options 0x00."""
        await self.client.rapid_move_xy(10000, 20000)
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == b"\xd9\x10\x00" + encode35(10000) + encode35(20000)


class TestRuidaClientEndOfFile:
    """Tests for end of file command."""

    def setup_method(self):
        self.mock_transport = MagicMock(
            spec=[
                "connect",
                "disconnect",
                "send",
                "send_command",
                "is_connected",
                "received",
                "decoded_received",
                "status_changed",
            ]
        )
        self.mock_transport.connect = AsyncMock()
        self.mock_transport.disconnect = AsyncMock()
        self.mock_transport.send = AsyncMock()
        self.mock_transport.send_command = AsyncMock()
        self.mock_transport.is_connected = False
        self.mock_transport.received = MagicMock()
        self.mock_transport.received.connect = MagicMock()
        self.mock_transport.decoded_received = MagicMock()
        self.mock_transport.decoded_received.connect = MagicMock()
        self.mock_transport.status_changed = MagicMock()
        self.mock_transport.status_changed.connect = MagicMock()

        self.client = RuidaClient(self.mock_transport)

    @pytest.mark.asyncio
    async def test_end_of_file(self):
        """Test end_of_file sends correct command."""
        await self.client.end_of_file()
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == b"\xd7"

    @pytest.mark.asyncio
    async def test_keep_alive(self):
        """Test keep_alive sends correct command."""
        await self.client.keep_alive()
        self.mock_transport.send_command.assert_called_once()
        sent = self.mock_transport.send_command.call_args[0][0]
        assert sent == b"\xce"

    def test_build_frequency(self):
        result = self.client._build_frequency(1, 1000)
        assert result[:2] == b"\xc6\x60"
        assert result[2] == 1
        assert result[3] == 0
        assert result[4:] == encode35(1000)

    def test_build_frequency_laser_2(self):
        result = self.client._build_frequency(2, 5000)
        assert result[2] == 2
        assert result[4:] == encode35(5000)

    def test_build_pulse_width(self):
        result = self.client._build_pulse_width(1, 50)
        assert result[:2] == b"\xc6\x10"
        assert result[2] == 1
        assert result[3] == 0
        assert result[4:] == encode35(50)

    def test_build_pulse_width_laser_3(self):
        result = self.client._build_pulse_width(3, 200)
        assert result[2] == 3
        assert result[4:] == encode35(200)


class TestRuidaClientAckSerialization:
    """Tests for ACK future isolation between senders."""

    def setup_method(self):
        self.mock_transport = MagicMock(
            spec=[
                "connect",
                "disconnect",
                "send",
                "send_command",
                "is_connected",
                "received",
                "decoded_received",
                "status_changed",
            ]
        )
        self.mock_transport.connect = AsyncMock()
        self.mock_transport.disconnect = AsyncMock()
        self.mock_transport.send = AsyncMock()
        self.mock_transport.send_command = AsyncMock()
        self.mock_transport.is_connected = False
        self.mock_transport.received = MagicMock()
        self.mock_transport.received.connect = MagicMock()
        self.mock_transport.decoded_received = MagicMock()
        self.mock_transport.decoded_received.connect = MagicMock()
        self.mock_transport.status_changed = MagicMock()
        self.mock_transport.status_changed.connect = MagicMock()

        self.client = RuidaClient(self.mock_transport)

    @pytest.mark.asyncio
    async def test_keepalive_ack_cannot_resolve_chunk_future(self):
        """A keepalive is held back while a chunk ACK is pending."""
        chunk_task = asyncio.create_task(
            self.client.send_command_wait_ack(b"\x88\x00", timeout=1.0)
        )
        await asyncio.sleep(0.01)
        assert self.mock_transport.send_command.call_count == 1

        keepalive_task = asyncio.create_task(self.client.keep_alive())
        await asyncio.sleep(0.01)
        # The keepalive must not go out while the chunk ACK is
        # pending, so its ACK can never resolve the chunk future.
        assert self.mock_transport.send_command.call_count == 1

        self.client._handle_response(None, b"\xcc")
        assert await chunk_task is True
        await keepalive_task
        assert self.mock_transport.send_command.call_count == 2


class StubJobTransport:
    """Signal-based in-memory stand-in for RuidaTransport."""

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


def _square_job_commands() -> list[bytes]:
    """A synthetic command list: 100 11-byte motion commands."""
    return [b"\x88" + bytes(10)] * 100


async def _ack_each_chunk(
    client: RuidaClient,
    transport: StubJobTransport,
    reply: bytes,
    count: int,
    timeout: float = 2.0,
) -> None:
    """Feed one reply per sent chunk until count chunks are ACKed."""
    acked = 0
    deadline = asyncio.get_event_loop().time() + timeout
    while acked < count:
        assert asyncio.get_event_loop().time() < deadline
        if len(transport.sent) > acked:
            client._handle_response(None, reply)
            acked += 1
        await asyncio.sleep(0.001)


class TestRuidaClientSendJob:
    """Tests for send_job chunking and ACK handling."""

    def setup_method(self):
        self.transport = StubJobTransport()
        self.client = RuidaClient(self.transport)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_chunks_respect_command_boundaries_and_size(self):
        """Chunks are <=1000 bytes and never split a command."""
        commands = _square_job_commands()
        blob = commands_to_rd_bytes(commands)

        task = asyncio.create_task(self.client.send_job(blob))
        await _ack_each_chunk(self.client, self.transport, b"\xcc", 2)
        await asyncio.wait_for(task, timeout=2.0)

        assert len(self.transport.sent) == 2
        assert all(len(c) <= 1000 for c in self.transport.sent)
        assert all(len(c) % 11 == 0 for c in self.transport.sent)
        assert b"".join(self.transport.sent) == b"".join(commands)

    @pytest.mark.asyncio
    async def test_sent_chunks_reassemble_to_blob(self):
        """Swizzling the sent chunks reproduces the input blob."""
        commands = _square_job_commands()
        blob = commands_to_rd_bytes(commands)

        task = asyncio.create_task(self.client.send_job(blob))
        await _ack_each_chunk(self.client, self.transport, b"\xcc", 2)
        await asyncio.wait_for(task, timeout=2.0)

        resent = bytes(
            swizzle_byte(b, JOB_MAGIC) for b in b"".join(self.transport.sent)
        )
        assert resent == blob

    @pytest.mark.asyncio
    async def test_swizzled_cc_reply_is_ack(self):
        """A swizzled 0xCC reply (decoded 0xCC) is accepted as ACK."""
        blob = commands_to_rd_bytes([b"\x88" + bytes(10)])

        task = asyncio.create_task(self.client.send_job(blob))
        await _ack_each_chunk(self.client, self.transport, b"\xcc", 1)
        await asyncio.wait_for(task, timeout=2.0)

        assert len(self.transport.sent) == 1

    @pytest.mark.asyncio
    async def test_raw_cc_reply_is_ack(self):
        """A raw 0xCC reply (decoded unswizzle(0xCC)) is an ACK too."""
        blob = commands_to_rd_bytes([b"\x88" + bytes(10)])
        decoded = bytes([unswizzle_byte(0xCC, JOB_MAGIC)])

        task = asyncio.create_task(self.client.send_job(blob))
        await _ack_each_chunk(self.client, self.transport, decoded, 1)
        await asyncio.wait_for(task, timeout=2.0)

        assert len(self.transport.sent) == 1

    @pytest.mark.asyncio
    async def test_persistent_nak_aborts_after_four_attempts(self):
        """Four NAKs on one chunk abort the job with an error."""
        blob = commands_to_rd_bytes([b"\x88" + bytes(10)])

        task = asyncio.create_task(self.client.send_job(blob))
        await _ack_each_chunk(self.client, self.transport, b"\xcf", 4)
        with pytest.raises(RuntimeError, match="did not acknowledge"):
            await asyncio.wait_for(task, timeout=2.0)

        assert len(self.transport.sent) == 4
        assert len(set(self.transport.sent)) == 1

    @pytest.mark.asyncio
    async def test_no_keepalive_between_chunks(self):
        """send_job emits only job chunks, never keepalive traffic."""
        commands = _square_job_commands()
        blob = commands_to_rd_bytes(commands)

        task = asyncio.create_task(self.client.send_job(blob))
        await _ack_each_chunk(self.client, self.transport, b"\xcc", 2)
        await asyncio.wait_for(task, timeout=2.0)

        assert b"\xce" not in self.transport.sent
        assert all(c[0] == 0x88 for c in self.transport.sent)

"""
Tests for RuidaUsbTransport (ruida_usb_transport.py).

Two groups:

- vcp-backend tests drive RuidaClient exactly the way ruida_driver.py
  wires RuidaTransport, wired instead to RuidaUsbTransport(backend=
  "vcp"). pyserial.Serial is mocked following the idiom established in
  tests/machine/transport/test_serial_transport.py. These prove that
  RuidaClient's existing chunking (split_commands/build_datagrams) and
  ACK-paced send loop (send_job/_send_job_chunk) work unmodified over
  the new transport -- nothing here reimplements either.

- d2xx-backend tests inject a fake D2xxLibrary (no ctypes, no real
  DLL) to verify the FUN_10001C80 open-sequence call order and abort
  behaviour, and device-selection logging, all mocked.
"""

import asyncio
import logging
import queue

import pytest

from swiftcut.machine.driver.ruida import ruida_client
from swiftcut.machine.driver.ruida.ruida_client import RuidaClient
from swiftcut.machine.driver.ruida.ruida_usb_transport import (
    FT_OK,
    FT_PURGE_RX,
    FT_PURGE_TX,
    D2xxDeviceInfo,
    RuidaUsbTransport,
    _select_device_index,
)
from swiftcut.machine.driver.ruida.ruida_util import (
    build_swizzle_lut,
    frame_packet,
)

MAGIC = 0x88
_SWIZZLE, _ = build_swizzle_lut(MAGIC)


def _device_reply(byte: int) -> bytes:
    """A single-byte device reply (ack/nak), swizzled as real hardware
    sends it -- see RuidaTransport's module docstring ("Server
    responses are NOT framed with checksums - they are just swizzled
    bytes")."""
    return bytes([_SWIZZLE[byte]])


class MockSerial:
    """
    Hand-rolled fake pyserial object, mirroring the MockSerial in
    tests/machine/transport/test_serial_transport.py.
    """

    def __init__(self, *args, **kwargs):
        self.port = kwargs.get("port", "")
        self.baudrate = kwargs.get("baudrate", 9600)
        self.timeout = kwargs.get("timeout", 0)
        self._read_queue: queue.Queue = queue.Queue()
        self._closed = False
        self._written: list[bytes] = []

    def read(self, size=1024):
        if self._closed:
            raise OSError("Port is closed")
        try:
            return self._read_queue.get(timeout=self.timeout or 0.05)
        except queue.Empty:
            return b""

    def write(self, data):
        if self._closed:
            raise OSError("Port is closed")
        self._written.append(bytes(data))
        return len(data)

    def close(self):
        self._closed = True

    def flush(self):
        pass

    def reset_input_buffer(self):
        while True:
            try:
                self._read_queue.get_nowait()
            except queue.Empty:
                break

    def feed_data(self, data: bytes):
        """Simulate incoming data from the device."""
        self._read_queue.put(data)


@pytest.fixture
def mock_serial(mocker):
    """Patch pyserial.Serial where ruida_usb_transport uses it."""
    mock_instance = MockSerial()
    mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_usb_transport.serial.Serial",
        return_value=mock_instance,
    )
    return mock_instance


class FakeD2xxLibrary:
    """
    Records every call made to it, in order, so the open sequence can
    be asserted against the brief's literal FUN_10001C80 list.
    """

    def __init__(
        self,
        devices: list[D2xxDeviceInfo] | None = None,
        reset_status: int = FT_OK,
    ):
        self.calls: list[tuple[str, tuple]] = []
        self._devices = devices or []
        self._reset_status = reset_status
        self._handle = 1001
        self._read_queue: queue.Queue = queue.Queue()
        self._written: list[bytes] = []

    def list_devices(self):
        self.calls.append(("list_devices", ()))
        return self._devices

    def open(self, index):
        self.calls.append(("open", (index,)))
        return self._handle

    def close(self, handle):
        self.calls.append(("close", (handle,)))

    def reset_device(self, handle):
        self.calls.append(("reset_device", (handle,)))
        return self._reset_status

    def set_data_characteristics(
        self, handle, word_length, stop_bits, parity
    ):
        self.calls.append(
            (
                "set_data_characteristics",
                (handle, word_length, stop_bits, parity),
            )
        )

    def set_usb_parameters(self, handle, in_size, out_size):
        self.calls.append(
            ("set_usb_parameters", (handle, in_size, out_size))
        )

    def set_deadman_timeout(self, handle, timeout_ms):
        self.calls.append(("set_deadman_timeout", (handle, timeout_ms)))

    def set_timeouts(self, handle, read_ms, write_ms):
        self.calls.append(("set_timeouts", (handle, read_ms, write_ms)))

    def set_baud_rate(self, handle, baud):
        self.calls.append(("set_baud_rate", (handle, baud)))

    def purge(self, handle, mask):
        self.calls.append(("purge", (handle, mask)))

    def clr_rts(self, handle):
        self.calls.append(("clr_rts", (handle,)))

    def clr_dtr(self, handle):
        self.calls.append(("clr_dtr", (handle,)))

    def set_reset_pipe_retry_count(self, handle, count):
        self.calls.append(("set_reset_pipe_retry_count", (handle, count)))

    def read(self, handle, size):
        try:
            return self._read_queue.get(timeout=0.05)
        except queue.Empty:
            return b""

    def write(self, handle, data):
        self._written.append(bytes(data))
        return len(data)

    def feed_data(self, data: bytes):
        self._read_queue.put(data)


async def _wait_until(predicate, timeout: float = 1.0, interval: float = 0.02):
    """Bounded poll loop -- never a fixed sleep (see
    test_serial_transport.py's own send/receive test)."""
    elapsed = 0.0
    while elapsed < timeout:
        if predicate():
            return True
        await asyncio.sleep(interval)
        elapsed += interval
    return predicate()


# --------------------------------------------------------------------
# vcp backend, driven through RuidaClient
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_command_has_no_checksum(mock_serial):
    """TX framing must be swizzle-only: no 2-byte checksum prefix."""
    transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
    client = RuidaClient(transport)
    await client.connect()
    try:
        command = b"\xd8\x2a"  # home_xy
        await client.send_command(command)

        assert len(mock_serial._written) == 1
        on_wire = mock_serial._written[0]
        swizzled = transport._codec.swizzle(command)

        assert on_wire == swizzled
        assert on_wire != frame_packet(swizzled)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_second_chunk_waits_for_ack(mock_serial, monkeypatch):
    """The sender must wait for 0xCC/0xC6 before sending the next chunk."""
    monkeypatch.setattr(ruida_client, "JOB_ACK_TIMEOUT", 0.3)
    monkeypatch.setattr(ruida_client, "JOB_CHUNK_MAX_BYTES", 2)

    transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
    client = RuidaClient(transport)
    await client.connect()
    try:
        # Two whole 2-byte commands; JOB_CHUNK_MAX_BYTES=2 forces them
        # into separate chunks.
        blob = b"\xd8\x2a" + b"\xd8\x00"
        task = asyncio.create_task(client.send_job(blob))
        try:
            assert await _wait_until(lambda: len(mock_serial._written) == 1)

            # No ack yet: the second chunk must not be sent.
            await asyncio.sleep(0.1)
            assert len(mock_serial._written) == 1

            mock_serial.feed_data(_device_reply(0xCC))
            assert await _wait_until(lambda: len(mock_serial._written) == 2)

            mock_serial.feed_data(_device_reply(0xCC))
            await asyncio.wait_for(task, timeout=1.0)
        finally:
            if not task.done():
                task.cancel()
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_nak_triggers_resend(mock_serial, monkeypatch):
    """A NAK (0xCF/0xCD) must trigger a resend of the same chunk."""
    monkeypatch.setattr(ruida_client, "JOB_ACK_TIMEOUT", 0.3)

    transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
    client = RuidaClient(transport)
    await client.connect()
    try:
        blob = b"\xd8\x2a"
        task = asyncio.create_task(client.send_job(blob))
        try:
            assert await _wait_until(lambda: len(mock_serial._written) == 1)

            # No NAK yet: the chunk must not be resent on its own.
            await asyncio.sleep(0.1)
            assert len(mock_serial._written) == 1

            mock_serial.feed_data(_device_reply(0xCF))  # NAK
            assert await _wait_until(lambda: len(mock_serial._written) == 2)
            assert mock_serial._written[0] == mock_serial._written[1]

            mock_serial.feed_data(_device_reply(0xCC))  # ACK
            await asyncio.wait_for(task, timeout=1.0)
        finally:
            if not task.done():
                task.cancel()
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_no_ack_ever_raises_after_all_attempts(mock_serial, monkeypatch):
    """If no ACK ever arrives, send_job must give up after the fixed
    number of attempts, having tried to send once per attempt."""
    monkeypatch.setattr(ruida_client, "JOB_ACK_TIMEOUT", 0.05)
    monkeypatch.setattr(ruida_client, "JOB_SEND_ATTEMPTS", 2)

    transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
    client = RuidaClient(transport)
    await client.connect()
    try:
        blob = b"\xd8\x2a"
        with pytest.raises(RuntimeError, match="did not acknowledge"):
            await asyncio.wait_for(client.send_job(blob), timeout=2.0)

        assert len(mock_serial._written) == 2
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_chunking_respects_command_boundaries_and_cap(mock_serial):
    """
    Chunking (split_commands/build_datagrams) is owned by RuidaClient
    and reused unmodified; this proves it still holds -- <=1000 bytes
    per chunk, never splitting a command -- when driven over the USB
    transport.
    """
    command = b"\xd9\x10" + b"\x00" * 11  # 13-byte whole command
    assert len(command) == 13
    plain = command * 90  # 1170 unswizzled bytes -> must split
    blob = bytes(_SWIZZLE[b] for b in plain)

    transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
    client = RuidaClient(transport)
    await client.connect()
    try:
        task = asyncio.create_task(client.send_job(blob))
        try:
            while not task.done():
                written_before = len(mock_serial._written)
                # Wait for either the next chunk to go out, or the job
                # to finish -- feeding one ACK too many races the task
                # completing on the final chunk.
                assert await _wait_until(
                    lambda: len(mock_serial._written) > written_before
                    or task.done()
                )
                if task.done():
                    break
                mock_serial.feed_data(_device_reply(0xCC))
            await asyncio.wait_for(task, timeout=1.0)
        finally:
            if not task.done():
                task.cancel()
    finally:
        await client.disconnect()

    chunks = [transport._codec.unswizzle(w) for w in mock_serial._written]
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= ruida_client.JOB_CHUNK_MAX_BYTES
        assert len(chunk) % 13 == 0  # never splits the 13-byte command
    assert b"".join(chunks) == plain


@pytest.mark.asyncio
async def test_keepalive_enq_ack(mock_serial):
    """Keepalive is ENQ (0xCE) out, ACK (0xCC) in, swizzle-only."""
    transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
    client = RuidaClient(transport)
    await client.connect()
    try:
        await client.keep_alive()
        assert len(mock_serial._written) == 1
        swizzled_enq = transport._codec.swizzle(b"\xce")
        assert mock_serial._written[0] == swizzled_enq
        assert mock_serial._written[0] != frame_packet(swizzled_enq)
        assert client.last_enq_sent_at is not None

        mock_serial.feed_data(_device_reply(0xCC))
        assert await _wait_until(
            lambda: client.last_ack_received_at is not None
        )
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_disconnect_joins_reader_thread_before_closing(mock_serial):
    """
    The reader thread must be stopped before the device handle is
    closed, not the other way around: closing while the reader thread
    may still be inside a blocking read() races FT_Close/serial.close()
    against that read at the driver level, not just a Python one.
    """
    transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
    await transport.connect()
    reader_thread = transport._raw._reader_thread
    assert reader_thread is not None

    thread_alive_when_closed = None
    orig_close = mock_serial.close

    def spy_close():
        nonlocal thread_alive_when_closed
        thread_alive_when_closed = reader_thread.is_alive()
        orig_close()

    mock_serial.close = spy_close

    await transport.disconnect()

    assert thread_alive_when_closed is False


# --------------------------------------------------------------------
# d2xx backend, with a fake D2xxLibrary (no ctypes, no real DLL)
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d2xx_open_sequence_matches_brief_order(monkeypatch):
    import swiftcut.machine.driver.ruida.ruida_usb_transport as mod

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    fake = FakeD2xxLibrary()
    transport = RuidaUsbTransport(backend="d2xx", d2xx_library=fake)
    await transport.connect()
    try:
        handle = fake._handle
        assert fake.calls[0] == ("list_devices", ())
        assert fake.calls[1:] == [
            ("open", (0,)),
            ("reset_device", (handle,)),
            ("set_data_characteristics", (handle, 8, 0, 0)),
            ("set_usb_parameters", (handle, 1024, 1204)),
            ("set_deadman_timeout", (handle, 0xFFFFFFFF)),
            ("set_timeouts", (handle, 100, 1000)),
            ("set_baud_rate", (handle, 19200)),
            ("purge", (handle, FT_PURGE_RX | FT_PURGE_TX)),
            ("clr_rts", (handle,)),
            ("clr_dtr", (handle,)),
            ("set_reset_pipe_retry_count", (handle, 100)),
        ]
    finally:
        await transport.disconnect()


@pytest.mark.asyncio
async def test_d2xx_reset_device_failure_aborts_open(monkeypatch):
    import swiftcut.machine.driver.ruida.ruida_usb_transport as mod

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    fake = FakeD2xxLibrary(reset_status=1)  # non-zero: FT_ResetDevice fails
    transport = RuidaUsbTransport(backend="d2xx", d2xx_library=fake)
    with pytest.raises(ConnectionError):
        await transport.connect()

    assert [c[0] for c in fake.calls] == [
        "list_devices",
        "open",
        "reset_device",
    ]


@pytest.mark.asyncio
async def test_d2xx_frames_have_no_checksum(monkeypatch):
    import swiftcut.machine.driver.ruida.ruida_usb_transport as mod

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    fake = FakeD2xxLibrary()
    transport = RuidaUsbTransport(backend="d2xx", d2xx_library=fake)
    client = RuidaClient(transport)
    await client.connect()
    try:
        command = b"\xd8\x2a"
        await client.send_command(command)

        assert len(fake._written) == 1
        on_wire = fake._written[0]
        swizzled = transport._codec.swizzle(command)
        assert on_wire == swizzled
        assert on_wire != frame_packet(swizzled)
    finally:
        await client.disconnect()


# --------------------------------------------------------------------
# Device selection
# --------------------------------------------------------------------


def test_device_selection_pinned_serial_wins():
    devices = [
        D2xxDeviceInfo(index=0, description="Ruida A", serial="AAA"),
        D2xxDeviceInfo(index=1, description="Ruida B", serial="BBB"),
    ]
    assert _select_device_index(devices, "BBB") == 1


def test_device_selection_falls_back_to_index0_with_warning(caplog):
    devices = [
        D2xxDeviceInfo(index=0, description="Ruida A", serial="AAA"),
        D2xxDeviceInfo(index=1, description="Ruida B", serial="BBB"),
    ]
    with caplog.at_level(logging.WARNING):
        index = _select_device_index(devices, None)

    assert index == 0
    warnings = [
        r.message for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any("BBB" in w and "Ruida B" in w for w in warnings)

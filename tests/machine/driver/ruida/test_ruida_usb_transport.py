"""
Tests for RuidaUsbTransport (ruida_usb_transport.py).

Two groups:

- vcp-backend tests drive RuidaClient exactly the way ruida_driver.py
  wires RuidaTransport, wired instead to RuidaUsbTransport(backend=
  "vcp"). pyserial.Serial is mocked following the idiom established in
  tests/machine/transport/test_serial_transport.py. These prove that
  RuidaClient's existing chunking (split_commands/build_datagrams) and
  ACK-paced send loop (send_job/_send_job_chunk) work unmodified over
  the new transport -- nothing here reimplements either. The vcp
  open sequence, reads, and FTDI port enumeration/selection are
  tested against the same mock.

- d2xx-backend tests inject a fake D2xxLibrary (no ctypes, no real
  DLL) to verify the FUN_10001C80 open-sequence call order and abort
  behaviour, and device-selection logging, all mocked.
"""

import asyncio
import errno
import logging
import os
import queue
import threading
from types import SimpleNamespace

import pytest
import serial

from swiftcut.machine.driver.ruida import ruida_client
from swiftcut.machine.driver.ruida.ruida_client import RuidaClient
from swiftcut.machine.driver.ruida.ruida_usb_transport import (
    FT_OK,
    FT_PURGE_RX,
    FT_PURGE_TX,
    D2xxDeviceInfo,
    RuidaUsbTransport,
    VcpDeviceInfo,
    _select_device_index,
    _select_vcp_device,
    list_vcp_devices,
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
        # Every modem-line set and buffer purge, in order, so the open
        # sequence can be asserted.
        self.calls: list[tuple] = []
        self.in_waiting = 0
        self.read_sizes: list[int] = []

    @property
    def rts(self):
        return None

    @rts.setter
    def rts(self, value):
        self.calls.append(("rts", value))

    @property
    def dtr(self):
        return None

    @dtr.setter
    def dtr(self, value):
        self.calls.append(("dtr", value))

    def read(self, size=1024):
        if self._closed:
            raise OSError("Port is closed")
        self.read_sizes.append(size)
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
        self.calls.append(("reset_input_buffer",))
        while True:
            try:
                self._read_queue.get_nowait()
            except queue.Empty:
                break

    def reset_output_buffer(self):
        self.calls.append(("reset_output_buffer",))

    def feed_data(self, data: bytes):
        """Simulate incoming data from the device."""
        self._read_queue.put(data)


@pytest.fixture
def serial_cls(mocker):
    """Patch pyserial.Serial where ruida_usb_transport uses it. Each
    construction (the open) is recorded as ("open",) in .calls."""
    instance = MockSerial()

    def open_port(*args, **kwargs):
        instance._closed = False
        instance.calls.append(("open",))
        return instance

    cls = mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_usb_transport.serial.Serial",
        side_effect=open_port,
    )
    cls.instance = instance
    return cls


@pytest.fixture
def mock_serial(serial_cls):
    return serial_cls.instance


def _ftdi_port(device, serial_number, description="FT245R USB FIFO"):
    """A list_ports.comports() entry for an FTDI chip."""
    return SimpleNamespace(
        device=device,
        vid=0x0403,
        pid=0x6001,
        description=description,
        serial_number=serial_number,
    )


@pytest.fixture
def comports(mocker):
    """Patch list_ports.comports(); set .return_value per test."""
    return mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_usb_transport"
        ".list_ports.comports",
        return_value=[],
    )


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


def _raw_io(caplog, direction: str) -> list[bytes]:
    return [
        r.data
        for r in caplog.records
        if getattr(r, "log_category", None) == "RAW_IO"
        and r.direction == direction
    ]


@pytest.mark.asyncio
async def test_raw_io_logs_tx_and_rx_like_the_udp_wrapper(mock_serial, caplog):
    """
    Both directions are logged at DEBUG under RAW_IO, unswizzled, the
    way RuidaTransport logs UDP, so a session log shows what crossed
    the USB wire.
    """
    transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
    client = RuidaClient(transport)
    await client.connect()
    try:
        with caplog.at_level(logging.DEBUG):
            await client.keep_alive()
            await transport.send(b"\x01\x02")
            mock_serial.feed_data(_device_reply(0xCC))
            assert await _wait_until(lambda: _raw_io(caplog, "RX"))
    finally:
        await client.disconnect()

    assert _raw_io(caplog, "TX") == [b"\xce", b"\x01\x02"]
    assert _raw_io(caplog, "RX") == [b"\xcc"]
    messages = [r.message for r in caplog.records]
    assert "TX: b'\\xce'" in messages
    assert "TX (raw): b'\\x01\\x02'" in messages
    assert "RX: b'\\xcc'" in messages


@pytest.mark.asyncio
async def test_first_ack_of_each_connection_logs_the_handshake(
    mock_serial, caplog
):
    received: list[bytes] = []
    transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
    transport.decoded_received.connect(
        lambda sender, data: received.append(data), weak=False
    )

    with caplog.at_level(logging.INFO):
        for connection in range(1, 3):
            await transport.connect()
            mock_serial.feed_data(_device_reply(0xCC))
            mock_serial.feed_data(_device_reply(0xCC))
            expected = 2 * connection
            assert await _wait_until(lambda n=expected: len(received) == n)
            await transport.disconnect()

    handshakes = [r for r in caplog.records if r.message == "USB handshake ok"]
    assert len(handshakes) == 2
    assert all(r.levelno == logging.INFO for r in handshakes)


@pytest.mark.asyncio
async def test_a_cancelled_connect_closes_the_port_its_open_returns(
    mock_serial, monkeypatch
):
    """
    Cancelling connect() does not stop _open in its executor thread.
    The port that open goes on to return must still be closed, or it
    stays open with no owner after a rebuild cancels the loop.
    """
    import swiftcut.machine.driver.ruida.ruida_usb_transport as mod

    in_open = threading.Event()
    release = threading.Event()

    def settle(seconds):
        in_open.set()
        release.wait(2.0)

    monkeypatch.setattr(mod.time, "sleep", settle)
    transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
    task = asyncio.create_task(transport.connect())
    assert await _wait_until(in_open.is_set)

    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert mock_serial._closed
    assert not transport.is_connected


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
# vcp backend: the open sequence, reads, and finding the device
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vcp_open_sequence_matches_brief(
    serial_cls, mock_serial, monkeypatch
):
    """
    The VCP form of FUN_10001C80: 8N1 at 19200 with FT_SetTimeouts'
    0.1 s read / 1 s write and no flow control, then -- after the
    open -- RTS and DTR cleared, both buffers purged, a 100 ms settle.
    """
    import swiftcut.machine.driver.ruida.ruida_usb_transport as mod

    monkeypatch.setattr(
        mod.time, "sleep", lambda s: mock_serial.calls.append(("sleep", s))
    )
    transport = RuidaUsbTransport(backend="vcp", port="/dev/cu.mock")
    await transport.connect()
    try:
        serial_cls.assert_called_once_with(
            port="/dev/cu.mock",
            baudrate=19200,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.1,
            write_timeout=1.0,
            rtscts=False,
            dsrdtr=False,
        )
        assert mock_serial.calls == [
            ("open",),
            ("rts", False),
            ("dtr", False),
            ("reset_input_buffer",),
            ("reset_output_buffer",),
            ("sleep", 0.1),
        ]
    finally:
        await transport.disconnect()


def test_vcp_read_asks_for_what_is_buffered(mock_serial):
    """At least one byte, else everything already buffered: an ACK is
    handed over as soon as it lands, not after the read timeout."""
    transport = RuidaUsbTransport(backend="vcp", port="/dev/mock")
    transport._raw._serial = mock_serial

    mock_serial.in_waiting = 0
    transport._raw._raw_read()
    mock_serial.in_waiting = 5
    transport._raw._raw_read()

    assert mock_serial.read_sizes == [1, 5]


@pytest.mark.asyncio
async def test_vcp_connect_opens_the_ftdi_port_and_logs_it(
    serial_cls, comports, caplog
):
    """With no port given, connect() enumerates FTDI ports itself and
    logs the chosen device's description and serial every time."""
    comports.return_value = [
        SimpleNamespace(
            device="/dev/cu.Bluetooth-Incoming-Port",
            vid=None,
            pid=None,
            description="n/a",
            serial_number=None,
        ),
        _ftdi_port("/dev/cu.usbserial-A10K3XYZ", "A10K3XYZ"),
    ]
    transport = RuidaUsbTransport(backend="vcp")

    with caplog.at_level(logging.INFO):
        for _ in range(2):
            await transport.connect()
            await transport.disconnect()

    assert serial_cls.call_count == 2
    assert serial_cls.call_args.kwargs["port"] == "/dev/cu.usbserial-A10K3XYZ"
    assert transport.device == VcpDeviceInfo(
        "/dev/cu.usbserial-A10K3XYZ", "FT245R USB FIFO", "A10K3XYZ"
    )
    logged = [
        r.message
        for r in caplog.records
        if r.levelno == logging.INFO
        and "A10K3XYZ" in r.message
        and "FT245R USB FIFO" in r.message
    ]
    assert len(logged) == 2


@pytest.mark.asyncio
async def test_vcp_connect_without_an_ftdi_port_fails_clearly(
    serial_cls, comports
):
    comports.return_value = [
        SimpleNamespace(
            device="/dev/cu.debug-console",
            vid=None,
            pid=None,
            description="n/a",
            serial_number=None,
        )
    ]
    transport = RuidaUsbTransport(backend="vcp")

    with pytest.raises(ConnectionError, match="No FTDI USB device"):
        await transport.connect()
    serial_cls.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [errno.EBUSY, errno.EACCES])
async def test_vcp_port_held_elsewhere_is_reported_as_in_use(
    comports, mocker, error
):
    """A port that enumerates but will not open is not a missing
    device: busy or permission denied names the port as in use."""
    comports.return_value = [_ftdi_port("/dev/cu.usbserial-AAA", "AAA")]
    mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_usb_transport.serial.Serial",
        side_effect=serial.SerialException(
            error, f"could not open port: {os.strerror(error)}"
        ),
    )
    transport = RuidaUsbTransport(backend="vcp")

    with pytest.raises(ConnectionError) as raised:
        await transport.connect()

    assert str(raised.value) == (
        "USB port in use (another app or a stale connection): "
        "/dev/cu.usbserial-AAA"
    )
    assert not transport.is_connected


@pytest.mark.asyncio
async def test_vcp_other_open_failures_keep_their_own_error(comports, mocker):
    comports.return_value = [_ftdi_port("/dev/cu.usbserial-AAA", "AAA")]
    failure = serial.SerialException(
        errno.ENOENT, "could not open port: No such file or directory"
    )
    mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_usb_transport.serial.Serial",
        side_effect=failure,
    )
    transport = RuidaUsbTransport(backend="vcp")

    with pytest.raises(serial.SerialException) as raised:
        await transport.connect()

    assert raised.value is failure


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


@pytest.mark.asyncio
async def test_d2xx_records_the_opened_device(monkeypatch):
    import swiftcut.machine.driver.ruida.ruida_usb_transport as mod

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    devices = [
        D2xxDeviceInfo(index=0, description="Ruida A", serial="AAA"),
        D2xxDeviceInfo(index=1, description="Ruida B", serial="BBB"),
    ]
    fake = FakeD2xxLibrary(devices=devices)
    transport = RuidaUsbTransport(
        backend="d2xx", usb_serial="BBB", d2xx_library=fake
    )
    await transport.connect()
    try:
        assert transport.device == devices[1]
    finally:
        await transport.disconnect()


_PORT_A = VcpDeviceInfo("/dev/cu.usbserial-AAA", "FT245R USB FIFO", "AAA")
_PORT_B = VcpDeviceInfo("/dev/cu.usbserial-BBB", "FT232R USB UART", "BBB")


def _warnings(caplog) -> list[str]:
    return [r.message for r in caplog.records if r.levelno == logging.WARNING]


def test_list_vcp_devices_keeps_only_ftdi_ports(comports):
    comports.return_value = [
        SimpleNamespace(
            device="/dev/cu.usbmodem1101",
            vid=0x2341,
            pid=0x0043,
            description="Arduino Uno",
            serial_number="ARD1",
        ),
        _ftdi_port("/dev/cu.usbserial-AAA", "AAA"),
    ]

    assert list_vcp_devices() == [_PORT_A]


def test_vcp_selection_pinned_serial_wins(caplog):
    with caplog.at_level(logging.WARNING):
        assert _select_vcp_device([_PORT_A, _PORT_B], "BBB") is _PORT_B
    assert _warnings(caplog) == []


def test_vcp_selection_sole_match_needs_no_pin(caplog):
    with caplog.at_level(logging.WARNING):
        assert _select_vcp_device([_PORT_A], None) is _PORT_A
    assert _warnings(caplog) == []


def test_vcp_selection_first_of_several_warns_with_the_others(caplog):
    with caplog.at_level(logging.WARNING):
        assert _select_vcp_device([_PORT_A, _PORT_B], None) is _PORT_A
    assert any(
        "BBB" in w and "FT232R USB UART" in w for w in _warnings(caplog)
    )


def test_vcp_selection_missing_pin_warns_and_falls_back(caplog):
    with caplog.at_level(logging.WARNING):
        assert _select_vcp_device([_PORT_A], "ZZZ") is _PORT_A
    assert any("ZZZ" in w for w in _warnings(caplog))


def test_vcp_selection_with_no_devices_raises():
    with pytest.raises(ConnectionError, match="No FTDI USB device"):
        _select_vcp_device([], None)

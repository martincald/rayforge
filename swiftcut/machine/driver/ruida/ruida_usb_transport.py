"""
Ruida L2 transport for a direct USB link (RuidaUsbTransport).

Counterpart to RuidaTransport (ruida_transport.py), which wraps UDP.
This wraps one of two USB backends -- d2xx (ctypes binding of the
FTDI D2XX DLL, Windows default) or vcp (pyserial, macOS/Linux default,
Windows optional) -- behind a single duck-typed surface. See
docs/reference/rdcam_usb.md for the owner's decompile brief this
module implements.

Two framing differences from the UDP path, both required because a
USB byte stream has neither a checksum nor datagram boundaries:

1. TX: send_command() swizzles the command but does NOT prepend the
   2-byte checksum frame_packet() adds for UDP. This mirrors
   RuidaTransport.send_response(), which is already swizzle-only.

2. RX: a read() returns an arbitrary slice of the byte stream, not one
   whole reply the way a UDP datagram is. Replies are reassembled from
   a buffer using the only two response shapes this repository's own
   Ruida code models: a single status byte (ack/nak/keepalive echo),
   or a 9-byte "DA 01 <addr> <encode35>" memory-read reply (see
   RuidaClient._handle_response's parser and ruida_server.py's
   response builder).

   ruida_util.estimate_packet_length() is deliberately NOT reused for
   this: it is calibrated for host->device job-stream commands (its
   own "DA 01" case is 14 bytes, a memory *write*), which is a
   different length than the 9-byte memory-*read* reply the
   controller actually sends back. Reusing it here would make
   read_position()/get_card_id() hang forever waiting for 5 bytes that
   never arrive.

Chunking (split_commands/build_datagrams, <=1000 bytes on command
boundaries) and the ACK-paced send loop (send_job/_send_job_chunk,
with NAK retry and timeout handling) both live in RuidaClient and are
transport-agnostic already -- this module does not reimplement either.
Passing an instance of this class as the `transport` argument to
RuidaClient(...) with no `jog_transport` (USB is a single stream; there
is no jog port) is sufficient: RuidaClient only type-hints its
transport under TYPE_CHECKING and never isinstance-checks it, so
duck-typing the same surface RuidaTransport already provides
(decoded_received, is_connected, connect/disconnect, send_command,
send, status_changed) is all that's required.

This supersedes the earlier ruida_serial_transport.py spike (absorbed
here: RuidaSerialTransport -> RuidaUsbTransport, backend names
"pyserial"/"ftd2xx" -> "vcp"/"d2xx" per the brief's own names, and the
"ftd2xx" backend's raw ftd2xx-package prototype replaced by a ctypes
D2XX binding -- see docs/reference/rdcam_usb.md section 3 for why the
PyPI ftd2xx package cannot be used in this environment).
"""

import asyncio
import ctypes
import glob
import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Literal

import serial
from blinker import Signal

from swiftcut.machine.transport.transport import TransportStatus

from .ruida_codec import RuidaCodec

logger = logging.getLogger(__name__)

Backend = Literal["vcp", "d2xx"]

# Read chunk size for both backends' reader threads.
_READ_CHUNK_SIZE = 1024

# FT_STATUS success value, and FT_Purge mask bits (D2XX API constants).
FT_OK = 0
FT_PURGE_RX = 1
FT_PURGE_TX = 2

_SERIAL_BUF_LEN = 16
_DESC_BUF_LEN = 64

# The DLL is only staged in the Windows driver store on this
# development machine (see docs/reference/rdcam_usb.md section 3); the
# hash suffix in the path is a per-package identifier that changes
# when the driver updates, so it is globbed rather than hardcoded.
_DRIVER_STORE_GLOB = (
    r"C:\Windows\System32\DriverStore\FileRepository"
    r"\ftdibus.inf_*\amd64\ftd2xx64.dll"
)


class D2xxNotAvailable(RuntimeError):
    """The FTDI D2XX DLL could not be located or loaded."""


class D2xxError(RuntimeError):
    """A D2XX call returned a non-zero FT_STATUS."""

    def __init__(self, function: str, status: int):
        self.function = function
        self.status = status
        super().__init__(f"{function} failed with FT_STATUS {status}")


def load_d2xx_dll() -> "ctypes.WinDLL":
    """
    Load the FTDI D2XX DLL.

    Tries the normal DLL search path first (ftd2xx64.dll, then
    ftd2xx.dll), then falls back to the Windows driver store, where
    the DLL is staged even before ftdibus.sys has bound to a device.
    """
    if sys.platform != "win32":
        raise D2xxNotAvailable(
            "The d2xx backend is only available on Windows; use "
            "backend='vcp' on this platform."
        )
    candidates = ["ftd2xx64.dll", "ftd2xx.dll"]
    candidates += sorted(glob.glob(_DRIVER_STORE_GLOB), reverse=True)
    tried = []
    for candidate in candidates:
        try:
            return ctypes.WinDLL(candidate)
        except OSError as e:
            tried.append(f"{candidate}: {e}")
    raise D2xxNotAvailable(
        "FTDI D2XX DLL not found. Install the FTDI D2XX driver "
        "(https://ftdichip.com/drivers/d2xx-drivers/), or plug the "
        "controller in so Windows binds ftdibus and stages "
        "ftd2xx64.dll on the DLL search path. Tried:\n  "
        + "\n  ".join(tried)
    )


@dataclass(frozen=True)
class D2xxDeviceInfo:
    """One entry from FT_GetDeviceInfoDetail."""

    index: int
    description: str
    serial: str


class D2xxLibrary:
    """
    Pythonic wrapper around the subset of the D2XX API this transport
    uses, bound via ctypes rather than the PyPI ftd2xx package -- see
    docs/reference/rdcam_usb.md section 3 for why: ftd2xx requires
    pywin32 (no MSYS2/MinGW build) and its sdist fails on Python 3.14,
    while ctypes.WinDLL loads the DLL directly and every needed
    FT_* export is verified present.
    """

    def __init__(self, dll: "ctypes.WinDLL"):
        self._dll = dll
        h = ctypes.c_void_p
        u = ctypes.c_ulong
        pu = ctypes.POINTER(u)

        dll.FT_Open.argtypes = [ctypes.c_int, ctypes.POINTER(h)]
        dll.FT_Open.restype = u
        dll.FT_Close.argtypes = [h]
        dll.FT_Close.restype = u
        dll.FT_ResetDevice.argtypes = [h]
        dll.FT_ResetDevice.restype = u
        dll.FT_SetDataCharacteristics.argtypes = [
            h,
            ctypes.c_ubyte,
            ctypes.c_ubyte,
            ctypes.c_ubyte,
        ]
        dll.FT_SetDataCharacteristics.restype = u
        dll.FT_SetUSBParameters.argtypes = [h, u, u]
        dll.FT_SetUSBParameters.restype = u
        dll.FT_SetDeadmanTimeout.argtypes = [h, u]
        dll.FT_SetDeadmanTimeout.restype = u
        dll.FT_SetTimeouts.argtypes = [h, u, u]
        dll.FT_SetTimeouts.restype = u
        dll.FT_SetBaudRate.argtypes = [h, u]
        dll.FT_SetBaudRate.restype = u
        dll.FT_Purge.argtypes = [h, u]
        dll.FT_Purge.restype = u
        dll.FT_ClrRts.argtypes = [h]
        dll.FT_ClrRts.restype = u
        dll.FT_ClrDtr.argtypes = [h]
        dll.FT_ClrDtr.restype = u
        dll.FT_SetResetPipeRetryCount.argtypes = [h, u]
        dll.FT_SetResetPipeRetryCount.restype = u
        dll.FT_Read.argtypes = [h, ctypes.c_void_p, u, pu]
        dll.FT_Read.restype = u
        dll.FT_Write.argtypes = [h, ctypes.c_void_p, u, pu]
        dll.FT_Write.restype = u
        dll.FT_CreateDeviceInfoList.argtypes = [pu]
        dll.FT_CreateDeviceInfoList.restype = u
        dll.FT_GetDeviceInfoDetail.argtypes = [
            u,
            pu,
            pu,
            pu,
            pu,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.POINTER(h),
        ]
        dll.FT_GetDeviceInfoDetail.restype = u

    def _check(self, function: str, status: int) -> None:
        if status != FT_OK:
            raise D2xxError(function, status)

    def list_devices(self) -> list[D2xxDeviceInfo]:
        num = ctypes.c_ulong(0)
        self._check(
            "FT_CreateDeviceInfoList",
            self._dll.FT_CreateDeviceInfoList(ctypes.byref(num)),
        )
        devices = []
        for i in range(num.value):
            flags = ctypes.c_ulong(0)
            dev_type = ctypes.c_ulong(0)
            dev_id = ctypes.c_ulong(0)
            loc_id = ctypes.c_ulong(0)
            serial_buf = ctypes.create_string_buffer(_SERIAL_BUF_LEN)
            desc_buf = ctypes.create_string_buffer(_DESC_BUF_LEN)
            handle = ctypes.c_void_p()
            self._check(
                "FT_GetDeviceInfoDetail",
                self._dll.FT_GetDeviceInfoDetail(
                    i,
                    ctypes.byref(flags),
                    ctypes.byref(dev_type),
                    ctypes.byref(dev_id),
                    ctypes.byref(loc_id),
                    serial_buf,
                    desc_buf,
                    ctypes.byref(handle),
                ),
            )
            devices.append(
                D2xxDeviceInfo(
                    index=i,
                    description=desc_buf.value.decode(
                        "ascii", errors="replace"
                    ),
                    serial=serial_buf.value.decode(
                        "ascii", errors="replace"
                    ),
                )
            )
        return devices

    def open(self, index: int):
        handle = ctypes.c_void_p()
        self._check("FT_Open", self._dll.FT_Open(index, ctypes.byref(handle)))
        return handle

    def close(self, handle) -> None:
        self._check("FT_Close", self._dll.FT_Close(handle))

    def reset_device(self, handle) -> int:
        """Returns the raw FT_STATUS; the brief calls out this one
        step as abort-on-failure, so the caller decides."""
        return self._dll.FT_ResetDevice(handle)

    def set_data_characteristics(
        self, handle, word_length: int, stop_bits: int, parity: int
    ) -> None:
        self._check(
            "FT_SetDataCharacteristics",
            self._dll.FT_SetDataCharacteristics(
                handle, word_length, stop_bits, parity
            ),
        )

    def set_usb_parameters(
        self, handle, in_transfer_size: int, out_transfer_size: int
    ) -> None:
        self._check(
            "FT_SetUSBParameters",
            self._dll.FT_SetUSBParameters(
                handle, in_transfer_size, out_transfer_size
            ),
        )

    def set_deadman_timeout(self, handle, timeout_ms: int) -> None:
        self._check(
            "FT_SetDeadmanTimeout",
            self._dll.FT_SetDeadmanTimeout(handle, timeout_ms),
        )

    def set_timeouts(
        self, handle, read_timeout_ms: int, write_timeout_ms: int
    ) -> None:
        self._check(
            "FT_SetTimeouts",
            self._dll.FT_SetTimeouts(
                handle, read_timeout_ms, write_timeout_ms
            ),
        )

    def set_baud_rate(self, handle, baud_rate: int) -> None:
        self._check(
            "FT_SetBaudRate", self._dll.FT_SetBaudRate(handle, baud_rate)
        )

    def purge(self, handle, mask: int) -> None:
        self._check("FT_Purge", self._dll.FT_Purge(handle, mask))

    def clr_rts(self, handle) -> None:
        self._check("FT_ClrRts", self._dll.FT_ClrRts(handle))

    def clr_dtr(self, handle) -> None:
        self._check("FT_ClrDtr", self._dll.FT_ClrDtr(handle))

    def set_reset_pipe_retry_count(self, handle, count: int) -> None:
        self._check(
            "FT_SetResetPipeRetryCount",
            self._dll.FT_SetResetPipeRetryCount(handle, count),
        )

    def read(self, handle, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        returned = ctypes.c_ulong(0)
        self._check(
            "FT_Read",
            self._dll.FT_Read(handle, buf, size, ctypes.byref(returned)),
        )
        return buf.raw[: returned.value]

    def write(self, handle, data: bytes) -> int:
        written = ctypes.c_ulong(0)
        self._check(
            "FT_Write",
            self._dll.FT_Write(
                handle, data, len(data), ctypes.byref(written)
            ),
        )
        return written.value


def _select_device_index(
    devices: list[D2xxDeviceInfo], pinned_serial: str | None
) -> int:
    """
    Pick a device index, better than RDWorks' FT_Open(0).

    Every detected device's description and serial is logged at INFO
    so the owner can pin one. A profile-pinned serial wins outright;
    otherwise index 0 is used, with a WARNING listing any other
    devices found (so a wrong-default connection is never silent).
    """
    for d in devices:
        logger.info(
            f"D2XX device {d.index}: description={d.description!r} "
            f"serial={d.serial!r}"
        )

    if pinned_serial:
        for d in devices:
            if d.serial == pinned_serial:
                return d.index
        logger.warning(
            f"Pinned usb_serial {pinned_serial!r} not found among "
            f"detected D2XX devices; falling back to index 0."
        )
        return 0

    others = [d for d in devices if d.index != 0]
    if others:
        found = ", ".join(
            f"{d.index}:{d.description!r}/{d.serial!r}" for d in others
        )
        logger.warning(
            f"No usb_serial pinned; opening device index 0. Other "
            f"devices found: {found}"
        )
    return 0


class _UsbBackendBase:
    """
    Shared reader-thread scaffolding for the vcp and d2xx backends.

    Both backends read from a driver whose own read() call blocks up
    to a bounded timeout (100 ms for d2xx via FT_SetTimeouts, 0.1 s for
    vcp via pyserial's timeout=). That bound is what keeps the reader
    thread from spinning without yielding: no additional sleep is
    needed between empty reads, unlike a non-blocking (timeout=0)
    read loop would require.
    """

    def __init__(self) -> None:
        self.received = Signal()
        self.status_changed = Signal()
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: threading.Event | None = None
        self._reader_thread: threading.Thread | None = None

    @property
    def is_connected(self) -> bool:
        return self._running

    def _open(self) -> None:
        raise NotImplementedError

    def _close(self) -> None:
        raise NotImplementedError

    def _raw_read(self) -> bytes:
        raise NotImplementedError

    def _raw_write(self, data: bytes) -> None:
        raise NotImplementedError

    def _raw_purge(self) -> None:
        raise NotImplementedError

    async def connect(self) -> None:
        loop = asyncio.get_running_loop()
        self.status_changed.send(self, status=TransportStatus.CONNECTING)
        try:
            await loop.run_in_executor(None, self._open)
        except Exception as e:
            self.status_changed.send(
                self, status=TransportStatus.ERROR, message=str(e)
            )
            raise
        self._running = True
        self._loop = loop
        self._stop_event = threading.Event()
        self.status_changed.send(self, status=TransportStatus.CONNECTED)
        self._reader_thread = threading.Thread(
            target=self._reader_thread_func, name="usb-reader", daemon=True
        )
        self._reader_thread.start()

    async def disconnect(self) -> None:
        """
        Stop the reader thread before closing the device handle.

        Both backends' _raw_read() is bounded by a driver-level read
        timeout (100 ms for d2xx via FT_SetTimeouts, 0.1 s for vcp via
        pyserial's timeout=), so the reader thread is guaranteed to
        notice _stop_event and exit on its own within that bound --
        closing the handle first (the previous order) raced FT_Close/
        serial.close() against a read that might still be in flight on
        the reader thread, an undefined-behaviour race at the driver
        level, not just a Python-level one.
        """
        self.status_changed.send(self, status=TransportStatus.CLOSING)
        self._running = False
        if self._stop_event:
            self._stop_event.set()
        loop = asyncio.get_running_loop()
        if self._reader_thread and self._reader_thread.is_alive():
            await loop.run_in_executor(
                None, self._reader_thread.join, 2.0
            )
        self._reader_thread = None
        try:
            await loop.run_in_executor(None, self._close)
        except Exception as e:
            logger.warning(f"Error closing USB device: {e}")
        self._loop = None
        self.status_changed.send(self, status=TransportStatus.DISCONNECTED)

    async def send(self, data: bytes) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._raw_write, data)

    async def purge(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._raw_purge)

    def _dispatch_received(self, data: bytes) -> None:
        self.received.send(self, data=data)

    def _dispatch_error(self, message: str) -> None:
        self.status_changed.send(
            self, status=TransportStatus.ERROR, message=message
        )

    def _reader_thread_func(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                data = self._raw_read()
            except Exception as e:
                if self._stop_event.is_set():
                    break
                logger.error(f"USB read error: {e}")
                if self._loop and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(
                        self._dispatch_error, str(e)
                    )
                break
            if not data:
                continue
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._dispatch_received, data)


class _VcpBackend(_UsbBackendBase):
    """vcp backend: pyserial over an FTDI VCP COM/tty device."""

    _READ_TIMEOUT_S = 0.1

    def __init__(self, port: str, baudrate: int = 19200):
        super().__init__()
        self._port = port
        self._baudrate = baudrate
        self._serial: serial.Serial | None = None

    def _open(self) -> None:
        self._serial = serial.Serial(
            port=self._port,
            baudrate=self._baudrate,
            timeout=self._READ_TIMEOUT_S,
        )

    def _close(self) -> None:
        if self._serial:
            try:
                self._serial.close()
            except serial.SerialException as e:
                logger.warning(f"Error closing USB serial port: {e}")
        self._serial = None

    def _raw_read(self) -> bytes:
        assert self._serial is not None
        return self._serial.read(_READ_CHUNK_SIZE)

    def _raw_write(self, data: bytes) -> None:
        if not self._serial:
            raise ConnectionError("USB serial port not open")
        self._serial.write(data)
        self._serial.flush()

    def _raw_purge(self) -> None:
        if self._serial:
            self._serial.reset_input_buffer()


class _D2xxBackend(_UsbBackendBase):
    """
    d2xx backend: ctypes binding of the FTDI D2XX DLL.

    The open sequence matches FUN_10001C80 from the owner's decompile
    brief (docs/reference/rdcam_usb.md section 2.1) exactly, in order,
    including the asymmetric setUSBParameters(1024, 1204) reproduced
    verbatim rather than "corrected". FT_ResetDevice failing aborts
    the open with no further calls made, per the brief.
    """

    _READ_TIMEOUT_MS = 100
    _WRITE_TIMEOUT_MS = 1000
    _BAUD_RATE = 19200

    def __init__(
        self,
        usb_serial: str | None,
        library: D2xxLibrary | None = None,
    ):
        super().__init__()
        self._usb_serial = usb_serial
        self._library = library
        self._handle = None

    def _open(self) -> None:
        lib = self._library
        if lib is None:
            lib = D2xxLibrary(load_d2xx_dll())
            self._library = lib

        devices = lib.list_devices()
        index = _select_device_index(devices, self._usb_serial)

        handle = lib.open(index)
        status = lib.reset_device(handle)
        if status != FT_OK:
            raise ConnectionError(
                f"FT_ResetDevice failed with FT_STATUS {status} for "
                f"device index {index}; aborting open."
            )
        time.sleep(0.1)
        lib.set_data_characteristics(handle, 8, 0, 0)
        lib.set_usb_parameters(handle, 1024, 1204)
        lib.set_deadman_timeout(handle, 0xFFFFFFFF)
        lib.set_timeouts(
            handle, self._READ_TIMEOUT_MS, self._WRITE_TIMEOUT_MS
        )
        lib.set_baud_rate(handle, self._BAUD_RATE)
        lib.purge(handle, FT_PURGE_RX | FT_PURGE_TX)
        lib.clr_rts(handle)
        lib.clr_dtr(handle)
        time.sleep(0.1)
        lib.set_reset_pipe_retry_count(handle, 100)
        self._handle = handle

    def _close(self) -> None:
        if self._handle is not None and self._library is not None:
            self._library.close(self._handle)
        self._handle = None

    def _raw_read(self) -> bytes:
        assert self._library is not None and self._handle is not None
        return self._library.read(self._handle, _READ_CHUNK_SIZE)

    def _raw_write(self, data: bytes) -> None:
        if self._handle is None or self._library is None:
            raise ConnectionError("D2XX device not open")
        self._library.write(self._handle, data)

    def _raw_purge(self) -> None:
        if self._handle is not None and self._library is not None:
            self._library.purge(self._handle, FT_PURGE_RX | FT_PURGE_TX)


class RuidaUsbTransport:
    """
    Ruida L2 transport over a direct USB link.

    Duck-type compatible with the subset of RuidaTransport's surface
    RuidaClient actually uses (decoded_received, is_connected,
    connect/disconnect, send_command, send, status_changed), so it can
    be passed directly to RuidaClient(transport) in place of a
    RuidaTransport(UdpTransport(...)). Pass jog_transport=None: USB is
    a single stream, there is no separate jog port.
    """

    # Length in bytes of a "DA 01" memory-read reply: opcode(2) +
    # address(2) + one encode35 value(5). Matches ruida_server.py's
    # response builder (`b"\xda\x01" + data[2:4] + encoded`) and
    # RuidaClient._handle_response's parser
    # (`len(data) >= 9 and data[0] == 0xDA and data[1] == 0x01`).
    _DA01_REPLY_LEN = 9

    def __init__(
        self,
        backend: Backend | None = None,
        port: str | None = None,
        baudrate: int = 19200,
        usb_serial: str | None = None,
        magic: int = 0x88,
        *,
        d2xx_library: D2xxLibrary | None = None,
    ):
        """
        Args:
            backend: "vcp" (pyserial) or "d2xx" (ctypes D2XX binding).
                Defaults to "d2xx" on Windows, "vcp" elsewhere, per
                docs/reference/rdcam_usb.md section 2.
            port: Serial device path or COM port. Required for
                backend="vcp".
            baudrate: Baud rate for backend="vcp" (nominal 19200; an
                FT245 FIFO ignores it). backend="d2xx" always uses a
                fixed 19200, per step 8 of the open sequence.
            usb_serial: FTDI serial number to pin for backend="d2xx".
                When unset, device index 0 is used and any other
                detected devices are logged as a warning.
            magic: Swizzle magic key. Magic auto-detection, which
                RuidaTransport performs for UDP multi-controller
                discovery, is out of scope here.
            d2xx_library: Inject a D2xxLibrary-compatible object
                (for tests); when None, the real ctypes binding is
                lazily loaded on connect().
        """
        if backend is None:
            backend = "d2xx" if sys.platform == "win32" else "vcp"

        self._raw: _UsbBackendBase
        if backend == "vcp":
            if not port:
                raise ValueError("backend='vcp' requires a port")
            self._raw = _VcpBackend(port, baudrate)
        elif backend == "d2xx":
            self._raw = _D2xxBackend(usb_serial, library=d2xx_library)
        else:
            raise ValueError(f"Unknown backend: {backend!r}")

        self._codec = RuidaCodec(magic)
        self._rx_buffer = bytearray()

        self.decoded_received = Signal()
        self.status_changed = Signal()

        self._raw.received.connect(self._on_raw_received)
        self._raw.status_changed.connect(self._on_status_changed)

    @property
    def is_connected(self) -> bool:
        return self._raw.is_connected

    async def connect(self) -> None:
        await self._raw.connect()

    async def disconnect(self) -> None:
        await self._raw.disconnect()

    async def purge(self) -> None:
        await self._raw.purge()
        self._rx_buffer.clear()

    async def send(self, data: bytes) -> None:
        """Send already-encoded bytes without framing/swizzling."""
        await self._raw.send(data)

    async def send_command(self, command: bytes) -> None:
        """
        Swizzle a command and send it, with NO checksum prefix.

        This is the USB-specific deviation from
        RuidaTransport.send_command(), which additionally calls
        frame_packet() to add the 2-byte UDP checksum. It mirrors
        RuidaTransport.send_response(), which is already swizzle-only.

        Args:
            command: Unswizzled command bytes.
        """
        swizzled = self._codec.swizzle(command)
        await self._raw.send(swizzled)

    def _on_raw_received(self, sender, data: bytes) -> None:
        """
        Buffer incoming bytes and emit whole, unswizzled replies.

        A USB read() boundary is not a message boundary, so bytes are
        accumulated until a complete reply -- one status byte, or a
        9-byte DA 01 memory-read reply -- is available.
        """
        self._rx_buffer.extend(data)
        while self._rx_buffer:
            first = self._codec.unswizzle(bytes([self._rx_buffer[0]]))[0]
            if first == 0xDA:
                if len(self._rx_buffer) < self._DA01_REPLY_LEN:
                    return  # wait for the rest of the reply
                msg_len = self._DA01_REPLY_LEN
            else:
                msg_len = 1
            raw_msg = bytes(self._rx_buffer[:msg_len])
            del self._rx_buffer[:msg_len]
            unswizzled = self._codec.unswizzle(raw_msg)
            logger.debug(
                f"RX: {unswizzled!r}",
                extra={
                    "log_category": "RAW_IO",
                    "direction": "RX",
                    "data": unswizzled,
                },
            )
            self.decoded_received.send(self, data=unswizzled)

    def _on_status_changed(
        self, sender, status: TransportStatus, message: str = ""
    ) -> None:
        self.status_changed.send(self, status=status, message=message)

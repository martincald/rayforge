"""
In-process mock USB backend for the docs/usb-spike/ ladder scripts'
--mock flag.

Reuses the existing Ruida protocol simulator (RuidaSimulator wrapping
RuidaServer, swiftcut/machine/driver/ruida/ruida_simulator.py) instead
of hand-rolling a second one -- the same simulator the UDP path's
run_udp_simulator() already ACK-wraps responses with.

MockD2xxLibrary implements exactly the D2xxLibrary surface
_D2xxBackend calls (list_devices/open/close/reset_device/set_*/purge/
clr_rts/clr_dtr/read/write -- see
swiftcut/machine/driver/ruida/ruida_usb_transport.py). Injecting it via
RuidaUsbTransport(backend="d2xx", d2xx_library=MockD2xxLibrary())
drives the real FUN_10001C80 open sequence, TX swizzle, and RX
reassembly completely unmodified -- only the FTDI DLL itself is
replaced. This is the same d2xx_library injection point
tests/machine/driver/ruida/test_ruida_usb_transport.py's
FakeD2xxLibrary uses; the read()/write() queueing idiom below is
copied from that same test file's FakeD2xxLibrary for the same reason
(thread safety between the reader thread and the executor thread that
calls write()).
"""

from __future__ import annotations

import queue

from swiftcut.machine.driver.ruida.ruida_codec import RuidaCodec
from swiftcut.machine.driver.ruida.ruida_simulator import RuidaSimulator
from swiftcut.machine.driver.ruida.ruida_usb_transport import (
    FT_OK,
    D2xxDeviceInfo,
)

# Matches FakeD2xxLibrary's read queue timeout in
# test_ruida_usb_transport.py: short enough not to stall the reader
# thread's shutdown, long enough not to busy-spin.
_READ_QUEUE_TIMEOUT_S = 0.05


class MockD2xxLibrary:
    """
    Duck-typed D2xxLibrary backed by RuidaSimulator, for --mock.

    answer_enq controls whether a keepalive ENQ (0xCE) gets an ACK
    back, so --mock can exercise both of the two outcomes
    docs/usb-spike/REPORT.md's decision table distinguishes: real
    hardware might behave like the UDP path (ENQ answered), or -- per
    meerk40t's own USB reverse-engineering notes
    (meerk40t/ruida/usb_transport.py:16-17, "There is no ACK
    handshake. The controller doesn't reply to ENQ since there is not
    ACK.") -- might not answer ENQ at all. Every other command (memory
    reads, job chunks) is unaffected either way; only the ENQ reply is
    gated, so probe_usb.py's card-ID/position steps still work
    identically in both modes.
    """

    def __init__(self, magic: int = 0x88, answer_enq: bool = True):
        self._codec = RuidaCodec(magic)
        self._simulator = RuidaSimulator()
        self._read_queue: queue.Queue[bytes] = queue.Queue()
        self._handle = 1
        self._answer_enq = answer_enq

    # -- enumeration / open sequence (FUN_10001C80) --------------------

    def list_devices(self) -> list[D2xxDeviceInfo]:
        return [
            D2xxDeviceInfo(
                index=0,
                description="Mock Ruida Laser (--mock)",
                serial="MOCK0001",
            )
        ]

    def open(self, index: int):
        return self._handle

    def close(self, handle) -> None:
        pass

    def reset_device(self, handle) -> int:
        return FT_OK

    def set_data_characteristics(
        self, handle, word_length: int, stop_bits: int, parity: int
    ) -> None:
        pass

    def set_usb_parameters(self, handle, in_size: int, out_size: int) -> None:
        pass

    def set_deadman_timeout(self, handle, timeout_ms: int) -> None:
        pass

    def set_timeouts(self, handle, read_ms: int, write_ms: int) -> None:
        pass

    def set_baud_rate(self, handle, baud: int) -> None:
        pass

    def purge(self, handle, mask: int) -> None:
        while True:
            try:
                self._read_queue.get_nowait()
            except queue.Empty:
                break

    def clr_rts(self, handle) -> None:
        pass

    def clr_dtr(self, handle) -> None:
        pass

    def set_reset_pipe_retry_count(self, handle, count: int) -> None:
        pass

    # -- data path -------------------------------------------------

    def read(self, handle, size: int) -> bytes:
        try:
            return self._read_queue.get(timeout=_READ_QUEUE_TIMEOUT_S)
        except queue.Empty:
            return b""

    def write(self, handle, data: bytes) -> int:
        """
        Unswizzle, run through the real protocol simulator, and queue
        a swizzled reply -- same ACK-wrapping rule
        run_udp_simulator() uses (ruida_simulator.py): an empty or
        already-ACK response gets exactly one ACK; anything else is
        ACK, then the response, concatenated (this transport has no
        datagram boundaries, so that is simply more queued bytes).
        """
        plain = self._codec.unswizzle(bytes(data))
        if not self._answer_enq and plain == b"\xce":
            # Simulate meerk40t's "no ACK, no ENQ reply" finding: queue
            # nothing back for this command specifically.
            return len(data)
        response = self._simulator.process_commands(plain)
        if response == b"\xcc" or not response:
            out = b"\xcc"
        else:
            out = b"\xcc" + response
        self._read_queue.put(self._codec.swizzle(out))
        return len(data)

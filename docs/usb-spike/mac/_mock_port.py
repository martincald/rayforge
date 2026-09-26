"""
The --mock port for the macOS USB ladder (docs/usb-spike/mac/).

A stand-in for pyserial's Serial with the in-repo Ruida simulator
(RuidaSimulator) behind it, plus list_ports entries that include one
with FTDI's VID. install() patches exactly the two places the vcp
backend reaches the OS -- serial.Serial and
serial.tools.list_ports.comports -- so the production
RuidaUsbTransport open sequence, device selection, framing and read
loop all run unmodified. Only the device is fake.
"""

from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest import mock

from swiftcut.machine.driver.ruida.ruida_codec import RuidaCodec
from swiftcut.machine.driver.ruida.ruida_simulator import RuidaSimulator

MOCK_FTDI_PORT = SimpleNamespace(
    device="/dev/cu.usbserial-MOCK0001",
    vid=0x0403,
    pid=0x6001,
    description="Mock Ruida FT245R (--mock)",
    serial_number="MOCK0001",
)
MOCK_PORTS = [
    SimpleNamespace(
        device="/dev/cu.Bluetooth-Incoming-Port",
        vid=None,
        pid=None,
        description="n/a",
        serial_number=None,
    ),
    MOCK_FTDI_PORT,
]


class MockFtdiPort:
    """
    Opens, like pyserial, with RTS and DTR asserted. Each write is
    answered the way run_udp_simulator answers a datagram -- an ACK,
    then any reply -- swizzled, with no checksum.
    """

    def __init__(
        self,
        port=None,
        baudrate=9600,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=None,
        write_timeout=None,
        rtscts=False,
        dsrdtr=False,
    ):
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.rtscts = rtscts
        self.dsrdtr = dsrdtr
        self.rts = True
        self.dtr = True
        self.in_waiting = 0
        self._codec = RuidaCodec(0x88)
        self._simulator = RuidaSimulator()
        self._replies: queue.Queue[bytes] = queue.Queue()

    def read(self, size=1):
        try:
            return self._replies.get(timeout=self.timeout or 0.05)
        except queue.Empty:
            return b""

    def write(self, data):
        plain = self._codec.unswizzle(bytes(data))
        response = self._simulator.process_commands(plain)
        if response in (b"", b"\xcc"):
            response = b""
        self._replies.put(self._codec.swizzle(b"\xcc" + response))
        return len(data)

    def reset_input_buffer(self):
        while not self._replies.empty():
            self._replies.get_nowait()

    def reset_output_buffer(self):
        pass

    def close(self):
        pass


def install() -> None:
    """Route pyserial to the mock for the rest of the process."""
    mock.patch("serial.Serial", MockFtdiPort).start()
    mock.patch(
        "serial.tools.list_ports.comports", return_value=MOCK_PORTS
    ).start()

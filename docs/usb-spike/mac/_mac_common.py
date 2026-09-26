"""
Shared plumbing for the macOS USB ladder (docs/usb-spike/mac/):
enumerate.py -> probe.py -> jog.py -> fixture.py.

Every rung talks through the classes the app itself uses --
RuidaUsbTransport(backend="vcp") and RuidaClient -- so the open
sequence, device selection, framing (swizzle, no checksum), chunking
and ACK pacing are exactly the app's. This module only adds:

- --usb-serial (the profile's usb_serial pin) and --mock;
- a print of every byte written to and read from the port, taken at
  the backend's raw write and read, below all framing;
- a print of the settings the port was opened with;
- the typed confirmation gate for the rungs that move the machine,
  shared with the parent ladder (../_usb_common.py).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# The parent ladder's confirmation gate and fixture builder are reused
# as they are, not copied.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _usb_common import add_confirmation_arg, confirm_or_exit

__all__ = [
    "add_args",
    "build_transport",
    "confirm_or_exit",
    "print_port_settings",
    "setup",
]


def add_args(parser: argparse.ArgumentParser, moves: bool = False) -> None:
    parser.add_argument(
        "--usb-serial",
        help="Pin this FTDI serial number, as the profile's usb_serial "
        "does. Default: the only FTDI port, or the first with a warning.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run against a simulated FTDI port (_mock_port.py) instead "
        "of the laser. Safe with nothing plugged in.",
    )
    if moves:
        add_confirmation_arg(parser)


def setup(args: argparse.Namespace) -> None:
    # INFO shows the transport's own "USB device: port=..." line.
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s"
    )
    if args.mock:
        import _mock_port

        _mock_port.install()
        print(
            f"--mock: simulated FTDI port "
            f"{_mock_port.MOCK_FTDI_PORT.device}, not real hardware.\n"
        )


def build_transport(args: argparse.Namespace):
    """The app's USB transport, with every wire byte printed."""
    from swiftcut.machine.driver.ruida.ruida_usb_transport import (
        RuidaUsbTransport,
    )

    transport = RuidaUsbTransport(backend="vcp", usb_serial=args.usb_serial)
    _print_wire_bytes(transport)
    return transport


def _print_wire_bytes(transport) -> None:
    """
    Prints each write and read exactly as it crossed the port
    ("wire", swizzled) and decoded ("plain"). Hooked at the backend's
    raw write and read, so nothing is reconstructed.
    """
    raw = transport._raw
    codec = transport._codec
    write = raw._raw_write

    def show(direction: str, data: bytes) -> None:
        print(f"{direction} {len(data):4d} B  wire:  {data.hex(' ')}")
        print(f"{'':12}plain: {codec.unswizzle(data).hex(' ')}")

    def logged_write(data: bytes) -> None:
        show("TX", data)
        write(data)

    raw._raw_write = logged_write
    raw.received.connect(lambda sender, data: show("RX", data), weak=False)


def print_port_settings(transport) -> None:
    """How the port was actually opened, read back from pyserial."""
    port = transport._raw._serial
    device = transport.device
    print(
        f"opened {port.port}: description={device.description!r} "
        f"serial={device.serial!r}"
    )
    print(
        f"  {port.baudrate} baud, {port.bytesize}{port.parity}"
        f"{port.stopbits}, timeout={port.timeout}s, "
        f"write_timeout={port.write_timeout}s, rtscts={port.rtscts}, "
        f"dsrdtr={port.dsrdtr}, rts={port.rts}, dtr={port.dtr}\n"
    )

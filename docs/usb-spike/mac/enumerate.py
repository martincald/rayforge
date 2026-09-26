#!/usr/bin/env python3
"""macOS USB ladder rung 1/4: list the serial ports. Sends nothing.

Prints every serial port macOS reports (/dev/cu.*) with its USB
VID:PID, description and serial number, marks FTDI's (VID 0x0403),
and shows which one the app would open -- the same list_vcp_devices()
and _select_vcp_device() the app runs on every connect.

Run it with the laser's USB cable plugged in and the controller on,
and report the FTDI line's description and serial so the device can
be pinned (usb_serial in the profile, or Device settings > USB
Device). No port is opened; no bytes are sent or received.

Ladder: 1) *enumerate.py*  2) probe.py  3) jog.py  4) fixture.py

Usage (from the repository root):
    PYTHONPATH=. python docs/usb-spike/mac/enumerate.py
    PYTHONPATH=. python docs/usb-spike/mac/enumerate.py --mock
"""

from __future__ import annotations

import argparse
import sys

from _mac_common import add_args, setup


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_args(parser)
    args = parser.parse_args()
    setup(args)

    from serial.tools import list_ports

    from swiftcut.machine.driver.ruida.ruida_usb_transport import (
        FTDI_VID,
        _select_vcp_device,
        list_vcp_devices,
    )

    print("=== serial ports ===")
    ports = sorted(list_ports.comports(), key=lambda p: p.device)
    if not ports:
        print("  (none)")
    for p in ports:
        vid_pid = (
            f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else "----:----"
        )
        ftdi = "   <- FTDI" if p.vid == FTDI_VID else ""
        print(
            f"  {p.device}  VID:PID={vid_pid}  "
            f"description={p.description!r}  "
            f"serial={p.serial_number!r}{ftdi}"
        )

    print("\n=== the app would open ===")
    try:
        chosen = _select_vcp_device(list_vcp_devices(), args.usb_serial)
    except ConnectionError as e:
        print(f"  nothing: {e}")
        print(
            "  If the laser is plugged in and on, look for it in "
            "`system_profiler SPUSBDataType` and report its Vendor ID "
            "and Product ID."
        )
        return 1
    print(
        f"  {chosen.port}  description={chosen.description!r}  "
        f"serial={chosen.serial!r}"
    )
    print(f"\nTo pin it: usb_serial: {chosen.serial}")
    print("\nBytes sent: none. Bytes received: none.")
    print("Next: docs/usb-spike/mac/probe.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

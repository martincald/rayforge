#!/usr/bin/env python3
"""USB ladder rung 1/4: USB/serial enumeration.

Lists every serial port pyserial can see (VID/PID/description), and on
Windows also probes the FTDI D2XX API through the production code path
-- load_d2xx_dll()/D2xxLibrary/_select_device_index() in
swiftcut/machine/driver/ruida/ruida_usb_transport.py, not a
hand-rolled copy -- since an FTDI chip can be bound to D2XX-only mode
(no COM port at all; see docs/usb-spike/README.md for the domain
notes). The headline output of this script is exactly which
backend(s), if any, can open the laser's FTDI chip.

This script only ENUMERATES. It never opens a device handle (D2XX
device-info listing does not require one), and it sends no bytes to
anything. It is safe to run with the laser connected or disconnected.

Ladder: 1) *enumerate.py*  2) probe_usb.py  3) jog_usb.py
        4) send_fixture_usb.py
Next: docs/usb-spike/probe_usb.py

Usage:
    PYTHONPATH=. python docs/usb-spike/enumerate.py
    PYTHONPATH=. python docs/usb-spike/enumerate.py --usb-serial ABC123
    PYTHONPATH=. python docs/usb-spike/enumerate.py --mock

For a reliable identification of which entry is the laser, run this
script once with the laser plugged in and once with it unplugged, and
diff the two outputs - whatever disappears is the laser's chip.
"""

from __future__ import annotations

import argparse
import sys

from _usb_common import configure_logging

from swiftcut.machine.driver.ruida.ruida_usb_transport import (
    D2xxDeviceInfo,
    D2xxLibrary,
    D2xxNotAvailable,
    _select_device_index,
    load_d2xx_dll,
)

FTDI_VID = 0x0403


def _list_pyserial_ports() -> list:
    """Return pyserial's view of the world (may be an empty list)."""
    from serial.tools import list_ports

    return list(list_ports.comports())


def _print_pyserial_ports(ports: list) -> None:
    print("=== pyserial: serial.tools.list_ports.comports() ===")
    if not ports:
        print("  (no serial ports found)")
        return
    for p in ports:
        vid = f"0x{p.vid:04X}" if p.vid is not None else "?"
        pid = f"0x{p.pid:04X}" if p.pid is not None else "?"
        is_ftdi = " <- FTDI VID" if p.vid == FTDI_VID else ""
        print(f"  {p.device}")
        print(f"    description: {p.description}")
        print(f"    hwid:        {p.hwid}")
        print(f"    vid:pid:     {vid}:{pid}{is_ftdi}")
        print(f"    serial_num:  {p.serial_number}")


def _probe_d2xx(
    mock: bool, pinned_serial: str | None
) -> list[D2xxDeviceInfo]:
    """
    Probe the FTDI D2XX API through the production code path.

    Returns the detected devices (empty if unavailable or none are
    present). Never raises: all failures are reported and treated as
    "backend unavailable". Also runs the production
    _select_device_index() so the script demonstrates exactly which
    index a real connection would pick.
    """
    print("=== D2XX: production ruida_usb_transport code path ===")
    if mock:
        from _usb_mock import MockD2xxLibrary

        print("  --mock: using an in-process RuidaSimulator device")
        library = MockD2xxLibrary()
    else:
        try:
            library = D2xxLibrary(load_d2xx_dll())
        except D2xxNotAvailable as exc:
            print(f"  {exc}")
            return []

    try:
        devices = library.list_devices()
    except Exception as exc:  # noqa: BLE001 - report, never crash
        print(f"  list_devices() failed: {exc}")
        return []

    if not devices:
        print("  0 D2XX-visible devices.")
        return []

    for d in devices:
        print(f"  device {d.index}: {d.description!r}  serial={d.serial!r}")

    index = _select_device_index(devices, pinned_serial)
    print(f"  _select_device_index() would open index {index}")
    return devices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--usb-serial",
        help="Serial to feed _select_device_index() (demonstrates the "
        "profile-pin/fallback choice; does not open anything).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="List an in-process RuidaSimulator device instead of "
        "probing real hardware/pyserial ports.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    configure_logging()

    print(f"platform: {sys.platform}\n")

    if args.mock:
        print("=== pyserial: skipped (--mock) ===")
        serial_ports = []
    else:
        serial_ports = _list_pyserial_ports()
        _print_pyserial_ports(serial_ports)
    print()

    d2xx_devices = []
    if args.mock or sys.platform == "win32":
        d2xx_devices = _probe_d2xx(args.mock, args.usb_serial)
    else:
        print("=== D2XX: skipped (not Windows; use --backend vcp) ===")
    print()

    ftdi_com_ports = [p for p in serial_ports if p.vid == FTDI_VID]

    print("=== headline: which backend can open the device? ===")
    if ftdi_com_ports:
        for p in ftdi_com_ports:
            print(f"  vcp  -> {p.device} (FTDI VID present)")
    if d2xx_devices:
        print(f"  d2xx -> {len(d2xx_devices)} device(s)")
    if not ftdi_com_ports and not d2xx_devices:
        print("  Nothing found by either backend.")
        print("  Plug in the laser's USB cable and re-run this script.")

    print()
    if args.mock:
        print(
            "--mock: that was an in-process RuidaSimulator, not real "
            "hardware. Re-run without --mock against the laser."
        )
    else:
        print(
            "For a reliable identification, re-run this script with the "
            "laser's USB cable unplugged and diff the two outputs - "
            "whatever entry disappears is the laser's FTDI chip."
        )
    print("Next: docs/usb-spike/probe_usb.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

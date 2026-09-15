#!/usr/bin/env python3
"""USB ladder rung 3/4: ONE relative rapid move, +1.0 mm on X (D9 00).

*** THIS SCRIPT MOVES THE MACHINE. *** It is the first script in the
ladder that does. Uses the production RuidaUsbTransport/RuidaClient
path (see swiftcut/machine/driver/ruida/ruida_usb_transport.py and
ruida_client.py) -- RuidaClient.rapid_move_axis() -- not a hand-rolled
command.

Run docs/usb-spike/enumerate.py and docs/usb-spike/probe_usb.py first.
Keep the machine's E-stop within reach before confirming.

Ladder: 1) enumerate.py  2) probe_usb.py  3) *jog_usb.py*
        4) send_fixture_usb.py
Next: docs/usb-spike/send_fixture_usb.py

Usage:
    PYTHONPATH=. python docs/usb-spike/jog_usb.py --port COM7
    PYTHONPATH=. python docs/usb-spike/jog_usb.py --backend d2xx
    PYTHONPATH=. python docs/usb-spike/jog_usb.py --mock --yes
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from _usb_common import (
    add_common_usb_args,
    add_confirmation_arg,
    build_transport,
    confirm_or_exit,
    configure_logging,
    install_hex_logging,
)

from swiftcut.machine.driver.ruida.ruida_client import RuidaClient

MOVE_UM = 1000  # 1.0 mm

BANNER = """\
================================================================
 WARNING: THIS SCRIPT MOVES THE MACHINE.
 It sends ONE relative rapid move (D9 00): +1.0 mm on X.
 KEEP THE MACHINE'S E-STOP WITHIN REACH before confirming.
================================================================
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_usb_args(parser)
    add_confirmation_arg(parser)
    return parser


async def run(args: argparse.Namespace) -> int:
    transport = build_transport(args)
    install_hex_logging(transport)
    client = RuidaClient(transport)

    await client.connect()
    try:
        print(f"--- rapid move X: +{MOVE_UM}um (D9 00, relative) ---")
        await client.rapid_move_axis(axis=0x00, coord=MOVE_UM)
    finally:
        await client.disconnect()
    print()
    print("Move sent. Confirm on the machine that X moved +1.0 mm.")
    print("Next: docs/usb-spike/send_fixture_usb.py")
    return 0


def main() -> int:
    print(BANNER)
    args = build_parser().parse_args()
    configure_logging()
    confirm_or_exit(args, expect="MOVE")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

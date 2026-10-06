#!/usr/bin/env python3
"""macOS USB ladder rung 2/4: card ID, then position. NO MOTION.

Opens the laser's FTDI port exactly as the app does
(RuidaUsbTransport, vcp backend), prints the settings it opened with,
then sends the app's own three queries, each printed byte for byte
as written and as read back:

1. handshake         DA 00 05 7E -- the card-ID read the app connects
   with (RuidaClient.usb_handshake: its DA 01 reply or a bare CC
   within 5 s). A pass here predicts the app connects.
2. X position read   DA 00 04 21 -- the app's position poll.
3. status read       DA 00 04 00 -- the app's USB keepalive, every
   2 s; three misses in a row drop the connection.

Three memory reads: nothing here moves the head or fires the laser.

Ladder: 1) enumerate.py  2) *probe.py*  3) jog.py  4) fixture.py

Usage (from the repository root):
    PYTHONPATH=. python docs/usb-spike/mac/probe.py
    PYTHONPATH=. python docs/usb-spike/mac/probe.py --usb-serial A10K3XYZ
    PYTHONPATH=. python docs/usb-spike/mac/probe.py --mock
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from _mac_common import add_args, build_transport, print_port_settings, setup

X_POSITION_ADDRESS = 0x0421
STATUS_ADDRESS = 0x0400


async def run(args: argparse.Namespace) -> int:
    from swiftcut.machine.driver.ruida.ruida_client import RuidaClient
    from swiftcut.machine.driver.ruida.ruida_maps import CARD_ID_TO_MODEL

    transport = build_transport(args)
    client = RuidaClient(transport)
    await client.connect()
    try:
        print_port_settings(transport)

        print("--- 1. handshake: card ID read DA 00 05 7E ---")
        try:
            card_id = await client.usb_handshake()
        except asyncio.TimeoutError:
            print("  TIMEOUT: no reply; the app cannot connect either.")
            return 1
        if card_id is None:
            print("  -> bare ACK (CC), no card ID\n")
        else:
            model = CARD_ID_TO_MODEL.get(card_id, "unknown")
            print(f"  -> card_id=0x{card_id:08X} model={model}\n")

        print("--- 2. X position: DA 00 04 21 ---")
        x_um = await client._read_memory_wait(X_POSITION_ADDRESS)
        if x_um is None:
            print("  TIMEOUT: no reply to the position read.")
            return 1
        print(f"  -> x={x_um} um\n")

        print("--- 3. keepalive: status read DA 00 04 00 ---")
        status = await client._read_memory_wait(STATUS_ADDRESS)
        if status is None:
            print("  TIMEOUT: no reply to the status read.")
            return 1
        print(f"  -> status=0x{status:08X}")
    finally:
        await client.disconnect()

    print("\nNo motion was sent. Next: docs/usb-spike/mac/jog.py")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_args(parser)
    args = parser.parse_args()
    setup(args)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

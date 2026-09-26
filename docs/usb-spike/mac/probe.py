#!/usr/bin/env python3
"""macOS USB ladder rung 2/4: card ID, then position. NO MOTION.

Opens the laser's FTDI port exactly as the app does
(RuidaUsbTransport, vcp backend), prints the settings it opened with,
then sends three commands, each printed byte for byte as written and
as read back:

1. card ID read      DA 00 05 7E
2. X position read   DA 00 04 21
3. keepalive ENQ     CE -- the byte the app sends every second. Its
   ACK (CC) is what the app's connect and every ACK-paced job send
   wait for, so a NO here means USB jobs cannot work yet.

Two memory reads and a keepalive: nothing here moves the head or
fires the laser.

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
ENQ_TIMEOUT_S = 1.0


async def run(args: argparse.Namespace) -> int:
    from swiftcut.machine.driver.ruida.ruida_client import RuidaClient
    from swiftcut.machine.driver.ruida.ruida_maps import CARD_ID_TO_MODEL

    transport = build_transport(args)
    client = RuidaClient(transport)
    await client.connect()
    try:
        print_port_settings(transport)

        print("--- 1. card ID: DA 00 05 7E ---")
        card_id = await client.get_card_id()
        if card_id is None:
            print("  TIMEOUT: no reply to the card ID read.")
            return 1
        model = CARD_ID_TO_MODEL.get(card_id, "unknown")
        print(f"  -> card_id=0x{card_id:08X} model={model}\n")

        print("--- 2. X position: DA 00 04 21 ---")
        x_um = await client._read_memory_wait(X_POSITION_ADDRESS)
        if x_um is None:
            print("  TIMEOUT: no reply to the position read.")
            return 1
        print(f"  -> x={x_um} um\n")

        print("--- 3. keepalive: ENQ CE ---")
        ack = await client.send_command_wait_ack(
            b"\xce", timeout=ENQ_TIMEOUT_S
        )
        if ack is None:
            print(f"  -> ENQ answered: NO (nothing in {ENQ_TIMEOUT_S}s)")
            return 1
        print(f"  -> ENQ answered: {'YES (ACK)' if ack else 'NO (NAK)'}")
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

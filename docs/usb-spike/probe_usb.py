#!/usr/bin/env python3
"""USB ladder rung 2/4: card-ID, position, and ENQ/ACK probe.

Uses the production RuidaUsbTransport/RuidaClient path (see
swiftcut/machine/driver/ruida/ruida_usb_transport.py and
ruida_client.py) instead of a hand-rolled swizzle/read loop: the same
transport, chunking, and framing the driver uses in production.

SAFE BY DESIGN: this script sends ONLY memory-read queries (the
card-ID query DA 00 05 7E, the X/Y position queries DA 00 04 21 /
DA 00 04 31) and one keepalive ENQ (0xCE) -- the exact byte the app
sends every second, never a motion/cutting/job-start command. It never
touches the network. Even so, treat any real connection to a laser
controller as live hardware and keep the machine's E-stop within reach
before running this against a real device - see
tests/machine/driver/ruida/send_fixture_test.py for the same
reminder on a script that (unlike this one) does move the gantry.

Run docs/usb-spike/enumerate.py first to see what is connected and
which backend (d2xx or vcp) can open it.

The third step (ENQ/ACK) exists because card-ID/position replies alone
cannot settle whether this hardware's USB link ACKs at all: meerk40t's
own USB reverse-engineering notes claim there is no ACK handshake and
no ENQ reply over USB (meerk40t/ruida/usb_transport.py:16-17), which
would starve every ACK-paced send this repo's send_job() depends on --
see docs/usb-spike/REPORT.md's decision table for what each of the
three results together mean before proceeding down the ladder.

Ladder: 1) enumerate.py  2) *probe_usb.py*  3) jog_usb.py
        4) send_fixture_usb.py
Next: read the REPORT.md decision table before running jog_usb.py --
do not run send_fixture_usb.py until the ENQ/ACK question above is
answered.

Usage:
    PYTHONPATH=. python docs/usb-spike/probe_usb.py --port COM7
    PYTHONPATH=. python docs/usb-spike/probe_usb.py --backend d2xx
    PYTHONPATH=. python docs/usb-spike/probe_usb.py --mock
    PYTHONPATH=. python docs/usb-spike/probe_usb.py --mock --mock-no-enq-reply
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from _usb_common import (
    add_common_usb_args,
    build_transport,
    configure_logging,
    install_hex_logging,
)

from swiftcut.machine.driver.ruida.ruida_client import RuidaClient

BANNER = """\
================================================================
 SAFE: this script sends ONLY memory-read queries (card ID and
 position) and one keepalive ENQ. It NEVER sends motion, cutting,
 or job-start commands, and it never touches the network.
 Keep the machine's E-stop within reach anyway before connecting
 to real hardware - this is a hardware spike script.
================================================================
"""

ENQ_TIMEOUT_S = 1.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_usb_args(parser)
    return parser


async def run(args: argparse.Namespace) -> int:
    transport = build_transport(args)
    install_hex_logging(transport)
    client = RuidaClient(transport)

    await client.connect()
    try:
        print("--- card ID query: DA 00 05 7E ---")
        card_info = await client.get_card_info()
        if card_info is None:
            sys.exit(
                "TIMEOUT: no card ID reply. Check wiring/power, or "
                "try --backend d2xx / --backend vcp explicitly."
            )
        card_id, model_name = card_info
        print(f"  -> card_id=0x{card_id:08x} model={model_name}")

        print()
        print("--- position query: DA 00 04 21 (X), DA 00 04 31 (Y) ---")
        position = await client.read_position()
        if position is None:
            sys.exit("TIMEOUT: no position reply.")
        x_um, y_um = position
        print(f"  -> x={x_um}um y={y_um}um")

        print()
        print("--- keepalive probe: ENQ 0xCE (no checksum) ---")
        print(
            "    (the same byte RuidaDriver sends every second; every "
            "ACK-paced send in this repo depends on a reply to this)"
        )
        enq_ack = await client.send_command_wait_ack(
            b"\xce", timeout=ENQ_TIMEOUT_S
        )
        if enq_ack is None:
            print("  ACK/ENQ support: NO (no reply within "
                  f"{ENQ_TIMEOUT_S}s)")
        elif enq_ack:
            print("  ACK/ENQ support: YES (0xCC/0xC6 received)")
        else:
            print("  ACK/ENQ support: NO (0xCF/0xCD NAK received)")
    finally:
        await client.disconnect()
    print()
    print(
        "See docs/usb-spike/REPORT.md's decision table before running "
        "jog_usb.py or send_fixture_usb.py -- do NOT run "
        "send_fixture_usb.py if ACK/ENQ support above is NO."
    )
    return 0


def main() -> int:
    print(BANNER)
    args = build_parser().parse_args()
    configure_logging()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

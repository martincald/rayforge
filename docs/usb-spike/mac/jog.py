#!/usr/bin/env python3
"""macOS USB ladder rung 3/4: ONE relative 1 mm rapid move on X.

*** THIS MOVES THE MACHINE. *** Keep the E-stop within reach, and
jog the head clear of the +X end first.

Sends exactly one motion command, through RuidaClient.jog_move_x:
D9 00 02 <+1000 um> -- the single-axis X rapid, option byte 02 (not
relative to the origin, pointer off). The in-repo references decode
D9 00 as a relative move, but no hardware capture confirms it
(MOTION_AUDIT.md MOT-47), so X is read (DA 00 04 21) before and after
and the printout shows which it was: +1000 um for a relative move,
or X landing on 1000 um for an absolute one.

Ladder: 1) enumerate.py  2) probe.py  3) *jog.py*  4) fixture.py

Usage (from the repository root):
    PYTHONPATH=. python docs/usb-spike/mac/jog.py
    PYTHONPATH=. python docs/usb-spike/mac/jog.py --mock --yes
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from _mac_common import (
    add_args,
    build_transport,
    confirm_or_exit,
    print_port_settings,
    setup,
)

MOVE_UM = 1000
X_POSITION_ADDRESS = 0x0421
# A 1 mm rapid is done well within this.
SETTLE_S = 1.0

BANNER = """\
================================================================
 WARNING: THIS SCRIPT MOVES THE MACHINE.
 It sends ONE rapid move (D9 00): X +1.0 mm, laser off.
 KEEP THE MACHINE'S E-STOP WITHIN REACH before confirming.
================================================================
"""


async def run(args: argparse.Namespace) -> int:
    from swiftcut.machine.driver.ruida.ruida_client import RuidaClient

    transport = build_transport(args)
    client = RuidaClient(transport)
    await client.connect()
    try:
        print_port_settings(transport)

        print("--- X before: DA 00 04 21 ---")
        before = await client._read_memory_wait(X_POSITION_ADDRESS)
        if before is None:
            print("  TIMEOUT: no position reply; nothing was moved.")
            return 1
        print(f"  -> x={before} um\n")

        print(f"--- the move: D9 00, X +{MOVE_UM} um ---")
        await client.jog_move_x(MOVE_UM)
        await asyncio.sleep(SETTLE_S)
        print()

        print("--- X after: DA 00 04 21 ---")
        after = await client._read_memory_wait(X_POSITION_ADDRESS)
        if after is None:
            print("  TIMEOUT: no position reply after the move.")
            return 1
        print(f"  -> x={after} um\n")
    finally:
        await client.disconnect()

    print(
        f"X before={before} um, after={after} um, "
        f"delta={after - before:+d} um "
        f"(+{MOVE_UM} means D9 00 is relative)"
    )
    print("Next: docs/usb-spike/mac/fixture.py")
    return 0


def main() -> int:
    print(BANNER)
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_args(parser, moves=True)
    args = parser.parse_args()
    setup(args)
    confirm_or_exit(args, expect="MOVE")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

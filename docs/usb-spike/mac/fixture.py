#!/usr/bin/env python3
"""macOS USB ladder rung 4/4: the RDWorks fixture job, power zeroed.

*** THIS MOVES THE MACHINE. *** The laser does not fire, but the
gantry runs every move in the job at its programmed speed. Keep the
E-stop within reach.

Sends tests/machine/driver/ruida/fixtures/rdworks_reference.rd with
every power command zeroed -- including C6 65 -- and the E5 05 file
checksum recomputed, using ../send_fixture_usb.py's build_patched_job
(reused, so there is one copy of the zeroing rule). Before anything
is sent, every power command in the patched job is checked to be
zero; any that is not aborts the run.

It goes out through the app's RuidaClient.stream_job: chunks of at
most 1000 bytes split on command boundaries, each swizzled with no
checksum prefix and written once, back to back, paced by the FTDI
FIFO. The controller answers no job chunk over USB, so nothing waits
for an ACK and nothing is re-sent: a re-sent chunk would run twice.

Ladder: 1) enumerate.py  2) probe.py  3) jog.py  4) *fixture.py*

Usage (from the repository root):
    PYTHONPATH=. python docs/usb-spike/mac/fixture.py
    PYTHONPATH=. python docs/usb-spike/mac/fixture.py --mock --yes
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
from send_fixture_usb import (
    _POWER2_OPCODES,
    _POWER3_OPCODES,
    FIXTURE,
    build_patched_job,
)

BANNER = """\
================================================================
 WARNING: THIS SCRIPT MOVES THE MACHINE.
 It sends the RDWorks reference job over USB with every power
 command zeroed (including C6 65). The laser will NOT fire, but
 the gantry WILL run every move at full programmed speed.
 KEEP THE MACHINE'S E-STOP WITHIN REACH before confirming.
================================================================
"""


def check_power_zeroed(swizzled: bytes) -> int:
    """Every power command's value is 00 00; returns how many."""
    from swiftcut.machine.driver.ruida.ruida_client import (
        JOB_MAGIC,
        split_commands,
    )
    from swiftcut.machine.driver.ruida.ruida_util import build_swizzle_lut

    _, unswizzle_lut = build_swizzle_lut(JOB_MAGIC)
    plain = bytes(unswizzle_lut[b] for b in swizzled)
    count = 0
    for command in split_commands(plain):
        opcode = command[:2]
        if opcode in _POWER2_OPCODES or opcode in _POWER3_OPCODES:
            count += 1
            if command[-2:] != b"\x00\x00":
                sys.exit(
                    f"ABORT: power command {command.hex(' ')} is not "
                    "zero. Nothing was sent."
                )
    return count


async def run(args: argparse.Namespace) -> int:
    from swiftcut.machine.driver.ruida.ruida_client import RuidaClient

    swizzled, command_count = build_patched_job()
    power_count = check_power_zeroed(swizzled)
    print(f"fixture: {FIXTURE}")
    print(
        f"{command_count} commands, {len(swizzled)} bytes; "
        f"{power_count} power commands, all zero (including C6 65)\n"
    )

    transport = build_transport(args)
    client = RuidaClient(transport)

    def on_start(blob_size: int, chunk_count: int) -> None:
        print(f"sending {blob_size} bytes in {chunk_count} chunk(s)\n")

    await client.connect()
    try:
        print_port_settings(transport)
        await client.stream_job(
            swizzled, should_stop=lambda: False, on_start=on_start
        )
    except RuntimeError as e:
        print(f"FAILED: {e}")
        return 1
    finally:
        await client.disconnect()

    print("All chunks sent, each once. Watch the machine run the job.")
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
    confirm_or_exit(args, expect="SEND")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

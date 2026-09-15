#!/usr/bin/env python3
"""USB ladder rung 4/4: send the RDWorks reference job, power zeroed.

*** THIS SCRIPT MOVES THE MACHINE. *** It reuses the same fixture the
UDP ground-truth sender uses
(tests/machine/driver/ruida/send_fixture_test.py ->
tests/machine/driver/ruida/fixtures/rdworks_reference.rd), zeroes
every power command including C6 65 (not covered by
send_fixture_test.py's UDP zeroing set -- see _POWER2_OPCODES below),
recomputes the E5 05 file checksum, and sends it with
RuidaClient.send_job() -- the production, ACK-paced, NAK-retrying
sender (swiftcut/machine/driver/ruida/ruida_client.py), swizzled with
NO checksum prefix, over RuidaUsbTransport
(swiftcut/machine/driver/ruida/ruida_usb_transport.py). Nothing here
reimplements chunking or the ACK loop.

Power zeroed means the laser will NOT fire, but the gantry WILL still
execute every move in the job at full programmed speed.

Note on --magic: it is passed through to the transport's own codec
(the actual wire encoding), but RuidaClient.send_job() itself
unswizzles the blob it is given, and detects the chunk ACK/NAK bytes,
using the hardcoded JOB_MAGIC constant in ruida_client.py (a file this
package does not edit) -- so the job blob built below is always
swizzled with JOB_MAGIC, regardless of --magic, matching
send_job()'s actual contract.

Run docs/usb-spike/enumerate.py, probe_usb.py, and jog_usb.py first.
Keep the machine's E-stop within reach before confirming.

Ladder: 1) enumerate.py  2) probe_usb.py  3) jog_usb.py
        4) *send_fixture_usb.py*
Next: none -- this is the last rung.

Usage:
    PYTHONPATH=. python docs/usb-spike/send_fixture_usb.py --port COM7
    PYTHONPATH=. python docs/usb-spike/send_fixture_usb.py --backend d2xx
    PYTHONPATH=. python docs/usb-spike/send_fixture_usb.py --mock --yes
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from _usb_common import (
    add_common_usb_args,
    add_confirmation_arg,
    build_transport,
    confirm_or_exit,
    configure_logging,
    install_hex_logging,
)

from swiftcut.machine.driver.ruida.ruida_client import (
    JOB_MAGIC,
    RuidaClient,
    split_commands,
)
from swiftcut.machine.driver.ruida.ruida_util import (
    build_swizzle_lut,
    encode35,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = (
    REPO_ROOT
    / "tests"
    / "machine"
    / "driver"
    / "ruida"
    / "fixtures"
    / "rdworks_reference.rd"
)

# Opcode(2) + 2-byte power payload -> zeroed to 00 00. Same set as
# send_fixture_test.py's UDP sender, PLUS C6 65: present in the
# fixture (c6 65 00 3d) and a verified 4-byte C6 command
# (ruida_util.py's _C6_LENGTHS[0x65] == 4), but not in
# send_fixture_test.py's zeroing set.
_POWER2_OPCODES = {
    b"\xc6\x01",
    b"\xc6\x02",
    b"\xc6\x21",
    b"\xc6\x22",
    b"\xc6\x50",
    b"\xc6\x51",
    b"\xc6\x65",
}
# Opcode(2) + part byte(1) + 2-byte power payload -> zeroed to 00 00.
_POWER3_OPCODES = {b"\xc6\x31", b"\xc6\x32", b"\xc6\x41", b"\xc6\x42"}

BANNER = """\
================================================================
 WARNING: THIS SCRIPT MOVES THE MACHINE.
 It sends the RDWorks reference job over USB with every power
 command zeroed (including C6 65), ACK-paced, no checksum
 prefix. Power zeroed means the laser will NOT fire, but the
 gantry WILL still execute every move at full programmed speed.
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


def build_patched_job() -> tuple[bytes, int]:
    """
    Load the fixture, zero every power command, recompute the E5 05
    file checksum, and return (swizzled_blob, command_count).

    Always swizzled with JOB_MAGIC (0x88), matching both the fixture
    file's own on-disk encoding and RuidaClient.send_job()'s
    hardcoded unswizzle step -- not parameterized by --magic (see the
    module docstring's note on --magic).

    Ported from send_fixture_test.py's proven zeroing/checksum logic,
    plus the C6 65 addition (see _POWER2_OPCODES above).
    """
    raw = FIXTURE.read_bytes()
    swizzle_lut, unswizzle_lut = build_swizzle_lut(JOB_MAGIC)
    plain = bytes(unswizzle_lut[b] for b in raw)
    commands = split_commands(plain)

    patched = []
    for c in commands:
        if c[:2] in _POWER2_OPCODES:
            c = c[:2] + b"\x00\x00"
        elif c[:2] in _POWER3_OPCODES:
            c = c[:3] + b"\x00\x00"
        patched.append(c)

    e5_index = next(i for i, c in enumerate(patched) if c[:2] == b"\xe5\x05")
    checksum = sum(sum(c) for c in patched[:e5_index]) + 0xD7
    patched[e5_index] = b"\xe5\x05" + encode35(checksum)

    plain_patched = b"".join(patched)
    swizzled = bytes(swizzle_lut[b] for b in plain_patched)
    return swizzled, len(patched)


async def run(args: argparse.Namespace) -> int:
    swizzled, command_count = build_patched_job()
    print(f"fixture: {FIXTURE}")
    print(
        f"{command_count} commands, {len(swizzled)} bytes swizzled, "
        "power zeroed (including C6 65)"
    )
    print()

    transport = build_transport(args)
    install_hex_logging(transport)
    client = RuidaClient(transport)

    def on_start(blob_size: int, chunk_count: int) -> None:
        print(f"sending {blob_size} bytes in {chunk_count} chunk(s)...")

    def on_chunk(
        index: int, chunk_count: int, chunk_size: int, attempts: int
    ) -> None:
        print(
            f"chunk {index}/{chunk_count}: ACKed ({chunk_size} bytes, "
            f"{attempts} attempt(s))"
        )

    await client.connect()
    try:
        await client.send_job(swizzled, on_start=on_start, on_chunk=on_chunk)
    except RuntimeError as exc:
        sys.exit(f"{exc} - transport problem, check wiring/power.")
    finally:
        await client.disconnect()
    print()
    print("All chunks ACKed. Watch the machine.")
    return 0


def main() -> int:
    print(BANNER)
    args = build_parser().parse_args()
    configure_logging()
    confirm_or_exit(args, expect="SEND")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

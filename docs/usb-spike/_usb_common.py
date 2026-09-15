"""
Shared plumbing for the docs/usb-spike/ USB ladder rungs 2-4
(probe_usb.py, jog_usb.py, send_fixture_usb.py). Rung 1
(enumerate.py) only lists devices and never opens a connection, so it
does not use this module.

Every rung talks to the controller through the exact same production
classes the driver uses -- RuidaUsbTransport and RuidaClient (see
swiftcut/machine/driver/ruida/ruida_usb_transport.py and
ruida_client.py) -- so nothing here reimplements framing, chunking, or
the ACK-paced send loop. This module adds only:

- CLI argument wiring shared by all three scripts (--backend, --port,
  --usb-serial, --baudrate, --magic, --mock).
- Hex logging of every byte actually put on / taken off the wire, by
  hooking the transport's own send_command()/signals rather than
  re-swizzling by hand.
- A confirmation gate for the two scripts that move the machine
  (jog_usb.py, send_fixture_usb.py).
- --mock: swaps in MockD2xxLibrary (_usb_mock.py) via the same
  d2xx_library injection point
  tests/machine/driver/ruida/test_ruida_usb_transport.py's
  FakeD2xxLibrary uses, so --mock still drives the real
  RuidaUsbTransport open sequence and framing -- only the FTDI DLL
  itself is replaced.
"""

from __future__ import annotations

import argparse
import logging
import sys


def configure_logging() -> None:
    """
    INFO is enough to see _select_device_index()'s device-selection
    log lines. DEBUG would also dump every RX byte a second time via
    RuidaUsbTransport's own logger, duplicating install_hex_logging().
    """
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s"
    )


def add_common_usb_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--backend",
        choices=["auto", "d2xx", "vcp"],
        default="auto",
        help="USB backend. auto picks d2xx on Windows, vcp elsewhere "
        "(docs/reference/rdcam_usb.md section 2). Ignored with --mock.",
    )
    parser.add_argument("--port", help="COM/tty port, for --backend vcp.")
    parser.add_argument(
        "--usb-serial",
        help="Pin a specific FTDI serial number, for --backend d2xx.",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=19200,
        help="Baud rate for --backend vcp (default: 19200).",
    )
    parser.add_argument(
        "--magic",
        type=lambda s: int(s, 0),
        default=0x88,
        help="Swizzle magic key (default: 0x88).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Drive this script against an in-process RuidaSimulator "
        "instead of real hardware (see _usb_mock.py). Safe with no "
        "device connected.",
    )
    parser.add_argument(
        "--mock-no-enq-reply",
        action="store_true",
        help="With --mock: simulate a device that never answers the "
        "keepalive ENQ (0xCE), per meerk40t's 'no ACK handshake' "
        "finding for USB. Ignored without --mock.",
    )


def add_confirmation_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the typed confirmation prompt (for scripted/--mock "
        "runs). Never implied by --mock: pass it explicitly.",
    )


def confirm_or_exit(args: argparse.Namespace, expect: str) -> None:
    """Require --yes or a typed confirmation before doing anything
    that can move the machine. Never proceeds silently."""
    if args.yes:
        print(f"--yes given: skipping the typed {expect!r} prompt.")
        return
    if not sys.stdin.isatty():
        sys.exit(
            "Refusing to proceed: not an interactive terminal and "
            "--yes was not given. Re-run with --yes to confirm "
            "non-interactively."
        )
    try:
        answer = input(f"Type {expect!r} to confirm, anything else cancels: ")
    except EOFError:
        sys.exit("No input available (EOF); aborting. Nothing was sent.")
    if answer.strip() != expect:
        sys.exit("Confirmation not given; aborting. Nothing was sent.")


def build_transport(args: argparse.Namespace):
    """Construct a RuidaUsbTransport from the parsed common args."""
    from swiftcut.machine.driver.ruida.ruida_usb_transport import (
        RuidaUsbTransport,
    )

    if args.mock:
        from _usb_mock import MockD2xxLibrary

        print(
            "--mock: using an in-process RuidaSimulator, not real "
            "hardware."
        )
        if args.mock_no_enq_reply:
            print("--mock-no-enq-reply: this mock device never ACKs ENQ.")
        return RuidaUsbTransport(
            backend="d2xx",
            magic=args.magic,
            d2xx_library=MockD2xxLibrary(
                magic=args.magic,
                answer_enq=not args.mock_no_enq_reply,
            ),
        )

    backend = None if args.backend == "auto" else args.backend
    if backend == "vcp" and not args.port:
        sys.exit(
            "--backend vcp requires --port (e.g. COM7 or /dev/ttyUSB0)"
        )
    return RuidaUsbTransport(
        backend=backend,
        port=args.port,
        baudrate=args.baudrate,
        usb_serial=args.usb_serial,
        magic=args.magic,
    )


def install_hex_logging(transport) -> None:
    """
    Print every raw byte sent/received, in hex, without touching the
    transport's own logic: hooks its existing signals and wraps its
    send_command(), rather than re-implementing swizzle/framing.
    """
    orig_send_command = transport.send_command

    async def logged_send_command(command: bytes) -> None:
        swizzled = transport._codec.swizzle(command)
        print(f"  tx (swizzled): {swizzled.hex(' ')}")
        await orig_send_command(command)

    transport.send_command = logged_send_command

    def on_raw(sender, data: bytes) -> None:
        print(f"  rx (raw):      {data.hex(' ')}")

    def on_decoded(sender, data: bytes) -> None:
        print(f"  rx (unswiz.):  {data.hex(' ')}")

    # weak=False: these closures have no other referent, and blinker
    # holds receivers weakly by default (same idiom as
    # ruida_simulator.py's run_udp_simulator).
    transport._raw.received.connect(on_raw, weak=False)
    transport.decoded_received.connect(on_decoded, weak=False)

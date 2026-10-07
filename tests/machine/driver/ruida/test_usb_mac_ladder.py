"""
The macOS USB ladder (docs/usb-spike/mac/) runs end to end against its
--mock port: each rung as the owner runs it, a subprocess from the
repository root, through the app's own transport and client.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from swiftcut.machine.driver.ruida.ruida_codec import RuidaCodec
from swiftcut.machine.driver.ruida.ruida_util import frame_packet

REPO = Path(__file__).resolve().parents[4]
LADDER = REPO / "docs" / "usb-spike" / "mac"
_CODEC = RuidaCodec(0x88)


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(LADDER / script), "--mock", *args],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(REPO)},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _tx(stdout: str) -> list[tuple[bytes, bytes]]:
    """Every write the rung printed, as (wire, plain) byte pairs."""
    lines = stdout.splitlines()
    writes = []
    for i, line in enumerate(lines):
        m = re.match(r"TX\s+\d+ B  wire:  (.*)$", line)
        if m:
            plain = lines[i + 1].split("plain: ", 1)[1]
            writes.append((bytes.fromhex(m[1]), bytes.fromhex(plain)))
    return writes


def test_enumerate_lists_ports_and_the_one_it_would_open():
    result = _run("enumerate.py")

    assert result.returncode == 0, result.stderr
    assert "/dev/cu.usbserial-MOCK0001  VID:PID=0403:6001" in result.stdout
    assert "serial='MOCK0001'   <- FTDI" in result.stdout
    assert "/dev/cu.Bluetooth-Incoming-Port  VID:PID=----:----" in (
        result.stdout
    )
    assert "To pin it: usb_serial: MOCK0001" in result.stdout
    assert _tx(result.stdout) == []


def test_probe_reads_card_id_then_position_and_never_moves():
    result = _run("probe.py")

    assert result.returncode == 0, result.stderr
    assert (
        "19200 baud, 8N1, timeout=0.1s, write_timeout=1.0s, "
        "rtscts=False, dsrdtr=False, rts=False, dtr=False"
    ) in result.stdout
    writes = _tx(result.stdout)
    # The app's own queries: handshake, position poll, keepalive.
    assert [plain for _wire, plain in writes] == [
        bytes.fromhex("da 00 05 7e"),
        bytes.fromhex("da 00 04 21"),
        bytes.fromhex("da 00 04 00"),
    ]
    for wire, plain in writes:
        assert wire == _CODEC.swizzle(plain)
        assert wire != frame_packet(_CODEC.swizzle(plain))
    assert "USB handshake ok, card id 0x" in result.stderr
    assert "card_id=0x" in result.stdout
    assert "-> x=0 um" in result.stdout
    assert "-> status=0x" in result.stdout


def test_jog_sends_exactly_one_relative_x_move():
    result = _run("jog.py", "--yes")

    assert result.returncode == 0, result.stderr
    moves = [plain for _wire, plain in _tx(result.stdout) if plain[0] == 0xD9]
    assert moves == [bytes.fromhex("d9 00 02 00 00 00 07 68")]
    assert "delta=+1000 um" in result.stdout


def test_jog_refuses_to_move_without_confirmation():
    result = _run("jog.py")

    assert result.returncode != 0
    assert _tx(result.stdout) == []


def test_fixture_streams_the_zero_power_job_each_chunk_once():
    """No chunk waits for an ACK over USB, and none is re-sent."""
    result = _run("fixture.py", "--yes")

    assert result.returncode == 0, result.stderr
    assert "power commands, all zero (including C6 65)" in result.stdout
    announced = re.search(r"in (\d+) chunk\(s\)", result.stdout)
    assert announced
    writes = _tx(result.stdout)
    assert len(writes) == int(announced[1]) >= 2
    assert all(len(wire) <= 1000 for wire, _plain in writes)
    plain = b"".join(p for _wire, p in writes)
    assert plain.startswith(b"\xd8\x12") and plain.endswith(b"\xd7")
    assert "All chunks sent, each once" in result.stdout

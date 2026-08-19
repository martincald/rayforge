#!/usr/bin/env python3
"""Motion-only transport test: sends the RDWorks ground-truth job with
all power zeroed. Bypasses Rayforge entirely. CLOSE RAYFORGE FIRST
(it holds local port 40200). Keep the E-stop in reach - the gantry
WILL move."""

import socket
import struct
import sys
from pathlib import Path

LASER_IP, DEST_PORT, LOCAL_PORT = "192.168.1.100", 50200, 40200
FIXTURE = Path(__file__).parent / "fixtures" / "rdworks_reference.rd"
MAGIC, MAX_CHUNK = 0x88, 1000


def _swz(b):
    b ^= (b >> 7) & 0xFF
    b ^= (b << 7) & 0xFF
    b ^= (b >> 7) & 0xFF
    b ^= MAGIC
    return (b + 1) & 0xFF


SWZ = bytes(_swz(b) for b in range(256))
UNSWZ = bytes(SWZ.index(i) for i in range(256))


def main():
    raw = FIXTURE.read_bytes()
    dec = bytes(UNSWZ[b] for b in raw)

    # split into commands on MSB-set bytes
    cmds, cur = [], bytearray([dec[0]])
    for b in dec[1:]:
        if b & 0x80:
            cmds.append(bytes(cur))
            cur = bytearray([b])
        else:
            cur.append(b)
    cmds.append(bytes(cur))

    # zero all power commands (payload after opcode/part bytes)
    power2 = {
        b"\xc6\x01",
        b"\xc6\x02",
        b"\xc6\x21",
        b"\xc6\x22",
        b"\xc6\x50",
        b"\xc6\x51",
    }  # opcode(2)+power(2)
    power3 = {b"\xc6\x31", b"\xc6\x32", b"\xc6\x41", b"\xc6\x42"}  # +part
    patched = []
    for c in cmds:
        if c[:2] in power2:
            c = c[:2] + b"\x00\x00"
        elif c[:2] in power3:
            c = c[:3] + b"\x00\x00"
        patched.append(c)

    # recompute E5 05 file sum
    e5 = next(i for i, c in enumerate(patched) if c[:2] == b"\xe5\x05")
    s = sum(sum(c) for c in patched[:e5]) + 0xD7
    enc35 = bytes((s >> (7 * i)) & 0x7F for i in (4, 3, 2, 1, 0))
    patched[e5] = b"\xe5\x05" + enc35
    print(f"{len(patched)} commands, power zeroed, sum={s}")

    # chunk on command boundaries, frame, send with ACK pacing
    chunks, cur = [], bytearray()
    for c in patched:
        if len(cur) + len(c) > MAX_CHUNK:
            chunks.append(bytes(cur))
            cur = bytearray()
        cur += c
    chunks.append(bytes(cur))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", LOCAL_PORT))
    sock.settimeout(4.0)
    for n, ch in enumerate(chunks, 1):
        swz = bytes(SWZ[b] for b in ch)
        pkt = struct.pack(">H", sum(swz) & 0xFFFF) + swz
        for attempt in range(4):
            sock.sendto(pkt, (LASER_IP, DEST_PORT))
            try:
                r, _ = sock.recvfrom(64)
            except TimeoutError:
                print(f"chunk {n}/{len(chunks)}: TIMEOUT (try {attempt + 1})")
                continue
            first = {r[0], UNSWZ[r[0]]}
            if first & {0xCC, 0xC6}:
                print(f"chunk {n}/{len(chunks)}: ACK ({len(ch)} bytes)")
                break
            print(
                f"chunk {n}/{len(chunks)}: reply {r.hex(' ')} "
                f"(try {attempt + 1})"
            )
        else:
            sys.exit(f"chunk {n}: no ACK after 4 tries - transport problem")
    print("All chunks ACKed. Watch the machine.")


if __name__ == "__main__":
    main()

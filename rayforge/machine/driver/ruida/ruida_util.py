"""
Ruida protocol utility functions for encoding, decoding, and swizzling.

Based on:
- https://edutechwiki.unige.ch/en/Ruida
- https://github.com/meerk40t/meerk40t/tree/main/meerk40t/ruida
- https://github.com/StevenIsaacs/ruida-protocol-analyzer
"""

from rayforge.machine.driver.ruida.ruida_maps import (
    DA_4_BYTE_RESPONSE_SUBCOMMANDS,
    DA_VARIABLE_4_BYTE_SUBCOMMANDS,
)

UM_PER_MM = 1000.0


def swizzle_byte(b: int, magic: int = 0x88) -> int:
    """Swizzle a single byte for transmission."""
    b ^= (b >> 7) & 0xFF
    b ^= (b << 7) & 0xFF
    b ^= (b >> 7) & 0xFF
    b ^= magic
    b = (b + 1) & 0xFF
    return b


def unswizzle_byte(b: int, magic: int = 0x88) -> int:
    """Unswizzle a single byte after reception."""
    b = (b - 1) & 0xFF
    b ^= magic
    b ^= (b >> 7) & 0xFF
    b ^= (b << 7) & 0xFF
    b ^= (b >> 7) & 0xFF
    return b


def build_swizzle_lut(magic: int) -> tuple[bytes, bytes]:
    """Build lookup tables for swizzling and unswizzling."""
    swizzle = bytes([swizzle_byte(i, magic) for i in range(256)])
    unswizzle = bytes([unswizzle_byte(i, magic) for i in range(256)])
    return swizzle, unswizzle


def encode14(v: int) -> bytes:
    """Encode a 14-bit value."""
    v = int(v) & 0x3FFF
    return bytes([(v >> 7) & 0x7F, v & 0x7F])


def encode35(v: int) -> bytes:
    """Encode a signed 35-bit coordinate as 5 bytes."""
    v = int(v) & 0x7FFFFFFFF
    return bytes(
        [
            (v >> 28) & 0x7F,
            (v >> 21) & 0x7F,
            (v >> 14) & 0x7F,
            (v >> 7) & 0x7F,
            v & 0x7F,
        ]
    )


def decode14(data: bytes) -> int:
    """Decode a 14-bit value from 2 bytes."""
    val = ((data[0] & 0x7F) << 7) | (data[1] & 0x7F)
    if val & 0x2000:
        val -= 0x4000
    return val


def decodeu14(data: bytes) -> int:
    """Decode an unsigned 14-bit value from 2 bytes."""
    return ((data[0] & 0x7F) << 7) | (data[1] & 0x7F)


def decode35(data: bytes) -> int:
    """Decode a signed 35-bit coordinate from 5 bytes."""
    val = (
        ((data[0] & 0x7F) << 28)
        | ((data[1] & 0x7F) << 21)
        | ((data[2] & 0x7F) << 14)
        | ((data[3] & 0x7F) << 7)
        | (data[4] & 0x7F)
    )
    if val & 0x400000000:
        val -= 0x800000000
    return val


def decodeu35(data: bytes) -> int:
    """Decode an unsigned 35-bit value from 5 bytes."""
    return (
        ((data[0] & 0x7F) << 28)
        | ((data[1] & 0x7F) << 21)
        | ((data[2] & 0x7F) << 14)
        | ((data[3] & 0x7F) << 7)
        | (data[4] & 0x7F)
    )


def parse_mem(data: bytes) -> int:
    """Parse memory address from 2 bytes (big-endian)."""
    return (data[0] << 8) | data[1]


def calculate_checksum(data: bytes) -> int:
    """Calculate 16-bit checksum (sum of all bytes)."""
    return sum(data) & 0xFFFF


def decode_abs_coords(data: bytes) -> tuple[float, float]:
    """
    Decode absolute X,Y coordinates from 10 bytes.
    Returns coordinates in millimeters.
    """
    x_um = decode35(data[:5])
    y_um = decode35(data[5:10])
    return x_um / UM_PER_MM, y_um / UM_PER_MM


def decode_rel_coords(data: bytes) -> tuple[float, float]:
    """
    Decode relative X,Y coordinates from 4 bytes.
    Returns coordinates in millimeters.
    """
    dx_um = decode14(data[:2])
    dy_um = decode14(data[2:4])
    return dx_um / UM_PER_MM, dy_um / UM_PER_MM


def frame_packet(payload: bytes) -> bytes:
    """
    Create a framed packet with checksum prefix.

    Args:
        payload: The payload bytes to frame

    Returns:
        Complete packet with 2-byte checksum prefix + payload
    """
    checksum = calculate_checksum(payload)
    return bytes([checksum >> 8, checksum & 0xFF]) + payload


def validate_packet(data: bytes) -> tuple[bool, bytes, int, int]:
    """
    Validate a complete packet and extract payload.

    Args:
        data: Complete packet with checksum prefix

    Returns:
        Tuple of (is_valid, payload, expected_checksum, actual_checksum)
    """
    if len(data) < 2:
        return False, b"", 0, 0

    checksum_received = (data[0] << 8) | data[1]
    payload = data[2:]
    checksum_calculated = calculate_checksum(payload)

    return (
        checksum_received == checksum_calculated,
        payload,
        checksum_received,
        checksum_calculated,
    )


# Per-subcommand command lengths (opcode byte included), matching the
# vendor DLL and verified against the RDWorks ground-truth file
# (tests/machine/driver/ruida/fixtures/rdworks_reference.rd).
_C6_LENGTHS: dict[int, int] = {
    0x01: 4,
    0x02: 4,
    0x05: 4,
    0x06: 4,
    0x07: 4,
    0x08: 4,
    0x21: 4,
    0x22: 4,
    0x50: 4,
    0x51: 4,
    0x65: 4,
    0x31: 5,
    0x32: 5,
    0x41: 5,
    0x42: 5,
    0x10: 7,
    0x12: 7,
    0x13: 7,
    0x60: 9,
}

_E7_LENGTHS: dict[int, int] = {
    0x00: 2,
    0x05: 3,
    0x0B: 3,
    0x24: 3,
    0x38: 3,
    0x3B: 3,
    0x60: 4,
    0x0A: 7,
    0x54: 8,
    0x55: 8,
    0x03: 12,
    0x06: 12,
    0x07: 12,
    0x13: 12,
    0x17: 12,
    0x23: 12,
    0x32: 12,
    0x37: 12,
    0x50: 12,
    0x51: 12,
    0x52: 13,
    0x53: 13,
    0x61: 13,
    0x62: 13,
    0x04: 16,
    0x08: 16,
}

_F2_LENGTHS: dict[int, int] = {
    0x00: 3,
    0x03: 12,
    0x04: 12,
    0x06: 12,
    0x07: 3,
    0x08: 12,
    0x05: 16,
}


def estimate_packet_length(payload: bytes) -> int:
    """
    Estimate the expected packet length from the payload.

    Args:
        payload: Payload bytes (without checksum prefix)

    Returns:
        Expected payload length, or -1 if unknown/insufficient data
    """
    if len(payload) < 1:
        return -1

    cmd = payload[0]

    if cmd in (0xCC, 0xCD, 0xCE, 0xD7, 0xE4, 0xEB, 0xF0):
        return 1

    if cmd in (0xE3, 0xEA):
        return 2

    if cmd in (0x88, 0xA8):
        return 11

    if cmd in (0x89, 0xA9):
        return 5

    if cmd in (0x8A, 0x8B, 0xAA, 0xAB):
        return 3

    # Immediate/end power for lasers 1-4: opcode + encode14.
    if cmd in (0xC0, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC7, 0xC8):
        return 3

    if cmd == 0xD0:
        if len(payload) < 2:
            return -1
        return 2

    if cmd == 0xD8:
        if len(payload) < 2:
            return -1
        return 2

    if cmd == 0xD9:
        if len(payload) < 2:
            return -1
        # D9 10 <opts> + two encode35 (rapid move XY); other forms
        # are D9 <axis> <opts> + one encode35.
        if payload[1] == 0x10:
            return 13
        return 8

    if cmd == 0xDA:
        if len(payload) < 4:
            return -1
        sub = payload[1]
        if sub == 0x00:
            return 4
        if sub == 0x01:
            # Memory write: DA 01 <addr> + doubled encode35 value.
            return 14
        if sub == 0x04:
            if len(payload) < 7:
                return -1
            return 7
        if sub == 0x05:
            if len(payload) < 8:
                return -1
            return 8
        if sub == 0x06:
            if len(payload) < 6:
                return -1
            return 6
        if sub == 0x07:
            if len(payload) < 7:
                return -1
            return 7
        if sub == 0x10:
            if len(payload) < 7:
                return -1
            extra = decode14(payload[4:])
            return 7 + extra
        if sub in DA_4_BYTE_RESPONSE_SUBCOMMANDS:
            return 4
        if sub == 0x54:
            if len(payload) < 6:
                return -1
            return 6
        if sub == 0x55:
            if len(payload) < 5:
                return -1
            return 5
        if sub in DA_VARIABLE_4_BYTE_SUBCOMMANDS:
            return 4
        return -1

    if cmd == 0xA5:
        if len(payload) < 3:
            return -1
        return 3

    if cmd == 0xA7:
        return 2

    if cmd == 0xC6:
        if len(payload) < 2:
            return -1
        return _C6_LENGTHS.get(payload[1], -1)

    if cmd == 0xC9:
        if len(payload) < 2:
            return -1
        # C9 04 carries a part byte before the encode35 speed.
        if payload[1] == 0x04:
            return 8
        return 7

    if cmd == 0xCA:
        if len(payload) < 2:
            return -1
        if payload[1] == 0x06:
            return 8
        if payload[1] == 0x41:
            return 4
        if payload[1] in (0x01, 0x02, 0x03, 0x10, 0x22):
            return 3
        return -1

    if cmd == 0xE5:
        if len(payload) < 2:
            return -1
        if payload[1] == 0x05:
            return 7
        return -1

    if cmd == 0xE7:
        if len(payload) < 2:
            return -1
        return _E7_LENGTHS.get(payload[1], -1)

    if cmd == 0xE8:
        if len(payload) < 2:
            return -1
        return 2

    if cmd == 0xF1:
        if len(payload) < 2:
            return -1
        if payload[1] == 0x03:
            return 12
        if payload[1] in (0x00, 0x01, 0x02):
            return 3
        return -1

    if cmd == 0xF2:
        if len(payload) < 2:
            return -1
        return _F2_LENGTHS.get(payload[1], -1)

    return -1

"""Per-layer settings must not bleed between layers.

Each layer opens with a block that restates its own speed and powers.
Nothing the previous layer emitted may suppress a command the next one
needs, and the RDWorks-style Min Power has to reach both the header and
the layer body.
"""

import logging

import pytest
from raygeo.ops import Ops

from rayforge.core.doc import Doc
from rayforge.machine.driver.ruida.ruida_encoder import RuidaEncoder
from rayforge.machine.driver.ruida.ruida_util import (
    decode35,
    encode14,
    encode35,
)
from rayforge.machine.models.laser import Laser

# 10 and 40 mm/s, in the mm/min the model stores.
SLOW_MM_MIN = 600
FAST_MM_MIN = 2400
SLOW_UM_S = 10000
FAST_UM_S = 40000


@pytest.fixture
def machine(isolated_machine):
    laser = Laser()
    laser.uid = "laser-1"
    isolated_machine.heads.clear()
    isolated_machine.add_head(laser)
    isolated_machine.active_wcs = "MACHINE"
    return isolated_machine


def _two_layer_job(uids=("layer-1", "layer-2")) -> Ops:
    ops = Ops()
    ops.job_start()
    ops.layer_start(uids[0])
    ops.set_power(0.5)
    ops.set_feed_rate(SLOW_MM_MIN)
    ops.move_to(0.0, 0.0, 0.0)
    ops.line_to(10.0, 0.0, 0.0)
    ops.layer_end(uids[0])
    ops.layer_start(uids[1])
    ops.set_power(0.8)
    ops.set_feed_rate(FAST_MM_MIN)
    ops.move_to(0.0, 5.0, 0.0)
    ops.line_to(10.0, 5.0, 0.0)
    ops.layer_end(uids[1])
    ops.job_end()
    return ops


def _one_layer_job(uid: str, power: float) -> Ops:
    ops = Ops()
    ops.job_start()
    ops.layer_start(uid)
    ops.set_power(power)
    ops.set_feed_rate(SLOW_MM_MIN)
    ops.move_to(0.0, 0.0, 0.0)
    ops.line_to(10.0, 0.0, 0.0)
    ops.layer_end(uid)
    ops.job_end()
    return ops


def _commands(ops, machine, doc=None):
    doc = doc or Doc()
    return RuidaEncoder().encode(ops, machine, doc).driver_data["commands"]


def _payloads(commands, opcode: bytes) -> list[bytes]:
    return [c[len(opcode) :] for c in commands if c.startswith(opcode)]


def _layer_blocks(commands) -> list[list[bytes]]:
    """Split the stream into one list per layer body block."""
    starts = [i for i, c in enumerate(commands) if c == b"\xca\x01\x00"]
    blocks = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(commands)
        blocks.append(commands[start:end])
    return blocks


class TestLayerSpeed:
    """Every layer body carries its own speed."""

    def test_each_layer_block_emits_its_own_speed(self, machine):
        commands = _commands(_two_layer_job(), machine)

        blocks = _layer_blocks(commands)
        assert len(blocks) == 2
        speeds = [
            decode35(_payloads(block, b"\xc9\x02")[0]) for block in blocks
        ]
        assert speeds == [SLOW_UM_S, FAST_UM_S]

    def test_header_carries_one_speed_per_part(self, machine):
        commands = _commands(_two_layer_job(), machine)

        speeds = [
            decode35(payload[1:])
            for payload in _payloads(commands, b"\xc9\x04")
        ]
        assert speeds == [SLOW_UM_S, FAST_UM_S]

    def test_identical_layers_still_each_emit_a_speed(self, machine):
        """A repeated value must not be suppressed at a layer boundary."""
        ops = Ops()
        ops.job_start()
        for uid in ("layer-1", "layer-2"):
            ops.layer_start(uid)
            ops.set_power(0.5)
            ops.set_feed_rate(SLOW_MM_MIN)
            ops.move_to(0.0, 0.0, 0.0)
            ops.line_to(10.0, 0.0, 0.0)
            ops.layer_end(uid)
        ops.job_end()

        blocks = _layer_blocks(_commands(ops, machine))

        assert [len(_payloads(b, b"\xc9\x02")) for b in blocks] == [1, 1]

    def test_layer_start_clears_the_emission_caches(self, machine):
        encoder = RuidaEncoder()
        encoder.encode(_two_layer_job(), machine, Doc())

        # Nothing is memoized across an encode pass either.
        encoder._reset_emission_state()
        assert encoder.cut_speed is None
        assert encoder.power is None
        assert encoder._min_power is None
        assert encoder._last_pos_um is None
        assert encoder._imd_power is None


class TestMinPower:
    """Min Power reaches the header and the layer body."""

    def test_default_layer_has_min_equal_to_max(self, machine):
        commands = _commands(_one_layer_job("layer-1", 0.6), machine)

        block = _layer_blocks(commands)[0]
        assert _payloads(block, b"\xc6\x01") == _payloads(block, b"\xc6\x02")
        assert _payloads(block, b"\xc6\x21") == _payloads(block, b"\xc6\x22")

    def test_default_header_has_min_equal_to_max(self, machine):
        commands = _commands(_one_layer_job("layer-1", 0.6), machine)

        assert _payloads(commands, b"\xc6\x31") == _payloads(
            commands, b"\xc6\x32"
        )
        assert _payloads(commands, b"\xc6\x41") == _payloads(
            commands, b"\xc6\x42"
        )

    def test_explicit_min_and_max_are_distinct(self, machine):
        doc, uid = _doc_with_powers(min_power=0.15, power=0.60)

        commands = _commands(_one_layer_job(uid, 0.60), machine, doc)

        min14 = encode14(int(0.15 * 16383))
        max14 = encode14(int(0.60 * 16383))
        block = _layer_blocks(commands)[0]
        assert _payloads(block, b"\xc6\x01") == [min14]
        assert _payloads(block, b"\xc6\x02") == [max14]
        assert _payloads(block, b"\xc6\x21") == [min14]
        assert _payloads(block, b"\xc6\x22") == [max14]

    def test_explicit_min_and_max_reach_the_header(self, machine):
        doc, uid = _doc_with_powers(min_power=0.15, power=0.60)

        commands = _commands(_one_layer_job(uid, 0.60), machine, doc)

        min14 = encode14(int(0.15 * 16383))
        max14 = encode14(int(0.60 * 16383))
        assert _payloads(commands, b"\xc6\x31") == [b"\x00" + min14]
        assert _payloads(commands, b"\xc6\x32") == [b"\x00" + max14]
        assert _payloads(commands, b"\xc6\x41") == [b"\x00" + min14]
        assert _payloads(commands, b"\xc6\x42") == [b"\x00" + max14]

    def test_min_power_never_exceeds_max_power(self, machine):
        """A floor above the cut power would raise it, not lower it."""
        doc, uid = _doc_with_powers(min_power=0.9, power=0.3)

        commands = _commands(_one_layer_job(uid, 0.3), machine, doc)

        block = _layer_blocks(commands)[0]
        assert _payloads(block, b"\xc6\x01") == _payloads(block, b"\xc6\x02")

    def test_unknown_layer_falls_back_to_min_equal_max(self, machine):
        """Jobs the document knows nothing about keep min == max."""
        doc, _uid = _doc_with_powers(min_power=0.15, power=0.60)
        ops = _one_layer_job("not-in-the-doc", 0.6)

        commands = _commands(ops, machine, doc)

        block = _layer_blocks(commands)[0]
        assert _payloads(block, b"\xc6\x01") == _payloads(block, b"\xc6\x02")

    def test_an_unknown_uid_says_so(self, machine, caplog):
        """A silent fallback is how a whole job ran on one step's
        settings, so a failed lookup names the uid and both uid
        spaces it was matched against."""
        doc, known_uid = _doc_with_powers(min_power=0.15, power=0.60)
        ops = _one_layer_job("not-in-the-doc", 0.6)

        with caplog.at_level(logging.WARNING):
            _commands(ops, machine, doc)

        warnings = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
        ]
        assert any("not-in-the-doc" in m for m in warnings)
        assert any(known_uid in m for m in warnings)

    def test_a_resolved_uid_is_quiet(self, machine, caplog):
        """The warning must not fire on a job that resolved."""
        doc, uid = _doc_with_powers(min_power=0.15, power=0.60)

        with caplog.at_level(logging.WARNING):
            _commands(_one_layer_job(uid, 0.60), machine, doc)

        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    def test_every_part_is_logged_with_its_settings(self, machine, caplog):
        """The console shows the truth on every real run."""
        with caplog.at_level(logging.INFO):
            _commands(_two_layer_job(), machine)

        parts = [
            r.getMessage()
            for r in caplog.records
            if r.getMessage().startswith("Part ")
        ]
        assert len(parts) == 2
        assert "Part 0 (layer-1): speed 10.0 mm/s power 50/50%" in parts[0]
        assert "Part 1 (layer-2): speed 40.0 mm/s power 80/80%" in parts[1]


class _Step:
    """Just the power attributes the encoder reads off a step."""

    def __init__(self, min_power: float, power: float):
        self.min_power = min_power
        self.power = power


class _Workflow:
    def __init__(self, steps):
        self.steps = steps


class _Layer:
    def __init__(self, uid: str, workflow):
        self.uid = uid
        self.workflow = workflow


class _Doc:
    """The document shape the encoder walks to find Min Power."""

    def __init__(self, layers):
        self.layers = layers


def _doc_with_powers(min_power: float, power: float):
    """A stand-in document whose layer step carries these powers."""
    uid = "layer-1"
    layer = _Layer(uid, _Workflow([_Step(min_power, power)]))
    return _Doc([layer]), uid


def _job(build) -> Ops:
    """A job whose single marker is filled by ``build``."""
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer-1")
    build(ops)
    ops.layer_end("layer-1")
    ops.job_end()
    return ops


class TestSettingsChangeOpensAPart:
    """A part is a settings combination, not a marker."""

    def test_a_change_after_geometry_opens_a_new_part(self, machine):
        """The second group cannot run at the first group's settings."""

        def build(ops):
            ops.set_power(0.5)
            ops.set_feed_rate(SLOW_MM_MIN)
            ops.move_to(0.0, 0.0, 0.0)
            ops.line_to(10.0, 0.0, 0.0)
            ops.set_power(0.8)
            ops.set_feed_rate(FAST_MM_MIN)
            ops.move_to(0.0, 5.0, 0.0)
            ops.line_to(10.0, 5.0, 0.0)

        commands = _commands(_job(build), machine)

        assert [p[0] for p in _payloads(commands, b"\xca\x02")] == [0, 1]
        assert _payloads(commands, b"\xca\x22") == [b"\x01"]
        speeds = [
            decode35(payload[1:])
            for payload in _payloads(commands, b"\xc9\x04")
        ]
        assert speeds == [SLOW_UM_S, FAST_UM_S]

    def test_a_change_before_the_first_cut_stays_in_the_part(self, machine):
        """The last value before the first cut is the part's value."""

        def build(ops):
            ops.set_power(0.5)
            ops.set_feed_rate(SLOW_MM_MIN)
            ops.set_feed_rate(FAST_MM_MIN)
            ops.move_to(0.0, 0.0, 0.0)
            ops.line_to(10.0, 0.0, 0.0)

        commands = _commands(_job(build), machine)

        assert [p[0] for p in _payloads(commands, b"\xca\x02")] == [0]
        speeds = [
            decode35(payload[1:])
            for payload in _payloads(commands, b"\xc9\x04")
        ]
        assert speeds == [FAST_UM_S]

    def test_no_bare_speed_override_survives_inside_a_part(self, machine):
        """Every C9 02 belongs to a block, never to the body."""

        def build(ops):
            ops.set_power(0.5)
            ops.set_feed_rate(SLOW_MM_MIN)
            ops.set_feed_rate(FAST_MM_MIN)
            ops.move_to(0.0, 0.0, 0.0)
            ops.line_to(10.0, 0.0, 0.0)

        commands = _commands(_job(build), machine)

        assert len(_payloads(commands, b"\xc9\x02")) == 1

    def test_each_part_switch_forces_an_absolute_first_move(self, machine):
        """CA 02 clears the controller's first-move state."""

        def build(ops):
            ops.set_power(0.5)
            ops.set_feed_rate(SLOW_MM_MIN)
            ops.move_to(0.0, 0.0, 0.0)
            ops.line_to(1.0, 0.0, 0.0)
            ops.set_feed_rate(FAST_MM_MIN)
            # A delta this small would otherwise be a relative move.
            ops.move_to(1.0, 0.5, 0.0)
            ops.line_to(2.0, 0.5, 0.0)

        commands = _commands(_job(build), machine)

        moves = [c for c in commands if c[0] in (0x88, 0x89, 0x8A, 0x8B)]
        assert [c[0] for c in moves] == [0x88, 0x88]


class TestEmptyPartsAreDropped:
    """A marker with nothing in it is not a part."""

    def test_a_marker_with_no_geometry_claims_no_part(self, machine):
        ops = Ops()
        ops.job_start()
        ops.layer_start("empty")
        ops.set_power(0.5)
        ops.set_feed_rate(SLOW_MM_MIN)
        ops.layer_end("empty")
        ops.layer_start("real")
        ops.set_power(0.8)
        ops.set_feed_rate(FAST_MM_MIN)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(10.0, 0.0, 0.0)
        ops.layer_end("real")
        ops.job_end()

        commands = _commands(ops, machine)

        assert [p[0] for p in _payloads(commands, b"\xca\x02")] == [0]
        assert _payloads(commands, b"\xca\x22") == [b"\x00"]
        speeds = [
            decode35(payload[1:])
            for payload in _payloads(commands, b"\xc9\x04")
        ]
        assert speeds == [FAST_UM_S]


class TestPartMode:
    """Every part declares its work mode, header and body."""

    def test_ca_41_is_emitted_without_the_reference_replay(self, machine):
        """The mode is a property of the job, not of the replay."""
        encoder = RuidaEncoder(follow_reference=False)

        commands = encoder.encode(
            _two_layer_job(), machine, Doc()
        ).driver_data["commands"]

        assert _payloads(commands, b"\xca\x41") == [b"\x00\x00", b"\x01\x00"]

    def test_the_body_mode_matches_the_header_mode(self, machine):
        commands = _commands(_two_layer_job(), machine)

        modes = {p[1] for p in _payloads(commands, b"\xca\x41")}
        blocks = _layer_blocks(commands)
        assert len(blocks) == 2
        assert modes == {block[0][2] for block in blocks}


class TestPartTravelSpeed:
    """A part's rapids run at the speed the part asked for."""

    def test_the_block_emits_c9_03_from_the_travel_speed(self, machine):
        def build(ops):
            ops.set_power(0.5)
            ops.set_feed_rate(SLOW_MM_MIN)
            ops.set_rapid_rate(FAST_MM_MIN)
            ops.move_to(0.0, 0.0, 0.0)
            ops.line_to(10.0, 0.0, 0.0)

        commands = _commands(_job(build), machine)

        assert _payloads(commands, b"\xc9\x03") == [encode35(FAST_UM_S)]

    def test_a_part_without_a_travel_speed_emits_none(self, machine):
        commands = _commands(_two_layer_job(), machine)

        assert _payloads(commands, b"\xc9\x03") == []

    def test_the_travel_speed_is_not_re_emitted_per_primitive(self, machine):
        """One C9 03 per part, not one per rapid."""

        def build(ops):
            ops.set_power(0.5)
            ops.set_feed_rate(SLOW_MM_MIN)
            ops.set_rapid_rate(FAST_MM_MIN)
            ops.move_to(0.0, 0.0, 0.0)
            ops.line_to(10.0, 0.0, 0.0)
            ops.set_rapid_rate(FAST_MM_MIN)
            ops.move_to(0.0, 5.0, 0.0)
            ops.line_to(10.0, 5.0, 0.0)

        commands = _commands(_job(build), machine)

        assert len(_payloads(commands, b"\xc9\x03")) == 1

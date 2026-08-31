"""A two-step job must reach the controller as two parts.

These tests build a real document and encode it through the exact path
a send takes -- the intent pipeline down to the machine-space ops, then
RuidaEncoder, which is what RuidaDriver.run does via build_rd_bytes.
Nothing here synthesises layer markers by hand: the whole point is that
the pipeline used to emit only one, so an engrave step followed by a
cut step ran the cut geometry at engrave speed and engrave power.
"""

from pathlib import Path

import pytest
from raygeo.geo import Geometry
from raygeo.pipeline.execute import execute_stages

from rayforge.core.doc import Doc
from rayforge.core.source_asset import SourceAsset
from rayforge.core.source_asset_segment import SourceAssetSegment
from rayforge.core.vectorization_spec import PassthroughSpec
from rayforge.core.workpiece import WorkPiece
from rayforge.image import SVG_RENDERER
from rayforge.machine.driver.ruida.ruida_encoder import RuidaEncoder
from rayforge.machine.driver.ruida.ruida_util import decode35, encode14
from rayforge.pipeline.intent_builder import (
    IntentBuilder,
    job_machinexform_key,
)

# 300 mm/s and 10 mm/s, in the mm/min the model stores and the um/s the
# controller wants.
ENGRAVE_MM_MIN = 18000
CUT_MM_MIN = 600
ENGRAVE_UM_S = 300000
CUT_UM_S = 10000

ENGRAVE_POWER = 0.20
CUT_POWER = 0.60

# A filled rectangle: the engrave step has something to raster, the
# contour step has an outline to cut.
SVG_DATA = b"""
<svg width="50mm" height="30mm" xmlns="http://www.w3.org/2000/svg">
<rect width="50" height="30" fill="#000000" />
</svg>"""


def _doc_with_two_steps(doc, context, engrave_cls, contour_cls):
    """One layer, one workpiece, an engrave step then a cut step."""
    layer = doc.active_layer
    assert layer.workflow is not None
    layer.workflow.set_steps([])

    workpiece = WorkPiece(name="rect.svg")
    source = SourceAsset(
        Path(workpiece.name),
        original_data=SVG_DATA,
        renderer=SVG_RENDERER,
    )
    doc.add_asset(source)
    workpiece.source_segment = SourceAssetSegment(
        source_asset_uid=source.uid,
        pristine_geometry=Geometry(),
        vectorization_spec=PassthroughSpec(),
    )
    workpiece.set_size(50, 30)
    workpiece.pos = 10, 20
    layer.add_workpiece(workpiece)

    engrave = engrave_cls.create(context, name="engrave")
    engrave.set_cut_speed(ENGRAVE_MM_MIN)
    engrave.set_power(ENGRAVE_POWER)
    engrave.set_min_power(ENGRAVE_POWER)
    layer.workflow.add_step(engrave)

    cut = contour_cls.create(context, name="cut")
    cut.set_cut_speed(CUT_MM_MIN)
    cut.set_power(CUT_POWER)
    cut.set_min_power(CUT_POWER)
    layer.workflow.add_step(cut)

    return engrave, cut


def _encode_like_a_send(doc, machine) -> list[bytes]:
    """Run the production path and return the Ruida command list.

    The pipeline is executed exactly as the job node does, and the
    machine-space ops it produces are handed to RuidaEncoder -- the
    same two steps RuidaDriver.run performs through build_rd_bytes.
    """
    nodes = IntentBuilder(machine=machine, generation_id=1).build(doc)
    completed = []
    execute_stages(nodes, completed.append)

    result = next(c for c in completed if c.key == job_machinexform_key())
    assert result.error is None, result.error
    ops = getattr(result.output, "ops", result.output)
    return RuidaEncoder().encode(ops, machine, doc).driver_data["commands"]


def _payloads(commands, opcode: bytes) -> list[bytes]:
    return [c[len(opcode) :] for c in commands if c.startswith(opcode)]


def _blocks(commands) -> list[list[bytes]]:
    """Split the stream into one list per layer body block."""
    starts = [i for i, c in enumerate(commands) if c == b"\xca\x01\x00"]
    return [
        commands[start : (starts[n + 1] if n + 1 < len(starts) else None)]
        for n, start in enumerate(starts)
    ]


def _part_speeds(commands) -> dict[int, int]:
    """The header's per-part speed, keyed by part index."""
    return {
        payload[0]: decode35(payload[1:])
        for payload in _payloads(commands, b"\xc9\x04")
    }


def _part_powers(commands, opcode: bytes) -> dict[int, bytes]:
    """One header power command's payload, keyed by part index."""
    return {p[0]: p[1:] for p in _payloads(commands, opcode)}


@pytest.fixture
def two_step_doc(
    context_initializer,
    test_machine_and_config,
    engrave_step_class,
    contour_step_class,
):
    """A real engrave-then-cut document and the machine to encode it."""
    machine, _config = test_machine_and_config
    machine.hydrate()
    # Ruida numbers its lasers from 1; the generic test machine's head
    # is left at the model default of 0.
    for head in machine.heads:
        head.tool_number = 1
    doc = Doc()
    engrave, cut = _doc_with_two_steps(
        doc, context_initializer, engrave_step_class, contour_step_class
    )
    return doc, machine, engrave, cut


class TestTwoStepJobEmitsTwoParts:
    """Every step is its own part, with its own settings."""

    def test_each_step_gets_its_own_part_index(self, two_step_doc):
        doc, machine, _engrave, _cut = two_step_doc

        commands = _encode_like_a_send(doc, machine)

        assert [p[0] for p in _payloads(commands, b"\xca\x02")] == [0, 1]
        # CA 22 names the last part, so two parts means 1.
        assert _payloads(commands, b"\xca\x22") == [b"\x01"]

    def test_header_carries_both_speeds_on_the_right_parts(self, two_step_doc):
        doc, machine, _engrave, _cut = two_step_doc

        commands = _encode_like_a_send(doc, machine)

        assert _part_speeds(commands) == {
            0: ENGRAVE_UM_S,
            1: CUT_UM_S,
        }

    def test_header_carries_both_power_pairs_on_the_right_parts(
        self, two_step_doc
    ):
        doc, machine, _engrave, _cut = two_step_doc

        commands = _encode_like_a_send(doc, machine)

        engrave14 = encode14(int(ENGRAVE_POWER * 16383))
        cut14 = encode14(int(CUT_POWER * 16383))
        expected = {0: engrave14, 1: cut14}
        # Min and max are both the step's own power, so a floor read
        # off the wrong step shows up as a mismatched min.
        for opcode in (b"\xc6\x31", b"\xc6\x32", b"\xc6\x41", b"\xc6\x42"):
            assert _part_powers(commands, opcode) == expected

    def test_each_body_block_restates_its_own_settings(self, two_step_doc):
        doc, machine, _engrave, _cut = two_step_doc

        blocks = _blocks(_encode_like_a_send(doc, machine))

        assert len(blocks) == 2
        speeds = [
            decode35(_payloads(block, b"\xc9\x02")[0]) for block in blocks
        ]
        assert speeds == [ENGRAVE_UM_S, CUT_UM_S]

        engrave14 = encode14(int(ENGRAVE_POWER * 16383))
        cut14 = encode14(int(CUT_POWER * 16383))
        for block, power14 in zip(blocks, (engrave14, cut14)):
            assert _payloads(block, b"\xc6\x01")[0] == power14
            assert _payloads(block, b"\xc6\x02")[0] == power14

    def test_the_cut_geometry_runs_under_the_cut_settings(self, two_step_doc):
        """Bind the geometry to the block, not just the values.

        Raster rows modulate power per sample and emit C7 immediate
        power; a plain contour cut never does. So the block that says
        the engrave speed is the one that must hold the raster, and the
        block that says the cut speed must hold cut moves and no C7.
        """
        doc, machine, _engrave, _cut = two_step_doc

        blocks = _blocks(_encode_like_a_send(doc, machine))
        engrave_block, cut_block = blocks

        def cut_moves(block):
            return [
                c
                for c in block
                if c[:1] in (b"\xa8", b"\xa9", b"\xaa", b"\xab")
            ]

        assert decode35(_payloads(engrave_block, b"\xc9\x02")[0]) == (
            ENGRAVE_UM_S
        )
        assert decode35(_payloads(cut_block, b"\xc9\x02")[0]) == CUT_UM_S

        assert [c for c in engrave_block if c[:1] == b"\xc7"]
        assert not [c for c in cut_block if c[:1] == b"\xc7"]
        assert cut_moves(cut_block)


def _first_move_after_each_switch(commands) -> list[int]:
    """The opcode of the first motion command after every CA 02."""
    opcodes = []
    pending = False
    for command in commands:
        if command.startswith(b"\xca\x02"):
            pending = True
        elif pending and command[:1] in (
            b"\x88",
            b"\x89",
            b"\x8a",
            b"\x8b",
            b"\xa8",
            b"\xa9",
            b"\xaa",
            b"\xab",
        ):
            opcodes.append(command[0])
            pending = False
    return opcodes


class TestPartSwitchResetsPosition:
    """A part switch makes the controller forget where the head was."""

    def test_the_first_move_after_each_switch_is_absolute(self, two_step_doc):
        """CA 02 resets the controller's first-move state.

        The DLL's RD_wSetLayerNum calls RD_SetFirstMove, so a relative
        delta after a switch is measured from a position the
        controller no longer holds.
        """
        doc, machine, _engrave, _cut = two_step_doc

        commands = _encode_like_a_send(doc, machine)

        opcodes = _first_move_after_each_switch(commands)
        assert len(opcodes) == 2
        # 0x88 is MOVE_ABS, 0xA8 CUT_ABS; the relative forms are odd
        # or low-nibble A/B and must not appear here.
        assert all(op in (0x88, 0xA8) for op in opcodes)


class TestDisabledStep:
    """The regression: a disabled first step must not lend settings."""

    def test_one_part_carrying_the_second_steps_settings(self, two_step_doc):
        """Hiding the engrave step leaves the cut running as the cut.

        This is the exact shape of the reported bug: the surviving
        step's geometry was emitted under the settings of a step the
        user had switched off.
        """
        doc, machine, engrave, _cut = two_step_doc
        engrave.set_visible(False)

        commands = _encode_like_a_send(doc, machine)

        assert [p[0] for p in _payloads(commands, b"\xca\x02")] == [0]
        assert _payloads(commands, b"\xca\x22") == [b"\x00"]
        assert _part_speeds(commands) == {0: CUT_UM_S}

        cut14 = encode14(int(CUT_POWER * 16383))
        for opcode in (b"\xc6\x31", b"\xc6\x32", b"\xc6\x41", b"\xc6\x42"):
            assert _part_powers(commands, opcode) == {0: cut14}

    def test_the_surviving_block_cuts_at_the_cut_speed(self, two_step_doc):
        doc, machine, engrave, _cut = two_step_doc
        engrave.set_visible(False)

        blocks = _blocks(_encode_like_a_send(doc, machine))

        assert len(blocks) == 1
        assert decode35(_payloads(blocks[0], b"\xc9\x02")[0]) == CUT_UM_S
        # A contour cut never modulates power per sample, so a C7
        # here would mean the raster survived its disabled step.
        assert not [c for c in blocks[0] if c[:1] == b"\xc7"]

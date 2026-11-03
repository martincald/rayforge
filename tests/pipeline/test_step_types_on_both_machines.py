"""
Every step type a student picks, encoded for both shop machines.

Each test builds a one-step document, runs the job the way a send
does (the intent pipeline to machine-space ops, then RuidaEncoder,
which build_rd_bytes wraps) on the bundled ilab-614 or ilab-626
profile, and checks what the controller would get: one part for the
one step, a declared bounding box that holds every move and fits the
bed, and the E5 05 file checksum the controller verifies.
"""

import copy
from pathlib import Path

import pytest
from raygeo.geo import Geometry
from raygeo.pipeline.execute import execute_stages

from swiftcut.core.doc import Doc
from swiftcut.core.source_asset import SourceAsset
from swiftcut.core.source_asset_segment import SourceAssetSegment
from swiftcut.core.step_registry import step_registry
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.image import SVG_RENDERER
from swiftcut.machine.driver.ruida.ruida_encoder import RuidaEncoder
from swiftcut.machine.driver.ruida.ruida_util import decode14, decode35
from swiftcut.machine.models.default_profile import BUNDLED_PROFILES
from swiftcut.machine.models.machine import Machine
from swiftcut.pipeline.intent_builder import (
    IntentBuilder,
    job_machinexform_key,
)

STEP_TYPES = {
    "Cut": "ContourStep",
    "Engrave": "EngraveStep",
    "Scan": "ScanStep",
    "Frame": "FrameStep",
}
MACHINES = ("ilab-614", "ilab-626")

SVG_DATA = b"""
<svg width="50mm" height="30mm" xmlns="http://www.w3.org/2000/svg">
<rect width="50" height="30" fill="#000000" />
</svg>"""

ABS_MOVES = (0x88, 0xA8)
REL_XY_MOVES = (0x89, 0xA9)
REL_X_MOVES = (0x8A, 0xAA)
REL_Y_MOVES = (0x8B, 0xAB)


@pytest.fixture
def bundled(context_initializer):
    """
    The two shop machines from their bundled profiles, in the context's
    machine manager, with auto_connect off so neither reaches a laser.
    """
    machines = {}
    for profile in BUNDLED_PROFILES:
        data = copy.deepcopy(profile)
        data["machine"]["auto_connect"] = False
        machine = Machine.from_dict(data, context=context_initializer)
        context_initializer.machine_mgr.add_machine(machine)
        machines[machine.name] = machine
    return machines


def _commands(context, machine, step_type: str) -> list[bytes]:
    doc = Doc()
    layer = doc.active_layer
    assert layer.workflow is not None
    layer.workflow.set_steps([])

    workpiece = WorkPiece(name="rect.svg")
    source = SourceAsset(
        Path(workpiece.name), original_data=SVG_DATA, renderer=SVG_RENDERER
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

    step = step_registry.get(step_type).create(context, name=step_type)
    layer.workflow.add_step(step)

    nodes = IntentBuilder(machine=machine, generation_id=1).build(doc)
    completed = []
    execute_stages(nodes, completed.append)
    result = next(c for c in completed if c.key == job_machinexform_key())
    assert result.error is None, result.error
    ops = getattr(result.output, "ops", result.output)
    return RuidaEncoder().encode(ops, machine, doc).driver_data["commands"]


def _payloads(commands, opcode: bytes) -> list[bytes]:
    return [c[len(opcode) :] for c in commands if c.startswith(opcode)]


def _xy35(payload: bytes) -> tuple[int, int]:
    return decode35(payload[:5]), decode35(payload[5:10])


def _move_points(commands) -> list[tuple[int, int]]:
    """Every point the head is sent to, absolute moves and relative."""
    points = []
    x = y = None
    for c in commands:
        op = c[0]
        if op in ABS_MOVES:
            x, y = _xy35(c[1:])
        elif x is None or y is None:
            continue
        elif op in REL_XY_MOVES:
            x += decode14(c[1:3])
            y += decode14(c[3:5])
        elif op in REL_X_MOVES:
            x += decode14(c[1:3])
        elif op in REL_Y_MOVES:
            y += decode14(c[1:3])
        else:
            continue
        points.append((x, y))
    return points


@pytest.mark.parametrize("machine_name", MACHINES)
@pytest.mark.parametrize("label", list(STEP_TYPES))
def test_one_step_encodes_one_part_inside_its_declared_bounds(
    context_initializer, bundled, machine_name, label
):
    machine = bundled[machine_name]
    commands = _commands(context_initializer, machine, STEP_TYPES[label])

    assert [p[0] for p in _payloads(commands, b"\xca\x02")] == [0]

    points = _move_points(commands)
    assert points, f"{label} on {machine_name} moved nowhere"
    ((min_x, min_y),) = [_xy35(p) for p in _payloads(commands, b"\xe7\x03")]
    ((max_x, max_y),) = [_xy35(p) for p in _payloads(commands, b"\xe7\x07")]
    for x, y in points:
        assert min_x <= x <= max_x and min_y <= y <= max_y, (x, y)

    width_um, height_um = (int(v * 1000) for v in machine.axis_extents)
    assert max_x - min_x <= width_um
    assert max_y - min_y <= height_um


@pytest.mark.parametrize("machine_name", MACHINES)
@pytest.mark.parametrize("label", list(STEP_TYPES))
def test_the_file_checksum_is_the_sum_the_controller_checks(
    context_initializer, bundled, machine_name, label
):
    machine = bundled[machine_name]
    commands = _commands(context_initializer, machine, STEP_TYPES[label])

    assert commands[-1] == b"\xd7"
    checksum = commands[-2]
    assert checksum[:2] == b"\xe5\x05"
    expected = sum(sum(c) for c in commands[:-2]) + 0xD7
    assert decode35(checksum[2:]) == expected


@pytest.mark.parametrize("machine_name", MACHINES)
def test_only_the_engrave_modulates_power_per_sample(
    context_initializer, bundled, machine_name
):
    machine = bundled[machine_name]
    for label, step_type in STEP_TYPES.items():
        commands = _commands(context_initializer, machine, step_type)
        modulations = [c for c in commands if c[:1] == b"\xc7"]
        assert bool(modulations) == (label == "Engrave"), label

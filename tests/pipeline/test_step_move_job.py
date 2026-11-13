"""
A step moved to another layer runs there in the job: on that layer's
shapes, in the layer's order, and no longer on the shapes of the layer
it left. Engrave on one layer and Cut on another, one shape each; the
Cut moved after the Engrave makes a job of both steps on the first
shape only, which still encodes to .rd bytes.
"""

import asyncio
from pathlib import Path

import pytest
from raygeo.geo import Geometry
from raygeo.ops import Ops
from raygeo.ops.types import CommandType

from swiftcut.core.doc import Doc
from swiftcut.core.layer import Layer
from swiftcut.core.source_asset import SourceAsset
from swiftcut.core.source_asset_segment import SourceAssetSegment
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.image import SVG_RENDERER
from swiftcut.machine.driver.ruida.ruida_encoder import build_rd_bytes
from swiftcut.pipeline.artifact import JobArtifact
from swiftcut.pipeline.pipeline import Pipeline

SVG_DATA = b"""
<svg width="50mm" height="30mm" xmlns="http://www.w3.org/2000/svg">
<rect width="50" height="30" fill="#000000" />
</svg>"""


@pytest.fixture(autouse=True)
def _zero_debounce(zero_debounce_delay):
    """Rebuild on the next main-loop turn instead of 200 ms later."""


def _add_workpiece(doc: Doc, layer: Layer, pos) -> WorkPiece:
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
    workpiece.pos = pos
    layer.add_workpiece(workpiece)
    return workpiece


async def _job(pipeline: Pipeline) -> Ops:
    """The job's ops, from the handle and checkout a Start uses."""
    handle = await asyncio.wait_for(
        pipeline.generate_job_artifact_async(), timeout=30
    )
    with pipeline.artifact_store.checkout_handle(handle) as artifact:
        assert isinstance(artifact, JobArtifact)
        return artifact.ops.copy()


def _sections(ops: Ops) -> dict[str, list[tuple[float, float]]]:
    """Each step's cutting points, by the uid its LayerStart carries."""
    starts = ops.indices_of(CommandType.LAYER_START)
    sections = {}
    for start in starts:
        uid = ops.layer_uid(start)
        end = next(
            i
            for i in ops.indices_of(CommandType.LAYER_END)
            if i > start and ops.layer_uid(i) == uid
        )
        sections[uid] = [
            tuple(ops.endpoint(i)[:2])
            for i in range(start, end)
            if ops.is_cutting(i)
        ]
    return sections


def _inside(point, workpiece: WorkPiece) -> bool:
    x, y, w, h = workpiece.bbox
    tol = 0.5
    return (
        x - tol <= point[0] <= x + w + tol
        and y - tol <= point[1] <= y + h + tol
    )


def _layer_start_uids(ops: Ops) -> list[str]:
    return [ops.layer_uid(i) for i in ops.indices_of(CommandType.LAYER_START)]


@pytest.mark.asyncio
async def test_a_moved_cut_runs_on_its_new_layers_shape(
    task_mgr,
    context_initializer,
    test_machine_and_config,
    contour_step_class,
    engrave_step_class,
):
    machine, _config = test_machine_and_config
    machine.driver_name = "RuidaDriver"
    machine.dialect_uid = None
    machine.hydrate()
    doc = Doc()
    first = doc.active_layer
    first.workflow.set_steps([])
    engrave = engrave_step_class.create(context_initializer, name="engrave")
    first.workflow.add_step(engrave)
    engraved = _add_workpiece(doc, first, (10.0, 20.0))
    second = Layer(name="second")
    doc.add_child(second)
    second.workflow.set_steps([])
    cut = contour_step_class.create(context_initializer, name="cut")
    second.workflow.add_step(cut)
    other = _add_workpiece(doc, second, (100.0, 90.0))
    editor = DocEditor(task_mgr, context_initializer, doc=doc)
    try:
        before = await _job(editor.pipeline)
        moved = editor.layer.move_step_to_layer(cut, first, 1)
        after = await _job(editor.pipeline)
        rd = build_rd_bytes(after, machine, doc)
    finally:
        await asyncio.to_thread(task_mgr.wait_until_settled, 5000)
        editor.cleanup()

    # Before the move each step cuts its own layer's shape, which is
    # also what shows the points are in the shapes' frame.
    assert _layer_start_uids(before) == [engrave.uid, cut.uid]
    sections = _sections(before)
    assert sections[engrave.uid]
    assert all(_inside(p, engraved) for p in sections[engrave.uid])
    assert sections[cut.uid]
    assert all(_inside(p, other) for p in sections[cut.uid])

    assert moved is cut
    assert first.workflow.steps == [engrave, cut]
    assert second.workflow.steps == []
    assert _layer_start_uids(after) == [engrave.uid, cut.uid]
    sections = _sections(after)
    for uid in (engrave.uid, cut.uid):
        assert sections[uid]
        assert all(_inside(p, engraved) for p in sections[uid])
        assert not any(_inside(p, other) for p in sections[uid])
    assert rd

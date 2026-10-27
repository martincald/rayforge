"""
A group ties items on different layers together beside the document
tree; the job is built per layer and step from the tree, so it must
not see the group. The .rd bytes of a document with a group across
two layers are those of the same document ungrouped, also after a
save and load.
"""

import asyncio
from pathlib import Path

import pytest
from raygeo.geo import Geometry
from raygeo.ops import Ops
from raygeo.ops.types import CommandCategory

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


def _two_layers(context, contour_cls):
    """A cut outline on one layer, its artwork on another."""
    doc = Doc()
    first = doc.active_layer
    assert first.workflow is not None
    first.workflow.set_steps([])
    first.workflow.add_step(contour_cls.create(context, name="outline"))
    outline = _add_workpiece(doc, first, (10.0, 20.0))
    second = Layer(name="artwork")
    doc.add_child(second)
    assert second.workflow is not None
    second.workflow.add_step(contour_cls.create(context, name="artwork"))
    artwork = _add_workpiece(doc, second, (80.0, 60.0))
    return doc, outline, artwork


async def _job(pipeline: Pipeline) -> Ops:
    """The job's ops, from the handle and checkout a Start uses."""
    handle = await asyncio.wait_for(
        pipeline.generate_job_artifact_async(), timeout=30
    )
    with pipeline.artifact_store.checkout_handle(handle) as artifact:
        assert isinstance(artifact, JobArtifact)
        return artifact.ops.copy()


@pytest.mark.asyncio
async def test_a_group_across_layers_leaves_the_rd_bytes_alone(
    task_mgr,
    context_initializer,
    test_machine_and_config,
    contour_step_class,
):
    machine, _config = test_machine_and_config
    machine.driver_name = "RuidaDriver"
    machine.dialect_uid = None
    machine.hydrate()
    doc, outline, artwork = _two_layers(
        context_initializer, contour_step_class
    )
    editor = DocEditor(task_mgr, context_initializer, doc=doc)
    loaded_pipeline = None
    try:
        ops = await _job(editor.pipeline)
        ungrouped = build_rd_bytes(ops, machine, doc)

        group = editor.group.group_items([outline, artwork])
        assert group is not None
        grouped = build_rd_bytes(await _job(editor.pipeline), machine, doc)

        loaded = Doc.from_dict(doc.to_dict())
        assert [g.member_uids for g in loaded.item_groups] == [
            [outline.uid, artwork.uid]
        ]
        loaded_pipeline = Pipeline(
            loaded, task_mgr, context_initializer.artifact_store, machine
        )
        reloaded = build_rd_bytes(await _job(loaded_pipeline), machine, loaded)
    finally:
        await asyncio.to_thread(task_mgr.wait_until_settled, 5000)
        if loaded_pipeline is not None:
            loaded_pipeline.shutdown()
        editor.cleanup()

    # Both rectangles are cut: a move and four lines each, at least.
    moves = [
        i for i in range(len(ops)) if ops.category(i) == CommandCategory.MOVING
    ]
    assert len(moves) >= 10
    assert grouped == ungrouped
    assert reloaded == ungrouped

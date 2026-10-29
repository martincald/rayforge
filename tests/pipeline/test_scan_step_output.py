"""A Scan step's job is a Cut step's job with the same numbers."""

import copy

from raygeo.geo import Geometry
from raygeo.pipeline.execute import execute_stages

from swiftcut.core.doc import Doc
from swiftcut.core.step_registry import step_registry
from swiftcut.core.workpiece import WorkPiece
from swiftcut.machine.driver.ruida.ruida_encoder import RuidaEncoder
from swiftcut.pipeline.intent_builder import (
    IntentBuilder,
    job_encode_key,
    job_machinexform_key,
)


def _cut_doc(context) -> Doc:
    """A document whose one Cut step cuts a rectangle outline."""
    geo = Geometry()
    geo.move_to(0.0, 0.0)
    geo.line_to(10.0, 0.0)
    geo.line_to(10.0, 10.0)
    geo.line_to(0.0, 10.0)
    geo.close_path()
    wp = WorkPiece(name="rect")
    wp._edited_boundaries = geo
    wp.set_size(50.0, 30.0)
    wp.pos = 20.0, 20.0

    doc = Doc()
    step = step_registry.get("ContourStep").create(context, name="cut")
    step.power = 0.2
    step.cut_speed = 12000
    doc.active_layer.workflow.add_child(step)
    doc.active_layer.add_child(wp)
    return doc


def _as_scan(doc: Doc) -> Doc:
    """The same document, uids and numbers alike, with a Scan step."""
    data = copy.deepcopy(doc.to_dict())
    for layer in data["children"]:
        for child in layer.get("children", []):
            for step in child.get("children", []):
                if step.get("step_type") == "ContourStep":
                    step["step_type"] = "ScanStep"
    return Doc.from_dict(data)


def _job(doc: Doc, machine):
    nodes = IntentBuilder(machine=machine, generation_id=1).build(doc)
    completed = []
    execute_stages(nodes, completed.append)
    by_key = {c.key: c for c in completed}
    ops_result = by_key[job_machinexform_key()]
    encode_result = by_key[job_encode_key()]
    assert ops_result.error is None, ops_result.error
    assert encode_result.error is None, encode_result.error
    ops = getattr(ops_result.output, "ops", ops_result.output)
    return ops, encode_result.output.text


def test_scan_and_cut_with_the_same_numbers_encode_the_same(
    test_machine_and_config,
):
    machine, context = test_machine_and_config
    machine.hydrate()
    cut_doc = _cut_doc(context)
    scan_doc = _as_scan(cut_doc)
    (scan_step,) = scan_doc.active_layer.workflow.steps
    assert type(scan_step).__name__ == "ScanStep"
    assert (scan_step.power, scan_step.cut_speed) == (0.2, 12000)

    cut_ops, cut_text = _job(cut_doc, machine)
    scan_ops, scan_text = _job(scan_doc, machine)

    assert cut_ops.len() > 0
    assert scan_ops.to_dict() == cut_ops.to_dict()
    assert scan_text == cut_text
    cut_rd = RuidaEncoder().encode(cut_ops, machine, cut_doc)
    scan_rd = RuidaEncoder().encode(scan_ops, machine, scan_doc)
    assert scan_rd.driver_data["commands"] == cut_rd.driver_data["commands"]

"""
A compound SVG path cut by a default Cut step: the move from one
subpath to the next is a travel, never a cut (a stray line).
"""

from pathlib import Path

import pytest
from raygeo.pipeline.execute import execute_stages

from swiftcut.image.svg.importer import SvgImporter
from swiftcut.pipeline.intent_builder import (
    IntentBuilder,
    job_key,
    step_key,
    workpiece_key,
)
from tests.pipeline.test_intent_builder import _make_doc


def _workpiece(path_data: str):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
        f'height="100mm" viewBox="0 0 100 100"><path d="{path_data}" '
        'fill="none" stroke="#000"/></svg>'
    ).encode()
    result = SvgImporter(svg, Path("compound.svg")).get_doc_items()
    assert result is not None and result.payload is not None
    (wp,) = result.payload.items
    return wp


def _cuts(ops) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Every cutting move as (from, to)."""
    cuts = []
    last = None
    for i in range(ops.len()):
        if not (ops.is_cutting(i) or ops.is_travel(i)):
            continue
        end = ops.endpoint(i)[:2]
        if ops.is_cutting(i):
            assert last is not None
            cuts.append((last, end))
        last = end
    return cuts


@pytest.mark.parametrize(
    "path_data, length, gap",
    [
        # Two closed squares, 10 apart.
        ("M10 10 H20 V20 H10 Z M30 10 H40 V20 H30 Z", 80.0, (20, 30)),
        # The same with relative moves after each close.
        ("m10 10 h10 v10 h-10 z m20 0 h10 v10 h-10 z", 80.0, (20, 30)),
        # Two squares 0.05 mm apart.
        ("M10 10 H20 V20 H10 Z M20.05 10 H30 V20 H20.05 Z", 79.9, (20, 20.05)),
        # A move after an open subpath.
        ("M10 10 H20 M30 10 H40", 20.0, (20, 30)),
    ],
    ids=["closed", "relative", "nearly-touching", "after-open"],
)
def test_the_move_between_subpaths_is_a_travel(
    contour_step_class, test_machine_and_config, path_data, length, gap
):
    """
    The cut length is the subpaths' own, and no cut crosses the gap
    between them, in the workpiece's ops, the step's and the job's.
    """
    machine, context = test_machine_and_config
    step = contour_step_class.create(context, name="cut")
    wp = _workpiece(path_data)
    assert len(wp.boundaries.split_into_contours()) == 2
    doc = _make_doc(step, wp)

    nodes = IntentBuilder(machine=machine, generation_id=1).build(doc)
    completed = {}
    execute_stages(nodes, lambda n: completed.__setitem__(n.key, n))

    wpk = workpiece_key(wp.uid, step.uid)
    for key in (wpk, step_key(step.uid), job_key()):
        assert completed[key].error is None, completed[key].error
        ops = completed[key].output.ops
        assert ops.cut_distance() == pytest.approx(length, abs=1e-3), key
    # The workpiece's own ops are in its own frame: the drawing's left
    # edge (x = 10 in the file) is their smallest x.
    cuts = _cuts(completed[wpk].output.ops)
    shift = min(point[0] for cut in cuts for point in cut) - 10
    left, right = gap[0] + shift, gap[1] + shift
    for start, end in cuts:
        xs = sorted((start[0], end[0]))
        assert not (xs[0] < right - 1e-3 and xs[1] > left + 1e-3), (
            start,
            end,
        )

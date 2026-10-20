"""Generate the two benchmark documents under tests/perf/.

``forty.ryp``: the 40 pieces of the Auto Layout benchmark
(tests/doceditor/layout_bench.FORTY), on a grid on the ilab-614 bed
(1400 x 900 mm), under one contour cut step. ``two_layer.ryp``: a
typical engrave+cut job, raster.png engraved on one layer at 150 x 100
mm and small.svg cut on a second layer.

Both are written by the app's one project writer
(file_cmd.write_project(project_json(doc))), so they open with
File > Open like any project. They are committed; this exists to
reproduce them. Like the other perf files it is not named test_*.py,
so it stays out of the suite, and runs as::

    python -m pytest tests/perf/make_docs.py -q -s

Regenerating changes uids (and so the bytes), never the geometry; do not
regenerate midway through a before/after comparison.
"""

import json
import zipfile
from pathlib import Path

import pytest

from swiftcut.core.doc import Doc
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.file_cmd import project_json, write_project
from swiftcut.image import import_file
from tests.doceditor import layout_bench as bench

HERE = Path(__file__).parent

# The ilab-614 bed, as tests/perf/perf_auto_layout.py uses it.
BED_MM = (1400.0, 900.0)
# forty.ryp's grid: 8 x 5 cells, each wider than the largest piece.
COLUMNS = 8
PITCH_MM = 130.0
ORIGIN_MM = (100.0, 100.0)
# Where two_layer.ryp's pieces go, and the engraving's size.
ENGRAVE_POS_MM = (100.0, 100.0)
ENGRAVE_SIZE_MM = (150.0, 100.0)
CUT_POS_MM = (300.0, 100.0)


def _workpieces(path, spec=None):
    """One imported file: its payload, and its workpieces."""
    payload = import_file(path, vectorization_spec=spec)
    assert payload is not None and payload.items, f"{path} did not import"
    pieces = []
    for item in payload.items:
        if isinstance(item, WorkPiece):
            pieces.append(item)
        else:
            pieces.extend(
                c
                for c in getattr(item, "children", [])
                if isinstance(c, WorkPiece)
            )
    return payload, pieces


def _bed(test_machine_and_config):
    machine, _config = test_machine_and_config
    machine.set_axis_extents(*BED_MM)
    return machine


@pytest.mark.asyncio
async def test_forty(
    tmp_path, context_initializer, test_machine_and_config, contour_step_class
):
    _bed(test_machine_and_config)
    doc = Doc()
    layer = doc.active_layer
    # A new document has three layers; this one keeps the first.
    for extra in doc.layers[1:]:
        doc.remove_layer(extra)
    assert layer.workflow is not None
    layer.workflow.set_steps([])
    for n, piece in enumerate(bench.FORTY):
        svg = bench.write_svg(tmp_path / f"{n:02d}-{piece.name}.svg", piece)
        payload, (workpiece,) = _workpieces(svg, PassthroughSpec())
        doc.add_asset(payload.source)
        layer.add_workpiece(workpiece)
        row, col = divmod(n, COLUMNS)
        workpiece.pos = (
            ORIGIN_MM[0] + col * PITCH_MM,
            ORIGIN_MM[1] + row * PITCH_MM,
        )
    layer.workflow.add_step(contour_step_class.create(context_initializer))
    _write(doc, HERE / "forty.ryp", pieces=40, layers=1)


@pytest.mark.asyncio
async def test_two_layer(
    context_initializer,
    test_machine_and_config,
    contour_step_class,
    engrave_step_class,
):
    _bed(test_machine_and_config)
    doc = Doc()
    # A new document has three layers; this one keeps two.
    engrave, cut, extra = doc.layers
    doc.remove_layer(extra)
    engrave.name = "Engrave"
    assert engrave.workflow is not None
    engrave.workflow.set_steps([])
    payload, (image,) = _workpieces(HERE / "raster.png")
    doc.add_asset(payload.source)
    engrave.add_workpiece(image)
    image.set_size(*ENGRAVE_SIZE_MM)
    image.pos = ENGRAVE_POS_MM
    engrave.workflow.add_step(engrave_step_class.create(context_initializer))

    cut.name = "Cut"
    assert cut.workflow is not None
    cut.workflow.set_steps([])
    payload, pieces = _workpieces(HERE / "small.svg")
    doc.add_asset(payload.source)
    for workpiece in pieces:
        cut.add_workpiece(workpiece)
        workpiece.pos = CUT_POS_MM
    cut.workflow.add_step(contour_step_class.create(context_initializer))
    _write(doc, HERE / "two_layer.ryp", pieces=1 + len(pieces), layers=2)


def _write(doc: Doc, path: Path, pieces: int, layers: int):
    """Writes the project, then proves the file reads back whole."""
    write_project(path, project_json(doc))
    with zipfile.ZipFile(path) as zf:
        back = Doc.from_dict(json.loads(zf.read("project.json")))
    assert len(back.all_workpieces) == pieces
    assert len(back.layers) == layers
    print(f"\n{path.name}: {pieces} workpieces on {layers} layer(s)")

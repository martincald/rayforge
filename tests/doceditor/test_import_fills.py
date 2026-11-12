"""
Each SVG path's fill comes through the import: through FileCmd's real
import path, in every grouping, each workpiece knows how its source
paths are filled (path_fills), and keeps it on save and load.
"""

from pathlib import Path

import pytest

from swiftcut.core.doc import Doc
from swiftcut.core.path_fills import paths_of
from swiftcut.core.vectorization_spec import PassthroughSpec, TraceSpec
from swiftcut.doceditor.import_materializer import (
    ImportGrouping,
    ImportOptions,
)
from swiftcut.image.svg.importer import SvgImporter
from tests.doceditor.test_import_materializer import _import

TESTS_DIR = Path(__file__).parent.parent
FIXTURES = TESTS_DIR / "fixtures" / "import"

# Real files, each with the spec the dialog gives it.
REAL_FILES = {
    "illustrator": (
        FIXTURES / "illustrator_two_layers.svg",
        PassthroughSpec(active_layer_ids=["Cut", "Engrave"], ppi=72),
    ),
    "shweshwe": (FIXTURES / "shweshwe.svg", PassthroughSpec()),
    "inkscape": (TESTS_DIR / "image" / "svg" / "twolayer.svg", None),
}

# A group of a filled square and an unfilled one, and an even-odd
# ring (a square with a square hole) on its own.
DRAWING = """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" \
height="100mm" viewBox="0 0 100 100">
  <g id="logo">
    <rect id="solid" x="10" y="10" width="20" height="20" fill="#ccc"/>
    <rect id="outline" x="40" y="10" width="20" height="20" fill="none" \
stroke="#000"/>
  </g>
  <path id="ring" fill-rule="evenodd" \
d="M10 50 H30 V70 H10 Z M15 55 H25 V65 H15 Z"/>
</svg>
"""

SOLID = [(1, "nonzero")]
OUTLINE = [(1, None)]
RING = [(2, "evenodd")]
# Individual cuts the ring into its outline and its hole, each with
# the ring's fill.
RING_PART = [(1, "evenodd")]

EXPECTED = {
    None: [[*SOLID, *OUTLINE, *RING]],
    ImportGrouping.SINGLE: [[*SOLID, *OUTLINE, *RING]],
    ImportGrouping.INDIVIDUAL: [SOLID, OUTLINE, RING_PART, RING_PART],
    ImportGrouping.PIECES: [SOLID, OUTLINE, RING],
    ImportGrouping.BY_SOURCE: [[*SOLID, *OUTLINE], RING],
}


@pytest.fixture
def bed(test_machine_and_config):
    """The ilab-614 bed: 1400 x 900 mm."""
    machine, _config = test_machine_and_config
    machine.set_axis_extents(1400, 900)
    return machine


@pytest.fixture
def drawing(tmp_path):
    path = tmp_path / "drawing.svg"
    path.write_text(DRAWING)
    return path


def _sorted(fills):
    return sorted(fills, key=repr)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "grouping",
    list(EXPECTED),
    ids=lambda g: "legacy" if g is None else g.value,
)
async def test_every_grouping_keeps_each_paths_fill(
    doc_editor, task_mgr, bed, drawing, grouping
):
    options = None if grouping is None else ImportOptions(grouping=grouping)

    added = await _import(
        doc_editor, task_mgr, drawing, PassthroughSpec(), options
    )

    fills = [wp.source_segment.path_fills for wp in added]
    assert _sorted(fills) == _sorted(EXPECTED[grouping])
    for wp in added:
        path_fills = wp.source_segment.path_fills
        assert paths_of(wp.boundaries, path_fills) is not None, wp.name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "grouping", list(ImportGrouping), ids=lambda g: g.value
)
@pytest.mark.parametrize("name", list(REAL_FILES))
async def test_real_files_know_every_vector_workpieces_fills(
    doc_editor, task_mgr, bed, name, grouping
):
    """Every contour the importer reads is one of the file's paths."""
    path, spec = REAL_FILES[name]

    added = await _import(
        doc_editor, task_mgr, path, spec, ImportOptions(grouping=grouping)
    )

    vector = [
        wp
        for wp in added
        if not isinstance(wp.source_segment.vectorization_spec, TraceSpec)
    ]
    assert vector
    for wp in vector:
        path_fills = wp.source_segment.path_fills
        assert paths_of(wp.boundaries, path_fills) is not None, wp.name


@pytest.mark.asyncio
async def test_a_save_and_load_keeps_them(doc_editor, task_mgr, bed, drawing):
    options = ImportOptions(grouping=ImportGrouping.PIECES)
    added = await _import(
        doc_editor, task_mgr, drawing, PassthroughSpec(), options
    )
    saved = {wp.uid: wp.source_segment.path_fills for wp in added}

    loaded = Doc.from_dict(doc_editor.doc.to_dict())

    assert {
        wp.uid: wp.source_segment.path_fills
        for wp in loaded.all_workpieces
        if wp.uid in saved
    } == saved


@pytest.mark.asyncio
async def test_undo_and_redo_keep_them(doc_editor, task_mgr, bed, drawing):
    options = ImportOptions(grouping=ImportGrouping.PIECES)
    added = await _import(
        doc_editor, task_mgr, drawing, PassthroughSpec(), options
    )
    saved = {wp.uid: wp.source_segment.path_fills for wp in added}

    doc_editor.history_manager.undo()
    assert not saved.keys() & {wp.uid for wp in doc_editor.doc.all_workpieces}
    doc_editor.history_manager.redo()

    assert {
        wp.uid: wp.source_segment.path_fills
        for wp in doc_editor.doc.all_workpieces
        if wp.uid in saved
    } == saved


def test_a_reimport_works_them_out_again(drawing):
    first = SvgImporter(drawing.read_bytes(), drawing).get_doc_items()
    assert first is not None and first.payload is not None

    again = SvgImporter(
        drawing.read_bytes(), drawing
    ).get_doc_items_for_reimport(first.payload.source, PassthroughSpec())

    assert again is not None and again.payload is not None
    assert [
        wp.source_segment.path_fills for wp in again.payload.items
    ] == EXPECTED[ImportGrouping.SINGLE]


@pytest.mark.asyncio
async def test_a_dxf_has_no_fill_data(doc_editor, task_mgr, bed):
    """A DXF does not say what is filled: it engraves as Both."""
    added = await _import(doc_editor, task_mgr, FIXTURES / "cad_plate.dxf")

    assert added
    assert {wp.source_segment.path_fills for wp in added} == {None}

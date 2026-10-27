"""
Import as PIECES or BY_SOURCE with interior detail on its own layer:
each piece's outline and interior come in as one group across their
two layers, through FileCmd's real import path, on the import
fixtures (tests/fixtures/import).
"""

import pytest

from swiftcut.core.vectorization_spec import LayerImportMode, PassthroughSpec
from swiftcut.doceditor import file_cmd
from swiftcut.doceditor.import_materializer import (
    ImportGrouping,
    ImportOptions,
)
from tests.doceditor.test_import_materializer import (
    ILLUSTRATOR,
    PLATES,
    TRACED,
    _illustrator_spec,
    _import,
)


@pytest.fixture
def bed(test_machine_and_config):
    """The ilab-614 bed: 1400 x 900 mm."""
    machine, _config = test_machine_and_config
    machine.set_axis_extents(1400, 900)
    return machine


@pytest.fixture
def prepared(monkeypatch):
    """The PreparedImport of each import, as materialize gets it."""
    seen = []
    materialize = file_cmd.materialize

    def spy(pairs, source, prepared, doc):
        seen.append(prepared)
        return materialize(pairs, source, prepared, doc)

    monkeypatch.setattr(file_cmd, "materialize", spy)
    return seen


def _both_sides(prepared) -> int:
    """The planned pieces that have a boundary and an interior."""
    return sum(
        1
        for plan in prepared.plans.values()
        for piece in plan
        if not piece.boundary.is_empty() and not piece.interior.is_empty()
    )


def _sides(doc, group, interior_layer):
    """
    A group's members as (outline, interior), checked: two items, the
    outline off the interior layer, the interior on it.
    """
    members = doc.item_groups.members(group)
    assert [m.uid for m in members] == group.member_uids
    outline, inside = members
    assert outline.layer is not interior_layer
    assert inside.layer is interior_layer
    return outline, inside


def _flat_illustrator_spec():
    """The Illustrator file's layers read into one workpiece."""
    return _illustrator_spec(layer_import_mode=LayerImportMode.FLATTEN)


INTERIOR = ImportOptions(
    grouping=ImportGrouping.PIECES, interior_on_own_layer=True
)


@pytest.mark.asyncio
async def test_traced_outline_and_artwork_are_one_group(
    doc_editor, task_mgr, bed, prepared
):
    """
    The traced DXF is one piece: its red outline on the current layer
    and its 120 dots on "<file> engrave", one group of the two, named
    after the outline.
    """
    doc = doc_editor.doc
    cut = doc.active_layer

    outline, dots = await _import(doc_editor, task_mgr, TRACED, None, INTERIOR)

    (made,) = prepared
    (group,) = doc.item_groups
    assert _both_sides(made) == 1
    assert made.groups == [group]
    assert group.member_uids == [outline.uid, dots.uid]
    assert group.name == outline.name
    assert _sides(doc, group, made.interior_layer) == (outline, dots)
    assert outline.layer is cut
    assert dots.layer.name == "illustrator_traced engrave"
    assert outline.layer is not dots.layer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path, spec, grouping, count",
    [
        # Cut and Engrave are workpieces of their own: the outline is
        # planned alone, the artwork's pieces have nothing inside.
        (ILLUSTRATOR, _illustrator_spec, ImportGrouping.PIECES, 0),
        (ILLUSTRATOR, _illustrator_spec, ImportGrouping.BY_SOURCE, 0),
        # The plates' holes are boundary (cut), not interior.
        (PLATES, PassthroughSpec, ImportGrouping.PIECES, 0),
        # One workpiece: the outline with the logo and text inside.
        (ILLUSTRATOR, _flat_illustrator_spec, ImportGrouping.PIECES, 1),
    ],
)
async def test_a_group_for_each_piece_with_both_sides(
    doc_editor, task_mgr, bed, prepared, path, spec, grouping, count
):
    """
    One group per planned piece that has a boundary and an interior,
    its outline and its interior on two layers.
    """
    doc = doc_editor.doc
    options = ImportOptions(grouping=grouping, interior_on_own_layer=True)

    await _import(doc_editor, task_mgr, path, spec(), options)

    (made,) = prepared
    groups = list(doc.item_groups)
    assert _both_sides(made) == count
    assert len(groups) == count
    assert made.groups == groups
    for group in groups:
        _sides(doc, group, made.interior_layer)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path, spec, options",
    [
        (TRACED, None, ImportOptions(grouping=ImportGrouping.PIECES)),
        (TRACED, None, ImportOptions(grouping=ImportGrouping.BY_SOURCE)),
        (
            ILLUSTRATOR,
            _flat_illustrator_spec,
            ImportOptions(grouping=ImportGrouping.PIECES),
        ),
        (
            TRACED,
            None,
            ImportOptions(
                grouping=ImportGrouping.SINGLE, interior_on_own_layer=True
            ),
        ),
        (
            TRACED,
            None,
            ImportOptions(
                grouping=ImportGrouping.INDIVIDUAL, interior_on_own_layer=True
            ),
        ),
    ],
)
async def test_no_groups_without_interior_layer_or_pieces(
    doc_editor, task_mgr, bed, prepared, path, spec, options
):
    """
    Interior detail kept in its piece, or a single or individual
    shapes import: no group.
    """
    added = await _import(doc_editor, task_mgr, path, spec and spec(), options)

    (made,) = prepared
    assert added
    assert made.groups == []
    assert len(doc_editor.doc.item_groups) == 0


@pytest.mark.asyncio
async def test_undo_removes_the_groups_with_the_pieces_redo_restores_them(
    doc_editor, task_mgr, bed, prepared
):
    doc = doc_editor.doc
    history = doc_editor.history_manager
    entries = len(history.undo_stack)

    outline, dots = await _import(doc_editor, task_mgr, TRACED, None, INTERIOR)

    (made,) = prepared
    groups = list(doc.item_groups)
    saved = [(g.uid, g.name, list(g.member_uids)) for g in groups]
    assert len(groups) == 1
    assert len(history.undo_stack) == entries + 1

    history.undo()

    assert len(doc.item_groups) == 0
    assert doc.all_workpieces == []
    assert made.interior_layer not in doc.layers

    history.redo()

    assert list(doc.item_groups) == groups
    assert [(g.uid, g.name, g.member_uids) for g in doc.item_groups] == saved
    assert _sides(doc, groups[0], made.interior_layer) == (outline, dots)

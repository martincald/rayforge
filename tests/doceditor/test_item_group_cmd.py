import pytest
from raygeo.geo import Geometry

from swiftcut.core.group import Group
from swiftcut.core.item_group import ItemGroup
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor


@pytest.fixture
def doc_editor(task_mgr, context_initializer):
    editor = DocEditor(task_manager=task_mgr, context=context_initializer)
    yield editor
    editor.cleanup()


def _pieces(doc_editor: DocEditor, *layer_indices: int) -> list[WorkPiece]:
    """One piece on each of the given layers."""
    pieces = []
    for i in layer_indices:
        wp = WorkPiece(name=f"on layer {i}")
        doc_editor.doc.layers[i].add_workpiece(wp)
        pieces.append(wp)
    return pieces


@pytest.mark.asyncio
async def test_group_items_across_layers_in_one_undo_step(
    doc_editor: DocEditor,
):
    outline, artwork = _pieces(doc_editor, 0, 1)
    groups = doc_editor.doc.item_groups
    history = doc_editor.history_manager
    entries = len(history.undo_stack)

    group = doc_editor.group.group_items([outline, artwork])

    assert group is not None
    assert list(groups) == [group]
    assert group.name == "Group 1"
    assert groups.items_of(group) == [outline, artwork]
    # No geometry merge: each piece stays where and as it was.
    assert outline.parent is doc_editor.doc.layers[0]
    assert artwork.parent is doc_editor.doc.layers[1]
    assert len(history.undo_stack) == entries + 1

    history.undo()
    assert list(groups) == []
    history.redo()
    assert list(groups) == [group]


@pytest.mark.asyncio
async def test_grouping_one_unit_does_nothing(doc_editor: DocEditor):
    outline, artwork = _pieces(doc_editor, 0, 1)
    history = doc_editor.history_manager
    group = doc_editor.group.group_items([outline, artwork])
    entries = len(history.undo_stack)

    # Both pieces are the one group: nothing new to group.
    assert doc_editor.group.group_items([outline, artwork]) is None
    assert doc_editor.group.group_items([outline]) is None
    assert list(doc_editor.doc.item_groups) == [group]
    assert len(history.undo_stack) == entries


@pytest.mark.asyncio
async def test_grouping_a_group_with_an_item_nests_it(doc_editor: DocEditor):
    outline, artwork, label = _pieces(doc_editor, 0, 1, 2)
    groups = doc_editor.doc.item_groups
    inner = doc_editor.group.group_items([outline, artwork])
    assert inner is not None

    outer = doc_editor.group.group_items([artwork, label])

    assert outer is not None
    assert groups.members(outer) == [inner, label]
    assert groups.parent_of(inner.uid) is outer
    assert groups.top_of(outline.uid) is outer


@pytest.mark.asyncio
async def test_ungroup_dissolves_one_level(doc_editor: DocEditor):
    outline, artwork, label = _pieces(doc_editor, 0, 1, 2)
    groups = doc_editor.doc.item_groups
    inner = doc_editor.group.group_items([outline, artwork])
    outer = doc_editor.group.group_items([outline, label])
    assert inner is not None and outer is not None
    history = doc_editor.history_manager
    entries = len(history.undo_stack)

    freed = doc_editor.group.ungroup_groups([outer])

    assert freed == [outline, artwork, label]
    assert list(groups) == [inner]
    assert groups.top_of(outline.uid) is inner
    assert groups.parent_of(label.uid) is None
    assert len(history.undo_stack) == entries + 1

    history.undo()
    assert list(groups) == [inner, outer]
    assert groups.top_of(outline.uid) is outer


@pytest.mark.asyncio
async def test_ungroup_of_a_nested_group_hands_its_members_up(
    doc_editor: DocEditor,
):
    outline, artwork, label = _pieces(doc_editor, 0, 1, 2)
    groups = doc_editor.doc.item_groups
    inner = doc_editor.group.group_items([outline, artwork])
    outer = doc_editor.group.group_items([outline, label])
    assert inner is not None and outer is not None

    doc_editor.group.ungroup_groups([inner])

    assert list(groups) == [outer]
    assert outer.member_uids == [outline.uid, artwork.uid, label.uid]

    doc_editor.history_manager.undo()
    assert list(groups) == [inner, outer]
    assert outer.member_uids == [inner.uid, label.uid]
    assert groups.parent_of(outline.uid) is inner


@pytest.mark.asyncio
async def test_rename_group_is_undoable(doc_editor: DocEditor):
    outline, artwork = _pieces(doc_editor, 0, 1)
    group = doc_editor.group.group_items([outline, artwork], name="Logo")
    assert isinstance(group, ItemGroup)

    doc_editor.group.rename_group(group, "Sign")
    assert group.name == "Sign"

    doc_editor.history_manager.undo()
    assert group.name == "Logo"


def _two_paths() -> Geometry:
    """A square and a line beside it: a shape Ungroup would split."""
    geo = Geometry()
    geo.move_to(0.0, 0.0)
    geo.line_to(0.5, 0.0)
    geo.line_to(0.5, 1.0)
    geo.line_to(0.0, 1.0)
    geo.close_path()
    geo.move_to(0.8, 0.0)
    geo.line_to(1.0, 1.0)
    return geo


def _container(layer, items) -> Group:
    """A Group container of the items, as Combine makes it."""
    result = Group.create_from_items(items, layer)
    layer.remove_children(items)
    layer.add_child(result.new_group)
    result.new_group.add_children(items)
    for item in items:
        item.matrix = result.child_matrices[item.uid]
    return result.new_group


@pytest.mark.asyncio
async def test_ungroup_items_dissolves_the_groups_and_nothing_else(
    doc_editor: DocEditor,
):
    first, second = doc_editor.doc.layers[:2]
    a, b = _pieces(doc_editor, 0, 0)
    container = _container(first, [a, b])
    shape = WorkPiece(name="two paths")
    shape._edited_boundaries = _two_paths()
    second.add_workpiece(shape)
    groups = doc_editor.doc.item_groups
    group = doc_editor.group.group_items([container, shape])
    assert group is not None
    history = doc_editor.history_manager
    entries = len(history.undo_stack)

    freed = doc_editor.group.ungroup_items([container, shape])

    assert freed == [container, shape]
    assert list(groups) == []
    # Not split, not dissolved: the group is gone, nothing else.
    assert first.get_content_items() == [container]
    assert set(container.children) == {a, b}
    assert second.get_content_items() == [shape]
    assert len(history.undo_stack) == entries + 1

    history.undo()
    assert list(groups) == [group]


@pytest.mark.asyncio
async def test_ungroup_items_of_a_nested_group_dissolves_the_outer_one(
    doc_editor: DocEditor,
):
    outline, artwork, label = _pieces(doc_editor, 0, 1, 2)
    groups = doc_editor.doc.item_groups
    inner = doc_editor.group.group_items([outline, artwork])
    outer = doc_editor.group.group_items([outline, label])
    assert inner is not None and outer is not None

    doc_editor.group.ungroup_items([artwork])

    assert list(groups) == [inner]


@pytest.mark.asyncio
async def test_ungroup_items_outside_a_group_splits_as_before(
    doc_editor: DocEditor,
):
    outline, artwork = _pieces(doc_editor, 0, 1)
    group = doc_editor.group.group_items([outline, artwork])
    layer = doc_editor.doc.layers[0]
    shape = WorkPiece(name="two paths")
    shape._edited_boundaries = _two_paths()
    shape.set_size(20, 20)
    layer.add_workpiece(shape)

    pieces = doc_editor.group.ungroup_items([shape])

    assert len(pieces) == 2
    assert shape not in layer.children
    assert list(doc_editor.doc.item_groups) == [group]

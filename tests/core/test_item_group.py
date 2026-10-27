import json

import pytest

from swiftcut.core.doc import Doc
from swiftcut.core.item_group import (
    AddItemGroupCommand,
    ItemGroup,
    RemoveItemGroupCommand,
    UpdateItemGroupCommand,
)
from swiftcut.core.workpiece import WorkPiece


@pytest.fixture
def doc():
    """A document with a piece on each of its first two layers."""
    doc = Doc()
    doc.layers[0].add_workpiece(WorkPiece(name="outline"))
    doc.layers[1].add_workpiece(WorkPiece(name="artwork"))
    return doc


def pieces(doc):
    return doc.layers[0].workpieces[0], doc.layers[1].workpieces[0]


def test_a_group_holds_items_on_different_layers(doc):
    outline, artwork = pieces(doc)
    group = ItemGroup([outline.uid, artwork.uid])
    doc.item_groups.add(group)

    assert doc.item_groups.items_of(group) == [outline, artwork]
    assert doc.item_groups.parent_of(outline.uid) is group
    assert doc.item_groups.parent_of(artwork.uid) is group
    # The tree is untouched: each piece stays on its layer.
    assert outline.parent is doc.layers[0]
    assert artwork.parent is doc.layers[1]


def test_an_item_is_in_at_most_one_group(doc):
    outline, artwork = pieces(doc)
    doc.item_groups.add(ItemGroup([outline.uid, artwork.uid]))

    with pytest.raises(ValueError):
        doc.item_groups.add(ItemGroup([outline.uid]))
    assert len(doc.item_groups) == 1


def test_nested_groups(doc):
    outline, artwork = pieces(doc)
    loose = WorkPiece(name="loose")
    doc.layers[2].add_workpiece(loose)
    inner = ItemGroup([outline.uid, artwork.uid], name="inner")
    doc.item_groups.add(inner)
    outer = ItemGroup([inner.uid, loose.uid], name="outer")
    doc.item_groups.add(outer)

    assert doc.item_groups.parent_of(outline.uid) is inner
    assert doc.item_groups.parent_of(inner.uid) is outer
    assert doc.item_groups.top_of(outline.uid) is outer
    assert doc.item_groups.top_of(loose.uid) is outer
    assert doc.item_groups.members(outer) == [inner, loose]
    assert doc.item_groups.items_of(outer) == [outline, artwork, loose]
    assert doc.item_groups.units([artwork, loose]) == [outer]
    assert doc.item_groups.closure([loose]) == [loose, outline, artwork]


def test_units_and_closure_of_ungrouped_items(doc):
    outline, artwork = pieces(doc)
    doc.item_groups.add(ItemGroup([outline.uid, artwork.uid]))
    loose = WorkPiece(name="loose")
    doc.layers[0].add_workpiece(loose)

    (group,) = doc.item_groups
    assert doc.item_groups.units([loose, outline]) == [loose, group]
    assert doc.item_groups.unit_of(loose) is loose
    assert doc.item_groups.closure([artwork]) == [artwork, outline]
    assert doc.item_groups.closure([loose]) == [loose]


def test_a_member_moved_to_another_layer_stays_in_its_group(doc):
    outline, artwork = pieces(doc)
    group = ItemGroup([outline.uid, artwork.uid])
    doc.item_groups.add(group)

    doc.layers[1].remove_workpiece(artwork)
    doc.layers[2].add_workpiece(artwork)

    assert doc.item_groups.items_of(group) == [outline, artwork]


def test_a_deleted_member_drops_out_until_it_comes_back(doc):
    outline, artwork = pieces(doc)
    group = ItemGroup([outline.uid, artwork.uid])
    doc.item_groups.add(group)

    doc.layers[1].remove_workpiece(artwork)
    assert doc.item_groups.items_of(group) == [outline]

    doc.layers[1].add_workpiece(artwork)
    assert doc.item_groups.items_of(group) == [outline, artwork]


def test_changed_is_sent_after_every_change(doc):
    outline, artwork = pieces(doc)
    sent = []

    def on_changed(sender):
        sent.append(sender)

    doc.item_groups.changed.connect(on_changed)
    group = ItemGroup([outline.uid, artwork.uid])

    doc.item_groups.add(group)
    doc.item_groups.update(group, name="Logo")
    doc.item_groups.remove(group)

    assert sent == [doc.item_groups] * 3


def test_a_document_never_grouped_saves_as_before(doc):
    assert "item_groups" not in doc.to_dict()


def test_groups_round_trip_through_a_saved_document(doc):
    outline, artwork = pieces(doc)
    loose = WorkPiece(name="loose")
    doc.layers[2].add_workpiece(loose)
    inner = ItemGroup([outline.uid, artwork.uid], name="Logo")
    doc.item_groups.add(inner)
    doc.item_groups.add(ItemGroup([inner.uid, loose.uid], name="Sign"))

    data = json.loads(json.dumps(doc.to_dict()))
    loaded = Doc.from_dict(data)

    names = [g.name for g in loaded.item_groups]
    assert names == ["Logo", "Sign"]
    logo, sign = loaded.item_groups
    assert [i.name for i in loaded.item_groups.items_of(logo)] == [
        "outline",
        "artwork",
    ]
    assert loaded.item_groups.top_of(outline.uid) is sign
    assert loaded.item_groups.items_of(sign)[-1].uid == loose.uid
    assert data["item_groups"] == [g.to_dict() for g in doc.item_groups]


def test_members_that_no_longer_exist_are_not_saved(doc):
    outline, artwork = pieces(doc)
    kept = ItemGroup([outline.uid, artwork.uid])
    gone = WorkPiece(name="gone")
    doc.layers[2].add_workpiece(gone)
    emptied = ItemGroup([gone.uid])
    doc.item_groups.add(kept)
    doc.item_groups.add(emptied)

    doc.layers[1].remove_workpiece(artwork)
    doc.layers[2].remove_workpiece(gone)

    saved = doc.to_dict()["item_groups"]
    assert saved == [
        {"uid": kept.uid, "name": kept.name, "members": [outline.uid]}
    ]
    # Saving changes nothing in the document itself.
    assert kept.member_uids == [outline.uid, artwork.uid]
    assert len(doc.item_groups) == 2


def test_group_commands_undo_and_redo_in_one_step(doc):
    outline, artwork = pieces(doc)
    history = doc.history_manager
    group = ItemGroup([outline.uid, artwork.uid])

    with history.transaction("Group") as t:
        t.execute(AddItemGroupCommand(doc.item_groups, group))
    assert list(doc.item_groups) == [group]

    with history.transaction("Rename") as t:
        t.execute(
            UpdateItemGroupCommand(doc.item_groups, group, new_name="Logo")
        )
    assert group.name == "Logo"

    with history.transaction("Ungroup") as t:
        t.execute(RemoveItemGroupCommand(doc.item_groups, group))
    assert list(doc.item_groups) == []
    assert doc.item_groups.parent_of(outline.uid) is None

    history.undo()
    assert list(doc.item_groups) == [group]
    assert doc.item_groups.parent_of(outline.uid) is group
    history.undo()
    assert group.name == "Group"
    history.undo()
    assert list(doc.item_groups) == []
    history.redo()
    assert list(doc.item_groups) == [group]


def test_update_members_undoes_to_the_old_members(doc):
    outline, artwork = pieces(doc)
    group = ItemGroup([outline.uid])
    doc.item_groups.add(group)

    cmd = UpdateItemGroupCommand(
        doc.item_groups, group, member_uids=[outline.uid, artwork.uid]
    )
    cmd.execute()
    assert doc.item_groups.parent_of(artwork.uid) is group
    cmd.undo()
    assert group.member_uids == [outline.uid]
    assert doc.item_groups.parent_of(artwork.uid) is None

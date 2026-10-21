"""Doc.batch: what a command changes is announced once, after it.

Inside a batch, and so inside every history transaction, command,
undo and redo, each item's descendant_added, descendant_removed and
descendant_transform_changed fire (and bubble) once when the outermost
batch ends, with the latest origin and every origin in `origins`.
"""

import pytest
from raygeo.geo import Matrix

from swiftcut.core.doc import Doc
from swiftcut.core.undo import ListItemCommand
from swiftcut.core.workpiece import WorkPiece

COALESCED = (
    "descendant_added",
    "descendant_removed",
    "descendant_transform_changed",
)


@pytest.fixture
def doc():
    return Doc()


@pytest.fixture
def heard(doc):
    """What the document's and its active layer's signals sent."""
    sent = []
    for item in (doc, doc.active_layer):
        for name in (*COALESCED, "descendant_updated"):

            def record(sender, _item=item, _name=name, **kwargs):
                sent.append((_item, _name, kwargs))

            getattr(item, name).connect(record, weak=False)
    return sent


def _import(doc, pieces):
    with doc.history_manager.transaction("Import") as t:
        for wp in pieces:
            t.execute(
                ListItemCommand(
                    owner_obj=doc.active_layer,
                    item=wp,
                    undo_command="remove_child",
                    redo_command="add_child",
                )
            )


def _names(heard, item):
    return [name for who, name, _kwargs in heard if who is item]


def test_an_import_of_many_is_added_once(doc, heard):
    pieces = [WorkPiece(name=f"wp{n}") for n in range(300)]

    _import(doc, pieces)

    assert _names(heard, doc) == ["descendant_added"]
    assert _names(heard, doc.active_layer) == ["descendant_added"]
    (_, _, kwargs) = heard[-1]
    assert kwargs["origins"] == tuple(pieces)
    assert kwargs["origin"] is pieces[-1]
    assert doc.active_layer.children[-300:] == pieces


def test_undo_and_redo_are_one_announcement_each(doc, heard):
    pieces = [WorkPiece(name=f"wp{n}") for n in range(5)]
    _import(doc, pieces)
    heard.clear()

    doc.history_manager.undo()
    assert _names(heard, doc) == ["descendant_removed"]
    assert heard[-1][2]["origins"] == tuple(reversed(pieces))
    heard.clear()

    doc.history_manager.redo()
    assert _names(heard, doc) == ["descendant_added"]
    assert heard[-1][2]["origins"] == tuple(pieces)


def test_moves_in_one_transaction_are_one_transform_change(doc, heard):
    pieces = [WorkPiece(name=f"wp{n}") for n in range(4)]
    for wp in pieces:
        doc.active_layer.add_child(wp)
    heard.clear()

    with doc.history_manager.transaction("Move"):
        for n, wp in enumerate(pieces):
            wp.matrix = Matrix.translation(n + 1, n + 1)

    assert _names(heard, doc) == ["descendant_transform_changed"]
    assert heard[-1][2]["origins"] == tuple(pieces)


def test_outside_a_batch_every_change_is_announced_as_before(doc, heard):
    pieces = [WorkPiece(name=f"wp{n}") for n in range(3)]

    for wp in pieces:
        doc.active_layer.add_child(wp)

    assert _names(heard, doc) == ["descendant_added"] * 3
    assert [kw["origin"] for who, _, kw in heard if who is doc] == pieces
    assert all("origins" not in kw for _, _, kw in heard)


def test_nested_batches_announce_when_the_outermost_ends(doc, heard):
    with doc.batch():
        with doc.batch():
            doc.active_layer.add_child(WorkPiece(name="a"))
        assert heard == []
        doc.active_layer.add_child(WorkPiece(name="b"))
    assert _names(heard, doc) == ["descendant_added"]
    assert len(heard[-1][2]["origins"]) == 2


def test_updates_are_not_batched(doc, heard):
    wp = WorkPiece(name="wp")
    doc.active_layer.add_child(wp)
    heard.clear()

    with doc.batch():
        wp.name = "one"
        wp.name = "two"
        assert _names(heard, doc) == ["descendant_updated"] * 2

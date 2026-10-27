"""
Arrange > Center, Align and Spread on groups across layers: a group is
one object, measured by the box of all its items (on hidden layers
too) and moved rigidly, every item by the same world move, in one
undo step. Without propagate (edit-in-group mode) each item is placed
on its own, as before groups.
"""

import numpy as np
import pytest
from raygeo.geo import Matrix

from swiftcut.core.layer import Layer
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.transform_cmd import TransformCmd
from tests.doceditor import layout_bench as bench


def _piece(layer, name, size, pos):
    workpiece = WorkPiece(name=name)
    workpiece.set_size(*size)
    workpiece.pos = pos
    layer.add_child(workpiece)
    return workpiece


def _engrave_layer(doc_editor, visible=True):
    layer = Layer(name="Engrave")
    doc_editor.doc.add_child(layer)
    layer.set_visible(visible)
    return layer


def _outline_and_artwork(doc_editor, outline_pos=(20.0, 30.0)):
    """
    A 100 x 60 outline on the active layer and a 30 x 20 artwork on
    another layer, 10 mm right of and 10 mm above its lower left
    corner, in one group.
    """
    x, y = outline_pos
    outline = _piece(doc_editor.doc.active_layer, "Outline", (100, 60), (x, y))
    artwork = _piece(
        _engrave_layer(doc_editor), "Artwork", (30, 20), (x + 10, y + 10)
    )
    assert doc_editor.group.group_items([outline, artwork]) is not None
    return outline, artwork


def _offset(item, other):
    """Where other is in item's space: unchanged while both move as
    one."""
    return item.get_world_transform().invert() @ other.get_world_transform()


def _same(a: Matrix, b: Matrix) -> bool:
    return np.allclose(a.to_numpy(), b.to_numpy(), atol=1e-9)


async def _run(doc_editor, task_mgr, method, *args, **kwargs):
    """Runs a LayoutCmd method; waits until it is applied."""
    getattr(doc_editor.layout, method)(*args, **kwargs)
    await bench.settle(doc_editor, task_mgr)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, args, expected_box",
    [
        # The group's box, 100 x 60, centred on a 400 mm wide surface.
        ("center_horizontally", (400.0,), (150.0, 30.0, 250.0, 90.0)),
        ("align_left", (), (0.0, 30.0, 100.0, 90.0)),
        # Its top on the top of a 300 mm high surface.
        ("align_top", (300.0,), (20.0, 240.0, 120.0, 300.0)),
    ],
)
async def test_a_group_alone_moves_as_one_to_the_surface(
    doc_editor, task_mgr, method, args, expected_box
):
    outline, artwork = _outline_and_artwork(doc_editor)
    offset = _offset(outline, artwork)
    before = [outline.matrix.copy(), artwork.matrix.copy()]
    history = doc_editor.history_manager
    steps = len(history.undo_stack)

    # The canvas selects both: a click on one selects its group.
    await _run(doc_editor, task_mgr, method, [outline, artwork], *args)

    box = TransformCmd.group_bbox_world([outline, artwork])
    assert box == pytest.approx(expected_box)
    assert _same(_offset(outline, artwork), offset)
    assert len(history.undo_stack) == steps + 1
    history.undo()
    assert outline.matrix == before[0]
    assert artwork.matrix == before[1]


@pytest.mark.asyncio
async def test_align_left_moves_a_group_rigidly_to_a_loose_item(
    doc_editor, task_mgr
):
    outline, artwork = _outline_and_artwork(doc_editor, (100.0, 30.0))
    loose = _piece(doc_editor.doc.active_layer, "Loose", (10, 10), (20, 200))
    offset = _offset(outline, artwork)

    await _run(doc_editor, task_mgr, "align_left", [outline, artwork, loose])

    assert outline.pos == pytest.approx((20.0, 30.0))
    assert artwork.pos == pytest.approx((30.0, 40.0))
    assert loose.pos == pytest.approx((20.0, 200.0))
    assert _same(_offset(outline, artwork), offset)


@pytest.mark.asyncio
async def test_spread_spaces_a_group_as_one_object(doc_editor, task_mgr):
    layer = doc_editor.doc.active_layer
    left = _piece(layer, "Left", (10, 10), (0, 0))
    right = _piece(layer, "Right", (10, 10), (200, 0))
    outline = _piece(layer, "Outline", (40, 10), (30, 0))
    artwork = _piece(_engrave_layer(doc_editor), "Art", (10, 5), (35, 2))
    assert doc_editor.group.group_items([outline, artwork]) is not None
    offset = _offset(outline, artwork)

    await _run(
        doc_editor,
        task_mgr,
        "spread_horizontally",
        [left, outline, artwork, right],
    )

    # 210 mm from end to end, 60 mm of it the three objects: two gaps
    # of 75 mm.
    assert outline.pos == pytest.approx((85.0, 0.0))
    assert artwork.pos == pytest.approx((90.0, 2.0))
    assert left.pos == pytest.approx((0.0, 0.0))
    assert right.pos == pytest.approx((200.0, 0.0))
    assert _same(_offset(outline, artwork), offset)


@pytest.mark.asyncio
async def test_a_member_on_a_hidden_layer_follows_and_counts_in_the_box(
    doc_editor, task_mgr
):
    outline = _piece(
        doc_editor.doc.active_layer, "Outline", (50, 50), (100, 30)
    )
    # Sticks out 20 mm left of the outline, on a hidden layer.
    hidden = _piece(
        _engrave_layer(doc_editor, visible=False), "Hidden", (10, 10), (80, 40)
    )
    assert doc_editor.group.group_items([outline, hidden]) is not None

    # The canvas selects the visible member only.
    await _run(doc_editor, task_mgr, "align_left", [outline])

    assert hidden.pos == pytest.approx((0.0, 40.0))
    assert outline.pos == pytest.approx((20.0, 30.0))


@pytest.mark.asyncio
async def test_a_follower_on_a_transformed_layer_makes_the_same_world_move(
    doc_editor, task_mgr
):
    outline, artwork = _outline_and_artwork(doc_editor)
    layer = artwork.parent
    world = artwork.get_world_transform()
    layer.matrix = Matrix.translation(10, 5) @ Matrix.rotation(30)
    artwork.matrix = layer.matrix.invert() @ world

    await _run(doc_editor, task_mgr, "center_horizontally", [outline], 400.0)

    assert outline.pos == pytest.approx((150.0, 30.0))
    assert _same(
        artwork.get_world_transform(), Matrix.translation(130, 0) @ world
    )


@pytest.mark.asyncio
async def test_without_propagate_each_item_is_placed_on_its_own(
    doc_editor, task_mgr
):
    outline, artwork = _outline_and_artwork(doc_editor)

    await _run(
        doc_editor,
        task_mgr,
        "center_horizontally",
        [outline, artwork],
        400.0,
        propagate=False,
    )

    # Two items: each centred on the selection's box, the outline's.
    assert outline.pos == pytest.approx((20.0, 30.0))
    assert artwork.pos == pytest.approx((55.0, 40.0))

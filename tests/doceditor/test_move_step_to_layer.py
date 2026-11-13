"""A step moved or copied to a layer, as a drag between layer cards does.

The same step moves, with its uid and every setting, in one undo step
that restores both workflows. A copy is a duplicate with a new uid. In
its own workflow a move is the reorder the operations row always did,
and none when the step would land where it is. A hidden layer takes no
step, a layer may hold two steps of one type, and a layer left without
steps stays, empty, also once saved and loaded.
"""

import asyncio

import pytest

from swiftcut.core.doc import Doc
from swiftcut.core.layer import Layer
from swiftcut.core.workpiece import WorkPiece


@pytest.fixture
def layers(
    doc_editor, context_initializer, contour_step_class, engrave_step_class
):
    """
    The first layer engraves, then cuts; the second cuts. They are on
    different materials, both filled for the active machine.
    """
    context = context_initializer
    doc = doc_editor.doc
    first = doc.layers[0]
    second = Layer("Second")
    doc.add_layer(second)
    engrave = engrave_step_class.create(context, name="engrave")
    cut = contour_step_class.create(context, name="cut")
    other_cut = contour_step_class.create(context, name="other cut")
    first.workflow.set_steps([engrave, cut])
    second.workflow.set_steps([other_cut])
    first.set_material(("mdf", 3.0))
    second.set_material(("acrylic", 5.0))
    first.material_machine = context.machine.name
    second.material_machine = context.machine.name
    return first, second, engrave, cut, other_cut


def _names(layer):
    return [s.name for s in layer.workflow.steps]


def _undo_names(doc_editor):
    return [c.name for c in doc_editor.history_manager.undo_stack]


@pytest.mark.parametrize(
    "index, order",
    [
        (0, ["other cut", "engrave", "cut"]),
        (1, ["engrave", "other cut", "cut"]),
        (2, ["engrave", "cut", "other cut"]),
        (None, ["engrave", "cut", "other cut"]),
    ],
    ids=["first", "middle", "end", "append"],
)
def test_a_step_moves_to_the_gap_in_one_undo_step(
    doc_editor, layers, index, order
):
    first, second, engrave, cut, other_cut = layers
    history = doc_editor.history_manager

    moved = doc_editor.layer.move_step_to_layer(other_cut, first, index)

    assert moved is other_cut
    assert _names(first) == order
    assert second.workflow.steps == []
    assert other_cut.parent is first.workflow
    assert _undo_names(doc_editor) == ["Move step 'other cut'"]

    history.undo()
    assert first.workflow.steps == [engrave, cut]
    assert second.workflow.steps == [other_cut]
    assert other_cut.parent is second.workflow
    assert engrave.parent is cut.parent is first.workflow

    history.redo()
    assert _names(first) == order
    assert second.workflow.steps == []
    assert other_cut.parent is first.workflow


def test_a_moved_step_keeps_its_uid_and_settings(
    doc_editor, layers, context_initializer, monkeypatch
):
    """
    Also on a layer of another material, once the history change
    has re-filled whatever layer was filled for another machine.
    """
    first, second, _, _, other_cut = layers
    history = doc_editor.history_manager
    other_cut.power = 0.37
    other_cut.cut_speed = 1234
    other_cut.visible = False
    other_cut.selected_head_uid = context_initializer.machine.heads[0].uid
    other_cut.applied_recipe_uid = "acrylic-cut"
    other_cut.per_step_transformers_dicts.append(
        {"name": "MultiPassTransformer", "passes": 3}
    )
    other_cut.per_workpiece_transformers_dicts[0]["enabled"] = False
    saved = other_cut.to_dict()
    refills = []
    refill = doc_editor.step.refill_layer_materials

    def counting_refill():
        refills.append(True)
        refill()

    monkeypatch.setattr(
        doc_editor.step, "refill_layer_materials", counting_refill
    )

    doc_editor.layer.move_step_to_layer(other_cut, first, 1)
    assert refills
    assert other_cut.to_dict() == saved
    history.undo()
    assert other_cut.to_dict() == saved
    history.redo()
    assert other_cut.to_dict() == saved
    assert len(refills) == 3
    assert first.material == ("mdf", 3.0)
    assert second.material == ("acrylic", 5.0)


def test_a_copy_is_a_duplicate_with_a_new_uid(doc_editor, layers):
    first, second, engrave, cut, other_cut = layers
    history = doc_editor.history_manager
    other_cut.power = 0.37
    other_cut.applied_recipe_uid = "acrylic-cut"
    saved = other_cut.to_dict()

    copy = doc_editor.layer.move_step_to_layer(other_cut, first, 0, copy=True)

    assert copy is not None and copy is not other_cut
    assert type(copy) is type(other_cut)
    assert copy.uid != other_cut.uid
    data = copy.to_dict()
    assert data.pop("uid") != saved.pop("uid")
    assert data == saved
    assert first.workflow.steps == [copy, engrave, cut]
    assert second.workflow.steps == [other_cut]
    assert other_cut.parent is second.workflow
    assert _undo_names(doc_editor) == ["Copy step 'other cut'"]

    history.undo()
    assert first.workflow.steps == [engrave, cut]
    assert second.workflow.steps == [other_cut]
    history.redo()
    assert first.workflow.steps == [copy, engrave, cut]


def test_a_copy_into_its_own_workflow_lands_at_the_gap(doc_editor, layers):
    first, _, engrave, cut, _ = layers

    copy = doc_editor.layer.move_step_to_layer(engrave, first, 2, copy=True)

    assert first.workflow.steps == [engrave, cut, copy]
    assert copy.uid != engrave.uid
    doc_editor.history_manager.undo()
    assert first.workflow.steps == [engrave, cut]


@pytest.mark.parametrize(
    "dragged, gap, order",
    [
        (0, 2, ["cut", "engrave", "third"]),
        (2, 0, ["third", "engrave", "cut"]),
        (0, 3, ["cut", "third", "engrave"]),
        (1, 0, ["cut", "engrave", "third"]),
    ],
    ids=["forward", "backward", "to-end", "to-front"],
)
def test_a_move_in_its_own_workflow_reorders(
    doc_editor,
    layers,
    contour_step_class,
    context_initializer,
    dragged,
    gap,
    order,
):
    first = layers[0]
    third = contour_step_class.create(context_initializer, name="third")
    first.workflow.add_step(third)
    steps = list(first.workflow.steps)

    moved = doc_editor.layer.move_step_to_layer(steps[dragged], first, gap)

    assert moved is steps[dragged]
    assert _names(first) == order
    assert _undo_names(doc_editor) == ["Reorder steps"]
    doc_editor.history_manager.undo()
    assert first.workflow.steps == steps


@pytest.mark.parametrize("gap", [0, 1], ids=["before", "after"])
def test_a_step_dropped_beside_itself_makes_no_undo_step(
    doc_editor, layers, gap
):
    """The gap before a step and the one after it are where it is."""
    first, _, engrave, cut, _ = layers

    moved = doc_editor.layer.move_step_to_layer(engrave, first, gap)

    assert moved is engrave
    assert first.workflow.steps == [engrave, cut]
    assert doc_editor.history_manager.undo_stack == []


@pytest.mark.parametrize(
    "index, order",
    [
        (-3, ["other cut", "engrave", "cut"]),
        (99, ["engrave", "cut", "other cut"]),
    ],
    ids=["below", "above"],
)
def test_a_gap_out_of_range_is_clamped(doc_editor, layers, index, order):
    first, _, _, _, other_cut = layers

    doc_editor.layer.move_step_to_layer(other_cut, first, index)

    assert _names(first) == order


@pytest.mark.parametrize("copy", [False, True], ids=["move", "copy"])
def test_a_hidden_layer_takes_no_step(doc_editor, layers, copy):
    first, second, engrave, cut, other_cut = layers
    second.set_visible(False)

    result = doc_editor.layer.move_step_to_layer(cut, second, 0, copy=copy)

    assert result is None
    assert first.workflow.steps == [engrave, cut]
    assert second.workflow.steps == [other_cut]
    assert doc_editor.history_manager.undo_stack == []


def test_a_layer_may_have_two_cuts(doc_editor, layers, contour_step_class):
    first, _, _, cut, other_cut = layers

    doc_editor.layer.move_step_to_layer(other_cut, first)

    cuts = [s for s in first.workflow.steps if type(s) is contour_step_class]
    assert cuts == [cut, other_cut]


def test_an_emptied_layer_stays_empty(doc_editor, layers):
    """It keeps its shapes, and nothing seeds a step into it."""
    first, second, _, _, other_cut = layers
    shape = WorkPiece(name="shape")
    second.add_workpiece(shape)

    doc_editor.layer.move_step_to_layer(other_cut, first)

    assert second in doc_editor.doc.layers
    assert second.workflow.steps == []
    assert second.workpieces == [shape]
    loaded = Doc.from_dict(doc_editor.doc.to_dict())
    (reloaded,) = [lyr for lyr in loaded.layers if lyr.uid == second.uid]
    assert reloaded.workflow.steps == []
    assert [wp.uid for wp in reloaded.workpieces] == [shape.uid]


async def _settled(pipeline, timeout=10.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while pipeline.is_busy and loop.time() < deadline:
        await asyncio.sleep(0.05)
    assert not pipeline.is_busy


@pytest.mark.asyncio
async def test_a_move_its_undo_and_redo_start_one_rebuild_each(
    zero_debounce_delay, doc_editor, layers
):
    first, _, _, _, other_cut = layers
    pipeline = doc_editor.pipeline
    history = doc_editor.history_manager
    await _settled(pipeline)

    for change in (
        lambda: doc_editor.layer.move_step_to_layer(other_cut, first, 1),
        history.undo,
        history.redo,
    ):
        generation = pipeline.data_generation_id
        change()
        await _settled(pipeline)
        assert pipeline.data_generation_id == generation + 1

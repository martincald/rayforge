"""Steps dragged in a layer card's operations row.

A step icon dragged along its own row and dropped in a gap between the
icons takes that place in the layer's workflow, in one undo step named
"Reorder steps". Dropped back where it was, nothing changes and the
history stays as it was. The handlers run in GTK's order: prepare,
drag-begin, motion, drop, drag-end, on a row with real allocations.

Dropped on another layer's row, the step goes to the gap under the
pointer; dropped elsewhere on that layer's card, it goes last. When
the drop offers only a copy (Option held on macOS, Ctrl on Windows and
Linux), a copy goes there instead. A hidden layer takes no step, and
the shapes, assets and layers dragged onto a card are not steps.
"""

from types import SimpleNamespace

import pytest

from swiftcut.core.layer import Layer
from swiftcut.core.step import Step
from swiftcut.core.workpiece import WorkPiece

pytestmark = pytest.mark.ui


def _settle(row):
    from gi.repository import GLib

    context = GLib.MainContext.default()
    for _ in range(200):
        while context.pending():
            context.iteration(False)
        buttons = row._step_buttons
        if buttons and all(b.get_width() > 0 for b in buttons):
            break


@pytest.fixture
def editor(ui_context_initializer, ui_task_mgr):
    from swiftcut.doceditor.editor import DocEditor

    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    yield editor
    editor.cleanup()


@pytest.fixture
def steps(editor):
    """Steps A, B and C on the document's layer."""
    steps = [Step(typelabel=name) for name in ("A", "B", "C")]
    editor.doc.layers[0].workflow.set_steps(steps)
    return steps


@pytest.fixture
def row(editor, steps):
    from gi.repository import Gtk

    from swiftcut.ui_gtk.doceditor.workflow_row import WorkflowRow

    row = WorkflowRow(editor, editor.doc.layers[0])
    window = Gtk.Window(child=row, default_width=400, default_height=60)
    window.present()
    _settle(row)
    yield row
    row.do_destroy()
    window.destroy()


def _button_of(row, step):
    return next(
        b for b in row._step_buttons if row._btn_uids[id(b)] == step.uid
    )


def _center_x(row, step) -> float:
    alloc = _button_of(row, step).get_allocation()
    return alloc.x + alloc.width / 2


def _gap_x(row, gap: int) -> float:
    """An x in the row that shows the drop indicator at gap."""
    buttons = row._step_buttons
    if gap < len(buttons):
        return float(buttons[gap].get_allocation().x)
    last = buttons[-1].get_allocation()
    return float(last.x + last.width + 1)


def _drag_in_row(row, monkeypatch, step, gap):
    """Drags step to gap, as GTK runs a drag inside one row."""
    from gi.repository import Gdk

    values = []
    new_for_value = Gdk.ContentProvider.new_for_value

    def recording(value):
        values.append(value)
        return new_for_value(value)

    monkeypatch.setattr(Gdk.ContentProvider, "new_for_value", recording)
    y = 5.0
    gap_x = _gap_x(row, gap)
    assert row._on_drag_prepare(row._drag_source, _center_x(row, step), y)
    row._on_drag_begin(row._drag_source, None)
    (value,) = values
    action = row._on_drop_motion(row._drop_target, gap_x, y)
    assert action == Gdk.DragAction.MOVE
    accepted = row._on_drop(row._drop_target, value, gap_x, y)
    row._on_drag_end(row._drag_source, None, accepted)


@pytest.mark.parametrize(
    "dragged, gap, order",
    [
        (0, 2, "BAC"),
        (2, 0, "CAB"),
        (0, 3, "BCA"),
        (1, 0, "BAC"),
    ],
    ids=["forward", "backward", "to-end", "to-front"],
)
def test_a_step_dropped_in_its_own_row_takes_the_gap(
    editor, steps, row, monkeypatch, dragged, gap, order
):
    workflow = editor.doc.layers[0].workflow
    history = editor.history_manager
    uids = [s.uid for s in steps]
    before = len(history.undo_stack)

    _drag_in_row(row, monkeypatch, steps[dragged], gap)

    assert "".join(s.typelabel for s in workflow.steps) == order
    assert [s.uid for s in steps] == uids
    assert set(workflow.steps) == set(steps)
    assert len(history.undo_stack) == before + 1
    assert history.undo_stack[-1].name == "Reorder steps"
    history.undo()
    assert workflow.steps == steps


def test_a_step_dropped_where_it_was_changes_nothing(
    editor, steps, row, monkeypatch
):
    workflow = editor.doc.layers[0].workflow
    history = editor.history_manager
    before = len(history.undo_stack)

    _drag_in_row(row, monkeypatch, steps[1], 1)

    assert workflow.steps == steps
    assert len(history.undo_stack) == before


@pytest.fixture(autouse=True)
def _no_step_drag():
    """A test that prepares a drag without ending it leaves none."""
    from swiftcut.ui_gtk.doceditor.workflow_row import WorkflowRow

    WorkflowRow.dragged_step = None
    yield
    WorkflowRow.dragged_step = None


def _target(copy=False, actions=None):
    """
    A drop target in a drop that offers a move or a copy, or only the
    copy the platform leaves while its copy key is held.
    """
    from gi.repository import Gdk

    if actions is None:
        actions = Gdk.DragAction.COPY
        if not copy:
            actions |= Gdk.DragAction.MOVE
    drop = SimpleNamespace(get_actions=lambda: actions)
    return SimpleNamespace(get_current_drop=lambda: drop)


@pytest.fixture
def tab(editor, steps):
    """
    The layers panel in a window: the first layer has steps A, B and
    C, the second X and Y.
    """
    from gi.repository import Gtk

    from swiftcut.ui_gtk.doceditor.layers_tab import LayersTab

    second = Layer("Second")
    editor.doc.add_layer(second)
    second.workflow.set_steps([Step(typelabel=name) for name in "XY"])
    tab = LayersTab(editor)
    window = Gtk.Window(child=tab, default_width=900, default_height=400)
    window.present()
    for column in tab._columns:
        _settle(column.workflow_row)
    yield tab
    tab.do_destroy()
    window.destroy()


@pytest.fixture
def calls(editor, monkeypatch):
    """The step command's calls, as (step, layer, index, copy)."""
    calls = []

    def recording(step, target_layer, index=None, copy=False):
        calls.append((step, target_layer, index, copy))
        return step

    monkeypatch.setattr(editor.layer, "move_step_to_layer", recording)
    return calls


def _payload(step):
    from swiftcut.ui_gtk.doceditor.workflow_row import step_payload

    return step_payload(step.parent.uid, step.uid)


@pytest.mark.parametrize("copy", [False, True], ids=["move", "copy"])
def test_a_step_dropped_on_another_layers_row_goes_to_the_gap(
    editor, steps, tab, calls, copy
):
    second = editor.doc.layers[1]
    row = tab._columns[1].workflow_row
    gap_x = _gap_x(row, 1)

    assert row._on_drop(_target(copy=copy), _payload(steps[0]), gap_x, 5)

    assert calls == [(steps[0], second, 1, copy)]


def test_a_step_prepared_in_one_row_is_moved_by_another(
    editor, steps, tab, monkeypatch
):
    """
    The real command, from the payload the source row offers. The
    card the pointer crossed to reach the row is no longer marked
    once the step has landed, though its own drop never ran.
    """
    from gi.repository import Gdk

    from swiftcut.ui_gtk.doceditor.workflow_row import WorkflowRow

    first, second = editor.doc.layers
    source = tab._columns[0].workflow_row
    card = tab._columns[1]
    target = card.workflow_row
    x, y = second.workflow.steps
    values = []
    new_for_value = Gdk.ContentProvider.new_for_value

    def recording(value):
        values.append(value)
        return new_for_value(value)

    monkeypatch.setattr(Gdk.ContentProvider, "new_for_value", recording)
    assert source._on_drag_prepare(
        source._drag_source, _center_x(source, steps[1]), 5
    )
    assert WorkflowRow.dragged_step is None
    source._on_drag_begin(source._drag_source, None)
    (value,) = values
    assert WorkflowRow.dragged_step is steps[1]
    gap_x = _gap_x(target, 2)
    move = Gdk.DragAction.MOVE
    assert card._on_drop_motion(_target(), 5, 5) == move
    assert "step-drop-target" in card.card.get_css_classes()
    assert target._on_drop_motion(_target(), gap_x, 5) == move
    assert target._on_drop(_target(), value, gap_x, 5)
    source._on_drag_end(source._drag_source, None, True)

    assert "step-drop-target" not in card.card.get_css_classes()
    assert WorkflowRow.dragged_step is None
    assert first.workflow.steps == [steps[0], steps[2]]
    assert second.workflow.steps == [x, y, steps[1]]
    editor.history_manager.undo()
    assert first.workflow.steps == steps
    assert second.workflow.steps == [x, y]


def test_a_cancelled_step_drag_is_no_drag(editor, steps, row):
    from swiftcut.ui_gtk.doceditor.workflow_row import WorkflowRow

    assert row._on_drag_prepare(row._drag_source, _center_x(row, steps[0]), 5)
    row._on_drag_begin(row._drag_source, None)
    assert WorkflowRow.dragged_step is steps[0]

    assert row._on_drag_cancel(row._drag_source, None, None) is False

    assert WorkflowRow.dragged_step is None
    assert row._on_drop_motion(_target(), 5, 5) == 0


def _not_steps(editor):
    """A shape's uid, an asset list and a layer, as dragged today."""
    shape = WorkPiece(name="shape")
    editor.doc.layers[0].add_workpiece(shape)
    return [
        shape.uid,
        f'["{shape.uid}"]',
        "layer:" + editor.doc.layers[0].uid,
        "step:no-such-workflow:no-such-step",
    ]


def test_a_row_ignores_what_is_not_a_step_of_the_document(editor, tab, calls):
    row = tab._columns[1].workflow_row

    for value in _not_steps(editor):
        assert row._on_drop(_target(), value, 5, 5) is False, value

    assert calls == []


def test_a_row_takes_no_motion_but_a_step_drags(editor, steps, tab):
    from swiftcut.ui_gtk.doceditor.workflow_row import WorkflowRow

    row = tab._columns[1].workflow_row
    assert row._on_drop_motion(_target(), 5, 5) == 0
    assert row._drop_indicator is None

    WorkflowRow.dragged_step = steps[0]
    assert row._on_drop_motion(_target(copy=True), 5, 5) != 0
    assert row._drop_indicator is not None


def test_a_step_dropped_on_a_card_goes_last(editor, steps, tab, calls):
    from gi.repository import Gdk

    from swiftcut.ui_gtk.doceditor.workflow_row import WorkflowRow

    second = editor.doc.layers[1]
    column = tab._columns[1]
    sent = []
    column.move_to_layer_requested.connect(
        lambda sender, **kw: sent.append(kw), weak=False
    )
    WorkflowRow.dragged_step = steps[0]

    assert column._on_drop_motion(_target(), 5, 5) == Gdk.DragAction.MOVE
    assert "step-drop-target" in column.card.get_css_classes()
    assert column._on_drop(_target(), _payload(steps[0]), 5, 5)

    assert "step-drop-target" not in column.card.get_css_classes()
    assert calls == [(steps[0], second, None, False)]
    assert sent == []


def test_a_step_on_its_own_card_moves_nowhere_and_copies_last(
    editor, steps, tab, calls
):
    from gi.repository import Gdk

    from swiftcut.ui_gtk.doceditor.workflow_row import WorkflowRow

    first = editor.doc.layers[0]
    column = tab._columns[0]
    WorkflowRow.dragged_step = steps[0]

    assert column._on_drop_motion(_target(), 5, 5) == 0
    assert "step-drop-target" not in column.card.get_css_classes()
    assert column._on_drop(_target(), _payload(steps[0]), 5, 5) is False
    assert calls == []

    copy = Gdk.DragAction.COPY
    assert column._on_drop_motion(_target(copy=True), 5, 5) == copy
    assert column._on_drop(_target(copy=True), _payload(steps[0]), 5, 5)
    assert calls == [(steps[0], first, None, True)]


def test_a_shape_dropped_on_a_card_still_moves_there(editor, tab, calls):
    first, second = editor.doc.layers
    shape = WorkPiece(name="shape")
    first.add_workpiece(shape)
    column = tab._columns[1]
    sent = []
    column.move_to_layer_requested.connect(
        lambda sender, **kw: sent.append(kw), weak=False
    )

    assert column._on_drop(_target(), shape.uid, 5, 5)

    assert sent == [{"items": [shape], "target_layer": second}]
    assert shape.layer is second
    assert calls == []


def test_a_hidden_layer_takes_no_step(editor, steps, tab, calls):
    from swiftcut.ui_gtk.doceditor.workflow_row import WorkflowRow

    editor.doc.layers[1].set_visible(False)
    column = tab._columns[1]
    row = column.workflow_row
    WorkflowRow.dragged_step = steps[0]
    value = _payload(steps[0])

    for copy in (False, True):
        assert row._on_drop_motion(_target(copy=copy), 5, 5) == 0
        assert row._on_drop(_target(copy=copy), value, 5, 5) is False
        assert column._on_drop_motion(_target(copy=copy), 5, 5) == 0
        assert column._on_drop(_target(copy=copy), value, 5, 5) is False
    assert "step-drop-target" not in column.card.get_css_classes()
    assert calls == []


def test_the_copy_decision():
    from gi.repository import Gdk

    from swiftcut.ui_gtk.doceditor.workflow_row import drop_copies

    move = Gdk.DragAction.MOVE
    assert drop_copies(_target(copy=True))
    assert not drop_copies(_target())
    assert not drop_copies(_target(actions=move))
    no_drop = SimpleNamespace(get_current_drop=lambda: None)
    assert not drop_copies(no_drop)


def test_a_step_payload_names_a_workflow_and_a_step():
    from swiftcut.ui_gtk.doceditor.workflow_row import (
        parse_step_payload,
        step_payload,
    )

    assert parse_step_payload(step_payload("wf", "st")) == ("wf", "st")
    for value in (None, "", "wf", "step:", "step:wf", "step:wf:", "a:b:c"):
        assert parse_step_payload(value) is None, value
    assert parse_step_payload("step:a:b:c") is None
    assert parse_step_payload('["step:a:b"]') is None
    assert parse_step_payload("layer:step:a") is None

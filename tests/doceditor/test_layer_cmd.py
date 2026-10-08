import pytest

from swiftcut.core.group import Group
from swiftcut.core.layer import Layer
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.layer_cmd import AddLayerAndSetActiveCommand, LayerCmd


@pytest.fixture
def layer_cmd(doc_editor):
    """Provides a LayerCmd instance."""
    return LayerCmd(doc_editor)


@pytest.fixture
def sample_layer(doc_editor):
    """Provides a sample Layer instance."""
    return Layer(name="Test Layer")


def test_add_layer_and_set_active_command_execute(layer_cmd, sample_layer):
    """Test that the command adds a layer and sets it as active."""
    initial_layer_count = len(layer_cmd._editor.doc.layers)
    cmd = AddLayerAndSetActiveCommand(
        layer_cmd._editor, sample_layer, name="Add layer"
    )
    cmd.execute()

    assert len(layer_cmd._editor.doc.layers) == initial_layer_count + 1
    assert layer_cmd._editor.doc.layers[-1] is sample_layer
    assert layer_cmd._editor.doc.active_layer is sample_layer


def test_add_layer_and_set_active_command_undo(layer_cmd, sample_layer):
    """Test that the command correctly undoes adding a layer."""
    initial_layer_count = len(layer_cmd._editor.doc.layers)
    initial_active_layer = layer_cmd._editor.doc.active_layer
    cmd = AddLayerAndSetActiveCommand(
        layer_cmd._editor, sample_layer, name="Add layer"
    )
    cmd.execute()
    cmd.undo()

    assert len(layer_cmd._editor.doc.layers) == initial_layer_count
    assert sample_layer not in layer_cmd._editor.doc.layers
    assert layer_cmd._editor.doc.active_layer is initial_active_layer


def test_layer_cmd_add_layer_and_set_active(layer_cmd, sample_layer):
    """Test that the LayerCmd wrapper correctly executes the command."""
    initial_layer_count = len(layer_cmd._editor.doc.layers)
    layer_cmd.add_layer_and_set_active(sample_layer)

    assert len(layer_cmd._editor.doc.layers) == initial_layer_count + 1
    assert layer_cmd._editor.doc.layers[-1] is sample_layer
    assert layer_cmd._editor.doc.active_layer is sample_layer
    assert len(layer_cmd._editor.history_manager.undo_stack) == 1


def test_layer_cmd_add_default_layer_and_set_active(layer_cmd):
    """
    Test that the LayerCmd wrapper creates a default layer if none is
    provided.
    """
    initial_layer_count = len(layer_cmd._editor.doc.layers)
    layer_cmd.add_layer_and_set_active()

    assert len(layer_cmd._editor.doc.layers) == initial_layer_count + 1
    assert layer_cmd._editor.doc.active_layer.name.startswith("Layer")
    assert len(layer_cmd._editor.history_manager.undo_stack) == 1


def test_layer_cmd_set_active_layer(layer_cmd):
    """Test setting the active layer."""
    layer1 = Layer(name="Layer 1")
    layer2 = Layer(name="Layer 2")
    layer_cmd._editor.doc.add_child(layer1)
    layer_cmd._editor.doc.add_child(layer2)
    layer_cmd._editor.doc.active_layer = layer1

    layer_cmd.set_active_layer(layer2)

    assert layer_cmd._editor.doc.active_layer is layer2
    assert len(layer_cmd._editor.history_manager.undo_stack) == 1


def test_layer_cmd_set_active_layer_no_change(layer_cmd):
    """Test that setting the same active layer does nothing."""
    layer1 = Layer(name="Layer 1")
    layer_cmd._editor.doc.add_child(layer1)
    layer_cmd._editor.doc.active_layer = layer1

    hm = layer_cmd._editor.history_manager
    initial_history_len = len(hm.undo_stack)
    layer_cmd.set_active_layer(layer1)

    assert layer_cmd._editor.doc.active_layer is layer1
    assert len(hm.undo_stack) == initial_history_len


def test_layer_cmd_delete_layer(layer_cmd):
    """Test deleting a layer."""
    layer1 = Layer(name="Layer 1")
    layer2 = Layer(name="Layer 2")
    layer_cmd._editor.doc.add_child(layer1)
    layer_cmd._editor.doc.add_child(layer2)
    initial_count = len(layer_cmd._editor.doc.layers)

    layer_cmd.delete_layer(layer1)

    assert len(layer_cmd._editor.doc.layers) == initial_count - 1
    assert layer1 not in layer_cmd._editor.doc.layers
    assert len(layer_cmd._editor.history_manager.undo_stack) == 1


def test_layer_cmd_reorder_layers(layer_cmd):
    """Test reordering layers."""
    layer1 = Layer(name="Layer 1")
    layer2 = Layer(name="Layer 2")
    layer_cmd._editor.doc.add_child(layer1)
    layer_cmd._editor.doc.add_child(layer2)

    new_order = [layer2, layer1]
    layer_cmd.reorder_layers(new_order)

    assert layer_cmd._editor.doc.layers == new_order
    assert len(layer_cmd._editor.history_manager.undo_stack) == 1


def _layers_with(layer_cmd, *names):
    """Adds one layer per name; returns them."""
    layers = [Layer(name=name) for name in names]
    for layer in layers:
        layer_cmd._editor.doc.add_child(layer)
    return layers


def test_move_items_to_layer_is_one_undo_step(layer_cmd):
    """Moving several shapes to a layer is undone in one step."""
    source, target = _layers_with(layer_cmd, "A", "B")
    wp1 = WorkPiece(name="wp1")
    wp2 = WorkPiece(name="wp2")
    wp1.pos = (10, 20)
    source.add_child(wp1)
    source.add_child(wp2)
    hm = layer_cmd._editor.history_manager
    before = len(hm.undo_stack)

    layer_cmd.move_items_to_layer([wp1, wp2], target)

    assert wp1.layer is target and wp2.layer is target
    assert wp1.pos == pytest.approx((10, 20))
    assert len(hm.undo_stack) == before + 1

    hm.undo()
    assert wp1.layer is source and wp2.layer is source
    assert len(hm.undo_stack) == before

    hm.redo()
    assert wp1.layer is target and wp2.layer is target


def test_moving_from_several_layers_is_one_undo_step(layer_cmd):
    """A selection spanning two layers moves, and comes back, at once."""
    layer_a, target, layer_c = _layers_with(layer_cmd, "A", "B", "C")
    wp_a = WorkPiece(name="on A")
    wp_c = WorkPiece(name="on C")
    layer_a.add_child(wp_a)
    layer_c.add_child(wp_c)
    hm = layer_cmd._editor.history_manager
    before = len(hm.undo_stack)

    layer_cmd.move_items_to_layer([wp_a, wp_c], target)

    assert wp_a.layer is target and wp_c.layer is target
    assert len(hm.undo_stack) == before + 1

    hm.undo()
    assert wp_a.layer is layer_a
    assert wp_c.layer is layer_c


def test_moving_to_the_items_own_layer_adds_no_undo_step(layer_cmd):
    (layer,) = _layers_with(layer_cmd, "A")
    wp = WorkPiece(name="wp")
    layer.add_child(wp)
    hm = layer_cmd._editor.history_manager
    before = len(hm.undo_stack)

    layer_cmd.move_items_to_layer([wp], layer)

    assert wp.layer is layer
    assert len(hm.undo_stack) == before


def test_a_group_moves_to_a_layer_with_its_children(layer_cmd):
    source, target = _layers_with(layer_cmd, "A", "B")
    group = Group(name="group")
    wp = WorkPiece(name="wp")
    source.add_child(group)
    group.add_child(wp)

    layer_cmd.move_items_to_layer([group], target)

    assert group.parent is target
    assert wp.parent is group
    assert wp.layer is target

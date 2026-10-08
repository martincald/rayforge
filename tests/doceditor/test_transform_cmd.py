import asyncio
import math
from unittest.mock import MagicMock, patch

import pytest

from swiftcut.core.bed_bounds import inside
from swiftcut.core.layer import Layer
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.transform_cmd import TransformCmd
from swiftcut.machine.models.machine import Machine


@pytest.fixture
def transform_cmd(doc_editor):
    """Provides a TransformCmd instance."""
    return TransformCmd(doc_editor)


@pytest.fixture
def sample_items(doc_editor):
    """Provides sample DocItem instances."""
    layer = Layer(name="Test Layer")
    doc_editor.doc.add_child(layer)
    item1 = WorkPiece(name="Item 1")
    item2 = WorkPiece(name="Item 2")
    item1.set_size(10, 10)
    item2.set_size(20, 20)
    item1.pos = (5, 5)
    item2.pos = (10, 10)
    layer.add_child(item1)
    layer.add_child(item2)
    return [item1, item2]


def test_set_position(transform_cmd, sample_items):
    """Per-item position set: each item's top-left goes to the same
    machine target independently."""
    with patch(
        "swiftcut.doceditor.transform_cmd.get_context"
    ) as mock_get_context:
        mock_get_context.return_value.machine = None
        hm = transform_cmd._editor.history_manager
        initial_history_len = len(hm.undo_stack)

        transform_cmd.set_position(sample_items, 15.0, 20.0)

        assert sample_items[0].pos == (15.0, 20.0)
        assert sample_items[1].pos == (15.0, 20.0)
        assert len(hm.undo_stack) == initial_history_len + 1
        hm.undo()
        assert sample_items[0].pos == (5.0, 5.0)
        assert sample_items[1].pos == (10.0, 10.0)


def test_set_position_with_y_axis_down(transform_cmd, sample_items):
    """Test setting position when Y-axis is down."""
    with patch(
        "swiftcut.doceditor.transform_cmd.get_context"
    ) as mock_get_context:
        mock_machine = MagicMock()
        mock_machine.x_axis_right = False
        mock_machine.y_axis_down = True
        mock_machine.axis_extents = (100, 100)

        # Configure the mock to simulate Y-axis inversion logic:
        # machine Y=0 -> world Y = height - item_height
        # Here: machine Y=0, height=100, item_height=20 -> world Y=80
        mock_space = MagicMock()
        mock_space.machine_item_to_world.side_effect = lambda pos, size: (
            pos[0],
            100 - pos[1] - size[1],
        )
        mock_machine.get_coordinate_space.return_value = mock_space
        mock_machine.panel.machine_item_to_world.side_effect = (
            mock_space.machine_item_to_world.side_effect
        )

        mock_get_context.return_value.machine = mock_machine
        hm = transform_cmd._editor.history_manager
        initial_history_len = len(hm.undo_stack)

        # Y=0 in machine coords means top of the bed.
        # For item2 (size 20), bottom-left should be at (15, 80).
        transform_cmd.set_position([sample_items[1]], 15.0, 0.0)

        assert sample_items[1].pos == (15.0, 80.0)
        assert len(hm.undo_stack) == initial_history_len + 1


def test_set_position_no_items(transform_cmd):
    hm = transform_cmd._editor.history_manager
    initial_history_len = len(hm.undo_stack)
    transform_cmd.set_position([], 10, 10)
    assert len(hm.undo_stack) == initial_history_len


def test_set_position_with_x_axis_right(transform_cmd, sample_items):
    with patch(
        "swiftcut.doceditor.transform_cmd.get_context"
    ) as mock_get_context:
        mock_machine = MagicMock()
        mock_machine.x_axis_right = True
        mock_machine.y_axis_down = False
        mock_machine.axis_extents = (100, 100)

        # Mock get_coordinate_space().machine_item_to_world() to return
        # expected world coordinates.
        # For x=10 (Machine) -> World X = 100 - 10 - 20 (width) = 70
        # For y=10 (Machine) -> World Y = 10
        mock_space = MagicMock()
        mock_space.machine_item_to_world.side_effect = lambda pos, size: (
            100 - pos[0] - size[0],
            pos[1],
        )
        mock_machine.get_coordinate_space.return_value = mock_space
        mock_machine.panel.machine_item_to_world.side_effect = (
            mock_space.machine_item_to_world.side_effect
        )

        mock_get_context.return_value.machine = mock_machine

        # Test with item2 (size 20x20)
        transform_cmd.set_position([sample_items[1]], 10.0, 10.0)

        # Expected World Position:
        # X: 100 (bed width) - 10 (machine x) - 20 (width) = 70
        # Y: 10 (machine y) = 10 (world y)
        assert sample_items[1].pos == (70.0, 10.0)


# ── set_position_group ───────────────────────────────────────────


def test_set_position_group_preserves_relative(doc_editor):
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (10, 10)
    b = WorkPiece(name="B")
    b.set_size(30, 20)
    b.pos = (50, 30)
    layer.add_child(a)
    layer.add_child(b)
    rel_x = b.pos[0] - a.pos[0]
    rel_y = b.pos[1] - a.pos[1]

    tc.set_position_group([a, b], 100.0, 50.0)

    nrel_x = b.pos[0] - a.pos[0]
    nrel_y = b.pos[1] - a.pos[1]
    assert nrel_x == pytest.approx(rel_x, abs=1e-6)
    assert nrel_y == pytest.approx(rel_y, abs=1e-6)


def test_set_position_group_all_machine_origins(doc_editor):
    """Verify group bbox lands at machine (0,0) for all 4 origin corners."""
    W, H = 200.0, 200.0
    transforms = {
        "TOP_LEFT": (
            lambda pos, size: (pos[0], H - pos[1] - size[1]),
            lambda pos, size: (pos[0], H - pos[1] - size[1]),
        ),
        "TOP_RIGHT": (
            lambda pos, size: (W - pos[0] - size[0], H - pos[1] - size[1]),
            lambda pos, size: (W - pos[0] - size[0], H - pos[1] - size[1]),
        ),
        "BOTTOM_LEFT": (
            lambda pos, size: (pos[0], pos[1]),
            lambda pos, size: (pos[0], pos[1]),
        ),
        "BOTTOM_RIGHT": (
            lambda pos, size: (W - pos[0] - size[0], pos[1]),
            lambda pos, size: (W - pos[0] - size[0], pos[1]),
        ),
    }
    for name, (m2w, w2m) in transforms.items():
        layer = Layer(name="L")
        doc_editor.doc.add_child(layer)
        a = WorkPiece(name="A")
        a.set_size(20, 20)
        a.pos = (10, 10)
        b = WorkPiece(name="B")
        b.set_size(30, 20)
        b.pos = (50, 30)
        layer.add_child(a)
        layer.add_child(b)

        mock_space = MagicMock()
        mock_space.machine_item_to_world.side_effect = m2w
        mock_space.world_item_to_machine.side_effect = w2m
        mock_machine = MagicMock()
        mock_machine.axis_extents = (W, H)
        mock_machine.get_coordinate_space.return_value = mock_space
        mock_machine.panel.machine_item_to_world.side_effect = m2w
        mock_machine.panel.world_item_to_machine.side_effect = w2m
        with patch("swiftcut.doceditor.transform_cmd.get_context") as m:
            m.return_value.machine = mock_machine
            TransformCmd(doc_editor).set_position_group([a, b], 0.0, 0.0)
            reported = TransformCmd.get_position_group([a, b])
            assert reported == pytest.approx((0.0, 0.0), abs=1e-6), name
        doc_editor.history_manager.clear()


# ── set_size ──────────────────────────────────────────────────────


def test_set_size(transform_cmd, sample_items):
    """Test setting the size of items."""
    hm = transform_cmd._editor.history_manager
    initial_history_len = len(hm.undo_stack)

    transform_cmd.set_size(sample_items, 30.0, 40.0)

    assert sample_items[0].size == (30.0, 40.0)
    assert sample_items[1].size == (30.0, 40.0)
    assert len(hm.undo_stack) == initial_history_len + 1
    hm.undo()
    assert sample_items[0].size == (10.0, 10.0)


def test_set_size_with_fixed_ratio(transform_cmd, sample_items):
    """Test setting size with fixed aspect ratio."""
    hm = transform_cmd._editor.history_manager
    initial_history_len = len(hm.undo_stack)

    # item1 has ratio 1.0, item2 has ratio 1.0
    transform_cmd.set_size(sample_items, 30.0, None, fixed_ratio=True)

    assert sample_items[0].size == (30.0, 30.0)
    assert sample_items[1].size == (30.0, 30.0)
    assert len(hm.undo_stack) == initial_history_len + 1


def test_set_size_with_individual_sizes(transform_cmd, sample_items):
    """Test setting size with a list of individual sizes."""
    hm = transform_cmd._editor.history_manager
    initial_history_len = len(hm.undo_stack)

    sizes = [(30.0, 40.0), (50.0, 60.0)]
    transform_cmd.set_size(sample_items, sizes=sizes)

    assert sample_items[0].size == (30.0, 40.0)
    assert sample_items[1].size == (50.0, 60.0)
    assert len(hm.undo_stack) == initial_history_len + 1


def test_set_size_with_mismatched_sizes(transform_cmd, sample_items, caplog):
    """Test that providing a mismatched sizes list logs an error."""
    transform_cmd.set_size(sample_items, sizes=[(10.0, 20.0)])
    assert "Length of sizes list must match" in caplog.text


def test_set_size_no_items(transform_cmd):
    """Test that set_size does nothing if no items are provided."""
    hm = transform_cmd._editor.history_manager
    initial_history_len = len(hm.undo_stack)
    transform_cmd.set_size([], 10, 10)
    assert len(hm.undo_stack) == initial_history_len


def test_set_size_with_fixed_ratio_width_only(transform_cmd, sample_items):
    """Test setting width with fixed aspect ratio, calculating height."""
    # Setup item with aspect ratio 2.0 (20x10)
    item = sample_items[0]
    item.set_size(20, 10)
    assert item.get_current_aspect_ratio() == 2.0

    hm = transform_cmd._editor.history_manager
    initial_history_len = len(hm.undo_stack)

    # Set width to 40, height should become 20
    transform_cmd.set_size([item], width=40.0, height=None, fixed_ratio=True)

    assert item.size == (40.0, 20.0)
    assert len(hm.undo_stack) == initial_history_len + 1


def test_set_size_with_fixed_ratio_height_only(transform_cmd, sample_items):
    """Test setting height with fixed aspect ratio, calculating width."""
    # Setup item with aspect ratio 0.5 (10x20)
    item = sample_items[0]
    item.set_size(10, 20)
    assert item.get_current_aspect_ratio() == 0.5

    hm = transform_cmd._editor.history_manager
    initial_history_len = len(hm.undo_stack)

    # Set height to 40, width should become 20
    transform_cmd.set_size([item], width=None, height=40.0, fixed_ratio=True)

    assert item.size == (20.0, 40.0)
    assert len(hm.undo_stack) == initial_history_len + 1


# ── set_size_group ────────────────────────────────────────────────


def test_set_size_group(doc_editor):
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (10, 10)
    b = WorkPiece(name="B")
    b.set_size(30, 20)
    b.pos = (50, 30)
    layer.add_child(a)
    layer.add_child(b)

    size0 = TransformCmd.get_size_group([a, b])
    assert size0 is not None
    gw, gh = size0
    scale_x = 80.0 / gw
    scale_y = 60.0 / gh

    tc.set_size_group([a, b], 80.0, 60.0)

    size1 = TransformCmd.get_size_group([a, b])
    assert size1 is not None
    ngw, ngh = size1
    assert ngw == pytest.approx(80.0, abs=1e-4)
    assert ngh == pytest.approx(60.0, abs=1e-4)

    rel_x = b.pos[0] - a.pos[0]
    rel_y = b.pos[1] - a.pos[1]
    assert rel_x == pytest.approx(40.0 * scale_x, abs=1e-4)
    assert rel_y == pytest.approx(20.0 * scale_y, abs=1e-4)


def test_set_size_group_fixed_ratio_width_only(doc_editor):
    """Group resize with only width provided and fixed_ratio=True:
    height is calculated to preserve the group's aspect ratio."""
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (60, 60)
    b = WorkPiece(name="B")
    b.set_size(30, 20)
    b.pos = (100, 80)
    layer.add_child(a)
    layer.add_child(b)

    size0 = TransformCmd.get_size_group([a, b])
    assert size0 is not None
    cur_gw, cur_gh = size0
    aspect = cur_gw / cur_gh

    centre_before = TransformCmd.group_center_world([a, b])

    # Set width to 100, height should be computed from aspect ratio
    tc.set_size_group([a, b], width=100.0, height=None, fixed_ratio=True)

    size1 = TransformCmd.get_size_group([a, b])
    assert size1 is not None
    ngw, ngh = size1
    assert ngw == pytest.approx(100.0, abs=1e-4)
    assert ngh == pytest.approx(100.0 / aspect, abs=1e-4)
    # Centre must be preserved
    centre_after = TransformCmd.group_center_world([a, b])
    assert centre_after == pytest.approx(centre_before, abs=1e-6)


def test_set_size_group_fixed_ratio_height_only(doc_editor):
    """Group resize with only height provided and fixed_ratio=True:
    width is calculated to preserve the group's aspect ratio."""
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (60, 60)
    b = WorkPiece(name="B")
    b.set_size(30, 20)
    b.pos = (100, 80)
    layer.add_child(a)
    layer.add_child(b)

    size0 = TransformCmd.get_size_group([a, b])
    assert size0 is not None
    cur_gw, cur_gh = size0
    aspect = cur_gw / cur_gh

    centre_before = TransformCmd.group_center_world([a, b])

    # Set height to 80, width should be computed from aspect ratio
    tc.set_size_group([a, b], width=None, height=80.0, fixed_ratio=True)

    size1 = TransformCmd.get_size_group([a, b])
    assert size1 is not None
    ngw, ngh = size1
    assert ngh == pytest.approx(80.0, abs=1e-4)
    assert ngw == pytest.approx(80.0 * aspect, abs=1e-4)
    # Centre must be preserved
    centre_after = TransformCmd.group_center_world([a, b])
    assert centre_after == pytest.approx(centre_before, abs=1e-6)


# ── set_angle ─────────────────────────────────────────────────────


def test_set_angle(transform_cmd, sample_items):
    """Per-item angle set: each item's angle becomes 45° independently."""
    hm = transform_cmd._editor.history_manager
    initial_history_len = len(hm.undo_stack)
    initial_angle = sample_items[0].angle

    transform_cmd.set_angle(sample_items, 45.0)

    assert sample_items[0].angle == 45.0
    assert sample_items[1].angle == 45.0
    assert len(hm.undo_stack) == initial_history_len + 1
    hm.undo()
    assert sample_items[0].angle == initial_angle


def test_set_angle_preserves_centers(doc_editor):
    """Per-item angle: each item rotates around its own center, so
    world-space centres remain unchanged."""
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (0, 0)
    b = WorkPiece(name="B")
    b.set_size(20, 20)
    b.pos = (40, 0)
    layer.add_child(a)
    layer.add_child(b)

    ca0 = a.get_world_transform().transform_point((0.5, 0.5))
    cb0 = b.get_world_transform().transform_point((0.5, 0.5))

    tc.set_angle([a, b], 90.0)

    ca1 = a.get_world_transform().transform_point((0.5, 0.5))
    cb1 = b.get_world_transform().transform_point((0.5, 0.5))
    assert ca1 == pytest.approx(ca0, abs=1e-6)
    assert cb1 == pytest.approx(cb0, abs=1e-6)


# ── set_angle_group ───────────────────────────────────────────────


def test_set_angle_group_rotates_as_whole(doc_editor):
    """Group rotation: items rotate around the bounding-box centre;
    their world-space centres move but the group midpoint stays fixed."""
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (60, 60)
    b = WorkPiece(name="B")
    b.set_size(20, 20)
    b.pos = (100, 60)
    layer.add_child(a)
    layer.add_child(b)

    ca0 = a.get_world_transform().transform_point((0.5, 0.5))
    cb0 = b.get_world_transform().transform_point((0.5, 0.5))
    mid0 = ((ca0[0] + cb0[0]) / 2, (ca0[1] + cb0[1]) / 2)
    sep0 = math.hypot(cb0[0] - ca0[0], cb0[1] - ca0[1])

    tc.set_angle_group([a, b], 90.0)

    ca1 = a.get_world_transform().transform_point((0.5, 0.5))
    cb1 = b.get_world_transform().transform_point((0.5, 0.5))
    mid1 = ((ca1[0] + cb1[0]) / 2, (ca1[1] + cb1[1]) / 2)
    sep1 = math.hypot(cb1[0] - ca1[0], cb1[1] - ca1[1])

    assert a.angle == pytest.approx(90.0)
    assert b.angle == pytest.approx(90.0)
    assert mid1 == pytest.approx(mid0, abs=1e-6)
    assert sep1 == pytest.approx(sep0, abs=1e-6)

    # Items' centres MUST move (unlike per-item rotation).
    assert ca1 != pytest.approx(ca0, abs=1.0)
    assert cb1 != pytest.approx(cb0, abs=1.0)


# ── set_shear ─────────────────────────────────────────────────────


def test_set_shear(transform_cmd, sample_items):
    """Per-item shear set."""
    hm = transform_cmd._editor.history_manager
    initial_history_len = len(hm.undo_stack)
    initial_shear = sample_items[0].shear

    transform_cmd.set_shear(sample_items, 15.0)

    assert sample_items[0].shear == pytest.approx(15.0)
    assert sample_items[1].shear == pytest.approx(15.0)
    assert len(hm.undo_stack) == initial_history_len + 1
    hm.undo()
    assert sample_items[0].shear == initial_shear


def test_set_shear_preserves_centers(doc_editor):
    """Per-item shear: centres stay put."""
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (60, 60)
    b = WorkPiece(name="B")
    b.set_size(20, 20)
    b.pos = (100, 70)
    layer.add_child(a)
    layer.add_child(b)

    ca0 = a.get_world_transform().transform_point((0.5, 0.5))
    cb0 = b.get_world_transform().transform_point((0.5, 0.5))

    tc.set_shear([a, b], 25.0)

    ca1 = a.get_world_transform().transform_point((0.5, 0.5))
    cb1 = b.get_world_transform().transform_point((0.5, 0.5))
    assert ca1 == pytest.approx(ca0, abs=1e-6)
    assert cb1 == pytest.approx(cb0, abs=1e-6)
    assert a.shear == pytest.approx(25.0)
    assert b.shear == pytest.approx(25.0)
    # Reset converges in one call.
    tc.set_shear([a, b], 0.0)
    assert a.shear == pytest.approx(0.0, abs=1e-6)
    assert b.shear == pytest.approx(0.0, abs=1e-6)


# ── set_shear_group ──────────────────────────────────────────────


def test_set_shear_group_preserves_midpoint(doc_editor):
    """Group shear keeps the group's bounding-box centre fixed."""
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (60, 60)
    b = WorkPiece(name="B")
    b.set_size(20, 20)
    b.pos = (100, 70)
    layer.add_child(a)
    layer.add_child(b)

    centre0 = TransformCmd.group_center_world([a, b])

    tc.set_shear_group([a, b], 25.0)

    centre1 = TransformCmd.group_center_world([a, b])
    assert a.shear == pytest.approx(25.0, abs=1e-4)
    assert b.shear == pytest.approx(25.0, abs=1e-4)
    assert centre1 == pytest.approx(centre0, abs=1e-6)


def test_set_shear_group_reset_converges(doc_editor):
    """Shear reset must converge to 0 in a single call, even after
    multiple incremental shear steps."""
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (0, 0)
    b = WorkPiece(name="B")
    b.set_size(20, 20)
    b.pos = (40, 10)
    layer.add_child(a)
    layer.add_child(b)

    # Build up shear in two increments
    tc.set_shear_group([a, b], 10.0)
    tc.set_shear_group([a, b], 25.0)

    # Reset in one click
    tc.reset_shear_group([a, b])

    assert a.shear == pytest.approx(0.0, abs=1e-6)
    assert b.shear == pytest.approx(0.0, abs=1e-6)


# ── Resets ────────────────────────────────────────────────────────


def test_reset_position(transform_cmd, sample_items):
    with patch("swiftcut.doceditor.transform_cmd.get_context") as m:
        m.return_value.machine = None
        transform_cmd.reset_position(sample_items)
        assert sample_items[0].pos == (0.0, 0.0)
        assert sample_items[1].pos == (0.0, 0.0)


def test_reset_position_group(doc_editor):
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (10, 10)
    b = WorkPiece(name="B")
    b.set_size(30, 20)
    b.pos = (50, 30)
    layer.add_child(a)
    layer.add_child(b)

    with patch("swiftcut.doceditor.transform_cmd.get_context") as m:
        m.return_value.machine = None
        tc.reset_position_group([a, b])

    # Group bbox-min lands at (0,0).
    min_x, min_y, _, _ = TransformCmd.group_bbox_world([a, b])
    assert min_x == pytest.approx(0.0, abs=1e-6)
    assert min_y == pytest.approx(0.0, abs=1e-6)
    # Relative offsets preserved.
    assert (b.pos[0] - a.pos[0], b.pos[1] - a.pos[1]) == (40.0, 20.0)


def test_reset_angle(transform_cmd, sample_items):
    """Per-item: both angles back to 0."""
    transform_cmd.set_angle(sample_items, 45.0)
    transform_cmd.reset_angle(sample_items)
    assert sample_items[0].angle == pytest.approx(0.0)
    assert sample_items[1].angle == pytest.approx(0.0)


def test_reset_angle_group(doc_editor):
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (0, 0)
    b = WorkPiece(name="B")
    b.set_size(20, 20)
    b.pos = (40, 0)
    layer.add_child(a)
    layer.add_child(b)
    tc.set_angle_group([a, b], 90.0)
    tc.reset_angle_group([a, b])
    assert a.angle == pytest.approx(0.0)
    assert b.angle == pytest.approx(0.0)


def test_reset_shear(transform_cmd, sample_items):
    transform_cmd.set_shear(sample_items, 15.0)
    transform_cmd.reset_shear(sample_items)
    assert sample_items[0].shear == pytest.approx(0.0)
    assert sample_items[1].shear == pytest.approx(0.0)


def test_reset_shear_group(doc_editor):
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (0, 0)
    b = WorkPiece(name="B")
    b.set_size(20, 20)
    b.pos = (40, 10)
    layer.add_child(a)
    layer.add_child(b)
    tc.set_shear_group([a, b], 25.0)
    tc.reset_shear_group([a, b])
    assert a.shear == pytest.approx(0.0, abs=1e-4)
    assert b.shear == pytest.approx(0.0, abs=1e-4)


# ── Getters ───────────────────────────────────────────────────────


def test_get_position_group(doc_editor):
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (10, 10)
    b = WorkPiece(name="B")
    b.set_size(30, 20)
    b.pos = (50, 30)
    layer.add_child(a)
    layer.add_child(b)

    pos = tc.get_position_group([a, b])
    assert pos is not None
    # Without machine, world = machine so bbox-min is returned.
    assert pos == (10.0, 10.0)


def test_get_size_group(doc_editor):
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (10, 10)
    b = WorkPiece(name="B")
    b.set_size(30, 20)
    b.pos = (50, 30)
    layer.add_child(a)
    layer.add_child(b)

    sz = tc.get_size_group([a, b])
    # bbox: min(10,50) max(30,80) => (70, 40)
    assert sz == pytest.approx((70.0, 40.0))


def test_get_angle_group(doc_editor):
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (0, 0)
    layer.add_child(a)
    assert tc.get_angle_group([a]) == pytest.approx(0.0)


def test_get_shear_group(doc_editor):
    tc = TransformCmd(doc_editor)
    layer = Layer(name="L")
    doc_editor.doc.add_child(layer)
    a = WorkPiece(name="A")
    a.set_size(20, 20)
    a.pos = (0, 0)
    layer.add_child(a)
    assert tc.get_shear_group([a]) == pytest.approx(0.0)


# ── Bed bounds ────────────────────────────────────────────────────


@pytest.fixture
def bed_200x100():
    """A 200 x 100 mm bed whose machine coordinates are world ones."""
    machine = MagicMock()
    machine.axis_extents = (200, 100)
    machine.panel.machine_item_to_world.side_effect = lambda pos, size: pos
    with patch("swiftcut.doceditor.transform_cmd.get_context") as m:
        m.return_value.machine = machine
        yield


def _piece(doc_editor, name, size, pos):
    wp = WorkPiece(name=name)
    wp.set_size(*size)
    wp.pos = pos
    doc_editor.doc.active_layer.add_child(wp)
    return wp


def _box(items):
    min_x, min_y, max_x, max_y = TransformCmd.group_bbox_world(items)
    return min_x, min_y, max_x - min_x, max_y - min_y


@pytest.mark.parametrize(
    "target, landed",
    [
        ((500.0, 40.0), (180.0, 40.0)),
        ((-50.0, 40.0), (0.0, 40.0)),
        ((50.0, 500.0), (50.0, 90.0)),
        ((50.0, -50.0), (50.0, 0.0)),
        ((-50.0, -50.0), (0.0, 0.0)),
        ((500.0, 500.0), (180.0, 90.0)),
    ],
)
def test_a_typed_position_past_the_bed_is_clamped(
    doc_editor, bed_200x100, target, landed
):
    wp = _piece(doc_editor, "A", (20, 10), (50, 40))
    history = doc_editor.history_manager
    steps = len(history.undo_stack)

    TransformCmd(doc_editor).set_position([wp], *target)

    assert wp.pos == pytest.approx(landed)
    assert len(history.undo_stack) == steps + 1


def test_a_typed_group_position_past_the_bed_is_clamped(
    doc_editor, bed_200x100
):
    a = _piece(doc_editor, "A", (20, 10), (50, 40))
    b = _piece(doc_editor, "B", (30, 20), (90, 50))

    TransformCmd(doc_editor).set_position_group([a, b], 500.0, -50.0)

    assert _box([a, b]) == pytest.approx((130.0, 0.0, 70.0, 30.0))
    assert b.pos[0] - a.pos[0] == pytest.approx(40.0)


def test_a_typed_size_past_an_edge_keeps_its_size_inside(
    doc_editor, bed_200x100
):
    wp = _piece(doc_editor, "A", (20, 10), (170, 40))

    TransformCmd(doc_editor).set_size([wp], 50.0, 10.0)

    assert wp.size == pytest.approx((50.0, 10.0))
    assert _box([wp]) == pytest.approx((150.0, 40.0, 50.0, 10.0))


def test_a_typed_group_size_past_an_edge_keeps_its_size_inside(
    doc_editor, bed_200x100
):
    a = _piece(doc_editor, "A", (20, 10), (150, 80))
    b = _piece(doc_editor, "B", (20, 10), (175, 85))

    TransformCmd(doc_editor).set_size_group([a, b], 90.0, 30.0)

    assert _box([a, b]) == pytest.approx((110.0, 70.0, 90.0, 30.0))


@pytest.mark.parametrize("group", [False, True])
def test_a_typed_size_larger_than_the_bed_is_refused(
    doc_editor, bed_200x100, group
):
    wp = _piece(doc_editor, "A", (20, 10), (50, 40))
    before = wp.matrix.copy()
    history = doc_editor.history_manager
    steps = len(history.undo_stack)
    tc = TransformCmd(doc_editor)

    if group:
        tc.set_size_group([wp], 250.0, 10.0)
    else:
        tc.set_size([wp], 250.0, 10.0)

    assert wp.matrix == before
    assert len(history.undo_stack) == steps


def test_a_typed_angle_near_an_edge_turns_inside(doc_editor, bed_200x100):
    wp = _piece(doc_editor, "A", (60, 10), (0, 0))

    TransformCmd(doc_editor).set_angle([wp], 90.0)

    assert wp.angle == pytest.approx(90.0)
    assert _box([wp]) == pytest.approx((25.0, 0.0, 10.0, 60.0))


def test_a_typed_group_angle_near_an_edge_turns_inside(
    doc_editor, bed_200x100
):
    a = _piece(doc_editor, "A", (20, 10), (150, 80))
    b = _piece(doc_editor, "B", (20, 10), (180, 90))

    TransformCmd(doc_editor).set_angle_group([a, b], 90.0)

    assert a.angle == pytest.approx(90.0)
    assert b.angle == pytest.approx(90.0)
    assert inside(_box([a, b]), (0, 0, 200, 100))
    assert _box([a, b])[1] + _box([a, b])[3] == pytest.approx(100.0)


# A 40 mm square flush with each edge and corner of the bed, centred
# between the others, and those edges (0 left, 1 bottom, 2 right,
# 3 top). Its turned box is never smaller, so it ends flush again.
FLUSH = [
    ((0, 30), (0,)),
    ((160, 30), (2,)),
    ((80, 0), (1,)),
    ((80, 60), (3,)),
    ((0, 0), (0, 1)),
    ((160, 0), (2, 1)),
    ((0, 60), (0, 3)),
    ((160, 60), (2, 3)),
]


@pytest.mark.parametrize("pos, edges", FLUSH)
@pytest.mark.parametrize("angle", [90.0, 45.0, -30.0])
@pytest.mark.parametrize("group", [False, True])
def test_a_typed_angle_at_each_edge_and_corner_turns_inside(
    doc_editor, bed_200x100, pos, edges, angle, group
):
    history = doc_editor.history_manager
    steps = len(history.undo_stack)
    tc = TransformCmd(doc_editor)

    if group:
        # The square's two halves, turned as one about its centre.
        items = [
            _piece(doc_editor, "A", (40, 20), pos),
            _piece(doc_editor, "B", (40, 20), (pos[0], pos[1] + 20)),
        ]
        tc.set_angle_group(items, angle)
    else:
        items = [_piece(doc_editor, "A", (40, 40), pos)]
        tc.set_angle(items, angle)

    for item in items:
        assert item.angle == pytest.approx(angle)
    assert inside(_box(items), (0, 0, 200, 100))
    box = TransformCmd.group_bbox_world(items)
    for edge in edges:
        assert box[edge] == pytest.approx((0, 0, 200, 100)[edge])
    assert len(history.undo_stack) == steps + 1


@pytest.mark.parametrize("group", [False, True])
def test_a_typed_angle_too_long_for_the_bed_is_refused(
    doc_editor, bed_200x100, group
):
    wp = _piece(doc_editor, "A", (150, 10), (20, 45))
    before = wp.matrix.copy()
    history = doc_editor.history_manager
    steps = len(history.undo_stack)
    tc = TransformCmd(doc_editor)

    if group:
        tc.set_angle_group([wp], 90.0)
    else:
        tc.set_angle([wp], 90.0)

    assert wp.matrix == before
    assert len(history.undo_stack) == steps


@pytest.mark.parametrize("group", [False, True])
def test_a_typed_shear_near_an_edge_stays_inside(
    doc_editor, bed_200x100, group
):
    wp = _piece(doc_editor, "A", (20, 20), (0, 40))
    tc = TransformCmd(doc_editor)

    if group:
        tc.set_shear_group([wp], 30.0)
    else:
        tc.set_shear([wp], 30.0)

    assert wp.shear == pytest.approx(30.0)
    assert inside(_box([wp]), (0, 0, 200, 100))
    assert _box([wp])[0] == pytest.approx(0.0)


def test_a_nudge_at_an_edge_is_a_no_op_without_an_undo_step(
    doc_editor, bed_200x100
):
    wp = _piece(doc_editor, "A", (20, 10), (0, 40))
    history = doc_editor.history_manager
    steps = len(history.undo_stack)

    TransformCmd(doc_editor).nudge_items([wp], -1.0, 0.0)

    assert wp.pos == pytest.approx((0.0, 40.0))
    assert len(history.undo_stack) == steps


def test_a_nudge_past_an_edge_stops_on_it(doc_editor, bed_200x100):
    wp = _piece(doc_editor, "A", (20, 10), (175, 40))

    TransformCmd(doc_editor).nudge_items([wp], 10.0, 0.0)

    assert wp.pos == pytest.approx((180.0, 40.0))


@pytest.mark.asyncio
async def test_a_nudge_stops_on_the_active_bed_after_a_switch(
    doc_editor, task_mgr
):
    """The clamp reads the active machine: once ilab-626 (900 x 900) is
    active, a nudge stops on its edge, not on ilab-614's."""
    context = doc_editor.context
    machines = {}
    for name, extents in (
        ("ilab-614", (1400, 900)),
        ("ilab-626", (900, 900)),
    ):
        machine = Machine(context)
        machine.name = name
        machine.set_axis_extents(*extents)
        context.machine_mgr.add_machine(machine)
        machines[name] = machine
    context.config.set_machine(machines["ilab-614"])
    a = _piece(doc_editor, "A", (20, 10), (850, 40))
    TransformCmd(doc_editor).nudge_items([a], 100.0, 0.0)
    assert a.pos == pytest.approx((950.0, 40.0))

    context.config.set_machine(machines["ilab-626"])
    b = _piece(doc_editor, "B", (20, 10), (850, 40))
    TransformCmd(doc_editor).nudge_items([b], 100.0, 0.0)

    assert b.pos == pytest.approx((880.0, 40.0))
    # The switch rebuilds the pipeline after its debounce: wait for
    # the rebuild, not only for the tasks already running.
    assert await asyncio.to_thread(doc_editor.wait_until_settled_sync, 10)
    await asyncio.to_thread(task_mgr.wait_until_settled, 10000)

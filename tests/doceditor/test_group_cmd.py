from pathlib import Path

import ezdxf
import numpy as np
import pytest
from raygeo.geo import Geometry, Matrix

from swiftcut.core.group import Group
from swiftcut.core.item import DocItem
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor


@pytest.fixture
def doc_editor(task_mgr, context_initializer):
    """
    Provides a DocEditor instance using the standard, fully-initialized
    test context provided by the `context_initializer` fixture.
    """
    editor = DocEditor(task_manager=task_mgr, context=context_initializer)
    yield editor
    # The editor's cleanup handles its internal resources like the pipeline.
    # The fixtures will handle their own teardown (context, task manager).
    editor.cleanup()


@pytest.mark.asyncio
async def test_group_and_ungroup_preserves_transform(doc_editor: DocEditor):
    """
    Tests that grouping and then ungrouping items restores their original
    local transformations relative to their parent layer. This is the core
    test for the user-reported bug.
    """
    # 1. Setup: Create items with known transforms in the active layer
    layer = doc_editor.doc.active_layer

    wp1 = WorkPiece(name="wp1.svg")
    # A simple translation and scale
    wp1.matrix = Matrix.translation(10, 20) @ Matrix.scale(5, 5)
    layer.add_child(wp1)

    wp2 = WorkPiece(name="wp2.svg")
    # A more complex transform with rotation
    wp2.matrix = (
        Matrix.translation(50, 60) @ Matrix.rotation(45) @ Matrix.scale(8, 2)
    )
    layer.add_child(wp2)

    # Capture original state (local matrices and world transforms for
    # good measure)
    original_wp1_matrix = wp1.matrix.copy()
    original_wp2_matrix = wp2.matrix.copy()
    original_wp1_world = wp1.get_world_transform()
    original_wp2_world = wp2.get_world_transform()

    # 2. Group the items using the command handler
    # Explicitly type hint the list to satisfy type checkers (List[Sub] is not
    # a subtype of List[Base]).
    items_to_group: list[DocItem] = [wp1, wp2]
    doc_editor.group.group_items(layer, items_to_group)
    await doc_editor.wait_until_settled(timeout=2)

    # Assert that grouping worked as expected
    assert len(layer.get_content_items()) == 1
    group = layer.get_content_items()[0]
    assert isinstance(group, Group)
    assert len(group.children) == 2
    assert wp1 in group.children
    assert wp2 in group.children

    # World transforms must be preserved after grouping
    assert wp1.get_world_transform() == original_wp1_world
    assert wp2.get_world_transform() == original_wp2_world

    # 3. Ungroup the items using the command handler
    doc_editor.group.ungroup_items([group])
    await doc_editor.wait_until_settled()

    # 4. Assert: Check if items are back in the layer with original transforms
    content_items = layer.get_content_items()
    assert len(content_items) == 2
    assert wp1 in content_items
    assert wp2 in content_items
    assert group.parent is None  # Group should be detached

    # The critical check: are the local matrices restored?
    assert wp1.matrix == original_wp1_matrix
    assert wp2.matrix == original_wp2_matrix

    # Double check world transforms as well
    assert wp1.get_world_transform() == original_wp1_world
    assert wp2.get_world_transform() == original_wp2_world


def _rect(geo: Geometry, x0, y0, x1, y1):
    geo.move_to(x0, y0)
    geo.line_to(x1, y0)
    geo.line_to(x1, y1)
    geo.line_to(x0, y1)
    geo.close_path()


def _multi_path_workpiece(layer, matrix: Matrix) -> WorkPiece:
    """A shape of three paths: an outline, a hole in it and a line."""
    geo = Geometry()
    _rect(geo, 0.0, 0.0, 0.5, 1.0)
    _rect(geo, 0.1, 0.2, 0.4, 0.8)
    geo.move_to(0.7, 0.0)
    geo.line_to(1.0, 1.0)
    wp = WorkPiece(name="paths")
    wp._edited_boundaries = geo
    wp.matrix = matrix
    layer.add_child(wp)
    return wp


def _square_workpiece(layer, x, y) -> WorkPiece:
    """A 10 mm square at (x, y): a single path."""
    geo = Geometry()
    _rect(geo, 0.0, 0.0, 1.0, 1.0)
    wp = WorkPiece(name="square")
    wp._edited_boundaries = geo
    wp.matrix = Matrix.translation(x, y) @ Matrix.scale(10, 10)
    layer.add_child(wp)
    return wp


def _world_paths(workpieces):
    """Sorted world rects of every path, and their total length."""
    contours = [
        contour
        for wp in workpieces
        for contour in wp.get_world_geometry().split_into_contours()
    ]
    rects = sorted(contour.rect() for contour in contours)
    return rects, sum(contour.distance() for contour in contours)


def _assert_same_paths(actual, expected):
    rects, length = actual
    expected_rects, expected_length = expected
    assert len(rects) == len(expected_rects)
    for rect, expected_rect in zip(rects, expected_rects, strict=True):
        assert rect == pytest.approx(expected_rect, abs=1e-6)
    assert length == pytest.approx(expected_length)


def test_ungroup_splits_a_shape_into_its_paths_in_one_undo_step(
    doc_editor: DocEditor,
):
    layer = doc_editor.doc.active_layer
    matrix = (
        Matrix.translation(30, 40) @ Matrix.rotation(30) @ Matrix.scale(40, 20)
    )
    wp = _multi_path_workpiece(layer, matrix)
    before = _world_paths([wp])
    history = doc_editor.history_manager
    entries = len(history.undo_stack)

    pieces = doc_editor.group.ungroup_items([wp])

    assert len(pieces) == 3
    assert wp not in layer.children
    assert all(piece in layer.children for piece in pieces)
    _assert_same_paths(_world_paths(pieces), before)
    assert len(history.undo_stack) == entries + 1

    history.undo()
    assert [c.uid for c in layer.get_content_items()] == [wp.uid]
    _assert_same_paths(_world_paths([wp]), before)

    history.redo()
    assert layer.get_content_items() == pieces
    _assert_same_paths(_world_paths(pieces), before)


def test_ungroup_of_a_single_path_is_a_no_op(doc_editor: DocEditor):
    layer = doc_editor.doc.active_layer
    wp = _square_workpiece(layer, 0, 0)
    history = doc_editor.history_manager
    entries = len(history.undo_stack)

    assert doc_editor.group.ungroup_items([wp]) == []

    assert layer.get_content_items() == [wp]
    assert len(history.undo_stack) == entries


@pytest.mark.asyncio
async def test_group_then_ungroup_round_trip(doc_editor: DocEditor):
    """
    Group is one undo step and hands the new group to on_done; Ungroup
    restores the items where they were, with the same geometry.
    """
    layer = doc_editor.doc.active_layer
    a = _square_workpiece(layer, 0, 0)
    b = _multi_path_workpiece(
        layer, Matrix.translation(50, 10) @ Matrix.scale(30, 30)
    )
    before = _world_paths([a, b])
    worlds = [a.get_world_transform(), b.get_world_transform()]
    history = doc_editor.history_manager
    entries = len(history.undo_stack)
    done: list[Group] = []

    doc_editor.group.group_items(layer, [a, b], on_done=done.append)
    await doc_editor.wait_until_settled(timeout=2)

    (group,) = done
    assert layer.get_content_items() == [group]
    assert set(group.children) == {a, b}
    assert len(history.undo_stack) == entries + 1
    _assert_same_paths(_world_paths([a, b]), before)

    assert set(doc_editor.group.ungroup_items([group])) == {a, b}

    assert set(layer.get_content_items()) == {a, b}
    assert [a.get_world_transform(), b.get_world_transform()] == worlds
    _assert_same_paths(_world_paths([a, b]), before)
    assert len(history.undo_stack) == entries + 2

    history.undo()
    assert layer.get_content_items() == [group]
    history.undo()
    assert set(layer.get_content_items()) == {a, b}
    assert [a.get_world_transform(), b.get_world_transform()] == worlds


@pytest.mark.asyncio
async def test_ungroup_of_a_group_and_a_shape_is_one_undo_step(
    doc_editor: DocEditor,
):
    layer = doc_editor.doc.active_layer
    a = _square_workpiece(layer, 0, 0)
    b = _square_workpiece(layer, 20, 0)
    done: list[Group] = []
    doc_editor.group.group_items(layer, [a, b], on_done=done.append)
    await doc_editor.wait_until_settled(timeout=2)
    (group,) = done
    shape = _multi_path_workpiece(
        layer, Matrix.translation(50, 10) @ Matrix.scale(30, 30)
    )
    history = doc_editor.history_manager
    entries = len(history.undo_stack)

    ungrouped = doc_editor.group.ungroup_items([group, shape])

    assert len(ungrouped) == 2 + 3
    assert set(layer.get_content_items()) == set(ungrouped)
    assert len(history.undo_stack) == entries + 1

    history.undo()
    assert set(layer.get_content_items()) == {group, shape}
    assert set(group.children) == {a, b}


def test_ungroup_keeps_paths_under_a_tenth_of_a_mm(doc_editor: DocEditor):
    """Split drops such dust; Ungroup keeps every path."""
    layer = doc_editor.doc.active_layer
    geo = Geometry()
    _rect(geo, 0.0, 0.0, 0.5, 1.0)
    geo.move_to(0.7, 0.0)
    geo.line_to(1.0, 1.0)
    # A 0.05 x 0.05 mm square on the 40 x 20 mm shape.
    _rect(geo, 0.6, 0.5, 0.60125, 0.5025)
    wp = WorkPiece(name="dust")
    wp._edited_boundaries = geo
    wp.matrix = Matrix.scale(40, 20)
    layer.add_child(wp)
    before = _world_paths([wp])

    pieces = doc_editor.group.ungroup_items([wp])

    assert len(pieces) == 3
    _assert_same_paths(_world_paths(pieces), before)


def _lines_svg(path: Path) -> Path:
    """
    A 100 x 60 mm SVG: a rectangle, a horizontal line and a vertical
    line, none touching.
    """
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
        'height="60mm" viewBox="0 0 100 60">'
        '<rect x="10" y="10" width="20" height="30" fill="none" '
        'stroke="black" stroke-width="0.5"/>'
        '<line x1="40" y1="20" x2="90" y2="20" stroke="black" '
        'stroke-width="0.5"/>'
        '<line x1="60" y1="30" x2="60" y2="55" stroke="black" '
        'stroke-width="0.5"/></svg>'
    )
    return path


# A horizontal and a vertical line in mm, and the lines of _lines_dxf.
_H_LINE = ((0, 50), (90, 50))
_V_LINE = ((60, 0), (60, 40))


def _lines_dxf(path: Path, *lines, rect: bool = True) -> Path:
    """A DXF in mm of the lines, with a 40 x 30 rectangle if rect."""
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    if rect:
        msp.add_lwpolyline([(0, 0), (40, 0), (40, 30), (0, 30)], close=True)
    for start, end in lines:
        msp.add_line(start, end)
    doc.saveas(path)
    return path


async def _import(editor: DocEditor, path: Path) -> list[WorkPiece]:
    """Imports a file as a single shape; returns what it added."""
    before = {wp.uid for wp in editor.doc.all_workpieces}
    await editor.import_file_from_path(path, None, PassthroughSpec())
    return [wp for wp in editor.doc.all_workpieces if wp.uid not in before]


def _ink(wp: WorkPiece, px_per_mm: float = 10) -> int:
    """The opaque pixels of the workpiece rendered at its size."""
    width, height = wp.size
    surface = wp.render_to_pixels(
        round(width * px_per_mm), round(height * px_per_mm)
    )
    assert surface is not None
    pixels = np.ndarray(
        (surface.get_height(), surface.get_stride() // 4, 4),
        dtype=np.uint8,
        buffer=surface.get_data(),
    )
    return int((pixels[:, : surface.get_width(), 3] > 128).sum())


@pytest.mark.asyncio
async def test_ungrouped_svg_line_pieces_render_their_line(
    doc_editor: DocEditor, test_machine_and_config, tmp_path
):
    """
    A horizontal or vertical line piece is 1 mm across, like a lone
    line imported (not a sliver too thin to render), and stays put.
    """
    (wp,) = await _import(doc_editor, _lines_svg(tmp_path / "lines.svg"))
    before = _world_paths([wp])

    pieces = doc_editor.group.ungroup_items([wp])

    assert len(pieces) == 3
    _assert_same_paths(_world_paths(pieces), before)
    lines = [p for p in pieces if not p.boundaries.is_closed()]
    assert sorted(p.size for p in lines) == [
        pytest.approx((1.0, 25.0)),
        pytest.approx((50.0, 1.0)),
    ]
    for piece in pieces:
        assert _ink(piece) > 0


@pytest.mark.asyncio
async def test_ungrouped_dxf_line_pieces_are_sized_like_a_lone_line(
    doc_editor: DocEditor, test_machine_and_config, tmp_path
):
    """
    The importer gives a lone horizontal or vertical line 1 mm across;
    a line piece gets the same, and stays put.
    """
    lone = []
    for name, line in (("h", _H_LINE), ("v", _V_LINE)):
        path = _lines_dxf(tmp_path / f"{name}.dxf", line, rect=False)
        (single,) = await _import(doc_editor, path)
        lone.append(single.size)
    path = _lines_dxf(tmp_path / "lines.dxf", _H_LINE, _V_LINE)
    (wp,) = await _import(doc_editor, path)
    before = _world_paths([wp])

    pieces = doc_editor.group.ungroup_items([wp])

    assert len(pieces) == 3
    _assert_same_paths(_world_paths(pieces), before)
    assert lone == [pytest.approx((90.0, 1.0)), pytest.approx((1.0, 40.0))]
    lines = [p for p in pieces if not p.boundaries.is_closed()]
    assert sorted(p.size for p in lines) == sorted(lone)

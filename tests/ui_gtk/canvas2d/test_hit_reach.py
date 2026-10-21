"""A pointer over one of many pieces tests that piece, not all of them:
a layer runs the stroke, inside and pixel tests only on the children
whose box, grown by the stroke hit distance, holds the point. A piece
that moves is found where it went.
"""

import pytest
from gi.repository import Gtk
from raygeo.geo import Geometry

from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.canvas2d.elements.workpiece import WorkPieceElement
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface

pytestmark = pytest.mark.ui


def _square():
    geo = Geometry()
    geo.move_to(0.0, 0.0)
    geo.line_to(1.0, 0.0)
    geo.line_to(1.0, 1.0)
    geo.line_to(0.0, 1.0)
    geo.close_path()
    return geo


@pytest.fixture
def grid(ui_context_initializer, ui_task_mgr):
    """A 10 x 10 grid of 10 mm squares, 15 mm apart, on a surface."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    s = WorkSurface(editor, Gtk.Window(), machine)
    s.get_width = lambda: 800
    s.get_height = lambda: 600
    s._rebuild_view_transform()
    pieces = []
    for n in range(100):
        wp = WorkPiece(name=f"wp{n}")
        wp._edited_boundaries = _square()
        wp.set_size(10, 10)
        wp.pos = (15 * (n % 10), 15 * (n // 10))
        editor.doc.active_layer.add_child(wp)
        pieces.append(wp)
    s.update_from_doc()
    yield s, pieces
    editor.cleanup()


@pytest.fixture
def stroke_tests(monkeypatch):
    tested = []
    near = WorkPieceElement.is_near_stroke

    def counting(elem, x, y):
        tested.append(elem.data)
        return near(elem, x, y)

    monkeypatch.setattr(WorkPieceElement, "is_near_stroke", counting)
    return tested


def test_a_motion_over_one_piece_tests_that_piece(grid, stroke_tests):
    s, pieces = grid
    target = pieces[55]
    x, y = target.pos

    hit = s._get_body_hit(x, y + 5)  # on the square's left edge

    assert hit is s.find_by_data(target)
    assert set(stroke_tests) == {target}


def test_a_moved_piece_is_hit_where_it_went(grid, stroke_tests):
    s, pieces = grid
    moved = pieces[0]
    s._get_body_hit(*moved.pos)  # fills the reach boxes

    moved.pos = (60, 160)
    hit = s._get_body_hit(60, 165)

    assert hit is s.find_by_data(moved)
    assert s._get_body_hit(0, 5) is None

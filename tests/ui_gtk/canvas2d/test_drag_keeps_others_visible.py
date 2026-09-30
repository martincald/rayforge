"""While a selection is moved, only its own ops hide: every other
object on the canvas keeps drawing its ops. A pan or zoom still hides
them all, and the restore after idle brings every one back.
"""

from unittest.mock import MagicMock

import cairo
import pytest
from gi.repository import Gdk, GLib, Gtk
from raygeo.geo import Geometry

from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface

pytestmark = pytest.mark.ui


def _square():
    """A closed square filling the workpiece's box."""
    geo = Geometry()
    geo.move_to(0.0, 0.0)
    geo.line_to(1.0, 0.0)
    geo.line_to(1.0, 1.0)
    geo.line_to(0.0, 1.0)
    geo.close_path()
    return geo


@pytest.fixture
def surface(ui_context_initializer, ui_task_mgr):
    """A real editor and an 800x600 surface; returns them with a
    function adding a workpiece with a path, on top of the rest."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    s = WorkSurface(editor, Gtk.Window(), machine)
    s.get_width = lambda: 800
    s.get_height = lambda: 600
    s._rebuild_view_transform()

    def add(geometry, pos, size):
        wp = WorkPiece(name="wp")
        wp._edited_boundaries = geometry
        wp.set_size(*size)
        wp.pos = pos
        editor.doc.active_layer.add_child(wp)
        s.update_from_doc()
        elem = s.find_by_data(wp)
        assert elem is not None
        return wp, elem

    yield editor, s, add

    editor.cleanup()


def _screen(s, elem, local_x, local_y):
    """A point in an element's local space, on screen."""
    to_screen = s.view_transform @ elem.get_world_transform()
    return to_screen.transform_point((local_x, local_y))


def _select(s, elem):
    elem.selected = True
    s._finalize_selection_state()


def _press(s, x, y):
    gesture = MagicMock()
    gesture.get_current_event.return_value = None
    gesture.get_button.return_value = Gdk.BUTTON_PRIMARY
    gesture.get_start_point.return_value = (True, x, y)
    s._drag_gesture = gesture
    s.on_button_press(gesture, 1, x, y)
    return gesture


@pytest.fixture
def dragging(surface):
    """Two objects, A and B; A is selected and mid-drag."""
    _, s, add = surface
    _, elem_a = add(_square(), (20, 20), (40, 30))
    _, elem_b = add(_square(), (120, 100), (40, 30))
    _select(s, elem_a)

    gesture = _press(s, *_screen(s, elem_a, 0.5, 0.5))
    s.on_mouse_drag(gesture, 30, -20)
    assert s._moving
    return s, elem_a, elem_b, gesture


def test_a_move_drag_suppresses_only_the_moving_element(dragging):
    s, elem_a, elem_b, _ = dragging

    assert s.ops_suppressed_for(elem_a) is True
    assert s.ops_suppressed_for(elem_b) is False
    assert s.ops_suppressed is False


def test_every_other_element_still_reaches_its_ops_stage_mid_drag(
    dragging, monkeypatch
):
    s, elem_a, elem_b, _ = dragging
    ops_a, ops_b = MagicMock(), MagicMock()
    monkeypatch.setattr(elem_a, "_draw_ops", ops_a)
    monkeypatch.setattr(elem_b, "_draw_ops", ops_b)

    target = cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 600)
    ctx = cairo.Context(target)
    ctx.transform(cairo.Matrix(*s.view_transform.for_cairo()))
    s.root.render(ctx)

    ops_b.assert_called_once()
    ops_a.assert_not_called()


def test_after_the_drag_ends_nothing_is_suppressed(dragging):
    s, elem_a, elem_b, gesture = dragging
    s.on_drag_end(gesture, 30, -20)

    # The restore waits for idle; until then the moved object's ops
    # stay hidden.
    assert s.ops_suppressed_for(elem_a) is True
    assert s._ops_restore_timer_id is not None
    GLib.source_remove(s._ops_restore_timer_id)
    s._restore_ops()

    assert s.ops_suppressed_for(elem_a) is False
    assert s.ops_suppressed_for(elem_b) is False


def test_pan_still_suppresses_every_element(surface):
    _, s, add = surface
    _, elem_a = add(_square(), (20, 20), (40, 30))
    _, elem_b = add(_square(), (120, 100), (40, 30))

    s.on_pan_begin(MagicMock(), 400, 300)

    assert s.ops_suppressed is True
    assert s.ops_suppressed_for(elem_a) is True
    assert s.ops_suppressed_for(elem_b) is True

"""Object snapping on the work surface: a snapped drag draws its guide
above a scene that still draws every object; arrow nudges move the
selection 1 mm, 10 mm with Shift, snapped after, in one undo step; and
a change to the document drops the lines a drag snaps to."""

from unittest.mock import MagicMock

import cairo
import pytest
from gi.repository import Gdk, Gtk
from raygeo.geo import Geometry

from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.canvas.overlays import ACCENT_RGB
from swiftcut.ui_gtk.canvas.snapping import SNAP_DISTANCE_PX
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface
from swiftcut.ui_gtk.shared.keyboard import (
    PRIMARY_MODIFIER_MASK,
    SNAP_OVERRIDE_MASK,
    is_primary_modifier,
)

pytestmark = pytest.mark.ui

NO_MODS = Gdk.ModifierType(0)


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
    """A real editor and an 800x600 surface on a 200x200 bed, with B,
    30x20 at (120, 100), and A, 30x20 wherever a test puts it,
    selected."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    s = WorkSurface(editor, Gtk.Window(), machine)
    s.get_width = lambda: 800
    s.get_height = lambda: 600
    s._rebuild_view_transform()

    def add(pos):
        wp = WorkPiece(name="wp")
        wp._edited_boundaries = _square()
        wp.set_size(30, 20)
        wp.pos = pos
        editor.doc.active_layer.add_child(wp)
        s.update_from_doc()
        elem = s.find_by_data(wp)
        assert elem is not None
        return wp, elem

    def place_a(pos):
        wp_a, elem_a = add(pos)
        elem_a.selected = True
        s._finalize_selection_state()
        return wp_a, elem_a

    _, elem_b = add((120, 100))
    yield editor, s, place_a, elem_b

    editor.cleanup()


def _reach(s):
    """How near a line snaps, in mm."""
    return SNAP_DISTANCE_PX / s.view_transform.get_abs_scale()[0]


def _press(s, x, y):
    gesture = MagicMock()
    gesture.get_current_event.return_value = None
    gesture.get_button.return_value = Gdk.BUTTON_PRIMARY
    gesture.get_start_point.return_value = (True, x, y)
    s._drag_gesture = gesture
    s.on_button_press(gesture, 1, x, y)
    return gesture


def _drag_by(s, elem, dx_mm, dy_mm):
    """Presses on elem's middle and drags it by (dx_mm, dy_mm)."""
    to_screen = s.view_transform @ elem.get_world_transform()
    x, y = to_screen.transform_point((0.5, 0.5))
    gesture = _press(s, x, y)
    wx, wy = s._get_world_coords(x, y)
    tx, ty = s.view_transform.transform_point((wx + dx_mm, wy + dy_mm))
    s.on_mouse_drag(gesture, tx - x, ty - y)
    return gesture, (tx - x, ty - y)


def _pixel(target, x, y):
    """The RGB of a pixel of an ARGB32 surface, 0-255."""
    target.flush()
    data = target.get_data()
    i = int(y) * target.get_stride() + int(x) * 4
    b, g, r = data[i], data[i + 1], data[i + 2]
    return r, g, b


def _overlays(s):
    target = cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 600)
    s._render_overlays(cairo.Context(target))
    return target


ACCENT = tuple(round(c * 255) for c in ACCENT_RGB)


def test_a_snapped_drag_draws_its_guide_over_every_object(
    surface, monkeypatch
):
    _, s, place_a, elem_b = surface
    _, elem_a = place_a((20, 20))

    # A's left edge half a millimetre past B's, 20 mm up.
    gesture, offset = _drag_by(s, elem_a, 100.5, 20)

    assert s._snap_guides == [
        (pytest.approx((120, 40)), pytest.approx((120, 120)))
    ]
    # Midway up the guide, clear of A's selection frame.
    gx, gy = s.view_transform.transform_point((120, 80))
    target = _overlays(s)
    assert _pixel(target, round(gx), gy) == ACCENT
    assert _pixel(target, round(gx) + 3, gy) != ACCENT

    ops_a, ops_b = MagicMock(), MagicMock()
    monkeypatch.setattr(elem_a, "_draw_ops", ops_a)
    monkeypatch.setattr(elem_b, "_draw_ops", ops_b)
    scene = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 600))
    scene.transform(cairo.Matrix(*s.view_transform.for_cairo()))
    s.root.render(scene)
    ops_a.assert_called_once()
    ops_b.assert_called_once()

    s.on_drag_end(gesture, *offset)
    assert _pixel(_overlays(s), round(gx), gy) != ACCENT


def test_the_dropped_object_lands_on_the_line(surface):
    _, s, place_a, _ = surface
    wp_a, elem_a = place_a((20, 20))

    gesture, offset = _drag_by(s, elem_a, 100.5, 20)
    s.on_drag_end(gesture, *offset)

    assert wp_a.pos == pytest.approx((120, 40))


@pytest.mark.parametrize(
    "keyval, mods, moved",
    [
        (Gdk.KEY_Right, NO_MODS, (1, 0)),
        (Gdk.KEY_Left, NO_MODS, (-1, 0)),
        (Gdk.KEY_Up, NO_MODS, (0, 1)),
        (Gdk.KEY_Down, NO_MODS, (0, -1)),
        (Gdk.KEY_Right, Gdk.ModifierType.SHIFT_MASK, (10, 0)),
        (Gdk.KEY_Down, Gdk.ModifierType.SHIFT_MASK, (0, -10)),
    ],
)
def test_arrows_nudge_the_selection_and_undo_in_one_step(
    surface, keyval, mods, moved
):
    editor, s, place_a, _ = surface
    wp_a, _ = place_a((20, 20))

    assert s.on_key_pressed(None, keyval, 0, mods) is True
    assert wp_a.pos == pytest.approx((20 + moved[0], 20 + moved[1]))

    editor.history_manager.undo()
    assert wp_a.pos == pytest.approx((20, 20))


def test_a_nudge_lands_on_a_line_in_reach(surface):
    editor, s, place_a, _ = surface
    start_x = 120 - 1 - _reach(s) / 2
    wp_a, _ = place_a((start_x, 20))

    s.on_key_pressed(None, Gdk.KEY_Right, 0, NO_MODS)

    assert wp_a.pos == pytest.approx((120, 20))
    editor.history_manager.undo()
    assert wp_a.pos == pytest.approx((start_x, 20))


@pytest.mark.parametrize("mods", [PRIMARY_MODIFIER_MASK, SNAP_OVERRIDE_MASK])
def test_the_fine_nudge_and_the_override_do_not_snap(surface, mods):
    _, s, place_a, _ = surface
    start_x = 120 - 1 - _reach(s) / 2
    wp_a, _ = place_a((start_x, 20))
    step = 0.1 if is_primary_modifier(mods) else 1.0

    s.on_key_pressed(None, Gdk.KEY_Right, 0, mods)

    assert wp_a.pos == pytest.approx((start_x + step, 20))


def test_the_snapping_toggle_leaves_a_nudge_exact(surface):
    _, s, place_a, _ = surface
    start_x = 120 - 1 - _reach(s) / 2
    wp_a, _ = place_a((start_x, 20))
    s.object_snap_enabled = False

    s.on_key_pressed(None, Gdk.KEY_Right, 0, NO_MODS)

    assert wp_a.pos == pytest.approx((start_x + 1, 20))


def test_a_document_change_drops_the_snap_lines(surface):
    editor, s, place_a, elem_b = surface
    _, elem_a = place_a((20, 20))
    _drag_by(s, elem_a, 10, 10)
    assert s._snap_lines is not None

    elem_b.data.pos = (130, 100)
    assert s._snap_lines is None

    _drag_by(s, elem_a, 12, 10)
    assert s._snap_lines is not None
    editor.doc.active_layer.add_child(WorkPiece(name="new"))
    assert s._snap_lines is None

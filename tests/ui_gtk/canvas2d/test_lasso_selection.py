"""Alt (Option on macOS) and a drag from the empty canvas draw a lasso:
on release it selects the shapes whose box center lies inside it, Shift
keeping the selection before it. A hidden layer's shapes are passed
over, and a plain drag still draws the rubber band.
"""

from unittest.mock import MagicMock, patch

import pytest
from gi.repository import Gdk, Gtk
from raygeo.geo import Geometry

from swiftcut.core.layer import Layer
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface

pytestmark = pytest.mark.ui

# A C opening to the right, in world mm: its notch is x 50..130,
# y 50..90.
C_LASSO = [
    (10, 10),
    (130, 10),
    (130, 50),
    (50, 50),
    (50, 90),
    (130, 90),
    (130, 130),
    (10, 130),
]


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
    """A real editor and an 800x600 surface with layers A (active) and
    B; returns them with a function adding a 10 mm square to a layer."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    s = WorkSurface(editor, Gtk.Window(), machine)
    s.get_width = lambda: 800
    s.get_height = lambda: 600
    s._rebuild_view_transform()
    layer_a = editor.doc.active_layer
    layer_b = Layer(name="B")
    editor.doc.add_child(layer_b)
    s.update_from_doc()

    def add(layer, pos):
        wp = WorkPiece(name="square")
        wp._edited_boundaries = _square()
        wp.set_size(10, 10)
        wp.pos = pos
        layer.add_child(wp)
        s.update_from_doc()
        assert s.find_by_data(wp) is not None
        return wp

    yield editor, s, layer_a, layer_b, add

    editor.cleanup()


def _gesture(s, x, y, mods):
    """A primary-button gesture starting at (x, y) with the modifiers."""
    event = MagicMock()
    event.get_modifier_state.return_value = mods
    gesture = MagicMock()
    gesture.get_current_event.return_value = event
    gesture.get_button.return_value = Gdk.BUTTON_PRIMARY
    gesture.get_start_point.return_value = (True, x, y)
    s._drag_gesture = gesture
    return gesture


def _along(points, step=3.0):
    """The closed path through the points, every step pixels or less."""
    path = []
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        n = max(1, int(max(abs(x2 - x1), abs(y2 - y1)) / step))
        path.extend(
            (x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(n)
        )
    return path


def _drag(s, world_points, mods, release=True):
    """Presses at the first world point and drags through the others."""
    to_screen = s.view_transform.transform_point
    screen = [to_screen(p) for p in world_points]
    start_x, start_y = screen[0]
    gesture = _gesture(s, start_x, start_y, mods)
    s.on_button_press(gesture, 1, start_x, start_y)
    for x, y in _along(screen)[1:]:
        s.on_mouse_drag(gesture, x - start_x, y - start_y)
    if release:
        last_x, last_y = screen[0]
        s.on_drag_end(gesture, last_x - start_x, last_y - start_y)
    return gesture


def _selected(s):
    return set(s.get_selected_items())


ALT = Gdk.ModifierType.ALT_MASK
SHIFT = Gdk.ModifierType.SHIFT_MASK


class TestLasso:
    def test_selects_by_box_center_inside_a_concave_lasso(self, surface):
        _, s, layer_a, _, add = surface
        bottom_arm = add(layer_a, (85, 25))
        top_arm = add(layer_a, (85, 105))
        spine = add(layer_a, (25, 65))
        add(layer_a, (85, 65))  # in the notch
        add(layer_a, (160, 65))  # outside
        # Its box reaches into the lasso, its center does not.
        add(layer_a, (128, 25))

        _drag(s, C_LASSO, ALT)

        assert _selected(s) == {bottom_arm, top_arm, spine}

    def test_selects_at_the_release_only(self, surface):
        _, s, layer_a, _, add = surface
        bottom_arm = add(layer_a, (85, 25))

        gesture = _drag(s, C_LASSO, ALT, release=False)

        assert s._lasso_points and s._selection_frame_rect is None
        assert _selected(s) == set()

        s.on_drag_end(gesture, 0, 0)

        assert _selected(s) == {bottom_arm}
        assert s._lasso_points is None

    def test_passes_over_a_hidden_layer(self, surface):
        editor, s, layer_a, layer_b, add = surface
        hidden = add(layer_a, (25, 65))
        shown = add(layer_b, (85, 25))
        editor.layer.set_layer_visibility(layer_a, False)

        _drag(s, C_LASSO, ALT)

        assert _selected(s) == {shown}
        assert hidden not in _selected(s)

    def test_shift_keeps_the_selection_before_it(self, surface):
        _, s, layer_a, _, add = surface
        outside = add(layer_a, (160, 65))
        spine = add(layer_a, (25, 65))
        s.select_items([outside])

        _drag(s, C_LASSO, ALT | SHIFT)

        assert _selected(s) == {outside, spine}

    def test_without_shift_it_replaces_the_selection(self, surface):
        _, s, layer_a, _, add = surface
        outside = add(layer_a, (160, 65))
        spine = add(layer_a, (25, 65))
        s.select_items([outside])

        _drag(s, C_LASSO, ALT)

        assert _selected(s) == {spine}

    def test_skips_pointer_steps_under_two_pixels(self, surface):
        _, s, _, _, _ = surface
        gesture = _gesture(s, 20, 20, ALT)
        s.on_button_press(gesture, 1, 20, 20)

        s.on_mouse_drag(gesture, 1, 0)
        s.on_mouse_drag(gesture, 1.5, 1)
        assert s._lasso_points == [(20, 20)]

        s.on_mouse_drag(gesture, 3, 0)
        assert s._lasso_points == [(20, 20), (23, 20)]

    def test_is_drawn_like_the_rubber_band(self, surface):
        _, s, _, _, _ = surface
        _drag(s, C_LASSO, ALT, release=False)
        ctx = MagicMock()

        with patch.object(s, "_paint_selection_frame") as paint:
            s._render_overlays(ctx)

        paint.assert_called_once_with(ctx)
        ctx.move_to.assert_any_call(*s._lasso_points[0])
        ctx.line_to.assert_any_call(*s._lasso_points[-1])

    def test_a_click_selects_nothing(self, surface):
        _, s, layer_a, _, add = surface
        add(layer_a, (25, 65))
        x, y = s.view_transform.transform_point((10, 10))
        gesture = _gesture(s, x, y, ALT)

        s.on_button_press(gesture, 1, x, y)
        s.on_click_released(gesture, 1, x, y)

        assert _selected(s) == set()
        assert s._lasso_points is None


class TestPlainDrag:
    def test_still_draws_the_rubber_band(self, surface):
        _, s, layer_a, _, add = surface
        in_the_notch = add(layer_a, (85, 65))
        to_screen = s.view_transform.transform_point
        left, top = to_screen((10, 130))
        right, bottom = to_screen((130, 10))
        gesture = _gesture(s, left, top, Gdk.ModifierType(0))

        s.on_button_press(gesture, 1, left, top)
        s.on_mouse_drag(gesture, right - left, bottom - top)

        assert s._framing_selection and s._lasso_points is None
        assert s._selection_frame_rect is not None
        # The band selects live, by overlap.
        assert _selected(s) == {in_the_notch}

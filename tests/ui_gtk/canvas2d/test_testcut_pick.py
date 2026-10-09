"""Where the test cut goes, on the canvas.

The marker is a 10 mm square whose start corner sits an offset away
from the job's start corner, the point the start-corner overlay marks.
By default it is outside the job, 15 mm beside the start corner's X
edge and level with its Y edge. In pick mode a click centers it on the
click; Escape and a right-click give up.
"""

import itertools
from unittest.mock import MagicMock

import pytest
from gi.repository import Gdk, Gtk
from raygeo.geo import Geometry

from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.cmd import TEST_CUT_SIZE_MM, default_test_cut_offset
from swiftcut.machine.models.machine import Machine, Origin, StartCorner
from swiftcut.machine.models.machine_panel import PanelOrientation
from swiftcut.ui_gtk.canvas2d.elements.testcut_marker import (
    square_from_corner,
)
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface

pytestmark = pytest.mark.ui

LEFT = (StartCorner.TOP_LEFT, StartCorner.BOTTOM_LEFT)
TOP = (StartCorner.TOP_LEFT, StartCorner.TOP_RIGHT)


def _square():
    geo = Geometry()
    geo.move_to(0.0, 0.0)
    geo.line_to(1.0, 0.0)
    geo.line_to(1.0, 1.0)
    geo.line_to(0.0, 1.0)
    geo.close_path()
    return geo


@pytest.fixture
def surface(ui_context_initializer, ui_task_mgr):
    """A real editor and an 800x600 surface with one 40x30 shape."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    s = WorkSurface(editor, Gtk.Window(), machine)
    s.get_width = lambda: 800
    s.get_height = lambda: 600
    s._rebuild_view_transform()
    wp = WorkPiece(name="square")
    wp._edited_boundaries = _square()
    wp.set_size(40, 30)
    wp.pos = (60, 50)
    editor.doc.active_layer.add_child(wp)
    s.update_from_doc()

    yield s, machine, wp

    editor.cleanup()


def _press(s, x, y, button=Gdk.BUTTON_PRIMARY):
    gesture = MagicMock()
    gesture.get_current_event.return_value = None
    gesture.get_button.return_value = button
    gesture.get_start_point.return_value = (True, x, y)
    s._drag_gesture = gesture
    s.on_button_press(gesture, 1, x, y)


def _record(signal):
    seen = []
    signal.connect(lambda sender, **kw: seen.append(kw), weak=False)
    return seen


def test_the_marker_is_hidden_until_asked_for(surface):
    s, _machine, _wp = surface

    assert s._test_cut_marker.visible is False
    assert s._test_cut_marker.selectable is False


def test_the_job_start_corner_is_the_overlays(surface):
    s, machine, _wp = surface
    x, y, w, h = s._start_corner_element.rect()

    for corner in StartCorner:
        machine.set_start_corner(corner)

        assert s.job_start_corner() == (
            x if corner in LEFT else x + w,
            y + h if corner in TOP else y,
        )


@pytest.mark.parametrize("corner", list(StartCorner))
def test_the_default_spot_is_beside_the_start_corners_x_edge(
    surface, corner
):
    s, machine, _wp = surface
    machine.set_start_corner(corner)
    x, y, w, h = s._start_corner_element.rect()

    s.show_test_cut_marker(default_test_cut_offset(corner))

    mx, my, mw, mh = s._test_cut_marker.rect()
    assert (mw, mh) == (10.0, 10.0)
    assert s._test_cut_marker.visible
    if corner in LEFT:
        # Its right edge 15 mm left of the job's left edge.
        assert mx + mw == pytest.approx(x - 15.0)
    else:
        assert mx == pytest.approx(x + w + 15.0)
    if corner in TOP:
        assert my + mh == pytest.approx(y + h)
    else:
        assert my == pytest.approx(y)


def test_hiding_the_marker(surface):
    s, _machine, _wp = surface
    s.show_test_cut_marker((-25.0, 0.0))

    s.hide_test_cut_marker()

    assert s._test_cut_marker.visible is False


@pytest.mark.parametrize("corner", list(StartCorner))
def test_a_picked_spot_centers_the_square_on_the_click(surface, corner):
    s, machine, _wp = surface
    machine.set_start_corner(corner)
    picked = _record(s.test_cut_spot_picked)
    s.set_test_cut_pick_mode(True)

    _press(s, *s.view_transform.transform_point((30.0, 20.0)))

    (kwargs,) = picked
    s.show_test_cut_marker(kwargs["offset"])
    mx, my, mw, mh = s._test_cut_marker.rect()
    assert (mx + mw / 2, my + mh / 2) == pytest.approx((30.0, 20.0))


def test_the_offset_is_from_the_job_start_corner_to_the_squares(surface):
    """Corner to corner, so it is what the head moves by."""
    s, machine, _wp = surface
    machine.set_start_corner(StartCorner.TOP_LEFT)
    start = s.job_start_corner()
    picked = _record(s.test_cut_spot_picked)
    s.set_test_cut_pick_mode(True)

    _press(s, *s.view_transform.transform_point((30.0, 20.0)))

    # The square's top-left corner is (25, 25).
    assert picked[0]["offset"] == pytest.approx(
        (25.0 - start[0], 25.0 - start[1])
    )


def test_outside_pick_mode_a_click_picks_nothing(surface):
    s, _machine, _wp = surface
    picked = _record(s.test_cut_spot_picked)

    _press(s, *s.view_transform.transform_point((30.0, 20.0)))

    assert picked == []


def test_a_right_click_gives_up(surface):
    s, _machine, _wp = surface
    picked = _record(s.test_cut_spot_picked)
    cancelled = _record(s.test_cut_pick_cancelled)
    s.set_test_cut_pick_mode(True)

    s.on_right_click_pressed(MagicMock(), 1, 100.0, 100.0)

    assert (picked, cancelled) == ([], [{}])


def test_escape_gives_up(surface):
    s, _machine, _wp = surface
    cancelled = _record(s.test_cut_pick_cancelled)
    s.set_test_cut_pick_mode(True)

    assert s.on_key_pressed(MagicMock(), Gdk.KEY_Escape, 0, 0) is True

    assert cancelled == [{}]


def test_outside_pick_mode_escape_is_not_taken(surface):
    s, _machine, _wp = surface
    cancelled = _record(s.test_cut_pick_cancelled)

    s.on_key_pressed(MagicMock(), Gdk.KEY_Escape, 0, 0)

    assert cancelled == []


def test_with_no_job_there_is_nowhere_to_put_it(surface):
    s, _machine, wp = surface
    s.editor.doc.active_layer.remove_child(wp)
    s.update_from_doc()
    cancelled = _record(s.test_cut_pick_cancelled)

    s.show_test_cut_marker((-25.0, 0.0))
    s.set_test_cut_pick_mode(True)
    _press(s, *s.view_transform.transform_point((30.0, 20.0)))

    assert s.job_start_corner() is None
    assert s._test_cut_marker.visible is False
    assert cancelled == [{}]


# The square is cut where the marker shows it, on every machine.


def _corners(x, y, w, h) -> set[tuple[float, float]]:
    """A rect's four corners, rounded so equal points compare equal."""
    return {
        (round(x + dx, 6) + 0.0, round(y + dy, 6) + 0.0)
        for dx in (0.0, w)
        for dy in (0.0, h)
    }


def _span(points) -> tuple[float, float, float, float]:
    xs = sorted(x for x, _ in points)
    ys = sorted(y for _, y in points)
    return xs[0], ys[0], xs[-1], ys[-1]


def _native(panel, start, rect) -> set[tuple[float, float]]:
    """A canvas rect's corners, from start, in native axes."""
    return {
        (round(nx, 6) + 0.0, round(ny, 6) + 0.0)
        for nx, ny in (
            panel.visual_offset_to_native(x - start[0], y - start[1])
            for x, y in _corners(*rect)
        )
    }


def _cut(panel, corner, offset) -> set[tuple[float, float]]:
    """
    The corners of the square cut after a jog by offset: the driver's
    start-corner move, then the square, in native axes.
    """
    size = TEST_CUT_SIZE_MM
    nx, ny = panel.visual_offset_to_native(*offset)
    sx, sy = panel.start_corner_offset(corner, size, size)
    return _corners(nx + sx, ny + sy, size, size)


@pytest.mark.parametrize("corner", list(StartCorner))
def test_the_square_is_cut_where_the_marker_shows_it(
    ui_context_initializer, corner
):
    """
    For every origin, axis reversal and panel orientation, the
    marker's corners, taken from the job's start corner into native
    axes as the head is jogged there, are the corners of the square
    the driver cuts from that spot: its start-corner move, then 10 mm
    in native axes. The default spot never overlaps the job.
    """
    jx, jy, jw, jh = 100.0, 200.0, 60.0, 40.0
    start = (
        jx if corner in LEFT else jx + jw,
        jy + jh if corner in TOP else jy,
    )
    for convention in itertools.product(
        Origin, (False, True), (False, True), PanelOrientation
    ):
        origin, reverse_x, reverse_y, orientation = convention
        machine = Machine(ui_context_initializer)
        machine.set_axis_extents(800.0, 600.0)
        machine.set_origin(origin)
        machine.set_reverse_x_axis(reverse_x)
        machine.set_reverse_y_axis(reverse_y)
        machine.panel.set_orientation(orientation)
        machine.set_start_corner(corner)
        panel = machine.panel

        for offset in (
            default_test_cut_offset(corner),
            (12.0, -30.0),
            (-7.5, 44.0),
        ):
            marker = square_from_corner(
                (start[0] + offset[0], start[1] + offset[1]),
                corner,
                TEST_CUT_SIZE_MM,
            )
            assert _native(panel, start, marker) == _cut(
                panel, corner, offset
            ), (convention, offset)

        # The job is cut from its start corner the same way, so the
        # default square, beside it on the canvas, is beside it on the
        # bed too.
        job = _native(panel, start, (jx, jy, jw, jh))
        x0, y0, x1, y1 = _span(job)
        sx, sy = panel.start_corner_offset(corner, x1 - x0, y1 - y0)
        assert job == _corners(sx, sy, x1 - x0, y1 - y0), convention
        square = _cut(panel, corner, default_test_cut_offset(corner))
        qx0, qy0, qx1, qy1 = _span(square)
        assert qx1 <= x0 or x1 <= qx0 or qy1 <= y0 or y1 <= qy0, convention

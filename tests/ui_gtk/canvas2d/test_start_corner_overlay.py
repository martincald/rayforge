"""The canvas overlay and the tooltips that explain the start corner.

A crosshair sits on the selected corner of the job's bounding box and
a dashed tick points toward the opposite corner; each toggle's tooltip
says the same thing in words. The overlay shows only while the toggles
are hovered and for a moment after the corner changes, then fades.
"""

import itertools
from unittest.mock import MagicMock, patch

import cairo
import pytest
from gi.repository import GLib

from swiftcut.machine.models.machine import (
    JogDirection,
    Machine,
    StartCorner,
)
from swiftcut.ui_gtk.canvas2d.elements import start_corner
from swiftcut.ui_gtk.canvas2d.elements.start_corner import StartCornerElement

WIDTH, HEIGHT = 50.0, 30.0

# Local space is y-up, so the top edge is at y = HEIGHT.
EXPECTED = {
    StartCorner.TOP_LEFT: ((0.0, HEIGHT), (WIDTH, 0.0)),
    StartCorner.TOP_RIGHT: ((WIDTH, HEIGHT), (0.0, 0.0)),
    StartCorner.BOTTOM_LEFT: ((0.0, 0.0), (WIDTH, HEIGHT)),
    StartCorner.BOTTOM_RIGHT: ((WIDTH, 0.0), (0.0, HEIGHT)),
}


def _element(corner: StartCorner) -> StartCornerElement:
    element = StartCornerElement()
    element.set_job((10.0, 20.0, WIDTH, HEIGHT), corner)
    return element


@pytest.mark.parametrize("corner", list(StartCorner))
def test_the_marker_is_on_the_selected_corner(corner):
    head, opposite = _element(corner).head_and_opposite()

    assert (head, opposite) == EXPECTED[corner]


def test_the_overlay_covers_the_job_box_without_showing():
    element = _element(StartCorner.TOP_LEFT)

    assert element.rect() == (10.0, 20.0, WIDTH, HEIGHT)
    assert element.visible is False


@pytest.fixture
def timers(monkeypatch):
    """GLib timeouts recorded instead of run: {id: (ms, callback)}."""
    pending: dict[int, tuple[int, object]] = {}
    ids = itertools.count(1)

    def timeout_add(ms, callback):
        source_id = next(ids)
        pending[source_id] = (ms, callback)
        return source_id

    monkeypatch.setattr(GLib, "timeout_add", timeout_add)
    monkeypatch.setattr(GLib, "source_remove", pending.pop)
    return pending


def _fade_out(element: StartCornerElement) -> int:
    """Runs the fade's frames to the end; returns how many there were."""
    frames = 1
    while element._fade_step() == GLib.SOURCE_CONTINUE:
        frames += 1
        assert frames < 100
    return frames


def test_show_makes_it_visible_at_full_strength(timers):
    element = _element(StartCorner.TOP_LEFT)
    element.alpha = 0.3

    element.show()

    assert element.visible is True
    assert element.alpha == 1.0


def test_without_a_job_nothing_shows(timers):
    element = StartCornerElement()

    element.show()
    element.set_hovered(True)

    assert element.visible is False


def test_a_flash_holds_then_fades_out(timers):
    element = _element(StartCorner.TOP_LEFT)

    element.flash()

    assert element.visible is True
    ((hold_ms, end_hold),) = timers.values()
    assert hold_ms == start_corner._HOLD_MS == 1500
    assert end_hold() == GLib.SOURCE_REMOVE
    # The hold's end started the fade.
    assert [ms for ms, _ in timers.values()] == [1500, start_corner._FRAME_MS]

    frames = _fade_out(element)

    assert element.alpha == 0.0
    assert element.visible is False
    # About a quarter of a second of frames.
    assert frames * start_corner._FRAME_MS == pytest.approx(250, abs=16)


def test_hovering_shows_it_and_leaving_fades_it(timers):
    element = _element(StartCorner.TOP_LEFT)

    element.set_hovered(True)
    assert element.visible is True
    assert timers == {}

    element.set_hovered(False)
    assert [ms for ms, _ in timers.values()] == [start_corner._FRAME_MS]
    _fade_out(element)
    assert element.visible is False


def test_leaving_during_a_flash_waits_for_the_hold(timers):
    element = _element(StartCorner.TOP_LEFT)
    element.flash()

    element.set_hovered(False)

    # Only the hold is pending; the fade starts when it ends.
    assert [ms for ms, _ in timers.values()] == [start_corner._HOLD_MS]
    assert element.visible is True


def test_a_hovered_flash_does_not_fade(timers):
    element = _element(StartCorner.TOP_LEFT)
    element.set_hovered(True)
    element.flash()
    ((_, end_hold),) = timers.values()

    end_hold()

    # No fade was started: the hold is the only timeout there was.
    assert len(timers) == 1
    assert element.visible is True


def test_the_fade_dims_the_drawing():
    element = _element(StartCorner.TOP_LEFT)
    element.show()

    def head_alpha():
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 120)
        ctx = cairo.Context(surface)
        ctx.translate(0, 120)
        ctx.scale(4.0, -4.0)
        element.draw(ctx)
        surface.flush()
        # One pixel along the crosshair's horizontal hair, on row 0.
        return _alpha_at(surface, 3, 0)

    full = head_alpha()
    element.alpha = 0.5
    assert 0 < head_alpha() < full


def _alpha_at(surface: cairo.ImageSurface, x: int, y: int) -> int:
    stride = surface.get_stride()
    return surface.get_data()[y * stride + x * 4 + 3]


@pytest.mark.parametrize("corner", list(StartCorner))
def test_it_draws_at_the_head_not_at_the_opposite_corner(corner):
    """Rendered the way the canvas does: mm, y-up, 4 px per mm."""
    element = _element(corner)
    element.show()
    scale = 4.0
    width_px, height_px = int(WIDTH * scale), int(HEIGHT * scale)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width_px, height_px)
    ctx = cairo.Context(surface)
    ctx.translate(0, height_px)
    ctx.scale(scale, -scale)

    element.draw(ctx)
    surface.flush()

    (hx, hy), (ox, oy) = element.head_and_opposite()

    def to_px(x, y):
        return (
            min(int(x * scale), width_px - 1),
            min(int(height_px - y * scale), height_px - 1),
        )

    # The crosshair crosses on the head; the far corner is untouched.
    assert _alpha_at(surface, *to_px(hx, hy)) > 0
    assert _alpha_at(surface, *to_px(ox, oy)) == 0


@pytest.fixture
def surface(lite_context):
    """A WorkSurface without GTK init, holding a real overlay element."""
    from swiftcut.ui_gtk.canvas2d.surface import WorkSurface

    s = WorkSurface.__new__(WorkSurface)
    s._start_corner_element = StartCornerElement()
    s._start_corner_seen = None
    s.queue_draw = MagicMock()
    s.editor = MagicMock()
    s.machine = Machine(lite_context)
    return s


def _update(surface):
    with patch(
        "swiftcut.ui_gtk.canvas2d.surface.TransformCmd.group_bbox_world",
        return_value=(10.0, 20.0, 60.0, 50.0),
    ):
        surface._update_start_corner_element()


def test_the_surface_puts_it_on_the_job_box(surface):
    surface.editor.doc.all_workpieces = [MagicMock()]
    surface.machine.set_start_corner(StartCorner.BOTTOM_RIGHT)

    _update(surface)

    element = surface._start_corner_element
    # The first placement only moves it.
    assert element.visible is False
    assert element.rect() == (10.0, 20.0, 50.0, 30.0)
    assert element.corner is StartCorner.BOTTOM_RIGHT


def test_the_surface_flashes_it_when_the_corner_changes(surface, timers):
    surface.editor.doc.all_workpieces = [MagicMock()]
    surface.machine.set_start_corner(StartCorner.BOTTOM_RIGHT)
    element = surface._start_corner_element
    element.flash = MagicMock(wraps=element.flash)

    _update(surface)
    _update(surface)
    assert element.flash.call_count == 0

    surface.machine.set_start_corner(StartCorner.TOP_LEFT)
    _update(surface)

    element.flash.assert_called_once_with()
    assert element.visible is True
    assert element.corner is StartCorner.TOP_LEFT


def test_the_surface_passes_the_selector_hover_on(surface, timers):
    surface.editor.doc.all_workpieces = [MagicMock()]
    _update(surface)

    surface.set_start_corner_hovered(True)
    assert surface._start_corner_element.visible is True

    surface.set_start_corner_hovered(False)
    _fade_out(surface._start_corner_element)
    assert surface._start_corner_element.visible is False


def test_no_job_hides_it(surface):
    surface.editor.doc.all_workpieces = []
    surface._start_corner_element.set_visible(True)

    surface._update_start_corner_element()

    assert surface._start_corner_element.visible is False
    # And hovering the selector does not bring back a stale marker.
    surface.set_start_corner_hovered(True)
    assert surface._start_corner_element.visible is False


_WORDS = {
    JogDirection.EAST: "right",
    JogDirection.WEST: "left",
    JogDirection.SOUTH: "bottom",
    JogDirection.NORTH: "top",
}


def test_each_tooltip_names_the_corner_the_job_grows_toward():
    from swiftcut.ui_gtk.doceditor.bottom_panel import _START_CORNER_BUTTONS

    for corner, _icon, tooltip in _START_CORNER_BUTTONS:
        horizontal, vertical = corner.toward_opposite
        toward = f"{_WORDS[vertical]}-{_WORDS[horizontal]}"
        assert tooltip == f"Start here, cut toward {toward}"
    assert [c for c, _i, _t in _START_CORNER_BUTTONS] == list(StartCorner)


@pytest.mark.ui
def test_hovering_the_toggles_is_announced(
    ui_context_initializer, ui_task_mgr
):
    from swiftcut.doceditor.editor import DocEditor
    from swiftcut.ui_gtk.doceditor.bottom_panel import BottomPanel

    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    try:
        panel = BottomPanel(
            ui_context_initializer.config.machine, editor, MagicMock()
        )
        heard = []
        panel.start_corner_hovered.connect(
            lambda sender, **kw: heard.append((sender, kw["hovered"])),
            weak=False,
        )
        motion = panel._start_corner_motion
        # On the box that holds the four toggles.
        assert {
            button.get_parent()
            for button in panel._start_corner_buttons.values()
        } == {motion.get_widget()}

        motion.emit("enter", 1.0, 1.0)
        motion.emit("leave")

        assert heard == [(panel, True), (panel, False)]
    finally:
        editor.cleanup()


def test_the_window_passes_the_hover_to_the_canvas():
    from swiftcut.ui_gtk.mainwindow import MainWindow

    win = MagicMock()

    MainWindow._on_start_corner_hovered(win, None, hovered=True)

    win.surface.set_start_corner_hovered.assert_called_once_with(True)

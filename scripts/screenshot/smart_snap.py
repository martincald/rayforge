"""Capture object snapping mid-drag, with its guide.

Run with::

    python -m swiftcut.app --config <isolated-config> \\
        --uiscript scripts/screenshot/smart_snap.py

Loads ``tests/assets/contour.ryp``, moves its workpiece near the bed's
left edge, adds a copy at 60 % size, zooms in on the two, and drags
the copy so that, released, it would land 0.6 mm off a line: the
other object's left edge, its centre, and the bed's left edge, each
time clear of every line on the other axis. Each drag is captured
before release, snapped and with its guide, into
``docs/screens/smart-snap/`` or ``$SMART_SNAP_OUT``, then undone.

Like ``selection_handles.py`` this renders through GTK's own renderer
and feeds the drags to the canvas's handlers directly.
"""

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import TypeVar

from gi.repository import Adw, Gdk, GLib, Graphene, Gtk

from swiftcut.ui_gtk.canvas.snapping import SNAP_DISTANCE_PX
from swiftcut.uiscript import app, win

logger = logging.getLogger(__name__)

T = TypeVar("T")

PROJECT_ROOT = Path(__file__).parent.parent.parent
PROJECT = PROJECT_ROOT / "tests" / "assets" / "contour.ryp"
OUTPUT_DIR = Path(
    os.environ.get(
        "SMART_SNAP_OUT",
        PROJECT_ROOT / "docs" / "screens" / "smart-snap",
    )
)
SIZE = (1440, 900)
SETTLE = 1.0
# sc_window_bg, light (docs/design/swift-cut-tokens.md).
WINDOW_BG = "#F5F5F7"
# How far off the line each drag would land unsnapped, in mm.
MISS = 0.6
ZOOM = 3.5
_FLAG = "_smart_snap_running"


def run_on_main_thread(func: Callable[[], T], timeout: float = 20.0) -> T:
    """Run func on the GTK main thread and wait for its result."""
    result: list[T] = []
    error: list[BaseException | None] = [None]
    done = Event()

    def wrapper() -> bool:
        try:
            result.append(func())
        except BaseException as e:  # noqa: BLE001 - main-thread callback
            error[0] = e
        finally:
            done.set()
        return GLib.SOURCE_REMOVE

    GLib.idle_add(wrapper)
    if not done.wait(timeout=timeout):
        raise TimeoutError(f"main-thread call exceeded {timeout}s")
    if error[0] is not None:
        raise error[0]
    return result[0]


def _capture(widget: Gtk.Widget, name: str) -> None:
    """Render one widget into a PNG over the window colour."""
    native = widget.get_native()
    assert native is not None
    renderer = native.get_renderer()
    assert renderer is not None
    width, height = widget.get_width(), widget.get_height()
    snapshot = Gtk.Snapshot()
    rgba = Gdk.RGBA()
    rgba.parse(WINDOW_BG)
    snapshot.append_color(rgba, Graphene.Rect().init(0, 0, width, height))
    Gtk.WidgetPaintable.new(widget).snapshot(snapshot, width, height)
    node = snapshot.to_node()
    assert node is not None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    renderer.render_texture(node, None).save_to_png(
        str(OUTPUT_DIR / f"{name}.png")
    )


class _Gesture:
    """Stands in for the click and drag gestures of one primary press."""

    def __init__(self, x: float, y: float):
        self._start = (x, y)

    def get_button(self) -> int:
        return Gdk.BUTTON_PRIMARY

    def get_current_event(self):
        return None

    def get_start_point(self) -> tuple[bool, float, float]:
        return True, *self._start


def _setup():
    """Places the original B near the bed's left edge and a 60 % copy
    A, which the drags move, selected, and frames the two. Returns A
    and B."""
    (wp_b,) = win.doc_editor.doc.all_workpieces[:1]
    (wp_a,) = win.doc_editor.edit.duplicate_items([wp_b])
    w, h = wp_b.size
    wp_b.pos = (1.6 * w, 180.0)
    wp_a.set_size(w * 0.6, h * 0.6)
    wp_a.pos = (20.0, 60.0)
    win.surface.select_items([wp_a])
    _frame(1.6 * w, 180.0 + h)
    logger.info("workpiece %s x %s", w, h)
    return wp_a, wp_b


def _frame(x: float, y: float) -> None:
    """Zooms to ZOOM and pans so world (x, y) sits mid-canvas."""
    surface = win.surface
    surface.set_zoom(ZOOM)
    for _ in range(3):
        sx, sy = surface.view_transform.transform_point((x, y))
        scale_x, scale_y = surface.view_transform.get_abs_scale()
        surface.set_pan(
            surface.pan_x_mm + (sx - surface.get_width() / 2) / scale_x,
            surface.pan_y_mm - (sy - surface.get_height() / 2) / scale_y,
        )
    logger.info(
        "framed at %s px",
        surface.view_transform.transform_point((x, y)),
    )


def _begin_drag(wp_a, left: float, bottom: float):
    """Presses on A's middle and drags it, without releasing, to where
    its box would sit at (left, bottom) unsnapped."""
    surface = win.surface
    elem = surface.find_by_data(wp_a)
    to_screen = surface.view_transform @ elem.get_world_transform()
    x, y = to_screen.transform_point((0.5, 0.5))
    ax, ay = elem.get_world_bounding_box()[:2]
    wx, wy = surface._get_world_coords(x, y)
    tx, ty = surface.view_transform.transform_point(
        (wx + left - ax, wy + bottom - ay)
    )
    gesture = _Gesture(x, y)
    surface._real_drag_gesture = surface._drag_gesture
    surface._drag_gesture = gesture
    surface.on_motion(None, x, y)
    surface.on_button_press(gesture, 1, x, y)
    surface.on_mouse_drag(gesture, tx - x, ty - y)
    surface.queue_draw()
    logger.info("guides: %s", surface._snap_guides)
    return gesture, (tx - x, ty - y)


def _end_drag(gesture: _Gesture, offset: tuple[float, float]) -> None:
    """Release a drag and undo what it did."""
    surface = win.surface
    surface.on_drag_end(gesture, *offset)
    surface._drag_gesture = surface._real_drag_gesture
    del surface._real_drag_gesture
    win.doc_editor.history_manager.undo()
    surface.on_motion_leave(None)


def _capture_snaps(wp_a, wp_b) -> None:
    surface = win.surface
    bx, by, bw, bh = surface.find_by_data(wp_b).get_world_bounding_box()
    aw = surface.find_by_data(wp_a).get_world_bounding_box()[2]
    reach = SNAP_DISTANCE_PX / surface.view_transform.get_abs_scale()[1]
    # Above B, three snaps' reach clear of its top.
    bottom = by + bh + 3 * reach
    drags = {
        "edge": bx + MISS,
        "center": bx + bw / 2 - aw / 2 + MISS,
        "bed-edge": MISS,
    }
    for name, left in drags.items():
        gesture, offset = run_on_main_thread(
            lambda left=left: _begin_drag(wp_a, left, bottom)
        )
        time.sleep(0.3)
        run_on_main_thread(lambda name=name: _capture(surface, name))
        run_on_main_thread(
            lambda gesture=gesture, offset=offset: _end_drag(gesture, offset)
        )


def main() -> None:
    if getattr(win, _FLAG, False):
        return
    setattr(win, _FLAG, True)
    # Whatever happens below, the app does not outlive the run.
    GLib.timeout_add_seconds(120, app.quit_idle)
    try:
        time.sleep(2)
        run_on_main_thread(
            lambda: win.doc_editor.file.load_project_from_path(PROJECT)
        )
        if not win.doc_editor.wait_until_settled_sync(timeout=20):
            logger.warning("document did not settle; capturing anyway")
        content = win.toast_overlay
        run_on_main_thread(lambda: content.set_size_request(*SIZE))
        run_on_main_thread(
            lambda: Adw.StyleManager.get_default().set_color_scheme(
                Adw.ColorScheme.FORCE_LIGHT
            )
        )
        time.sleep(SETTLE)
        wp_a, wp_b = run_on_main_thread(_setup)
        if not win.doc_editor.wait_until_settled_sync(timeout=20):
            logger.warning("copy did not settle; capturing anyway")
        time.sleep(1.5)
        _capture_snaps(wp_a, wp_b)
        run_on_main_thread(lambda: content.set_size_request(-1, -1))
        logger.info("smart snap captures written to %s", OUTPUT_DIR)
    finally:
        app.quit_idle()


main()

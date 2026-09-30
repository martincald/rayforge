"""Capture the canvas selection handles and the start-corner overlay.

Run with::

    python -m swiftcut.app --config <isolated-config> \\
        --uiscript scripts/screenshot/selection_handles.py

Loads ``tests/assets/contour.ryp``, selects its first workpiece and
captures the canvas in the light and the dark theme into
``docs/screens/selection-handles/`` or ``$SELECTION_HANDLES_OUT``:
idle, hovering a corner handle, mid-rotate, mid-resize, and the
start-corner overlay while its selector is hovered (with nothing
selected, so no handle covers it).

Like ``dock_fit.py`` this renders through GTK's own renderer and does
not import ``utils``. The rotate and resize drags are fed to the
canvas's handlers directly, as the canvas tests do, then undone.
"""

import logging
import math
import os
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import TypeVar

from gi.repository import Adw, Gdk, GLib, Graphene, Gtk

from swiftcut.ui_gtk.canvas.region import ElementRegion, handle_anchor
from swiftcut.uiscript import app, win

logger = logging.getLogger(__name__)

T = TypeVar("T")

PROJECT_ROOT = Path(__file__).parent.parent.parent
PROJECT = PROJECT_ROOT / "tests" / "assets" / "contour.ryp"
OUTPUT_DIR = Path(
    os.environ.get(
        "SELECTION_HANDLES_OUT",
        PROJECT_ROOT / "docs" / "screens" / "selection-handles",
    )
)
SIZE = (1440, 900)
SETTLE = 1.0
# sc_window_bg, light and dark (docs/design/swift-cut-tokens.md).
WINDOW_BG = {False: "#F5F5F7", True: "#1C1C1E"}
_FLAG = "_selection_handles_running"


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


def _capture(widget: Gtk.Widget, name: str, background: str) -> None:
    """Render one widget into a PNG over a solid colour."""
    native = widget.get_native()
    assert native is not None
    renderer = native.get_renderer()
    assert renderer is not None
    width, height = widget.get_width(), widget.get_height()
    snapshot = Gtk.Snapshot()
    rgba = Gdk.RGBA()
    rgba.parse(background)
    snapshot.append_color(rgba, Graphene.Rect().init(0, 0, width, height))
    Gtk.WidgetPaintable.new(widget).snapshot(snapshot, width, height)
    node = snapshot.to_node()
    assert node is not None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    renderer.render_texture(node, None).save_to_png(
        str(OUTPUT_DIR / f"{name}.png")
    )


def _set_scheme(dark: bool) -> None:
    run_on_main_thread(
        lambda: Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT
        )
    )
    time.sleep(SETTLE)


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


def _element():
    """The selected workpiece's canvas element."""
    (elem,) = win.surface.get_selected_elements()
    return elem


def _handle(region: ElementRegion) -> tuple[float, float]:
    """A resize handle's anchor on screen."""
    elem = _element()
    to_screen = win.surface.view_transform @ elem.get_world_transform()
    return to_screen.transform_point(
        handle_anchor(region, elem.width, elem.height, to_screen.is_flipped())
    )


def _ring_point() -> tuple[float, float]:
    """A point in the top-right corner's rotate ring, on screen."""
    x, y = _handle(ElementRegion.TOP_RIGHT)
    d = 10 / math.sqrt(2)
    return x + d, y - d


def _rotated(x: float, y: float, degrees: float) -> tuple[float, float]:
    """Screen (x, y) rotated about the selection's centre."""
    surface = win.surface
    wx, wy = surface._get_world_coords(x, y)
    px, py = _element().get_world_center()
    a = math.radians(degrees)
    rx = px + (wx - px) * math.cos(a) - (wy - py) * math.sin(a)
    ry = py + (wx - px) * math.sin(a) + (wy - py) * math.cos(a)
    return surface.view_transform.transform_point((rx, ry))


def _begin_drag(x: float, y: float, to: tuple[float, float]) -> _Gesture:
    """Press at screen (x, y) and drag to `to`, without releasing."""
    surface = win.surface
    gesture = _Gesture(x, y)
    surface._real_drag_gesture = surface._drag_gesture
    surface._drag_gesture = gesture
    surface.on_motion(None, x, y)
    surface.on_button_press(gesture, 1, x, y)
    surface.on_mouse_drag(gesture, to[0] - x, to[1] - y)
    surface.queue_draw()
    return gesture


def _end_drag(gesture: _Gesture, to: tuple[float, float]) -> None:
    """Release a drag and undo what it did."""
    surface = win.surface
    x, y = gesture.get_start_point()[1:]
    surface.on_drag_end(gesture, to[0] - x, to[1] - y)
    surface._drag_gesture = surface._real_drag_gesture
    del surface._real_drag_gesture
    win.doc_editor.history_manager.undo()
    surface.on_motion_leave(None)


def _select_first_workpiece() -> None:
    workpieces = list(win.doc_editor.doc.all_workpieces)
    assert workpieces, f"{PROJECT.name} has no workpiece"
    win.surface.select_items(workpieces[:1])
    win.surface.queue_draw()


def _capture_states(dark: bool) -> None:
    theme = "dark" if dark else "light"
    background = WINDOW_BG[dark]
    surface = win.surface

    def shot(state: str) -> None:
        time.sleep(0.3)
        run_on_main_thread(
            lambda: _capture(surface, f"{state}-{theme}", background)
        )

    run_on_main_thread(lambda: surface.on_motion_leave(None))
    shot("idle")

    run_on_main_thread(
        lambda: surface.on_motion(None, *_handle(ElementRegion.TOP_LEFT))
    )
    shot("hover-corner")
    run_on_main_thread(lambda: surface.on_motion_leave(None))

    start = run_on_main_thread(_ring_point)
    to = run_on_main_thread(lambda: _rotated(*start, -35))
    gesture = run_on_main_thread(lambda: _begin_drag(*start, to))
    shot("rotating")
    run_on_main_thread(lambda: _end_drag(gesture, to))

    start = run_on_main_thread(lambda: _handle(ElementRegion.BOTTOM_RIGHT))
    to = (start[0] + 60, start[1] + 40)
    gesture = run_on_main_thread(lambda: _begin_drag(*start, to))
    shot("resizing")
    run_on_main_thread(lambda: _end_drag(gesture, to))

    # Unselected, or the job's corner handle would cover the marker.
    run_on_main_thread(lambda: surface.select_items([]))
    run_on_main_thread(lambda: surface.set_start_corner_hovered(True))
    shot("start-corner")
    run_on_main_thread(lambda: surface.set_start_corner_hovered(False))
    run_on_main_thread(_select_first_workpiece)


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
        time.sleep(1.5)
        run_on_main_thread(_select_first_workpiece)
        for dark in (False, True):
            _set_scheme(dark)
            _capture_states(dark)
        run_on_main_thread(lambda: content.set_size_request(-1, -1))
        logger.info("selection handle captures written to %s", OUTPUT_DIR)
    finally:
        app.quit_idle()


main()

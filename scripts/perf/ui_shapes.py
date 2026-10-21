"""uiscript: many shapes (PERF_AUDIT_M1.md, "many shapes").

Imports $PERF_SCENE as individual shapes (one workpiece per closed
path) with the import dialog's default spec, PassthroughSpec, whose
MAP_TO_EXISTING mode adds every piece to the document's layer one by
one, into the empty document, with a tick callback on the canvas probing the frame clock
the whole time: the longest frame interval is the longest the main
thread was blocked. Then, with the pieces loaded:

- pan at fit and zoom, as scripts/perf/ui_canvas.py drives them,
  nothing selected, and pan again with every piece selected;
- drag of one piece: a press on it, one drag step per frame;
- hit testing: pointer motion over a grid of points on the canvas,
  timing on_motion and counting the fine tests it runs (stroke
  distance, inside test, pixel test), per motion;
- idle CPU of the app for $PERF_SHAPES_IDLE_S seconds after settling.

Writes the result to $PERF_OUT and quits. With $PERF_PROFILE set, a
cProfile of the import (from the call to settled) is dumped there.
"""

import cProfile
import itertools
import mimetypes
import os
import statistics
import time
from pathlib import Path
from unittest.mock import MagicMock

import procstat
import uiperf
from gi.repository import Gdk, GLib
from uiperf import on_main, win

from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.ui_gtk.canvas.element import CanvasElement
from swiftcut.ui_gtk.canvas2d.elements.workpiece import WorkPieceElement

FRAMES = int(os.environ.get("PERF_FRAMES", "240"))
SCENE = Path(os.environ["PERF_SCENE"])
PROFILE = os.environ.get("PERF_PROFILE")
IDLE_S = float(os.environ.get("PERF_SHAPES_IDLE_S", "10"))
ZOOM_STEP = 1.012
HIT_GRID = (20, 10)
#: The element methods a hit test runs once an element is a candidate.
FINE_TESTS = (
    (WorkPieceElement, "is_near_stroke"),
    (WorkPieceElement, "encloses_point"),
    (CanvasElement, "is_pixel_opaque"),
)

surface = win.surface
editor = win.doc_editor


def _wait_settled(timeout_s=600.0):
    """
    Like uiperf.settle, but returns the moment the editor went quiet
    for good (perf_counter), not the end of the quiet window.
    """
    quiet = uiperf.intent_controller.REBUILD_DEBOUNCE_MS / 1000 + 0.2
    deadline = time.monotonic() + timeout_s
    idle_since = None
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("the editor did not settle")
        busy = on_main(
            lambda: uiperf.task_mgr.has_tasks() or editor.is_processing
        )
        now = time.perf_counter()
        if busy:
            idle_since = None
        elif idle_since is None:
            idle_since = now
        elif now - idle_since > quiet:
            return idle_since
        time.sleep(0.02)


def import_individually():
    """The import, timed, with the frame clock probed throughout."""
    stamps = {}
    ticks = []

    def on_imported(sender, **kwargs):
        stamps["imported"] = time.perf_counter()
        stamps["pieces"] = len(kwargs.get("items") or ())

    def tick(_widget, _clock):
        ticks.append(time.perf_counter())
        return GLib.SOURCE_CONTINUE

    def start():
        editor.file.items_imported.connect(on_imported)
        tick_id = surface.add_tick_callback(tick)
        stamps["start"] = time.perf_counter()
        editor.file.load_file_from_path(
            SCENE,
            mimetypes.guess_type(SCENE)[0],
            PassthroughSpec(),
            None,
            True,
        )
        return tick_id

    profile = cProfile.Profile() if PROFILE else None
    if profile:
        on_main(profile.enable)
    tick_id = on_main(start)
    settled = _wait_settled()
    if profile and PROFILE:
        on_main(profile.disable)
        profile.dump_stats(PROFILE)
    on_main(surface.remove_tick_callback, tick_id)
    on_main(editor.file.items_imported.disconnect, on_imported)
    intervals = [(b - a) * 1000 for a, b in itertools.pairwise(ticks)]
    return {
        "pieces": stamps.get("pieces"),
        "workpieces": on_main(lambda: len(editor.doc.all_workpieces)),
        "imported_s": stamps["imported"] - stamps["start"],
        "settled_s": settled - stamps["start"],
        "interval_ms": intervals,
        "longest_stall_ms": max(intervals) if intervals else None,
    }


def fit():
    surface.set_zoom(1.0)
    surface.set_pan(0.0, 0.0)


def pan(i):
    sign = 1.0 if i < FRAMES // 2 else -1.0
    surface._suppress_ops()
    surface._pan_by_scroll_delta(10.0 * sign, 6.0 * sign)
    surface._defer_restore_ops()


def zoom(i):
    factor = ZOOM_STEP if i < FRAMES // 2 else 1.0 / ZOOM_STEP
    surface._suppress_ops()
    surface._zoom_about_point_live(
        surface.get_width() / 2.0,
        surface.get_height() / 2.0,
        surface.zoom_level * factor,
    )
    surface._defer_restore_ops()


def _screen_center(elem):
    to_screen = surface.view_transform @ elem.get_world_transform()
    return to_screen.transform_point((elem.width / 2, elem.height / 2))


def _drag_piece():
    """
    The piece nearest the canvas centre among the widest ones (in
    many_shapes.dxf a plate outline, not a hole).
    """
    cx, cy = surface.get_width() / 2.0, surface.get_height() / 2.0

    def distance(elem):
        x, y = _screen_center(elem)
        return (x - cx) ** 2 + (y - cy) ** 2

    elems = list(surface.find_by_type(WorkPieceElement))
    widest = max(e.get_world_bounding_box()[2] for e in elems)
    return min(
        (e for e in elems if e.get_world_bounding_box()[2] >= 0.9 * widest),
        key=distance,
    )


def drag_one_piece():
    """One piece pressed and dragged, one step per frame."""
    gesture = MagicMock()
    gesture.get_current_event.return_value = None
    gesture.get_button.return_value = Gdk.BUTTON_PRIMARY
    state = {}

    def press():
        elem = _drag_piece()
        surface.select_items([elem.data])
        # A press on the plate's inside, off the slot and the holes.
        to_screen = surface.view_transform @ elem.get_world_transform()
        x, y = to_screen.transform_point((elem.width * 0.1, elem.height * 0.5))
        gesture.get_start_point.return_value = (True, x, y)
        state["saved"] = surface._drag_gesture
        surface._drag_gesture = gesture
        surface.on_button_press(gesture, 1, x, y)
        return surface.get_selected_items()

    def step(i):
        half = FRAMES // 2
        offset = 2.0 * (i if i < half else FRAMES - i)
        surface.on_mouse_drag(gesture, offset, offset * 0.5)

    def release():
        surface.on_drag_end(gesture, 0.0, 0.0)
        surface._drag_gesture = state["saved"]

    selected = on_main(press)
    frames = uiperf.drive(surface, step, FRAMES)
    on_main(release)
    frames["selected"] = len(selected or ())
    return frames


def hit_test():
    """on_motion over a grid of canvas points: time and fine tests."""
    counts = {"n": 0}
    originals = []

    def counting(cls, name):
        original = getattr(cls, name)

        def wrapper(*args, **kwargs):
            counts["n"] += 1
            return original(*args, **kwargs)

        originals.append((cls, name, original))
        setattr(cls, name, wrapper)

    def sweep():
        for cls, name in FINE_TESTS:
            counting(cls, name)
        w, h = surface.get_width(), surface.get_height()
        cols, rows = HIT_GRID
        times, tests = [], []
        try:
            for j in range(rows):
                for i in range(cols):
                    x = w * (i + 0.5) / cols
                    y = h * (j + 0.5) / rows
                    counts["n"] = 0
                    t = time.perf_counter()
                    surface.on_motion(None, x, y)
                    times.append((time.perf_counter() - t) * 1000)
                    tests.append(counts["n"])
        finally:
            for cls, name, original in originals:
                setattr(cls, name, original)
        return times, tests

    on_main(surface.unselect_all)
    times, tests = on_main(sweep)
    return {
        "motions": len(times),
        "motion_ms_p50": statistics.median(times),
        "motion_ms_p95": sorted(times)[int(0.95 * (len(times) - 1))],
        "motion_ms_max": max(times),
        "fine_tests_mean": statistics.mean(tests),
        "fine_tests_max": max(tests),
    }


def idle_cpu():
    """CPU % of the app over IDLE_S seconds, nothing driven."""
    pid = os.getpid()
    a = procstat.sample(pid)
    t0 = time.monotonic()
    time.sleep(IDLE_S)
    b = procstat.sample(pid)
    return {
        "cpu_pct": 100.0 * (b["cpu_s"] - a["cpu_s"]) / (time.monotonic() - t0),
        "seconds": IDLE_S,
    }


def main():
    uiperf.settle(extra_s=1.0)
    result = {"scene": SCENE.name, "frames_per_gesture": FRAMES}
    result["import"] = import_individually()
    uiperf.settle(extra_s=2.0)
    result["selected_after_import"] = len(
        on_main(surface.get_selected_items) or ()
    )
    result["renderer"] = uiperf.renderer_name()
    result["scale_factor"] = on_main(surface.get_scale_factor)
    result["canvas_px"] = on_main(
        lambda: (surface.get_width(), surface.get_height())
    )

    on_main(fit)
    uiperf.settle(extra_s=1.0)
    result["pan_selected"] = uiperf.drive(surface, pan, FRAMES)
    on_main(surface.unselect_all)
    on_main(fit)
    uiperf.settle(extra_s=1.0)
    result["pan"] = uiperf.drive(surface, pan, FRAMES)
    on_main(fit)
    result["zoom"] = uiperf.drive(surface, zoom, FRAMES)
    on_main(fit)
    uiperf.settle(extra_s=1.5)
    result["drag"] = drag_one_piece()
    uiperf.settle(extra_s=1.5)
    result["hit"] = hit_test()
    uiperf.settle(extra_s=2.0)
    result["idle"] = idle_cpu()
    uiperf.write_result(result)


uiperf.run(main)

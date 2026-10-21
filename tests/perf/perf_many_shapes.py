"""Many shapes in the main window, measured without showing it.

Builds the main window (never presented: nothing appears on the
owner's screen, and no frame clock is needed) on the ilab-614 bed
(1400 x 900 mm), imports $PERF_SHAPES (tests/perf/many_shapes.dxf, 300
closed paths, by default) as individual shapes, then measures with the
pieces loaded. One RESULT line per test, JSON after the word:

- test_import, with the import dialog's default spec, PassthroughSpec
  (each piece goes into the document's layer on its own): wall time to the items_imported signal and to settled
  (no task, the editor idle), the longest the main loop was blocked
  (a 5 ms GLib timeout probe; the gaps between its ticks), and how
  many times the document's bubbled signals and the handlers the
  brief names ran during it;
- test_frames: the main thread's cost of a canvas frame, offscreen:
  WorkSurface.do_snapshot into a Gtk.Snapshot of the window's canvas
  size at scale 2, the render node, and the CPU raster the GL renderer
  does for it (each cairo node replayed at scale 2; no GPU upload or
  composite), per frame of a pan at fit, a pan with everything
  selected, and a drag of one piece;
- test_hit: on_motion over a grid of canvas points, its time and the
  fine tests (stroke distance, inside test, pixel test) per motion.

Not named test_*.py: it must not join the default suite. Run::

    python -m pytest tests/perf/perf_many_shapes.py -q -s
    PERF_SHAPES=/path/to/other.dxf python -m pytest ...
"""

import itertools
import json
import math
import os
import statistics
import time
from pathlib import Path
from unittest.mock import MagicMock

import cairo
import pytest
from gi.repository import Adw, Gdk, GLib, Gsk, Gtk

from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.pipeline.intent_controller import IntentController
from swiftcut.ui_gtk.canvas.element import CanvasElement
from swiftcut.ui_gtk.canvas2d.elements.workpiece import WorkPieceElement
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface
from swiftcut.ui_gtk.doceditor.layer_column import LayerColumn
from swiftcut.ui_gtk.mainwindow import MainWindow

pytestmark = pytest.mark.ui

SHAPES = Path(
    os.environ.get("PERF_SHAPES", Path(__file__).parent / "many_shapes.dxf")
)
#: The canvas of the app's default window on the M1, in points; at
#: scale 2 (docs/PERF_AUDIT_M1.md).
CANVAS = (1285, 406)
SCALE = 2
FRAMES = int(os.environ.get("PERF_FRAMES", "120"))
HIT_GRID = (20, 10)
FINE_TESTS = (
    (WorkPieceElement, "is_near_stroke"),
    (WorkPieceElement, "encloses_point"),
    (CanvasElement, "is_pixel_opaque"),
)
SETTLE_TIMEOUT_S = float(os.environ.get("PERF_SETTLE_TIMEOUT_S", "3600"))
#: Handlers counted during an import, patched on their classes before
#: the window connects them.
COUNTED = (
    (WorkSurface, "_update_start_corner_element"),
    (WorkSurface, "update_from_doc"),
    (IntentController, "_schedule_rebuild"),
    (IntentController, "_rebuild"),
    (MainWindow, "_update_actions_and_ui"),
    (LayerColumn, "_rebuild_workpiece_list"),
)
COUNTS: dict[str, int] = {}


def _pump(seconds):
    context = GLib.main_context_default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.005)


@pytest.fixture
def win(ui_context_initializer, ui_task_mgr, monkeypatch):
    """The main window on the ilab-614 bed, never presented."""
    for cls, name in COUNTED:
        monkeypatch.setattr(cls, name, _counter(name, getattr(cls, name)))
    machine = ui_context_initializer.config.machine
    machine.set_axis_extents(1400, 900)

    class PerfApp(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)

    app = PerfApp(application_id="org.swiftcut.swiftcut.perf.shapes")
    app.register(None)
    app.activate()
    window = app.win
    surface = window.surface
    surface.get_width = lambda: CANVAS[0]
    surface.get_height = lambda: CANVAS[1]
    surface.get_scale_factor = lambda: SCALE
    surface._rebuild_view_transform()
    _pump(0.5)
    yield window
    window.doc_editor.cleanup()
    window.destroy()
    app.quit()
    _pump(0.2)


def _counter(name, fn):
    def counting(*args, **kwargs):
        COUNTS[name] = COUNTS.get(name, 0) + 1
        return fn(*args, **kwargs)

    return counting


def _import(win, task_mgr, spec):
    """Imports SHAPES individually; returns the timings and counts."""
    editor = win.doc_editor
    doc = editor.doc
    for name in (
        "descendant_added",
        "descendant_removed",
        "descendant_updated",
        "descendant_transform_changed",
    ):
        getattr(doc, name).connect(
            _counter(name, lambda *a, **k: None), weak=False
        )
    COUNTS.clear()

    stamps = {}
    ticks = []

    def probe():
        ticks.append(time.perf_counter())
        return GLib.SOURCE_CONTINUE

    def on_imported(sender, **kwargs):
        stamps["imported"] = time.perf_counter()
        stamps["pieces"] = len(kwargs.get("items") or ())

    editor.file.items_imported.connect(on_imported, weak=False)
    probe_id = GLib.timeout_add(5, probe)
    start = time.perf_counter()
    ticks.append(start)
    editor.file.load_file_from_path(SHAPES, None, spec, None, True)
    context = GLib.main_context_default()
    quiet = 0.7
    idle_since = None
    deadline = time.monotonic() + SETTLE_TIMEOUT_S
    while True:
        while context.pending():
            context.iteration(False)
        busy = task_mgr.has_tasks() or editor.is_processing
        now = time.perf_counter()
        if busy or "imported" not in stamps:
            idle_since = None
        elif idle_since is None:
            idle_since = now
        elif now - idle_since > quiet:
            break
        assert time.monotonic() < deadline, "the import did not settle"
        time.sleep(0.002)
    GLib.source_remove(probe_id)
    gaps = [(b - a) * 1000 for a, b in itertools.pairwise(ticks)]
    return {
        "scene": SHAPES.name,
        "pieces": stamps.get("pieces"),
        "workpieces": len(doc.all_workpieces),
        "imported_s": stamps["imported"] - start,
        "settled_s": idle_since - start,
        "longest_stall_ms": max(gaps),
        "stalls_over_100ms": sum(1 for g in gaps if g > 100),
        "counts": dict(COUNTS),
    }


def _rasterize(node):
    """
    What the GL renderer does on the CPU for a frame: every cairo node
    (a recording) replayed into an image at device scale, which it
    then uploads. Texture nodes (view tiles) cost nothing here: the
    GPU composites them.
    """
    if isinstance(node, Gsk.CairoNode):
        bounds = node.get_bounds()
        image = cairo.ImageSurface(
            cairo.FORMAT_ARGB32,
            math.ceil(bounds.get_width() * SCALE),
            math.ceil(bounds.get_height() * SCALE),
        )
        ctx = cairo.Context(image)
        ctx.scale(SCALE, SCALE)
        ctx.translate(-bounds.get_x(), -bounds.get_y())
        ctx.set_source_surface(node.get_surface(), 0, 0)
        ctx.paint()
        image.flush()
        return
    if hasattr(node, "get_n_children"):
        for i in range(node.get_n_children()):
            _rasterize(node.get_child(i))
    elif hasattr(node, "get_child"):
        _rasterize(node.get_child())


def _frame(surface):
    """One frame: snapshot, render node, cairo raster; in ms."""
    t = time.perf_counter()
    snapshot = Gtk.Snapshot()
    surface.do_snapshot(snapshot)
    node = snapshot.to_node()
    if node is not None:
        _rasterize(node)
    return (time.perf_counter() - t) * 1000


def _stats(ms):
    s = sorted(ms)
    return {
        "p50_ms": statistics.median(s),
        "p95_ms": s[int(0.95 * (len(s) - 1))],
        "max_ms": s[-1],
        "frames": len(s),
    }


def _fit(surface):
    surface.set_zoom(1.0)
    surface.set_pan(0.0, 0.0)


def _pan(surface):
    times = []
    for i in range(FRAMES):
        sign = 1.0 if i < FRAMES // 2 else -1.0
        surface._suppress_ops()
        surface._pan_by_scroll_delta(10.0 * sign, 6.0 * sign)
        times.append(_frame(surface))
    surface._defer_restore_ops()
    _pump(0.5)
    return _stats(times)


def _drag_piece(surface):
    """The widest piece (a plate outline) nearest the canvas centre."""
    cx, cy = CANVAS[0] / 2, CANVAS[1] / 2
    elems = list(surface.find_by_type(WorkPieceElement))
    widest = max(e.get_world_bounding_box()[2] for e in elems)

    def distance(elem):
        to_screen = surface.view_transform @ elem.get_world_transform()
        x, y = to_screen.transform_point((elem.width / 2, elem.height / 2))
        return (x - cx) ** 2 + (y - cy) ** 2

    return min(
        (e for e in elems if e.get_world_bounding_box()[2] >= 0.9 * widest),
        key=distance,
    )


def _drag(surface):
    elem = _drag_piece(surface)
    surface.select_items([elem.data])
    to_screen = surface.view_transform @ elem.get_world_transform()
    x, y = to_screen.transform_point((elem.width * 0.1, elem.height * 0.5))
    gesture = MagicMock()
    gesture.get_current_event.return_value = None
    gesture.get_button.return_value = Gdk.BUTTON_PRIMARY
    gesture.get_start_point.return_value = (True, x, y)
    saved, surface._drag_gesture = surface._drag_gesture, gesture
    surface.on_button_press(gesture, 1, x, y)
    start = elem.get_world_transform().get_translation()
    times, moved = [], 0
    try:
        for i in range(FRAMES):
            offset = 2.0 * (i if i < FRAMES // 2 else FRAMES - i)
            surface.on_mouse_drag(gesture, offset, offset * 0.5)
            moved += elem.get_world_transform().get_translation() != start
            times.append(_frame(surface))
        surface.on_drag_end(gesture, 0.0, 0.0)
    finally:
        surface._drag_gesture = saved
    _pump(0.5)
    return _stats(times) | {"moved_frames": moved}


def _hit(surface):
    counts = {"n": 0}
    originals = []
    for cls, name in FINE_TESTS:
        original = getattr(cls, name)

        def wrapper(*args, _original=original, **kwargs):
            counts["n"] += 1
            return _original(*args, **kwargs)

        originals.append((cls, name, original))
        setattr(cls, name, wrapper)
    times, tests = [], []
    try:
        cols, rows = HIT_GRID
        for j in range(rows):
            for i in range(cols):
                x = CANVAS[0] * (i + 0.5) / cols
                y = CANVAS[1] * (j + 0.5) / rows
                counts["n"] = 0
                t = time.perf_counter()
                surface.on_motion(None, x, y)
                times.append((time.perf_counter() - t) * 1000)
                tests.append(counts["n"])
    finally:
        for cls, name, original in originals:
            setattr(cls, name, original)
    s = sorted(times)
    return {
        "motions": len(times),
        "motion_ms_p50": statistics.median(s),
        "motion_ms_p95": s[int(0.95 * (len(s) - 1))],
        "fine_tests_mean": statistics.mean(tests),
        "fine_tests_max": max(tests),
    }


def _result(name, data):
    print(f"\nRESULT {name} {json.dumps(data)}")


def test_import(win, ui_task_mgr):
    _result("import", _import(win, ui_task_mgr, PassthroughSpec()))


def _load(win, task_mgr):
    """
    The same pieces for the canvas tests, the quick way: without a
    spec they arrive in one new layer, in one insertion.
    """
    _import(win, task_mgr, None)


def test_frames(win, ui_task_mgr):
    _load(win, ui_task_mgr)
    surface = win.surface
    _fit(surface)
    _pump(0.5)
    out = {"scene": SHAPES.name, "canvas": CANVAS, "scale": SCALE}
    surface.select_all()
    out["pan_selected"] = _pan(surface)
    surface.unselect_all()
    _fit(surface)
    out["pan"] = _pan(surface)
    _fit(surface)
    out["drag"] = _drag(surface)
    _result("frames", out)


def test_hit(win, ui_task_mgr):
    _load(win, ui_task_mgr)
    surface = win.surface
    _fit(surface)
    surface.unselect_all()
    _pump(0.5)
    _result("hit", {"scene": SHAPES.name, **_hit(surface)})

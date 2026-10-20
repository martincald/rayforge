"""Helpers the perf uiscripts share: main-thread calls, settling, and
frame timing on the window's frame clock.

A uiscript runs on a background thread (swiftcut/uiscript.py), so every
GTK call goes through ``on_main``. Frame time is measured between the
frame clock's ``before-paint`` and ``after-paint`` signals: that span
holds the tick callbacks (where the drive happens), layout, every
widget's snapshot and the GSK render, which is the main thread's whole
cost of a frame. ``interval`` is before-paint to before-paint.
"""

import json
import os
import threading
import time
from pathlib import Path

from gi.repository import GLib

from swiftcut.pipeline import intent_controller
from swiftcut.shared.tasker import task_mgr
from swiftcut.uiscript import app, win

assert app is not None and win is not None


def on_main(fn, *args):
    """Runs fn(*args) on the GTK main thread; returns its result."""
    done = threading.Event()
    box = {}

    def run():
        try:
            box["value"] = fn(*args)
        except BaseException as e:  # noqa: BLE001 - re-raised below
            box["error"] = e
        done.set()
        return GLib.SOURCE_REMOVE

    GLib.idle_add(run)
    done.wait()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def settle(extra_s=1.0, timeout_s=300.0):
    """
    Waits until no task runs and the editor is not processing for
    longer than the rebuild debounce, then extra_s more for canvas
    surfaces rendered in the background.
    """
    quiet = intent_controller.REBUILD_DEBOUNCE_MS / 1000 + 0.2
    deadline = time.monotonic() + timeout_s
    idle_since = None
    while True:
        now = time.monotonic()
        if now > deadline:
            raise TimeoutError("the editor did not settle")
        busy = on_main(
            lambda: task_mgr.has_tasks() or win.doc_editor.is_processing
        )
        if busy:
            idle_since = None
        elif idle_since is None:
            idle_since = now
        elif now - idle_since > quiet:
            break
        time.sleep(0.05)
    time.sleep(extra_s)


def renderer_name():
    renderer = on_main(lambda: win.get_native().get_renderer())
    return type(renderer).__name__


def drive(widget, step, frames, tail_s=1.0):
    """
    Calls step(i) from a tick callback on widget for `frames` frames,
    and returns each frame's time (before-paint to after-paint) and
    interval in ms, plus the frames of the tail_s after the last step
    (where deferred work such as the ops restore lands).
    """
    done = threading.Event()
    state = {"i": 0, "t0": None, "last": None, "stop": None}
    drive_ms, intervals, tail_ms = [], [], []
    clock = on_main(widget.get_frame_clock)
    assert clock is not None

    def before_paint(_clock):
        now = time.perf_counter()
        if state["last"] is not None and state["stop"] is None:
            intervals.append((now - state["last"]) * 1000)
        state["last"] = now
        state["t0"] = now

    def after_paint(_clock):
        if state["t0"] is None:
            return
        ms = (time.perf_counter() - state["t0"]) * 1000
        if state["stop"] is None:
            drive_ms.append(ms)
        elif time.perf_counter() < state["stop"] + tail_s:
            tail_ms.append(ms)
        state["t0"] = None

    def tick(_widget, _clock):
        if state["i"] >= frames:
            state["stop"] = time.perf_counter()
            done.set()
            return GLib.SOURCE_REMOVE
        step(state["i"])
        state["i"] += 1
        return GLib.SOURCE_CONTINUE

    handlers = on_main(
        lambda: (
            clock.connect("before-paint", before_paint),
            clock.connect("after-paint", after_paint),
        )
    )
    on_main(widget.add_tick_callback, tick)
    done.wait()
    # The tail's frames only paint if something queues a draw; an
    # idle tail is no frames, which is the right answer.
    time.sleep(tail_s)
    assert handlers is not None
    on_main(lambda: [clock.disconnect(h) for h in handlers])
    # The first sample spans the setup; the rest are the drive's.
    return {
        "frame_ms": drive_ms[1:],
        "interval_ms": intervals[1:],
        "tail_frame_ms": tail_ms,
    }


def write_result(result):
    Path(os.environ["PERF_OUT"]).write_text(
        json.dumps(result), encoding="utf-8"
    )


def finish():
    app.quit_idle()


def run(main, quit_after=True):
    """
    Runs a uiscript's main(); quits the app after it, and always on an
    error, so a failed measurement never leaves the app open.
    """
    try:
        main()
    except BaseException:
        finish()
        raise
    if quit_after:
        finish()

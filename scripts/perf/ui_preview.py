"""uiscript: job preview playback frame times (PERF_AUDIT_M1.md, f).

Opens $PERF_SCENE (tests/perf/two_layer.ryp), waits for it to settle,
picks the x16 speed and turns the preview on as the Preview toggle does.
Records how long the job took to be previewable, then the frame times
of $PERF_FRAMES frames of playback on the canvas' frame clock (the app's
own tick, MainWindow._on_job_preview_tick), then of $PERF_FRAMES scrubs:
a jump to a new time each frame, every other one backwards, as dragging
the scrub bar back and forth does. Writes $PERF_OUT and quits.
"""

import os
import time
from pathlib import Path

import uiperf
from uiperf import on_main, win

FRAMES = int(os.environ.get("PERF_FRAMES", "240"))
SCENE = Path(os.environ["PERF_SCENE"])

surface = win.surface
bar = win._time_estimate_overlay.preview_bar
element = surface._job_preview_element


def main():
    on_main(win.load_project, SCENE)
    uiperf.settle(extra_s=2.0)

    on_main(lambda: bar.speed_buttons[16].set_active(True))
    asked = time.perf_counter()
    on_main(lambda: bar.toggle.set_active(True))
    deadline = asked + 300.0
    while not on_main(lambda: element.model is not None and bar.playing):
        if time.perf_counter() > deadline:
            raise TimeoutError("the preview never loaded")
        time.sleep(0.01)
    result = {
        "scene": SCENE.name,
        "renderer": uiperf.renderer_name(),
        "scale_factor": on_main(surface.get_scale_factor),
        "canvas_px": on_main(
            lambda: (surface.get_width(), surface.get_height())
        ),
        "preview_ready_s": time.perf_counter() - asked,
        "segments": on_main(lambda: len(element.model.segments)),
        "total_s": on_main(lambda: element.model.total_time),
    }

    # Playback is already running on the app's own tick; this drive
    # only times its frames.
    result["play"] = uiperf.drive(surface, lambda i: None, FRAMES)
    on_main(lambda: bar.set_playing(False))
    total = result["total_s"]

    def scrub(i):
        # Forwards to a growing time on even frames, back to half of it
        # on odd ones: every other frame starts the finished image over.
        t = total * (i // 2 + 1) / (FRAMES // 2 + 1)
        bar.set_time(t if i % 2 == 0 else t / 2)

    result["scrub"] = uiperf.drive(surface, scrub, FRAMES)
    uiperf.write_result(result)


uiperf.run(main)

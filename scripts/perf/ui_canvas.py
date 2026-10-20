"""uiscript: canvas pan and zoom frame times (PERF_AUDIT_M1.md, d).

Loads $PERF_SCENE (an asset to import, or a .ryp project to open),
waits for the editor and the canvas surfaces to settle, selects
everything if $PERF_SELECT_ALL is set, then drives three gestures for
$PERF_FRAMES frames each, one step per frame from a tick callback:

- pan at fit: the trackpad two-finger pan path of WorkSurface.on_scroll
  (_suppress_ops, _pan_by_scroll_delta, _defer_restore_ops);
- zoom: the trackpad Ctrl/pinch path (_zoom_about_point_live about the
  view centre), in to about 4x and back out;
- pan at 4x, after the ops have re-rendered at that zoom.

Writes the frame times (uiperf.drive) to $PERF_OUT and quits. With
$PERF_PROFILE set, a cProfile of the three gestures is dumped there.
"""

import cProfile
import mimetypes
import os
import time
from pathlib import Path

import uiperf
from uiperf import on_main, win

FRAMES = int(os.environ.get("PERF_FRAMES", "240"))
SCENE = Path(os.environ["PERF_SCENE"])
PROFILE = os.environ.get("PERF_PROFILE")
ZOOM_STEP = 1.012  # 1.012 ** 120 is about 4.2

surface = win.surface


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


def zoom_in():
    surface._zoom_about_point_live(
        surface.get_width() / 2.0, surface.get_height() / 2.0, 4.0
    )


def main():
    if SCENE.suffix == ".ryp":
        on_main(win.load_project, SCENE)
    else:
        on_main(
            win.doc_editor.file.load_file_from_path,
            SCENE,
            mimetypes.guess_type(SCENE)[0],
            None,
        )
    uiperf.settle(extra_s=2.0)
    if os.environ.get("PERF_SELECT_ALL"):
        on_main(surface.select_all)
    on_main(fit)
    uiperf.settle(extra_s=1.0)
    result = {
        "scene": SCENE.name,
        "selected": len(on_main(surface.get_selected_items)),
        "renderer": uiperf.renderer_name(),
        "scale_factor": on_main(surface.get_scale_factor),
        "canvas_px": on_main(
            lambda: (surface.get_width(), surface.get_height())
        ),
        "frames_per_gesture": FRAMES,
    }
    profile = cProfile.Profile() if PROFILE else None
    if profile:
        on_main(profile.enable)
    started = time.perf_counter()
    result["pan"] = uiperf.drive(surface, pan, FRAMES)
    on_main(fit)
    result["zoom"] = uiperf.drive(surface, zoom, FRAMES)
    on_main(zoom_in)
    uiperf.settle(extra_s=1.5)
    result["pan_zoomed"] = uiperf.drive(surface, pan, FRAMES)
    result["zoom_level_zoomed"] = on_main(lambda: surface.zoom_level)
    result["wall_s"] = time.perf_counter() - started
    if profile:
        on_main(profile.disable)
        profile.dump_stats(PROFILE)
    uiperf.write_result(result)


uiperf.run(main)

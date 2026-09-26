"""Capture the compact dock at the sizes it is judged at, and measure it.

Run with::

    python -m swiftcut.app --config <isolated-config> \\
        --uiscript scripts/screenshot/dock_fit.py

For each size in ``$DOCK_FIT_SIZES`` (default ``1440x900 2560x1440``)
the window content is laid out at that size, as ``window_fit.py``
does for a size larger than the screen, and captured in the light and
the dark theme into ``docs/design/screens/compact-dock/`` or
``$DOCK_FIT_OUT``. Next to the captures, ``measurements.txt`` gives
the dock's height, the share of the window above it and the canvas's
own, and the width of the machine settings list.

Like ``window_fit.py`` this renders through GTK's own renderer and does
not import ``utils``.
"""

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import TypeVar

from gi.repository import Adw, Gdk, GLib, Graphene, Gtk

from swiftcut.ui_gtk.layout import JOG_CELL, PANEL_MAX_WIDTH
from swiftcut.uiscript import app, win

logger = logging.getLogger(__name__)

T = TypeVar("T")

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = Path(
    os.environ.get(
        "DOCK_FIT_OUT",
        PROJECT_ROOT / "docs" / "design" / "screens" / "compact-dock",
    )
)
SIZES = [
    (int(width), int(height))
    for width, height in (
        size.split("x")
        for size in os.environ.get(
            "DOCK_FIT_SIZES", "1440x900 2560x1440"
        ).split()
    )
]
SETTLE = 1.0
# sc_window_bg, light and dark (docs/design/swift-cut-tokens.md).
WINDOW_BG = {False: "#F5F5F7", True: "#1C1C1E"}
_FLAG = "_dock_fit_running"


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


def _size(widget: Gtk.Widget, reference: Gtk.Widget) -> tuple[int, int]:
    """A widget's allocated size, border included."""
    ok, bounds = widget.compute_bounds(reference)
    assert ok
    return round(bounds.get_width()), round(bounds.get_height())


def _measure(size: tuple[int, int]) -> str:
    """One line per quantity the compact dock is judged by."""
    content = win.toast_overlay
    total = content.get_height()
    dock = _size(win.bottom_panel, content)[1]
    above = _size(win.main_stack, content)[1]
    canvas = _size(win._canvas_bin, content)[1]
    settings = _size(win.bottom_panel.wcs_group, content)[0]
    cell = _size(win.bottom_panel.jog_widget.north_btn, content)
    return "\n".join(
        [
            (
                f"window content {size[0]}x{size[1]} "
                f"(laid out {content.get_width()}x{total})"
            ),
            f"  dock            {dock}px  {100 * dock / total:.1f}%",
            f"  above the dock  {above}px  {100 * above / total:.1f}%",
            f"  canvas alone    {canvas}px  {100 * canvas / total:.1f}%",
            (
                f"  settings list   {settings}px wide "
                f"(PANEL_MAX_WIDTH {PANEL_MAX_WIDTH}px)"
            ),
            (
                f"  jog cell        {cell[0]}x{cell[1]}px "
                f"(JOG_CELL {JOG_CELL}px)"
            ),
        ]
    )


def _set_scheme(dark: bool) -> None:
    run_on_main_thread(
        lambda: Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT
        )
    )
    time.sleep(SETTLE)


def main() -> None:
    if getattr(win, _FLAG, False):
        return
    setattr(win, _FLAG, True)
    time.sleep(2)
    run_on_main_thread(lambda: win.bottom_panel.set_visible(True))

    content = win.toast_overlay
    report = []
    for size in SIZES:
        run_on_main_thread(lambda s=size: content.set_size_request(*s))
        time.sleep(1.5)
        for dark in (False, True):
            _set_scheme(dark)
            theme = "dark" if dark else "light"
            name = f"dock-{size[0]}x{size[1]}-{theme}"
            run_on_main_thread(
                lambda n=name, d=dark: _capture(content, n, WINDOW_BG[d])
            )
        report.append(run_on_main_thread(lambda s=size: _measure(s)))
    run_on_main_thread(lambda: content.set_size_request(-1, -1))

    (OUTPUT_DIR / "measurements.txt").write_text("\n".join(report) + "\n")
    logger.info("dock fit captures written to %s", OUTPUT_DIR)
    app.quit_idle()


main()

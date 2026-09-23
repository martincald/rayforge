"""Capture the main window at the sizes the macOS fit is judged at.

Run with::

    python -m swiftcut --config <isolated-config> \\
        --uiscript scripts/screenshot/window_fit.py

Three captures per theme, into ``docs/design/screens/macos-fit/`` or
``$WINDOW_FIT_OUT``:

- the size the window opened at (the first-launch rule),
- the window maximized to its monitor's work area,
- the content laid out at ``$WINDOW_FIT_FORCED`` (default 2560x1415,
  a 27" display less its menu bar), for a check on a smaller screen.
  macOS will not size a window past its screen, so the content is
  given that size request for one frame instead; the window
  background it would sit on is painted under it.

Like ``ui_audit.py`` this renders through GTK's own renderer and does
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

from swiftcut.uiscript import app, win

logger = logging.getLogger(__name__)

T = TypeVar("T")

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = Path(
    os.environ.get(
        "WINDOW_FIT_OUT",
        PROJECT_ROOT / "docs" / "design" / "screens" / "macos-fit",
    )
)
FORCED = tuple(
    int(v) for v in os.environ.get("WINDOW_FIT_FORCED", "2560x1415").split("x")
)
SETTLE = 0.8
# sc_window_bg, light and dark (docs/design/swift-cut-tokens.md).
WINDOW_BG = {False: "#F5F5F7", True: "#1C1C1E"}
_FLAG = "_window_fit_running"


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


def _capture(widget: Gtk.Widget, name: str, background: str | None) -> str:
    """Render one widget into a PNG, optionally over a solid colour."""
    native = widget.get_native()
    assert native is not None
    renderer = native.get_renderer()
    assert renderer is not None
    width, height = widget.get_width(), widget.get_height()
    snapshot = Gtk.Snapshot()
    if background is not None:
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
    return f"{width}x{height}"


def _set_scheme(dark: bool) -> None:
    run_on_main_thread(
        lambda: Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT
        )
    )
    time.sleep(SETTLE)


def _shoot(label: str, dark: bool) -> None:
    theme = "dark" if dark else "light"
    size = run_on_main_thread(lambda: _capture(win, f"{label}-{theme}", None))
    logger.info("%s %s: %s", label, theme, size)


def _shoot_forced(dark: bool) -> None:
    theme = "dark" if dark else "light"
    content = win.toast_overlay
    run_on_main_thread(lambda: content.set_size_request(*FORCED))
    time.sleep(1.5)
    name = f"forced-{FORCED[0]}x{FORCED[1]}-{theme}"
    size = run_on_main_thread(lambda: _capture(content, name, WINDOW_BG[dark]))
    logger.info("%s: %s", name, size)
    run_on_main_thread(lambda: content.set_size_request(-1, -1))
    time.sleep(SETTLE)


def main() -> None:
    if getattr(win, _FLAG, False):
        return
    setattr(win, _FLAG, True)
    time.sleep(2)
    run_on_main_thread(lambda: win.bottom_panel.set_visible(True))

    opened = run_on_main_thread(
        lambda: f"{win.get_width()}x{win.get_height()}"
    )
    for dark in (False, True):
        _set_scheme(dark)
        _shoot(f"opened-{opened}", dark)

    run_on_main_thread(win.maximize)
    time.sleep(1.2)
    for dark in (False, True):
        _set_scheme(dark)
        _shoot("workarea", dark)
    for dark in (False, True):
        _set_scheme(dark)
        _shoot_forced(dark)

    run_on_main_thread(win.unmaximize)
    logger.info("window fit captures written to %s", OUTPUT_DIR)
    app.quit_idle()


main()

"""Capture every floating surface over a busy canvas, light and dark.

Run with::

    python -m swiftcut.app --config <isolated-config> \\
        --uiscript scripts/screenshot/glass_surfaces.py

Loads ``tests/assets/pretty.ryp``, adds two photos and two SVGs from
``tests/image`` and lays them out on the bed's top right, under the
floating panels, selects a workpiece so Workpiece Properties shows,
and forces every other floating surface on: the time estimate, the
"Drop files to import" HUD and a status message. The window content
and the right pane alone are captured in the light and the dark theme
into ``docs/screens/glass/``, and ``measurements.txt`` records each
surface's box, the pane's width and any ellipsized label under it.

Like ``floating_panels.py`` this renders through GTK's own renderer.
"""

import logging
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
PROJECT = PROJECT_ROOT / "tests" / "assets" / "pretty.ryp"
IMAGES = PROJECT_ROOT / "tests" / "image"
# What to add to the project, and where it goes on the 1400x900 bed:
# (file, mime type, x, y, width, height), in mm from the bottom left.
BUSY = (
    (IMAGES / "png" / "grayscale.png", "image/png", 1150, 600, 250, 300),
    (IMAGES / "jpg" / "color.jpg", "image/jpeg", 1150, 380, 250, 220),
    (IMAGES / "svg" / "rayforge.svg", "image/svg+xml", 480, 380, 620, 380),
    (IMAGES / "svg" / "multicolor.svg", "image/svg+xml", 960, 760, 190, 140),
)
# Zoomed in on the bed's top right, which the panels float over.
ZOOM = 2.0
PAN = (520, 0)
OUTPUT_DIR = PROJECT_ROOT / "docs" / "screens" / "glass"
SIZE = (1440, 900)
SETTLE = 1.0
# sc_window_bg, light and dark (docs/design/swift-cut-tokens.md).
WINDOW_BG = {False: "#F5F5F7", True: "#1C1C1E"}
_FLAG = "_glass_surfaces_running"


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


def _walk(widget: Gtk.Widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


def _surfaces() -> dict[str, Gtk.Widget]:
    """Every floating surface, by name."""
    surfaces = {
        "workflow card": win.workflowview,
        "properties card": win.item_props_widget._main_expander,
        "canvas toolbar": win._surface_vis_overlay,
        "time estimate": win._time_estimate_overlay,
        "status message": win._status_message_label,
    }
    hud = win.drag_drop_cmd._drop_overlay_label
    if hud is not None:
        surfaces["drop HUD"] = hud
    return surfaces


def _measure(theme: str, content: Gtk.Widget) -> str:
    lines = [f"{SIZE[0]}x{SIZE[1]} {theme}"]
    pane = win._right_pane
    lines.append(f"  right pane      {pane.get_width()}px wide")
    for name, widget in _surfaces().items():
        ok, box = widget.compute_bounds(content)
        assert ok
        lines.append(
            f"  {name:<15} x {box.get_x():.0f} y {box.get_y():.0f} "
            f"{box.get_width():.0f}x{box.get_height():.0f}, "
            f"sc-overlay: {widget.has_css_class('sc-overlay')}"
        )
    ellipsized = [
        f"    {label.get_text()!r}"
        for label in _walk(pane)
        if isinstance(label, Gtk.Label)
        and label.get_mapped()
        and label.get_layout().is_ellipsized()
    ]
    lines.append(f"  ellipsized labels: {len(ellipsized) or 'none'}")
    lines.extend(ellipsized)
    return "\n".join(lines)


def _load_project() -> None:
    win.doc_editor.file.load_project_from_path(PROJECT)


def _import_busy() -> None:
    for path, mime, *_ in BUSY:
        win.doc_editor.file.load_file_from_path(path, mime, None)


def _lay_out_busy() -> None:
    items = {
        item.name: item
        for item in win.doc_editor.doc.layers[0].get_content_items()
    }
    for path, _mime, x, y, width, height in BUSY:
        item = items[path.stem]
        item.set_size(width, height)
        item.set_pos(x, y)
    win.surface.set_zoom(ZOOM)
    win.surface.set_pan(*PAN)


def _select_workpiece() -> None:
    win.surface.update_from_doc()
    items = win.doc_editor.doc.layers[0].get_content_items()
    win.surface.select_items(items[:1])


def _show_every_surface() -> None:
    # The app hides the status message on its own status updates, so
    # this runs again right before each capture.
    win._time_estimate_overlay.set_estimated_time(754)
    win._status_message_label.set_text("Job finished in 12:34")
    win._status_message_label.set_visible(True)
    win.drag_drop_cmd._show_drop_overlay()


def main() -> None:
    if getattr(win, _FLAG, False):
        return
    setattr(win, _FLAG, True)
    try:
        _run()
    finally:
        app.quit_idle()


def _run() -> None:
    time.sleep(2)
    run_on_main_thread(_load_project)
    win.doc_editor.wait_until_settled_sync(timeout=20)
    run_on_main_thread(_import_busy)
    time.sleep(3)
    win.doc_editor.wait_until_settled_sync(timeout=30)
    run_on_main_thread(_lay_out_busy)
    win.doc_editor.wait_until_settled_sync(timeout=30)
    run_on_main_thread(_select_workpiece)

    content = win.toast_overlay
    size = f"{SIZE[0]}x{SIZE[1]}"
    run_on_main_thread(lambda: content.set_size_request(*SIZE))
    time.sleep(1.5)
    report = []
    for dark in (False, True):
        _set_scheme(dark)
        theme = "dark" if dark else "light"
        run_on_main_thread(_show_every_surface)
        time.sleep(0.5)
        run_on_main_thread(
            lambda d=dark, t=theme: _capture(
                content, f"glass-{size}-{t}", WINDOW_BG[d]
            )
        )
        run_on_main_thread(
            lambda d=dark, t=theme: _capture(
                win._right_pane, f"glass-pane-{t}", WINDOW_BG[d]
            )
        )
        report.append(run_on_main_thread(lambda t=theme: _measure(t, content)))
    run_on_main_thread(win.drag_drop_cmd._hide_drop_overlay)
    run_on_main_thread(lambda: content.set_size_request(-1, -1))

    (OUTPUT_DIR / "measurements.txt").write_text("\n".join(report) + "\n")
    logger.info("glass surface captures written to %s", OUTPUT_DIR)


main()

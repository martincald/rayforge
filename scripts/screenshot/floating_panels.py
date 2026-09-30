"""Capture the floating panels over the canvas, and measure them.

Run with::

    python -m swiftcut.app --config <isolated-config> \\
        --uiscript scripts/screenshot/floating_panels.py

Loads ``tests/assets/contour.ryp``, gives its first layer a second
Contour step, selects the workpiece and lays the window content out at
1440x900 with the dock visible, as ``dock_fit.py`` does. The window
content and the sidebar alone are captured in the light and the dark
theme into ``docs/screens/floating-panels/``. Next to the captures,
``measurements.txt`` gives the canvas height and the panels' cap, each
panel's allocated height against its natural one, every row fully in
view or cut, and every label under the sidebar that is ellipsized.

Like ``dock_fit.py`` this renders through GTK's own renderer and does
not import ``utils``.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import TypeVar

from gi.repository import Adw, Gdk, GLib, Graphene, Gtk

from swiftcut.core.step_registry import step_registry
from swiftcut.ui_gtk.layout import OVERLAY_PANEL_HEIGHT_FRACTION
from swiftcut.uiscript import app, win

logger = logging.getLogger(__name__)

T = TypeVar("T")

PROJECT_ROOT = Path(__file__).parent.parent.parent
PROJECT = PROJECT_ROOT / "tests" / "assets" / "contour.ryp"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "screens" / "floating-panels"
SIZE = (1440, 900)
SETTLE = 1.0
# sc_window_bg, light and dark (docs/design/swift-cut-tokens.md).
WINDOW_BG = {False: "#F5F5F7", True: "#1C1C1E"}
_FLAG = "_floating_panels_running"


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
    """Every descendant of widget, depth first."""
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


def _span(widget: Gtk.Widget, reference: Gtk.Widget) -> tuple[float, float]:
    """A widget's top and bottom in the reference's coordinates."""
    ok, bounds = widget.compute_bounds(reference)
    assert ok
    return bounds.get_y(), bounds.get_y() + bounds.get_height()


def _natural_height(widget: Gtk.Widget) -> int:
    return widget.measure(Gtk.Orientation.VERTICAL, widget.get_width())[1]


def _row_name(row: Gtk.ListBoxRow) -> str:
    stepbox = getattr(row, "stepbox", None)
    if stepbox is not None:
        return f"step {stepbox.title_label.get_text()}"
    if isinstance(row, Adw.PreferencesRow):
        return row.get_title()
    return type(row).__name__


def _row_lines(pane: Gtk.Widget) -> list[str]:
    """Every row under the sidebar, in view, cut, or scrolled away.

    A row is seen through the sidebar and, inside a panel, through that
    panel's own scroller.
    """
    lines = []
    inside = cut = away = 0
    for row in _walk(pane):
        if not isinstance(row, Gtk.ListBoxRow) or not row.get_mapped():
            continue
        top, bottom = _span(row, pane)
        clip_top, clip_bottom = 0.0, float(pane.get_height())
        scroller = row.get_ancestor(Gtk.ScrolledWindow)
        if scroller is not None and scroller is not pane:
            s_top, s_bottom = _span(scroller, pane)
            clip_top, clip_bottom = (
                max(clip_top, s_top),
                min(clip_bottom, s_bottom),
            )
        if top >= clip_top and bottom <= clip_bottom:
            state = "inside"
            inside += 1
        elif bottom <= clip_top or top >= clip_bottom:
            state = "scrolled away"
            away += 1
        else:
            state = "CUT"
            cut += 1
        lines.append(
            f"    {_row_name(row)!r}: {top:.0f}-{bottom:.0f} "
            f"in view {clip_top:.0f}-{clip_bottom:.0f}: {state}"
        )
    lines.insert(
        0,
        f"  rows: {inside} fully inside, {cut} cut, {away} scrolled away",
    )
    return lines


def _ellipsized(pane: Gtk.Widget) -> list[str]:
    return [
        f"    {label.get_text()!r}"
        for label in _walk(pane)
        if isinstance(label, Gtk.Label)
        and label.get_mapped()
        and label.get_layout().is_ellipsized()
    ]


def _measure(theme: str) -> str:
    """One line per quantity the floating panels are judged by."""
    overlay = win._canvas_overlay
    pane = win._right_pane
    lines = [
        f"{SIZE[0]}x{SIZE[1]} {theme}",
        f"  canvas overlay  {overlay.get_height()}px tall",
        (
            f"  panel cap       {win._panel_height_cap}px "
            f"({OVERLAY_PANEL_HEIGHT_FRACTION:.0%} of the canvas)"
        ),
        (
            f"  sidebar         {pane.get_width()}x{pane.get_height()}px "
            f"allocated of {_natural_height(pane.get_child())}px natural"
        ),
    ]
    # A card's list is the part that can be cut, so it is the list's
    # allocation that is set against its natural height.
    for name, panel, scroller in (
        ("workflow", win.workflowview, win.workflowview.scroller),
        (
            "properties",
            win.item_props_widget,
            win.item_props_widget.scroller,
        ),
    ):
        lines.append(
            f"  {name:<15} card {panel.get_height()}px; list "
            f"{scroller.get_height()}px allocated of "
            f"{_natural_height(scroller.get_child())}px natural "
            f"(max {scroller.get_max_content_height()}px)"
        )
    lines.extend(_row_lines(pane))
    ellipsized = _ellipsized(pane)
    lines.append(f"  ellipsized labels: {len(ellipsized) or 'none'}")
    lines.extend(ellipsized)
    return "\n".join(lines)


def _load_project() -> None:
    win.doc_editor.file.load_project_from_path(PROJECT)


def _add_second_step() -> None:
    workflow = win.doc_editor.doc.layers[0].workflow
    assert workflow is not None
    if len(workflow.steps) < 2:
        step_class = step_registry.get("ContourStep")
        assert step_class is not None
        step = step_class.create(win.doc_editor.context)
        win.doc_editor.step.apply_best_recipe_to_step(step)
        workflow.add_step(step)


def _select_workpiece() -> None:
    win.surface.update_from_doc()
    items = win.doc_editor.doc.layers[0].get_content_items()
    win.surface.select_items(items[:1])


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
    run_on_main_thread(_add_second_step)
    win.doc_editor.wait_until_settled_sync(timeout=20)
    run_on_main_thread(_select_workpiece)
    run_on_main_thread(lambda: win.bottom_panel.set_visible(True))

    content = win.toast_overlay
    pane = win._right_pane
    size = f"{SIZE[0]}x{SIZE[1]}"
    run_on_main_thread(lambda: content.set_size_request(*SIZE))
    time.sleep(1.5)
    report = []
    for dark in (False, True):
        _set_scheme(dark)
        theme = "dark" if dark else "light"
        run_on_main_thread(
            lambda d=dark, t=theme: _capture(
                content, f"panels-{size}-{t}", WINDOW_BG[d]
            )
        )
        run_on_main_thread(
            lambda d=dark, t=theme: _capture(
                pane, f"pane-{size}-{t}", WINDOW_BG[d]
            )
        )
        report.append(run_on_main_thread(lambda t=theme: _measure(t)))
    run_on_main_thread(lambda: content.set_size_request(-1, -1))

    (OUTPUT_DIR / "measurements.txt").write_text("\n".join(report) + "\n")
    logger.info("floating panel captures written to %s", OUTPUT_DIR)


main()

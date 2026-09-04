"""Capture every panel and dialog for the UI consistency audit.

Run with::

    python -m rayforge.app --config <isolated-config> \\
        --uiscript scripts/screenshot/ui_audit.py

Output goes to ``docs/design/audit/`` as
``<target>-<theme>-<width>.png``, or to ``$UI_AUDIT_OUT`` when that is
set - which is how the "after" set was captured without overwriting
the audit's own.

Like ``swift_cut_review.py`` this renders through GTK's own renderer
rather than shelling out to ``gnome-screenshot`` or ImageMagick's
``import``: neither exists on Windows, and asking the toolkit for its
frame captures exactly what was drawn, with no compositor, cursor or
window shadow in the way. It does not import ``utils`` for the same
reason that script does not - ``utils`` fails at import time on a
stale path - so the handful of helpers it needs are inlined.

The matrix is theme x window width. Dialogs are their own toplevels,
so "window width" for them means the size they are given: a dialog
asked for 900px shows the narrow reflow, one asked for 1300px the
wide one.
"""

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import TypeVar

from gi.repository import Adw, GLib, Gtk

from rayforge.uiscript import app, win

logger = logging.getLogger(__name__)

T = TypeVar("T")

PROJECT_ROOT = Path(__file__).parent.parent.parent
# Where the PNGs land. The neighbouring scripts read TARGET from the
# environment the same way; set UI_AUDIT_OUT to capture a second set
# without overwriting the first.
OUTPUT_DIR = Path(
    os.environ.get(
        "UI_AUDIT_OUT", PROJECT_ROOT / "docs" / "design" / "audit"
    )
)

# GTK draws on the next frame-clock tick, not on the property write,
# so every capture waits out a theme swap and a relayout first.
SETTLE = 0.7

# The two window widths the audit compares. The height is the same in
# both so only the width varies between a pair of captures.
WIDTHS = ((1280, 860), (1920, 1080))

# Dialogs are separate toplevels, so they get their own size per
# window width rather than inheriting the main window's.
DIALOG_SIZES = {1280: (900, 760), 1920: (1300, 900)}

# Every dock item the bottom panel registers, captured one at a time.
DOCK_TABS = ("controls", "laser", "layers", "assets", "gcode", "console")

MACHINE_PAGES = (
    "general",
    "hardware",
    "advanced",
    "gcode",
    "hooks-macros",
    "device",
    "heads",
    "rotary-module",
    "nogo-zones",
    "camera",
    "maintenance",
    "capabilities",
)

APP_PAGES = (
    "general",
    "machines",
    "materials",
    "recipes",
    "color_presets",
    "ai",
    "addons",
    "licenses",
)


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


def _capture(widget: Gtk.Widget, name: str) -> bool:
    """Render one widget straight off GTK's renderer into a PNG."""
    native = widget.get_native()
    if native is None:
        logger.error("%s: widget has no native surface", name)
        return False
    renderer = native.get_renderer()
    if renderer is None:
        logger.error("%s: no renderer on the native surface", name)
        return False

    width, height = widget.get_width(), widget.get_height()
    if width <= 0 or height <= 0:
        logger.error("%s: widget has no allocation yet", name)
        return False

    paintable = Gtk.WidgetPaintable.new(widget)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        logger.error("%s: nothing was drawn", name)
        return False

    texture = renderer.render_texture(node, None)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{name}.png"
    texture.save_to_png(str(path))
    logger.info("wrote %s (%dx%d)", path.name, width, height)
    return True


def _set_scheme(dark: bool) -> None:
    """Switch the colour scheme the way the app's own preference does.

    Forcing ``Adw.StyleManager`` alone does not hold: ``MainWindow``
    re-runs ``apply_theme()`` from a config-changed handler, which
    resets the scheme to whatever ``config.theme`` says. Opening a
    settings dialog is enough to trigger that, which silently turned
    the "light" dialog captures dark. Setting the preference means
    every re-application agrees with the capture.
    """
    from rayforge.context import get_context

    get_context().config.set_theme("dark" if dark else "light")
    Adw.StyleManager.get_default().set_color_scheme(
        Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT
    )


def _set_window_size(width: int, height: int) -> None:
    """Resize the main window, shrinking as well as growing.

    Neither obvious call shrinks a mapped toplevel on this backend:
    ``set_size_request`` only ever raises the *minimum*, and
    ``set_default_size`` on an already-mapped window is ignored (both
    measured - the window sat at 2048px through either). Hiding the
    window and presenting it again does apply the new default size,
    so that is what this does.

    Re-presenting re-emits ``map``, which is the signal the app hangs
    the ``--uiscript`` runner on, so the window would start a second
    copy of this script. ``_AUDIT_FLAG`` on the window is how the
    second copy knows to bow out.
    """
    if run_on_main_thread(win.get_width) == width:
        return

    def _resize() -> None:
        win.set_size_request(-1, -1)
        if win.is_maximized():
            win.unmaximize()
        win.set_visible(False)
        win.set_default_size(width, height)
        win.present()

    run_on_main_thread(_resize)

    actual = 0
    for _attempt in range(30):
        actual = run_on_main_thread(win.get_width)
        if actual == width:
            return
        time.sleep(0.1)
    logger.warning("window did not reach %dpx (got %d)", width, actual)


def _show_dock_tab(name: str) -> None:
    def _switch() -> None:
        area = win.bottom_panel.dock_layout.find_item_area(name)
        if area is not None:
            area.set_active_item(name)

    run_on_main_thread(_switch)


def _machine_settings(page: str):
    from rayforge.context import get_context
    from rayforge.ui_gtk.machine.settings_dialog import MachineSettingsDialog

    machine = get_context().config.machine
    if machine is None:
        return None
    return MachineSettingsDialog(
        machine=machine, transient_for=win, initial_page=page
    )


def _app_settings(page: str):
    from rayforge.ui_gtk.settings.settings_dialog import SettingsWindow

    return SettingsWindow(initial_page=page, transient_for=win)


def _cut_scale_sheet():
    from rayforge.ui_gtk.machine.cut_scale_dialog import CutScaleDialog

    dialog = CutScaleDialog(
        default_power_percent=15.0,
        on_confirm=lambda speed, power: None,
    )
    dialog.set_transient_for(win)
    return dialog


def _wcs_sheet():
    from rayforge.context import get_context
    from rayforge.ui_gtk.machine.wcs_dialog import WcsDialog

    machine = get_context().config.machine
    if machine is None:
        return None
    dialog = WcsDialog(machine=machine)
    dialog.set_transient_for(win)
    return dialog


def _step_settings():
    from rayforge.ui_gtk.doceditor.step_settings.dialog import (
        StepSettingsDialog,
    )

    step = None
    for layer in win.doc_editor.doc.layers:
        if layer.workflow and layer.workflow.steps:
            step = layer.workflow.steps[0]
            break
    if step is None:
        return None
    return StepSettingsDialog(
        editor=win.doc_editor, step=step, transient_for=win
    )


def _step_type_sheet():
    from rayforge.ui_gtk.doceditor.step_type_selection_dialog import (
        StepTypeSelectionDialog,
    )

    return StepTypeSelectionDialog(
        parent=win, selected=set(), on_select_callback=lambda names: None
    )


# name -> factory. A factory returning None means the target does not
# apply to this configuration (no machine, no step); it is logged and
# skipped rather than failing the run.
DIALOGS: tuple[tuple[str, Callable[[], object]], ...] = (
    *(
        (f"machine-settings-{p}", (lambda p=p: _machine_settings(p)))
        for p in MACHINE_PAGES
    ),
    *(
        (f"app-settings-{p.replace('_', '-')}", (lambda p=p: _app_settings(p)))
        for p in APP_PAGES
    ),
    ("cut-scale-sheet", _cut_scale_sheet),
    ("wcs-sheet", _wcs_sheet),
    ("step-settings", _step_settings),
    ("step-type-sheet", _step_type_sheet),
)


def _shoot_panels(theme: str, width: int) -> None:
    suffix = f"{theme}-{width}"

    run_on_main_thread(lambda: win.bottom_panel.set_visible(True))
    time.sleep(SETTLE)

    run_on_main_thread(lambda: _capture(win, f"main-window-{suffix}"))
    run_on_main_thread(lambda: _capture(win.toolbar, f"toolbar-{suffix}"))

    for tab in DOCK_TABS:
        _show_dock_tab(tab)
        time.sleep(SETTLE)
        # The dock item widgets paint nothing of their own, so the
        # bottom panel - the nearest ancestor with a surface - is what
        # gets captured, with the tab of interest active.
        run_on_main_thread(
            lambda t=tab: _capture(win.bottom_panel, f"dock-{t}-{suffix}")
        )

    _show_dock_tab("controls")


def _shoot_dialogs(theme: str, width: int) -> None:
    suffix = f"{theme}-{width}"
    dw, dh = DIALOG_SIZES[width]

    for name, factory in DIALOGS:
        try:
            dialog = run_on_main_thread(factory)
        except Exception as e:  # noqa: BLE001 - one target must not
            logger.warning("%s: could not be built (%s)", name, e)
            continue
        if dialog is None:
            logger.warning("%s: not available in this configuration", name)
            continue

        def _present(d=dialog) -> None:
            d.set_default_size(dw, dh)
            d.present()

        run_on_main_thread(_present)
        time.sleep(SETTLE)
        run_on_main_thread(lambda d=dialog: _capture(d, f"{name}-{suffix}"))
        run_on_main_thread(dialog.close)
        time.sleep(0.35)


# Set on the window by the first copy of this script, so the copy the
# resize re-presentation starts can recognise itself and stop.
_AUDIT_FLAG = "_ui_audit_running"


def main() -> None:
    if getattr(win, _AUDIT_FLAG, False):
        logger.debug("audit already running in this window; second copy exits")
        return
    setattr(win, _AUDIT_FLAG, True)

    for width, height in WIDTHS:
        _set_window_size(width, height)
        time.sleep(SETTLE)
        for theme, dark in (("light", False), ("dark", True)):
            run_on_main_thread(lambda d=dark: _set_scheme(d))
            time.sleep(SETTLE)
            logger.info("=== %s @ %dpx ===", theme, width)
            _shoot_panels(theme, width)
            _shoot_dialogs(theme, width)

    logger.info("audit captures written to %s", OUTPUT_DIR)
    app.quit_idle()


main()

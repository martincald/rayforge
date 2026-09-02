"""Capture the Swift Cut reskin for design review, light and dark.

Run with::

    python -m rayforge.app --uiscript scripts/screenshot/swift_cut_review.py

Two things make this script stand apart from its neighbours here.

It renders through GTK rather than shelling out to ``gnome-screenshot``
or ImageMagick's ``import``: neither exists on Windows, and asking the
toolkit for its own frame captures exactly what was drawn, with no
compositor, cursor or window shadow in the way.

And it does not import ``utils``. That module currently fails at
import time on a stale path (``doceditor.edit_recipe_dialog`` now
lives under ``doceditor/recipes/``), which would take this script down
with it, so the two helpers it needed are inlined below.

Output goes to ``docs/design/screens/``.
"""

import logging
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
OUTPUT_DIR = PROJECT_ROOT / "docs" / "design" / "screens"

# GTK draws on the next frame-clock tick, not on the property write,
# so every capture waits out a theme swap and a relayout first.
SETTLE = 0.8


def run_on_main_thread(func: Callable[[], T], timeout: float = 15.0) -> T:
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
    logger.info("wrote %s (%dx%d)", path, width, height)
    return True


def _set_scheme(dark: bool) -> None:
    Adw.StyleManager.get_default().set_color_scheme(
        Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT
    )


def _open_machine_settings(page: str):
    from rayforge.context import get_context
    from rayforge.ui_gtk.machine.settings_dialog import (
        MachineSettingsDialog,
    )

    machine = get_context().config.machine
    if machine is None:
        return None
    dialog = MachineSettingsDialog(
        machine=machine, transient_for=win, initial_page=page
    )
    dialog.present()
    return dialog


def _open_cut_scale_sheet():
    from rayforge.ui_gtk.machine.cut_scale_dialog import CutScaleDialog

    dialog = CutScaleDialog(
        default_power_percent=15.0,
        on_confirm=lambda speed, power: None,
    )
    dialog.set_transient_for(win)
    dialog.present()
    return dialog


def shoot(theme: str) -> None:
    """Capture every review target in the current colour scheme."""
    run_on_main_thread(lambda: win.bottom_panel.set_visible(True))
    time.sleep(SETTLE)

    run_on_main_thread(lambda: _capture(win, f"main-window-{theme}"))
    run_on_main_thread(
        lambda: _capture(win.bottom_panel.jog_widget, f"jog-panel-{theme}")
    )

    # The Ruida connection - hostname, main port 50200, jog port
    # 50207 - is the driver's setup VarSet, which this app renders
    # in General under "Driver Settings". The Device page is for
    # settings read back off the controller, so both are captured.
    for page in ("general", "device"):
        settings = run_on_main_thread(
            lambda p=page: _open_machine_settings(p)
        )
        if settings is None:
            logger.warning("no machine configured; settings skipped")
            break
        time.sleep(SETTLE)
        run_on_main_thread(
            lambda s=settings, p=page: _capture(
                s, f"machine-settings-{p}-{theme}"
            )
        )
        run_on_main_thread(settings.close)
        time.sleep(0.4)

    sheet = run_on_main_thread(_open_cut_scale_sheet)
    time.sleep(SETTLE)
    run_on_main_thread(lambda: _capture(sheet, f"cut-scale-sheet-{theme}"))
    run_on_main_thread(sheet.close)
    time.sleep(0.4)


def main() -> None:
    run_on_main_thread(lambda: _set_scheme(False))
    time.sleep(SETTLE)
    shoot("light")

    run_on_main_thread(lambda: _set_scheme(True))
    time.sleep(SETTLE)
    shoot("dark")

    logger.info("Swift Cut captures written to %s", OUTPUT_DIR)
    app.quit_idle()


main()

"""Report the minimum width every top-level UI region demands.

The audit capture could not shrink the main window below 2048px, and
``Gtk.Window`` cannot go under the minimum its content asks for. This
walks the window's children and prints each one's measured minimum so
the region that sets the floor can be named rather than guessed at.

Run with::

    python -m rayforge.app --config <isolated-config> \\
        --uiscript scripts/screenshot/ui_min_width.py
"""

import logging
from collections.abc import Callable
from threading import Event
from typing import TypeVar

from gi.repository import GLib, Gtk

from rayforge.uiscript import app, win

logger = logging.getLogger(__name__)

T = TypeVar("T")


def run_on_main_thread(func: Callable[[], T], timeout: float = 20.0) -> T:
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


def _min_width(widget: Gtk.Widget) -> int:
    minimum, _nat, _b1, _b2 = widget.measure(
        Gtk.Orientation.HORIZONTAL, -1
    )
    return minimum


def _walk(widget: Gtk.Widget, depth: int = 0, limit: int = 4) -> None:
    name = type(widget).__name__
    classes = ",".join(widget.get_css_classes())
    logger.info(
        "%s%s [%s] min_w=%d visible=%s",
        "  " * depth,
        name,
        classes,
        _min_width(widget),
        widget.get_visible(),
    )
    if depth >= limit:
        return
    child = widget.get_first_child()
    while child is not None:
        _walk(child, depth + 1, limit)
        child = child.get_next_sibling()


def main() -> None:
    def report() -> None:
        logger.info("window is %dx%d", win.get_width(), win.get_height())
        logger.info("window minimum width: %d", _min_width(win))
        _walk(win)

        # And again with the bottom panel hidden, to separate the dock's
        # demand from the rest of the window's.
        was_visible = win.bottom_panel.get_visible()
        win.bottom_panel.set_visible(False)
        logger.info(
            "window minimum width without the bottom panel: %d",
            _min_width(win),
        )
        win.bottom_panel.set_visible(was_visible)

    run_on_main_thread(report)
    app.quit_idle()


main()

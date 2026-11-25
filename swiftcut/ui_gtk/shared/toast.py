import threading
from collections.abc import Callable
from functools import partial

from gi.repository import Adw

from ...shared.util.glib import idle_add


def show_toast(
    overlay: Adw.ToastOverlay,
    message: str,
    *,
    timeout: int | None = None,
    priority: Adw.ToastPriority | None = None,
    button_label: str | None = None,
    on_button: Callable[[], None] | None = None,
    on_shown: Callable[[Adw.Toast], None] | None = None,
) -> None:
    """
    Show a toast with this message on the overlay.

    GTK widgets may only be made and used on the main thread, the one
    the GTK main loop runs on. Called there, the toast is shown at
    once. Called from any other thread, such as the TaskManager's
    event loop, it is built and shown on the main thread once that
    thread is idle.

    The message is plain text, never markup. timeout and priority
    keep the toast's defaults when None. on_button runs when the
    button labelled button_label is pressed. on_shown is handed the
    new toast, on the main thread, just before the overlay shows it.
    """
    show = partial(
        _show,
        overlay,
        message,
        timeout,
        priority,
        button_label,
        on_button,
        on_shown,
    )
    if threading.current_thread() is threading.main_thread():
        show()
    else:
        idle_add(show)


def _show(
    overlay: Adw.ToastOverlay,
    message: str,
    timeout: int | None,
    priority: Adw.ToastPriority | None,
    button_label: str | None,
    on_button: Callable[[], None] | None,
    on_shown: Callable[[Adw.Toast], None] | None,
) -> None:
    """Build a fresh toast and show it. Main thread only."""
    toast = Adw.Toast.new(message)
    # Adw.Toast defaults use-markup to True, and messages interpolate
    # filenames and raw exception text. A project called
    # "Cut & Engrave.ryp" produces markup Pango cannot parse, and the
    # toast renders empty. No caller passes markup.
    toast.set_use_markup(False)
    if timeout is not None:
        toast.set_timeout(timeout)
    if priority is not None:
        toast.set_priority(priority)
    if button_label and on_button:
        toast.set_button_label(button_label)
        toast.connect("button-clicked", lambda t: on_button())
    if on_shown is not None:
        on_shown(toast)
    overlay.add_toast(toast)

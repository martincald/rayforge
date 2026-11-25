# flake8: noqa: E402
"""Toasts are built and shown on the GTK main thread."""

import threading
import time
from unittest.mock import patch

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

from swiftcut.ui_gtk.shared.toast import show_toast


class _Recorded:
    """The toasts an overlay was given, and the threads involved."""

    def __init__(self):
        self.built: list[threading.Thread] = []
        self.toasts: list[Adw.Toast] = []
        self.added: list[threading.Thread] = []


@pytest.fixture
def overlay():
    """A real overlay whose add_toast records each call."""
    overlay = Adw.ToastOverlay()
    recorded = _Recorded()
    build = Adw.Toast.new
    add = overlay.add_toast

    def recording_build(message):
        recorded.built.append(threading.current_thread())
        return build(message)

    def recording_add(toast):
        recorded.toasts.append(toast)
        recorded.added.append(threading.current_thread())
        if threading.current_thread() is threading.main_thread():
            add(toast)

    with (
        patch.object(Adw.Toast, "new", side_effect=recording_build),
        patch.object(overlay, "add_toast", side_effect=recording_add),
    ):
        yield overlay, recorded


def _pump_until(condition, timeout_sec: float = 5.0) -> bool:
    """Iterates the main context until condition holds, or time is up."""
    context = GLib.main_context_default()
    end_time = time.monotonic() + timeout_sec
    while not condition() and time.monotonic() < end_time:
        while context.pending():
            context.iteration(False)
        time.sleep(0.005)
    return condition()


@pytest.mark.ui
def test_a_toast_asked_for_off_the_main_thread_is_made_on_it(overlay):
    overlay, recorded = overlay
    worker = threading.Thread(target=show_toast, args=(overlay, "Saved"))
    worker.start()
    worker.join()

    # Nothing is built or shown until the main loop runs.
    assert recorded.built == []
    assert recorded.added == []
    assert _pump_until(lambda: recorded.added)

    main = threading.main_thread()
    assert recorded.built == [main]
    assert recorded.added == [main]
    assert recorded.toasts[0].get_title() == "Saved"


@pytest.mark.ui
def test_on_the_main_thread_the_toast_is_shown_at_once(overlay):
    overlay, recorded = overlay

    show_toast(overlay, "Saved")

    main = threading.main_thread()
    assert recorded.built == [main]
    assert recorded.added == [main]


@pytest.mark.ui
def test_each_call_shows_a_fresh_plain_text_toast(overlay):
    overlay, recorded = overlay

    show_toast(overlay, "Cut & Engrave.ryp saved")
    show_toast(overlay, "Cut & Engrave.ryp saved")

    first, second = recorded.toasts
    assert first is not second
    assert first.get_title() == "Cut & Engrave.ryp saved"
    assert not first.get_use_markup()


@pytest.mark.ui
def test_unset_options_keep_the_toast_defaults(overlay):
    overlay, recorded = overlay
    default = Adw.Toast.new("Default")

    show_toast(overlay, "Saved")

    [toast] = recorded.toasts
    assert toast.get_timeout() == default.get_timeout()
    assert toast.get_priority() == default.get_priority()
    assert toast.get_button_label() is None


@pytest.mark.ui
def test_the_toast_carries_the_given_options(overlay):
    overlay, recorded = overlay
    pressed, shown = [], []

    def on_shown(toast):
        # Called before the overlay has the toast.
        shown.append((toast, len(recorded.toasts)))

    show_toast(
        overlay,
        "Updates are available",
        timeout=0,
        priority=Adw.ToastPriority.HIGH,
        button_label="Install All",
        on_button=lambda: pressed.append(True),
        on_shown=on_shown,
    )

    [toast] = recorded.toasts
    assert toast.get_timeout() == 0
    assert toast.get_priority() == Adw.ToastPriority.HIGH
    assert toast.get_button_label() == "Install All"
    assert shown == [(toast, 0)]
    toast.emit("button-clicked")
    assert pressed == [True]


@pytest.mark.ui
def test_on_shown_runs_on_the_main_thread_for_a_worker_toast(overlay):
    overlay, recorded = overlay
    shown = []

    def on_shown(toast):
        shown.append(threading.current_thread())

    worker = threading.Thread(
        target=lambda: show_toast(overlay, "Saved", on_shown=on_shown)
    )
    worker.start()
    worker.join()
    assert _pump_until(lambda: recorded.added)

    assert shown == [threading.main_thread()]

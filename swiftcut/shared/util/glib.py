from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from gi.repository import GLib

_discrete_edits = 0


@contextmanager
def discrete_edit() -> Iterator[None]:
    """
    Mark the changes made inside as one discrete edit.

    A typed value committed in a numeric field is one edit, not a
    stream of them: debouncers run it at once instead of waiting for
    more, which keeps it one undo step and lands it before whatever
    control is pressed next.
    """
    global _discrete_edits
    _discrete_edits += 1
    try:
        yield
    finally:
        _discrete_edits -= 1


def in_discrete_edit() -> bool:
    """Whether a :func:`discrete_edit` is in progress."""
    return _discrete_edits > 0


def falsify(func, *args, **kwargs):
    """
    Wrapper for GLib.idle_add, as function must return False, otherwise it
    is automatically rescheduled into the event loop.
    """
    func(*args, **kwargs)
    return False


def idle_add(func, *args, **kwargs):
    """
    Wrapper for GLib.idle_add to support multiple args and kwargs.
    """
    GLib.idle_add(lambda: falsify(func, *args, **kwargs))


class DebounceMixin:
    """A mixin to add debouncing capabilities to a class."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._debounce_timer = 0
        self._debounced_callback: Callable | None = None
        self._debounced_args: tuple = ()

    def _debounce(self, callback: Callable, *args: Any):
        """
        Schedules a callback to be called after a short delay, cancelling any
        previously scheduled callback.
        """
        if self._debounce_timer > 0:
            GLib.source_remove(self._debounce_timer)
            if in_discrete_edit():
                # The pending call may be for another field: run it
                # rather than lose it.
                self._commit_debounced_change()
        self._debounced_callback = callback
        self._debounced_args = args
        if in_discrete_edit():
            self._commit_debounced_change()
            return
        self._debounce_timer = GLib.timeout_add(
            150, self._commit_debounced_change
        )

    def _commit_debounced_change(self) -> bool:
        """Executes the debounced callback and resets the timer."""
        if self._debounced_callback:
            self._debounced_callback(*self._debounced_args)
        self._debounce_timer = 0
        return GLib.SOURCE_REMOVE

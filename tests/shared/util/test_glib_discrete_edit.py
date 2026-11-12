"""DebounceMixin and discrete edits."""

from gi.repository import GLib

from swiftcut.shared.util.glib import (
    DebounceMixin,
    discrete_edit,
    in_discrete_edit,
)


class _Page(DebounceMixin):
    def __init__(self):
        super().__init__()
        self.calls = []

    def record(self, name, value):
        self.calls.append((name, value))


def _cancel(page):
    if page._debounce_timer:
        GLib.source_remove(page._debounce_timer)
        page._debounce_timer = 0


def test_discrete_edit_is_scoped_and_nests():
    assert not in_discrete_edit()
    with discrete_edit():
        with discrete_edit():
            assert in_discrete_edit()
        assert in_discrete_edit()
    assert not in_discrete_edit()


def test_a_continuous_change_still_waits():
    page = _Page()
    page._debounce(page.record, "angle", 10)
    try:
        assert page.calls == []
        assert page._debounce_timer != 0
    finally:
        _cancel(page)


def test_a_discrete_edit_runs_at_once():
    page = _Page()
    with discrete_edit():
        page._debounce(page.record, "passes", 3)
    assert page.calls == [("passes", 3)]
    assert page._debounce_timer == 0


def test_a_discrete_edit_runs_a_pending_change_first():
    """The page has one timer for all its fields: a pending change to
    another field must not be dropped by a commit."""
    page = _Page()
    page._debounce(page.record, "angle", 10)
    with discrete_edit():
        page._debounce(page.record, "passes", 3)
    assert page.calls == [("angle", 10), ("passes", 3)]
    assert page._debounce_timer == 0

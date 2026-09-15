"""
Tests for the single-instance guard (see swiftcut.single_instance).

Pure socket-level tests: no Gtk/Adw import and no GTK application is
ever created here, per the guard's own design goal of detecting a
duplicate launch before any GTK object exists.
"""

import socket
import threading

from swiftcut.single_instance import SingleInstanceGuard


def _free_port() -> int:
    """An ephemeral port free right now, for test isolation."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_first_guard_acquires_and_second_does_not():
    port = _free_port()
    first = SingleInstanceGuard(port=port)
    second = SingleInstanceGuard(port=port)
    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        assert first._sock is not None
        first._sock.close()


def test_second_instance_notifies_the_primary():
    port = _free_port()
    first = SingleInstanceGuard(port=port)
    second = SingleInstanceGuard(port=port)
    assert first.acquire() is True

    received = threading.Event()
    first.listen(lambda: received.set())

    assert second.acquire() is False
    second.notify_primary()

    assert received.wait(timeout=2.0), (
        "the primary instance was never notified of the second launch"
    )
    assert first._sock is not None
    first._sock.close()


def test_notify_primary_does_not_raise_when_nothing_is_listening():
    """
    Best-effort: if the primary vanished between acquire() failing and
    notify_primary() running, this must not crash the exiting launch.
    """
    port = _free_port()
    guard = SingleInstanceGuard(port=port)
    guard.notify_primary()

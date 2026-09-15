"""
Single-instance guard for SwiftCut, for platforms where GApplication's
own uniqueness cannot be relied on.

GApplication normally uses D-Bus (Linux) or a platform-specific
backend to detect an already-running instance and hand off to it
instead of starting a duplicate. On this Windows build that backend
does not work: probing it (two processes registering
Gio.Application(application_id=...) with the same id) showed the
second process's get_is_remote() still False while the first was
alive and holding -- i.e. every launch believes it is the primary
instance. On the Ruida driver this matters more than for most GTK
apps: a second launch would try to bind the same fixed local UDP
response port (RuidaDriver.RESPONSE_PORT) the first already holds,
producing exactly the silent "port in use" symptom this package's
diagnostics were built to catch.

This is a minimal, GTK-independent replacement: a fixed localhost TCP
port doubles as both the lock (whoever binds it first is the primary
instance) and the signal channel (a later launch connects to it and
sends one message to ask the primary to present its window).
"""

import logging
import socket
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Arbitrary and namespaced away from every port this application
# actually talks to (Ruida: 50200, 50207, 40200; the simulator/e2e
# tests use their own loopback ports again distinct from these).
GUARD_PORT = 51987
_PRESENT_MESSAGE = b"present"


class SingleInstanceGuard:
    """
    Claims GUARD_PORT to detect whether this is the first SwiftCut
    instance.

    Usage::

        guard = SingleInstanceGuard()
        if guard.acquire():
            guard.listen(lambda: GLib.idle_add(present_window))
            # ... continue normal startup ...
        else:
            guard.notify_primary()
            # ... exit without creating a window ...
    """

    def __init__(self, port: int = GUARD_PORT):
        self._port = port
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def acquire(self) -> bool:
        """
        Try to become the primary instance.

        Returns True if this process now holds the port (primary),
        False if another process already holds it.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", self._port))
        except OSError:
            sock.close()
            return False
        sock.listen(1)
        self._sock = sock
        return True

    def listen(self, on_second_instance: Callable[[], None]) -> None:
        """
        Start reacting to later launches, in a background thread.

        Only valid after a successful acquire(). ``on_second_instance``
        is called from that background thread, not the caller's -- a
        GTK caller must hop back to the main loop itself (e.g. via
        GLib.idle_add) before touching any widget.
        """
        assert self._sock is not None
        listener = self._sock

        def _serve() -> None:
            while True:
                try:
                    conn, _addr = listener.accept()
                except OSError:
                    return
                try:
                    conn.recv(64)
                finally:
                    conn.close()
                on_second_instance()

        self._thread = threading.Thread(
            target=_serve, name="single-instance-guard", daemon=True
        )
        self._thread.start()

    def notify_primary(self) -> None:
        """
        Ask the primary instance (already holding the port) to
        present its window.

        Best-effort: a failure here just means this launch exits
        without raising the other window, which is no worse than the
        duplicate launch this guard exists to prevent.
        """
        try:
            with socket.create_connection(
                ("127.0.0.1", self._port), timeout=1.0
            ) as sock:
                sock.sendall(_PRESENT_MESSAGE)
        except OSError as e:
            logger.warning(f"Could not notify the running instance: {e}")

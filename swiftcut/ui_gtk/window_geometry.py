"""
Where the main window opens, and how big.

A monitor the window has never been on gets the design size, or 90%
of the monitor's work area when that is smaller: a 13" MacBook gets a
window that fits between the menu bar and the Dock, and a 27" display
gets the size the layout was reviewed at. After that each monitor
remembers its own size and maximized state, and on macOS its position.

GTK 4 has no window position API, so on macOS the position goes
through the NSWindow GDK already holds, and the work area through
GDK's own macOS monitor call. Both are reached with ctypes: the
GdkMacos typelib cannot be loaded, because it declares a
gdk_macos_monitor_get_geometry the library does not export, which
breaks get_geometry() on every monitor once it is imported.
"""

import ctypes
import ctypes.util
import logging
import platform
import sys

from gi.repository import Gdk, Gtk

logger = logging.getLogger(__name__)

#: The size the layout was reviewed at, in the audit's wide pass
#: (docs/design/audit/AUDIT.md, 1920px).
DESIGN_SIZE = (1920, 1080)

#: How much of a monitor's work area a first window may take.
WORKAREA_FRACTION = 0.9


def default_size(workarea: Gdk.Rectangle) -> tuple[int, int]:
    """The size a window opens at on a monitor it has never been on."""
    return (
        min(DESIGN_SIZE[0], int(workarea.width * WORKAREA_FRACTION)),
        min(DESIGN_SIZE[1], int(workarea.height * WORKAREA_FRACTION)),
    )


def monitor_key(monitor: Gdk.Monitor) -> str:
    """
    Name a monitor by where it sits and how big it is.

    Two identical displays swapped between ports are the same place to
    the user, and a monitor that moved in the arrangement is not: a
    remembered position is only valid where it was taken.
    """
    geometry = monitor.get_geometry()
    return f"{geometry.width}x{geometry.height}+{geometry.x}+{geometry.y}"


def restore_size(
    saved: dict | None, workarea: Gdk.Rectangle
) -> tuple[int, int]:
    """The remembered size, never larger than the work area."""
    width, height = default_size(workarea)
    if saved:
        width = min(int(saved.get("width", width)), workarea.width)
        height = min(int(saved.get("height", height)), workarea.height)
    return width, height


class _Rect(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
    ]


class _NSPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _NSRect(ctypes.Structure):
    _fields_ = [("origin", _NSPoint), ("size", _NSPoint)]


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _gpointer(obj) -> int:
    """The C address of a GObject wrapper."""
    get_pointer = ctypes.pythonapi.PyCapsule_GetPointer
    get_pointer.restype = ctypes.c_void_p
    get_pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
    return get_pointer(obj.__gpointer__, None)


def monitor_workarea(monitor: Gdk.Monitor) -> Gdk.Rectangle:
    """
    The part of a monitor a window may use.

    On macOS that excludes the menu bar and the Dock. Elsewhere GTK 4
    offers no portable answer, so the whole monitor is used.
    """
    geometry = monitor.get_geometry()
    if not _is_macos():
        return geometry
    try:
        get_workarea = ctypes.CDLL(None).gdk_macos_monitor_get_workarea
        get_workarea.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Rect)]
        get_workarea.restype = None
        rect = _Rect()
        get_workarea(_gpointer(monitor), ctypes.byref(rect))
    except (AttributeError, OSError):
        logger.debug("No macOS work area; using the monitor geometry")
        return geometry
    if rect.width <= 0 or rect.height <= 0:
        return geometry
    workarea = Gdk.Rectangle()
    workarea.x, workarea.y = rect.x, rect.y
    workarea.width, workarea.height = rect.width, rect.height
    return workarea


def _objc_call(receiver: int, selector: bytes, restype, *args):
    """Send one Objective-C message through the runtime's C entry."""
    objc = ctypes.CDLL(ctypes.util.find_library("objc"))
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    # x86-64 returns a struct this large through objc_msgSend_stret.
    entry = (
        objc.objc_msgSend_stret
        if restype is _NSRect and platform.machine() == "x86_64"
        else objc.objc_msgSend
    )
    argtypes = [type(arg) for arg in args]
    send = ctypes.CFUNCTYPE(
        restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes
    )(ctypes.cast(entry, ctypes.c_void_p).value)
    return send(receiver, objc.sel_registerName(selector), *args)


def _ns_window(window: Gtk.Window) -> int | None:
    """The NSWindow behind a realized GTK window, on macOS."""
    surface = window.get_surface()
    if not _is_macos() or surface is None:
        return None
    try:
        native = ctypes.CDLL(None).gdk_macos_surface_get_native_window
        native.argtypes = [ctypes.c_void_p]
        native.restype = ctypes.c_void_p
        return native(_gpointer(surface))
    except (AttributeError, OSError):
        return None


def window_position(window: Gtk.Window) -> tuple[float, float] | None:
    """The window's frame origin in screen points, where supported."""
    ns_window = _ns_window(window)
    if not ns_window:
        return None
    frame = _objc_call(ns_window, b"frame", _NSRect)
    return frame.origin.x, frame.origin.y


def move_window(window: Gtk.Window, x: float, y: float) -> None:
    """Put the window's frame origin back where it was, if supported."""
    ns_window = _ns_window(window)
    if ns_window:
        _objc_call(ns_window, b"setFrameOrigin:", None, _NSPoint(x, y))


def capture(window: Gtk.Window) -> tuple[str, dict] | None:
    """What to remember about the window, keyed by its monitor."""
    surface = window.get_surface()
    if surface is None:
        return None
    monitor = window.get_display().get_monitor_at_surface(surface)
    if monitor is None:
        return None
    state: dict = {"maximized": window.is_maximized()}
    if not window.is_maximized():
        state["width"] = window.get_width()
        state["height"] = window.get_height()
    position = window_position(window)
    if position is not None:
        state["x"], state["y"] = position
    return monitor_key(monitor), state

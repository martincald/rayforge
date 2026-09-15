import logging
from gettext import gettext as _
from typing import cast

from gi.repository import Gdk, Gtk

from ...image.registry import FileFilter
from ...shared.util.once import once_per_object

logger = logging.getLogger(__name__)

# Name on the scroll-guard controller installed on every numeric
# spin/scale widget, so tests can assert the guard is still in place.
SPINROW_SCROLL_GUARD_NAME = "spinrow-scroll-guard"


def install_scroll_guard(widget: Gtk.Widget) -> Gtk.EventControllerScroll:
    """
    Install a focus-gated scroll guard on a numeric spin/scale widget.

    A SpinButton or Scale on a scrollable page otherwise consumes wheel
    events and silently edits its own value as the page scrolls past
    it -- that is how a machine's Ruida port was changed from 50200 to
    50201 by nothing more than scrolling, corrupting a live profile
    (the Driver Settings group applies every change immediately).

    The guard lets a scroll reach the widget (and change its value)
    only while the widget has keyboard focus; otherwise it swallows
    the scroll and forwards it to the nearest ancestor
    Gtk.ScrolledWindow instead, so the page still scrolls normally
    underneath it. Forwarding is required, not cosmetic: GtkScrolled
    Window's own capture-phase controller (gtkscrolledwindow.c,
    captured_scroll_cb) is a passthrough for the first event of any
    scroll -- it only takes over once its bubble-phase controller
    (scroll_controller_scroll) has already started a smooth-scroll
    sequence. That bubble-phase controller is the one that actually
    moves the adjustment, for both wheel and touchpad input, and a
    CAPTURE-phase controller here returning True stops the event
    before it ever reaches that bubble phase (GTK4 propagation: a
    stopped event never runs later phases). So without forwarding,
    scrolling over an unfocused guarded field would do nothing at
    all, not merely fail to edit the field. Verified against GTK
    4.22.4 (mingw-w64-x86_64-gtk4).
    """
    guard = Gtk.EventControllerScroll.new(
        Gtk.EventControllerScrollFlags.BOTH_AXES
    )
    guard.set_name(SPINROW_SCROLL_GUARD_NAME)
    guard.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def _on_scroll(_controller, dx: float, dy: float) -> bool:
        # FOCUS_WITHIN, not has_focus(). Gtk.SpinButton is not itself
        # focusable -- focus lands on its internal Gtk.Text child --
        # so has_focus() is permanently False on a SpinButton and the
        # gate would swallow every scroll unconditionally, focused or
        # not. Measured: after grab_focus(), sb.has_focus() is False
        # while FOCUS_WITHIN is True, and the same holds for
        # Gtk.Scale.
        if widget.get_state_flags() & Gtk.StateFlags.FOCUS_WITHIN:
            return False
        _forward_scroll_to_ancestor(widget, dx, dy)
        return True

    guard.connect("scroll", _on_scroll)
    widget.add_controller(guard)
    return guard


def _forward_scroll_to_ancestor(
    widget: Gtk.Widget, dx: float, dy: float
) -> None:
    """
    Apply a swallowed scroll to the nearest ancestor ScrolledWindow.

    Mirrors GtkScrolledWindow's own wheel-detent step
    (pow(page_size, 2/3) per axis, gtkscrolledwindow.c
    get_wheel_detent_scroll_step) closely enough that the page scrolls
    at the speed the user expects, without depending on GTK internals
    that are not part of the public API.
    """
    scrolled = widget.get_ancestor(Gtk.ScrolledWindow)
    if scrolled is None:
        return
    for adj, delta in (
        (scrolled.get_hadjustment(), dx),
        (scrolled.get_vadjustment(), dy),
    ):
        if not delta or adj is None:
            continue
        step = adj.get_page_size() ** (2.0 / 3.0)
        lower = adj.get_lower()
        upper = adj.get_upper() - adj.get_page_size()
        adj.set_value(max(lower, min(adj.get_value() + delta * step, upper)))


def get_monitor_geometry() -> Gdk.Rectangle | None:
    """
    Returns a rectangle for the current monitor dimensions. If not found,
    may return None.
    """
    display = Gdk.Display.get_default()
    if not display:
        return None

    monitors = display.get_monitors()
    if not monitors:
        return None
    monitor = cast(Gdk.Monitor, monitors[0])

    # Try to get the monitor under the cursor (heuristic for active
    # monitor). Note: Wayland has no concept of "primary monitor"
    # anymore, so Gdk.get_primary_monitor() is obsolete.
    # Fallback to the first monitor if no monitor is found under the cursor
    seat = display.get_default_seat()
    if not seat:
        return monitor.get_geometry()

    pointer = seat.get_pointer()
    if not pointer:
        return monitor.get_geometry()

    surface, _x, _y = pointer.get_surface_at_position()
    if not surface:
        return monitor.get_geometry()

    monitor_under_mouse = display.get_monitor_at_surface(surface)
    if not monitor_under_mouse:
        return monitor.get_geometry()

    return monitor_under_mouse.get_geometry()


def get_screen_size() -> tuple[int, int] | None:
    """Get the current monitor's screen size as (width, height)."""
    geometry = get_monitor_geometry()
    if not geometry:
        return None
    return (geometry.width, geometry.height)


@once_per_object
def apply_css(css: str):
    provider = Gtk.CssProvider()
    provider.load_from_string(css)
    display = Gdk.Display.get_default()
    if not display:
        logger.warning("No default Gdk display found. CSS may not apply.")
        return
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def file_filter_to_gtk(
    filt: FileFilter, translate: bool = True
) -> Gtk.FileFilter:
    """
    Convert a FileFilter dataclass to a Gtk.FileFilter.

    Args:
        filt: The FileFilter to convert.
        translate: Whether to translate the label using gettext.

    Returns:
        A configured Gtk.FileFilter instance.
    """
    gtk_filter = Gtk.FileFilter()
    label = _(filt.label) if translate else filt.label
    gtk_filter.set_name(label)
    for ext in filt.extensions:
        gtk_filter.add_pattern(f"*{ext}")
    for mime_type in filt.mime_types:
        gtk_filter.add_mime_type(mime_type)
    return gtk_filter

"""
The three layers a guided tour lays over the main window.

The mask dims the whole window but a hole at the step's target. The
shield under it takes every click outside the hole. The bubble beside
the hole says what the step is about. They sit in the window's tour
overlay only while a tour plays.
"""

import math
from collections.abc import Callable, Iterable, Sequence
from gettext import gettext as _

from gi.repository import Adw, Gdk, Graphene, Gsk, Gtk

from ..layout import CSS_LENGTHS, SPACE_CONTROL, SPACE_GROUP, SPACE_TIGHT
from ..machine.connection_status_widget import ConnectionStatusWidget

# x, y, width and height, in the tour overlay's logical pixels.
Rect = tuple[float, float, float, float]

# The room the hole leaves around its target, and its corner: a
# button's radius grown by that room, so the two curves run parallel.
HOLE_PAD = SPACE_TIGHT
_BUTTON_RADIUS = float(CSS_LENGTHS["radius_button"].removesuffix("px"))
HOLE_RADIUS = _BUTTON_RADIUS + HOLE_PAD

# The dim is black at this opacity. The theme has no scrim token, so
# these are the tour's own. Work in the dark theme is dark already and
# needs a deeper dim to fall back behind the target.
SCRIM_ALPHA_LIGHT = 0.5
SCRIM_ALPHA_DARK = 0.6

# A hole taller than this share of the window (the canvas) gets the
# bubble at its middle: beside it, the bubble would leave the window.
_TALL_HOLE = 0.4

# The room the bubble's arrow keeps from the bubble's ends: about half
# its base, so it never hangs off a corner.
_ARROW_ROOM = SPACE_GROUP

# The width the bubble's text wraps at, in characters.
_TEXT_WIDTH = 36


def hole_rect(
    bounds: Rect, clips: Sequence[Rect], scale: float, pad: float = HOLE_PAD
) -> Rect | None:
    """
    The hole for a target with these bounds, or None if none shows.

    The bounds grow by pad and are cut to every clip: the scrollers the
    target is seen through, and the window. The hole then rounds out to
    whole device pixels at scale, so its edge never halves a pixel.
    """
    x, y, width, height = bounds
    left, top = x - pad, y - pad
    right, bottom = x + width + pad, y + height + pad
    for clip_x, clip_y, clip_width, clip_height in clips:
        left, top = max(left, clip_x), max(top, clip_y)
        right = min(right, clip_x + clip_width)
        bottom = min(bottom, clip_y + clip_height)
    if right <= left or bottom <= top:
        return None
    # A bound a float's hair past a pixel edge stays on that edge.
    left = math.floor(left * scale + 1e-6) / scale
    top = math.floor(top * scale + 1e-6) / scale
    right = math.ceil(right * scale - 1e-6) / scale
    bottom = math.ceil(bottom * scale - 1e-6) / scale
    return left, top, right - left, bottom - top


def target_hole(target: Gtk.Widget, overlay: Gtk.Widget) -> Rect | None:
    """The hole for target, in overlay's coordinates and at its scale."""
    bounds = bounds_in(target, overlay)
    if bounds is None:
        return None
    width, height = overlay.get_width(), overlay.get_height()
    clips = [(0.0, 0.0, float(width), float(height))]
    scroller = target.get_ancestor(Gtk.ScrolledWindow)
    while scroller is not None:
        clip = bounds_in(scroller, overlay)
        if clip is not None:
            clips.append(clip)
        parent = scroller.get_parent()
        scroller = parent.get_ancestor(Gtk.ScrolledWindow) if parent else None
    surface = overlay.get_native().get_surface()
    scale = surface.get_scale() if surface else overlay.get_scale_factor()
    return hole_rect(bounds, clips, scale)


def bounds_in(widget: Gtk.Widget, reference: Gtk.Widget) -> Rect | None:
    """widget's bounds in reference's coordinates, if they have any."""
    ok, bounds = widget.compute_bounds(reference)
    if not ok:
        return None
    return (
        bounds.get_x(),
        bounds.get_y(),
        bounds.get_width(),
        bounds.get_height(),
    )


def _inside(rect: Rect, x: float, y: float) -> bool:
    left, top, width, height = rect
    return left <= x < left + width and top <= y < top + height


def _meet(a: Rect, b: Rect) -> bool:
    """Whether two rects share any area."""
    return (
        a[0] < b[0] + b[2]
        and b[0] < a[0] + a[2]
        and a[1] < b[1] + b[3]
        and b[1] < a[1] + a[3]
    )


def _pixels(left: float, top: float, right: float, bottom: float):
    """The whole pixels that hold these edges."""
    rect = Gdk.Rectangle()
    rect.x, rect.y = math.floor(left), math.floor(top)
    rect.width = math.ceil(right) - rect.x
    rect.height = math.ceil(bottom) - rect.y
    return rect


class TourMask(Gtk.Widget):
    """
    The dim over the whole window, with a rounded hole at the target.

    It is painted here, not by a stylesheet, because the theme owns
    every colour a stylesheet writes. It takes no input; the shield
    under it does. The bubble is its child.
    """

    def __init__(self):
        super().__init__(can_target=False)
        self.hole: Rect | None = None

    def set_hole(self, hole: Rect | None):
        if hole != self.hole:
            self.hole = hole
            self.queue_draw()

    @staticmethod
    def scrim() -> Gdk.RGBA:
        """The dim's colour in the theme now showing."""
        dark = Adw.StyleManager.get_default().get_dark()
        color = Gdk.RGBA()
        color.red = color.green = color.blue = 0.0
        color.alpha = SCRIM_ALPHA_DARK if dark else SCRIM_ALPHA_LIGHT
        return color

    def do_snapshot(self, snapshot):
        builder = Gsk.PathBuilder.new()
        builder.add_rect(
            Graphene.Rect().init(0, 0, self.get_width(), self.get_height())
        )
        if self.hole is not None:
            rounded = Gsk.RoundedRect()
            rounded.init_from_rect(
                Graphene.Rect().init(*self.hole), HOLE_RADIUS
            )
            builder.add_rounded_rect(rounded)
        snapshot.append_fill(
            builder.to_path(), Gsk.FillRule.EVEN_ODD, self.scrim()
        )

    def do_size_allocate(self, width, height, baseline):
        # A popover is placed by its parent, as the parent is allocated.
        child = self.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Popover):
                child.present()
            child = child.get_next_sibling()


class TourShield(Gtk.Widget):
    """
    Takes every pointer event over the window but those in the hole
    and over the controls that must always work.

    It has no event controllers, so what it takes goes nowhere. Where
    it does not contain a point it is not there at all: a press in the
    hole reaches the target as if no tour played, and the release that
    press's implicit grab owns reaches the target wherever it happens.
    """

    def __init__(self, passes: Callable[[], Iterable[Gtk.Widget]]):
        super().__init__()
        self.hole: Rect | None = None
        # Stop, Pause and the others a tour never covers, as they are
        # now.
        self.passes = passes

    def do_contains(self, x, y):
        if self.hole is not None and _inside(self.hole, x, y):
            return False
        for widget in self.passes():
            if not (widget.get_mapped() and widget.is_sensitive()):
                continue
            bounds = bounds_in(widget, self)
            if bounds is not None and _inside(bounds, x, y):
                return False
        return True


class TourBubble(Gtk.Popover):
    """
    A step's heading and text beside its hole, with Back, Skip and
    Next.

    It never hides by itself: a popover that does grabs the pointer as
    it opens, which would cancel a jog held down in the hole.
    """

    def __init__(self):
        super().__init__(autohide=False, has_arrow=True)
        self.heading = Gtk.Label(
            xalign=0, wrap=True, max_width_chars=_TEXT_WIDTH
        )
        self.heading.add_css_class("sc-title")
        self.body = Gtk.Label(xalign=0, wrap=True, max_width_chars=_TEXT_WIDTH)
        # Why the step's control is not there to point at.
        self.reason = Gtk.Label(
            xalign=0, wrap=True, max_width_chars=_TEXT_WIDTH, visible=False
        )
        self.reason.add_css_class("sc-caption")
        # The live connection state, for the step that asks to connect.
        self.connection_status = ConnectionStatusWidget()
        self.connection_status.set_visible(False)

        self.counter = Gtk.Label(xalign=0, hexpand=True)
        self.counter.add_css_class("sc-caption")
        self.back_button = Gtk.Button(label=_("Back"))
        self.back_button.add_css_class("flat")
        self.skip_button = Gtk.Button(label=_("Skip"))
        self.skip_button.add_css_class("flat")
        self.next_button = Gtk.Button(label=_("Next"))
        self.next_button.add_css_class("suggested-action")
        buttons = Gtk.Box(spacing=SPACE_CONTROL)
        for widget in (
            self.counter,
            self.back_button,
            self.skip_button,
            self.next_button,
        ):
            buttons.append(widget)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_CONTROL
        )
        content.set_margin_start(SPACE_CONTROL)
        content.set_margin_end(SPACE_CONTROL)
        content.set_margin_top(SPACE_CONTROL)
        content.set_margin_bottom(SPACE_CONTROL)
        for widget in (
            self.heading,
            self.body,
            self.connection_status,
            self.reason,
            buttons,
        ):
            content.append(widget)
        self.set_child(content)

    def show_step(self, heading: str, body: str, number: int, count: int):
        """Show step number of count; the last one ends with Done."""
        self.heading.set_label(heading)
        self.body.set_label(body)
        self.counter.set_label(
            _("{number} of {count}").format(number=number, count=count)
        )
        self.back_button.set_sensitive(number > 1)
        self.skip_button.set_visible(number < count)
        self.next_button.set_label(_("Done") if number == count else _("Next"))

    def set_reason(self, reason: str):
        self.reason.set_label(reason)
        self.reason.set_visible(bool(reason))

    def point_at(
        self,
        hole: Rect | None,
        width: float,
        height: float,
        keep_clear: Sequence[Rect] = (),
    ):
        """
        Beside the hole: above it in the window's lower half, below it
        in the upper, slid along that side to stay in the window and
        off keep_clear, the controls that must always take a click.
        Where it cannot stand beside the hole like that, or there is no
        hole, it sits in the window's middle; a hole too tall to stand
        beside has it in the hole's middle. A bubble in a middle slides
        off keep_clear too, if it can. Only a bubble beside its hole
        has an arrow; in a middle it points at nothing.
        """
        middle_x, middle_y = width / 2, height / 2
        if hole is not None and hole[3] <= height * _TALL_HOLE:
            x, y, hole_width, hole_height = hole
            rect = _pixels(x, y, x + hole_width, y + hole_height)
            above = y + hole_height / 2 > height / 2
            self.set_has_arrow(True)
            self.set_position(
                Gtk.PositionType.TOP if above else Gtk.PositionType.BOTTOM
            )
            # A control in the hole is the step's own, and the bubble
            # stands outside the hole.
            offset = self._slide(
                rect,
                above,
                width,
                [clear for clear in keep_clear if not _meet(clear, hole)],
            )
            if offset is not None:
                self.set_offset(offset, 0)
                self.set_pointing_to(rect)
                return
        elif hole is not None:
            middle_x = hole[0] + hole[2] / 2
            middle_y = hole[1] + hole[3] / 2
        # Hung from a point half its height above the middle. Its
        # content is measured: a popover not yet shown measures 0.
        natural = self.get_child().measure(Gtk.Orientation.VERTICAL, -1)[1]
        x, y = middle_x, max(0.0, middle_y - natural / 2)
        rect = _pixels(x, y, x + 1, y + 1)
        self.set_has_arrow(False)
        self.set_position(Gtk.PositionType.BOTTOM)
        # A window too small to hold it clear of them all gets it in
        # the middle all the same.
        offset = self._slide(rect, False, width, keep_clear)
        self.set_offset(offset or 0, 0)
        self.set_pointing_to(rect)

    def _slide(
        self,
        rect: Gdk.Rectangle,
        above: bool,
        width: float,
        keep_clear: Sequence[Rect],
    ) -> int | None:
        """
        How far the bubble slides along rect's side, the hole or the
        point a bubble in a middle hangs from, to stay in the window,
        with its whole popup off keep_clear and its arrow, if it has
        one, still on the hole; None if it cannot.

        The popup is the drawn bubble and the shadow round it. The
        shadow is see-through, but macOS may still hand it a click, so
        it must not lie over a control that has to take one.
        """
        horizontal = Gtk.Orientation.HORIZONTAL
        # The popover's own measure: measure() gives 0 while it is not
        # shown, this gives the size it will be shown at.
        popup_width = Gtk.Popover.do_measure(self, horizontal, -1)[1]
        popup_height = Gtk.Popover.do_measure(
            self, Gtk.Orientation.VERTICAL, popup_width
        )[1]
        drawn = self.get_child().get_parent().measure(horizontal, -1)[1]
        shadow = popup_width - drawn
        # GTK hangs the popup's middle from the hole's, the arrow's tip
        # on the hole's edge. Past the tip only the shadow reaches, no
        # deeper than its two sides are wide together.
        anchor = rect.x + rect.width // 2
        left = anchor - popup_width // 2
        tip = rect.y if above else rect.y + rect.height
        top = tip - popup_height if above else tip - shadow

        def popup(offset: int) -> Rect:
            return (left + offset, top, popup_width, popup_height + shadow)

        # The drawn bubble stays a control's space inside the window;
        # its shadow may hang out, as the popup is a window of its own.
        start = left + shadow / 2
        end = start + drawn
        offset = 0
        if end > width - SPACE_CONTROL:
            offset = math.floor(width - SPACE_CONTROL - end)
        elif start < SPACE_CONTROL:
            offset = math.ceil(SPACE_CONTROL - start)
        for clear in keep_clear:
            if not _meet(popup(offset), clear):
                continue
            # To the control's near side, the side the hole's middle
            # is on.
            if clear[0] + clear[2] / 2 > anchor:
                offset = math.floor(clear[0]) - left - popup_width
            else:
                offset = math.ceil(clear[0] + clear[2]) - left
        start, end = start + offset, end + offset
        if (
            start < SPACE_CONTROL
            or end > width - SPACE_CONTROL
            or (
                self.get_has_arrow()
                and not start + _ARROW_ROOM <= anchor <= end - _ARROW_ROOM
            )
            or any(_meet(popup(offset), clear) for clear in keep_clear)
        ):
            return None
        return offset

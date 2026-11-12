import locale
from collections.abc import Callable

from gi.repository import Adw, Gtk

from .gtk import apply_css, install_scroll_guard
from .numeric_entry import NumericEntry

SLIDER_TRACK_WIDTH = 200
VALUE_LABEL_WIDTH = 60


def create_slider(
    adjustment: Gtk.Adjustment,
    digits: int = 1,
    draw_value: bool = True,
    on_value_changed: Callable[[Gtk.Scale], None] | None = None,
) -> Gtk.Scale:
    scale = Gtk.Scale(
        orientation=Gtk.Orientation.HORIZONTAL,
        adjustment=adjustment,
        digits=digits,
        draw_value=draw_value,
    )
    scale.set_size_request(SLIDER_TRACK_WIDTH, 60 if draw_value else -1)
    scale.set_valign(Gtk.Align.CENTER)
    # See install_scroll_guard: a Scale on a scrollable page otherwise
    # consumes wheel events meant for the page.
    install_scroll_guard(scale)

    if on_value_changed:
        scale.connect("value-changed", on_value_changed)

    return scale


_SLIDER_VALUE_ENTRY_CSS = """
.slider-value-entry { outline: none; }
"""


class NumericSliderRow(Adw.ActionRow):
    """A slider row whose value entry is a :class:`NumericEntry`."""

    __gtype_name__ = "RayforgeNumericSliderRow"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.numeric_entry: NumericEntry | None = None


def create_slider_row(
    title: str,
    adjustment: Gtk.Adjustment,
    subtitle: str | None = None,
    digits: int = 1,
    draw_value: bool = True,
    on_value_changed: Callable[[Gtk.Scale], None] | None = None,
    format_suffix: str | None = None,
    numeric_entry: bool = False,
) -> tuple[Adw.ActionRow, Gtk.Scale]:
    """
    Build a row holding a slider and, with ``draw_value``, an entry
    showing its value.

    By default the entry commits on Enter and focus loss and reads a
    plain number. With ``numeric_entry`` the row is a
    :class:`NumericSliderRow` and the entry behaves as a
    :class:`NumericEntry`: expressions, Esc, arrow steps and the rest.
    """
    scale = create_slider(
        adjustment=adjustment,
        digits=digits,
        draw_value=False,
        on_value_changed=on_value_changed,
    )

    numeric_row = NumericSliderRow(title=title) if numeric_entry else None
    row = numeric_row or Adw.ActionRow(title=title)
    if subtitle:
        row.set_subtitle(subtitle)

    if draw_value:
        entry = Gtk.Entry()
        entry.set_width_chars(8)
        entry.set_alignment(1.0)
        entry.set_has_frame(False)
        entry.add_css_class("slider-value-entry")
        apply_css(_SLIDER_VALUE_ENTRY_CSS)

        def format_value(val):
            text = locale.format_string(f"%.{digits}f", val)
            if format_suffix:
                text += format_suffix
            return text

        def update_entry(s):
            entry.set_text(format_value(s.get_value()))

        scale.connect("value-changed", update_entry)
        update_entry(scale)

        def commit_entry(e):
            text = e.get_text()
            if format_suffix and text.endswith(format_suffix):
                text = text[: -len(format_suffix)]
            try:
                adjustment.set_value(locale.atof(text))
            except ValueError:
                update_entry(scale)

        if numeric_row is not None:
            numeric_row.numeric_entry = NumericEntry(
                entry,
                adjustment=adjustment,
                digits=digits,
                render=lambda: update_entry(scale),
                suffix=format_suffix or "",
            )
        else:
            entry.connect("activate", commit_entry)

            focus_ctrl = Gtk.EventControllerFocus()
            focus_ctrl.connect("leave", lambda c: commit_entry(entry))
            entry.add_controller(focus_ctrl)

        row.add_suffix(entry)

    row.add_suffix(scale)

    return row, scale

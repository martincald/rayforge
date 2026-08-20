"""Generic slider row for one numeric step attribute."""

from typing import TYPE_CHECKING, Any

from gi.repository import Adw, Gtk

from rayforge.ui_gtk.shared.slider import create_slider

from .step_row import DebouncedMixin, StepRow

if TYPE_CHECKING:
    from rayforge.doceditor.editor import DocEditor


class SliderRow(DebouncedMixin, StepRow):
    """A slider row bound to one numeric step attribute.

    The slider and the numeric entry beside it share one
    :class:`Gtk.Adjustment`, so typing and dragging stay in sync with
    no extra wiring. ``display_scale`` lets a row whose attribute is a
    0.0-1.0 fraction present itself on a 0-100 scale; the adjustment
    (and therefore both widgets) works in display units and only
    :meth:`commit` / :meth:`set_widget_value` cross back to attribute
    units.
    """

    def __init__(
        self,
        editor: "DocEditor",
        step: Any,
        attr: str,
        title: str,
        subtitle: str | None,
        lower: float,
        upper: float,
        step_inc: float,
        digits: int,
        display_scale: float = 1.0,
        suffix: str | None = None,
    ):
        self._display_scale = display_scale
        self._suffix = suffix
        self._adj = Gtk.Adjustment(
            lower=lower * display_scale,
            upper=upper * display_scale,
            step_increment=step_inc,
            page_increment=step_inc * 10,
        )
        self._digits = digits
        self._title = title
        self._subtitle = subtitle
        DebouncedMixin.__init__(self)
        StepRow.__init__(self, editor, step)
        self.attr = attr
        self._scale.connect("value-changed", self._on_scale)
        self._sync_from_step()
        self._sync_dependencies()

    def build_widget(self) -> Adw.ActionRow:
        if self._subtitle:
            row = Adw.ActionRow(title=self._title, subtitle=self._subtitle)
        else:
            row = Adw.ActionRow(title=self._title)
        self._spin = Gtk.SpinButton(adjustment=self._adj, digits=self._digits)
        self._spin.set_valign(Gtk.Align.CENTER)
        self._spin.set_width_chars(6)
        self._scale = create_slider(
            adjustment=self._adj,
            digits=self._digits,
            draw_value=False,
        )
        row.add_suffix(self._spin)
        if self._suffix:
            suffix_label = Gtk.Label(label=self._suffix)
            suffix_label.add_css_class("dim-label")
            suffix_label.set_valign(Gtk.Align.CENTER)
            row.add_suffix(suffix_label)
        row.add_suffix(self._scale)
        return row

    def _on_scale(self, scale):
        if self._syncing:
            return
        self._debounced(
            self.commit, self._adj.get_value() / self._display_scale
        )

    def set_widget_value(self, value):
        if value is None:
            return
        target = float(value) * self._display_scale
        if abs(self._adj.get_value() - target) > 1e-9:
            self._adj.set_value(target)

    def set_range(self, lower: float, upper: float):
        lower *= self._display_scale
        upper *= self._display_scale
        if (
            abs(self._adj.get_lower() - lower) > 1e-9
            or abs(self._adj.get_upper() - upper) > 1e-9
        ):
            self._adj.set_lower(lower)
            self._adj.set_upper(upper)

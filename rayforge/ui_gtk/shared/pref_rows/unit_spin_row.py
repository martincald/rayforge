import logging
from gettext import gettext as _

from gi.repository import Gtk

from ....context import get_context
from ....shared.units.definitions import Unit, get_unit
from .base import SpinRow

logger = logging.getLogger(__name__)


class UnitSpinRow(SpinRow):
    """
    A unit-aware spin row.

    Builds on :class:`SpinRow`, showing the current unit (e.g. ``"mm"``)
    after the entry box, live conversion on display-unit changes, and
    base-unit get/set.

    The unit used to live only in the entry's tooltip, so that it was
    not "repeated in every subtitle or as a suffix". The audit found
    the cost of that: rows like Max Cut Speed, Acceleration, Offset
    and Overcut showed a bare number with no unit visible anywhere,
    and a unit an operator has to hover to find is a unit they will
    get wrong. It is a suffix now - once, in the field, never also in
    the title or the caption.

    Values are exchanged with the caller in application base units through
    :meth:`get_value_in_base_units` / :meth:`set_value_in_base_units`.
    Bounds passed as ``lower``/``upper`` (or :meth:`set_range`) are also
    expressed in base units and converted to the display unit whenever it
    changes.
    """

    __gtype_name__ = "RayforgeUnitSpinRow"

    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        *,
        quantity: str = "length",
        lower: float = 0.0,
        upper: float = 1e9,
        step_increment: float = 1.0,
        page_increment: float | None = None,
        digits: int = 2,
        numeric: bool = False,
        value_in_base: float | None = None,
        debounce_ms: int = 0,
    ):
        super().__init__(
            title,
            subtitle,
            lower=lower,
            upper=upper,
            step_increment=step_increment,
            page_increment=page_increment,
            digits=digits,
            numeric=numeric,
            debounce_ms=debounce_ms,
        )

        self.quantity = quantity
        self._unit: Unit | None = None
        self._min_digits = digits
        self._lower = lower
        self._upper = upper

        self._unit_label = Gtk.Label()
        self._unit_label.add_css_class("sc-caption")
        self._unit_label.set_valign(Gtk.Align.CENTER)
        self._suffix.append(self._unit_label)

        self._config_handler_id = get_context().config.changed.connect(
            self._on_config_changed
        )

        # Guard the initial unit/value setup so it does not fire
        # ``value_changed``.
        self._is_updating = True
        try:
            self.update_unit_and_bounds()
            if value_in_base is not None and self._unit:
                self._spin_button.set_value(
                    self._unit.from_base(value_in_base)
                )
        finally:
            self._is_updating = False

    def _resolve_unit_name(self) -> str | None:
        """Return the name of the unit to display for this row.

        Defaults to the configured preference for :attr:`quantity`;
        subclasses (e.g. a row with an inline unit chooser) override this
        to return a per-row choice instead.
        """
        return get_context().config.unit_preferences.get(self.quantity)

    def update_unit_and_bounds(self) -> None:
        """
        Re-read the active unit and refresh the unit tooltip, adjustment
        bounds, and digits.

        The bounds are converted from base units to the active display
        unit. Does not touch the current value and does not manage the
        ``_is_updating`` guard; callers wrap as needed.
        """
        unit_name = self._resolve_unit_name()
        self._unit = get_unit(unit_name) if unit_name else None
        if not self._unit:
            logger.warning(
                "UnitSpinRow: no unit found for quantity %r", self.quantity
            )
            self._unit_label.set_label("")
            return

        self._unit_label.set_label(self._unit.label)
        self._spin_button.set_tooltip_text(
            _("Value in {unit}").format(unit=self._unit.label)
        )

        adj = self._spin_button.get_adjustment()
        adj.set_lower(self._unit.from_base(self._lower))
        adj.set_upper(self._unit.from_base(self._upper))
        self._spin_button.set_digits(
            max(self._unit.precision, self._min_digits)
        )

    def get_value_in_base_units(self) -> float:
        """Return the current value converted to application base units."""
        if not self._unit:
            return self._get_display_value()
        return float(self._unit.to_base(self._get_display_value()))

    def set_value_in_base_units(self, base_value: float) -> None:
        """Set the value from an application base-unit value."""
        if self._is_updating:
            return
        self._is_updating = True
        try:
            self.update_unit_and_bounds()
            if not self._unit:
                logger.warning("UnitSpinRow: skipping set, no unit")
                return
            self._spin_button.set_value(self._unit.from_base(base_value))
        finally:
            self._is_updating = False

    def set_range(self, lower: float, upper: float) -> None:
        """Set the adjustment bounds (in base units) and re-render."""
        self._lower = lower
        self._upper = upper
        self.update_unit_and_bounds()

    def set_min_digits(self, min_digits: int) -> None:
        """Override the minimum number of decimal digits shown."""
        self._min_digits = min_digits
        self.update_unit_and_bounds()

    def _on_config_changed(self, _sender, **_kwargs) -> None:
        # Preserve the semantic value across a display-unit switch.
        if not self._unit:
            self.update_unit_and_bounds()
            return
        base_value = self._unit.to_base(self._get_display_value())
        self._is_updating = True
        try:
            self.update_unit_and_bounds()
            if self._unit:
                display_value = self._unit.from_base(base_value)
                if abs(display_value - self._get_display_value()) >= 1e-12:
                    self._spin_button.set_value(display_value)
        finally:
            self._is_updating = False

    def _on_destroy(self, _widget) -> None:
        super()._on_destroy(_widget)
        if self._config_handler_id:
            get_context().config.changed.disconnect(self._config_handler_id)
        self._config_handler_id = None

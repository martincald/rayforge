# flake8: noqa: E402
"""A default spin row reports every keystroke, as it always has."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import pytest

from swiftcut.ui_gtk.shared.pref_rows import LengthSpinRow, SpeedSpinRow


@pytest.mark.ui
@pytest.mark.parametrize(
    "row_cls, unit_quantity, unit",
    [(LengthSpinRow, "length", "mm"), (SpeedSpinRow, "speed", "mm/s")],
)
def test_typing_emits_on_every_keystroke(
    ui_context_initializer, row_cls, unit_quantity, unit
):
    ui_context_initializer.config.unit_preferences[unit_quantity] = unit
    row = row_cls("Field", lower=0, upper=10000, value_in_base=0.0)
    seen = []
    row.value_changed.connect(lambda r: seen.append(r.get_value()), weak=False)
    spin = row.get_spin_button()

    for text in ("1", "12", "125"):
        spin.set_text(text)

    assert seen == [1.0, 12.0, 125.0]

# flake8: noqa: E402
"""Which numeric fields commit typed values, and which keep keystrokes."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import pytest
from gi.repository import Adw, Gtk

from swiftcut.core.varset import (
    FloatVar,
    IntVar,
    LengthVar,
    SliderFloatVar,
    VarSet,
)
from swiftcut.ui_gtk.doceditor.property_providers.transform import (
    TransformPropertyProvider,
)
from swiftcut.ui_gtk.doceditor.property_providers.workpiece import (
    TabsPropertyProvider,
)
from swiftcut.ui_gtk.shared.pref_rows import (
    AngleSpinRow,
    LengthSpinRow,
    SpeedSpinRow,
    SpinRow,
)
from swiftcut.ui_gtk.shared.slider import NumericSliderRow, create_slider_row
from swiftcut.ui_gtk.varset.adapter.slider import SliderAdapter
from swiftcut.ui_gtk.varset.varsetwidget import VarSetRowList, VarSetWidget


def _varset():
    return VarSet(
        vars=[
            IntVar("count", "Count", default=2),
            FloatVar("ratio", "Ratio", default=0.5),
            LengthVar("gap", "Gap", default=1.0),
        ]
    )


def _spin_rows(rows):
    return [row for row, _var in rows.widget_map.values()]


@pytest.mark.ui
def test_a_spin_row_keeps_keystrokes_by_default(ui_context_initializer):
    for row in (
        SpinRow("Count"),
        LengthSpinRow("Length"),
        SpeedSpinRow("Speed"),
        AngleSpinRow("Angle"),
    ):
        assert row.numeric_entry is None


@pytest.mark.ui
def test_properties_panel_fields_commit(ui_context_initializer):
    transform = TransformPropertyProvider()
    transform.create_widgets()
    tabs = TabsPropertyProvider()
    tabs.create_widgets()
    for row in (
        transform.x_row,
        transform.y_row,
        transform.width_row,
        transform.height_row,
        transform.angle_row,
        transform.shear_row,
        tabs.tab_width_row,
    ):
        assert row.numeric_entry is not None, row.get_title()


@pytest.mark.ui
def test_varset_rows_commit_only_where_asked(ui_context_initializer):
    settings = VarSetWidget()
    settings.populate(_varset())
    plain_list = VarSetRowList()
    plain_list.populate(_varset())
    committing = VarSetRowList(numeric_entries=True)
    committing.populate(_varset())

    for rows in (settings, plain_list):
        spin_rows = _spin_rows(rows)
        assert len(spin_rows) == 3
        assert all(row.numeric_entry is None for row in spin_rows)
    spin_rows = _spin_rows(committing)
    assert len(spin_rows) == 3
    assert all(row.numeric_entry is not None for row in spin_rows)


@pytest.mark.ui
def test_slider_rows_keep_their_entry_unless_asked(ui_context_initializer):
    adj = Gtk.Adjustment(lower=0, upper=100, step_increment=1)
    row, _scale = create_slider_row("Power", adj)
    assert type(row) is Adw.ActionRow
    asked, _scale = create_slider_row(
        "Power", Gtk.Adjustment(upper=100), numeric_entry=True
    )
    assert isinstance(asked, NumericSliderRow)
    assert asked.numeric_entry is not None

    adapter_row, _adapter = SliderAdapter.create(
        SliderFloatVar("power", "Power", min_val=0.0, max_val=1.0), "value"
    )
    assert not isinstance(adapter_row, NumericSliderRow)

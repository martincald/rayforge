"""The dock is built at one density, from one definition.

The compact density is defined once, in ``swiftcut/ui_gtk/layout.py``.
No other module in ``ui_gtk`` writes a pixel length, the dock's own
modules size nothing with a bare number, every jog-grid button asks
for one size, and every spin field in the dock is the compact one.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from swiftcut.ui_gtk import layout

UI_GTK = Path(layout.__file__).parent
TOKEN_MODULE = Path(layout.__file__)

# The dock's own modules. Beyond writing no "px", they size nothing
# with a bare number: a margin, gap or size request names a token.
DOCK_MODULES = (
    "doceditor/asset_browser.py",
    "doceditor/bottom_panel.py",
    "doceditor/group_row.py",
    "doceditor/layer_column.py",
    "doceditor/layers_tab.py",
    "doceditor/workflow_row.py",
    "doceditor/workpiece_row.py",
    "machine/console.py",
    "machine/jog_widget.py",
    "machine/laser_control_widget.py",
    "shared/dock_area.py",
    "shared/dock_item.py",
    "shared/dock_layout.py",
    "shared/responsive_box.py",
)

# The floating panels over the canvas, Layer Workflow and Workpiece
# Properties, take the dock's density and are held to the same rule.
PANEL_MODULES = (
    "doceditor/item_properties.py",
    "doceditor/property_providers/transform.py",
    "doceditor/property_providers/workpiece.py",
    "doceditor/step_box.py",
    "doceditor/workflow_view.py",
    "shared/draglist.py",
    "shared/expander.py",
    "shared/number_badge.py",
)

_PIXELS = re.compile(r"\d+(\.\d+)?px")
_BARE_SIZE = re.compile(
    r"\b(set_size_request|set_margin_\w+|set_spacing|set_row_spacing"
    r"|set_column_spacing|set_min_content_\w+|set_max_content_\w+)"
    r"\(\s*[1-9]"
    r"|\b(spacing|margin_\w+)=\s*[1-9]"
)
# The asset thumbnails are pictures, not controls, and keep their own
# size (docs/design/swift-cut-layout.md, section 2).
_PICTURES = re.compile(r"THUMBNAIL_SIZE|CARD_SIZE|type_icon\.set_pixel_size")


def _lines(path: Path):
    return enumerate(path.read_text().splitlines(), 1)


def test_no_module_but_the_token_module_writes_a_pixel_length():
    offenders = [
        f"{path.relative_to(UI_GTK)}:{number}: {line.strip()}"
        for path in sorted(UI_GTK.rglob("*.py"))
        if path != TOKEN_MODULE
        for number, line in _lines(path)
        if _PIXELS.search(line)
    ]

    assert offenders == []


@pytest.mark.parametrize("module", DOCK_MODULES + PANEL_MODULES)
def test_the_dock_sizes_nothing_with_a_bare_number(module):
    offenders = [
        f"{module}:{number}: {line.strip()}"
        for number, line in _lines(UI_GTK / module)
        if _BARE_SIZE.search(line) and not _PICTURES.search(line)
    ]

    assert offenders == []


def test_there_is_exactly_one_density():
    densities = [
        value
        for value in vars(layout).values()
        if isinstance(value, layout.Density)
    ]
    defined_elsewhere = [
        f"{path.relative_to(UI_GTK)}:{number}"
        for path in sorted(UI_GTK.rglob("*.py"))
        if path != TOKEN_MODULE
        for number, line in _lines(path)
        if "Density(" in line
    ]

    assert densities == [layout.COMPACT]
    assert defined_elsewhere == []


def test_the_compact_density_is_the_one_the_dock_asked_for():
    assert layout.COMPACT.row_height == 32
    assert layout.COMPACT.control_size == 32
    assert layout.COMPACT.icon_glyph == 16
    assert layout.COMPACT.jog_cell == 40
    assert (layout.COMPACT.spin_width, layout.COMPACT.spin_height) == (
        96,
        28,
    )
    assert (layout.COMPACT.space_control, layout.COMPACT.space_group) == (
        4,
        8,
    )
    assert layout.COMPACT.panel_max_width == 400
    assert layout.COMPACT.caption_font < layout.DESIGN_FONT_PX


def test_the_floating_panels_are_capped_as_asked():
    assert layout.COMPACT.overlay_panel_width == 360
    assert layout.OVERLAY_PANEL_HEIGHT_FRACTION == 0.6


def test_a_stylesheet_role_that_does_not_exist_fails_loudly():
    with pytest.raises(KeyError):
        layout.stylesheet(".x { margin: $no_such_role; }")


def _descendants(widget, kind):
    found = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, kind):
            found.append(child)
        found.extend(_descendants(child, kind))
        child = child.get_next_sibling()
    return found


@pytest.mark.ui
def test_every_jog_grid_button_shares_one_size_request(
    ui_context_initializer,
):
    from gi.repository import Gtk

    from swiftcut.ui_gtk.machine.jog_widget import JogWidget

    widget = JogWidget()
    buttons = _descendants(widget, Gtk.Button)

    # Eight arrows, Home, the two scales and the five-button job column.
    assert len(buttons) == 16
    assert {tuple(b.get_size_request()) for b in buttons} == {
        (layout.JOG_CELL, layout.JOG_CELL)
    }


@pytest.mark.ui
def test_every_dock_spin_button_is_the_compact_size(
    ui_context_initializer, ui_task_mgr
):
    from gi.repository import Gtk

    from swiftcut.doceditor.editor import DocEditor
    from swiftcut.ui_gtk.doceditor.bottom_panel import BottomPanel

    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    try:
        panel = BottomPanel(
            ui_context_initializer.config.machine, editor, MagicMock()
        )
        spins = _descendants(panel, Gtk.SpinButton)

        # Jog speed and distance, and the laser tab's three fields.
        assert len(spins) == 5
        assert {tuple(s.get_size_request()) for s in spins} == {
            (layout.SPIN_WIDTH, layout.SPIN_HEIGHT)
        }
    finally:
        editor.cleanup()


@pytest.mark.ui
def test_the_properties_panel_is_at_the_compact_density(
    ui_context_initializer, ui_task_mgr, monkeypatch
):
    from gi.repository import Gtk

    from swiftcut.doceditor.editor import DocEditor
    from swiftcut.ui_gtk.doceditor.item_properties import (
        DocItemPropertiesWidget,
    )
    from swiftcut.ui_gtk.doceditor.property_providers import (
        property_provider_registry,
        register_builtin_providers,
    )

    # The main window registers these; the addons' own stay out.
    monkeypatch.setattr(property_provider_registry, "_providers", [])
    monkeypatch.setattr(property_provider_registry, "_addon_map", {})
    register_builtin_providers()
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    try:
        panel = DocItemPropertiesWidget(editor)
        spins = _descendants(panel, Gtk.SpinButton)
        buttons = [
            b
            for b in _descendants(panel, Gtk.Button)
            if b.get_ancestor(Gtk.SpinButton) is None
        ]

        # X, Y, width, height, angle, shear and the tab width.
        assert len(spins) == 7
        assert {tuple(s.get_size_request()) for s in spins} == {
            (layout.SPIN_WIDTH, layout.SPIN_HEIGHT)
        }
        # The resets, the file buttons and Remove all tabs.
        assert buttons
        assert all(b.has_css_class("sc-icon-button") for b in buttons)
    finally:
        editor.cleanup()


@pytest.mark.ui
def test_a_step_is_one_compact_row(ui_context_initializer, ui_task_mgr):
    from gi.repository import Gtk

    from swiftcut.core.step import Step
    from swiftcut.doceditor.editor import DocEditor
    from swiftcut.ui_gtk import theme
    from swiftcut.ui_gtk.doceditor.step_box import StepBox

    theme.install()
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    try:
        step = Step(typelabel="Contour")
        step.name = "Contour"
        box = StepBox(editor, step, 1)
        box.subtitle_label.set_text("1000 mm/s, 80% power")
        window = Gtk.Window(child=box)
        window.present()

        _, natural, _, _ = box.measure(Gtk.Orientation.VERTICAL, -1)

        assert natural <= layout.ROW_MIN_HEIGHT_COMPACT
        window.destroy()
    finally:
        editor.cleanup()


@pytest.mark.ui
def test_a_narrow_step_row_cuts_the_summary_not_the_name(
    ui_context_initializer, ui_task_mgr
):
    from gi.repository import Gtk

    from swiftcut.core.step import Step
    from swiftcut.doceditor.editor import DocEditor
    from swiftcut.ui_gtk.doceditor.step_box import StepBox

    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    try:
        step = Step(typelabel="Contour")
        step.name = "Contour"
        box = StepBox(editor, step, 1)
        box.mode_tag_label.set_text("Centerline")
        box.mode_tag.set_visible(True)
        box.subtitle_label.set_text("100% power, 8.3 mm/s")

        def shortfall(widget):
            low, high, _, _ = widget.measure(Gtk.Orientation.HORIZONTAL, -1)
            return high - low

        # Room for the name and the mode in full, and little more.
        width = (
            box.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
            + shortfall(box.title_label)
            + shortfall(box.mode_tag)
            + 4
        )
        box.allocate(width, layout.ROW_MIN_HEIGHT_COMPACT, -1, None)

        assert not box.title_label.get_layout().is_ellipsized()
        assert box.subtitle_label.get_layout().is_ellipsized()
        assert box.subtitle_label.get_tooltip_text() == step.get_summary()
    finally:
        editor.cleanup()


@pytest.mark.ui
def test_the_sidebar_is_capped_at_a_share_of_the_canvas():
    from gi.repository import Gdk

    from swiftcut.ui_gtk.mainwindow import MainWindow

    pane, other = MagicMock(), MagicMock()
    window = MagicMock(_right_pane=pane)
    overlay = MagicMock()
    overlay.get_width.return_value = 1100
    overlay.get_height.return_value = 800

    allocation = Gdk.Rectangle()
    placed = MainWindow._on_canvas_overlay_child_position(
        window, overlay, pane, allocation
    )

    assert placed is True
    assert (allocation.x, allocation.y) == (0, 0)
    assert allocation.width == 1100
    assert allocation.height == round(
        800 * layout.OVERLAY_PANEL_HEIGHT_FRACTION
    )
    # Every other overlay keeps GTK's own placement.
    assert (
        MainWindow._on_canvas_overlay_child_position(
            window, overlay, other, Gdk.Rectangle()
        )
        is False
    )

"""The floating panels over the canvas render whole, never cropped.

Layer Workflow and Workpiece Properties each take their natural height
up to a share of the canvas and scroll inside their own card past it,
header in view. A step row gives its labels their natural width: at
the panel's width everything sits on one line, and narrower its
controls wrap onto a line of their own instead of cutting the name,
the mode or the summary short.
"""

from functools import partial
from unittest.mock import MagicMock

import pytest

from swiftcut.ui_gtk import layout


@pytest.fixture
def editor(ui_context_initializer, ui_task_mgr):
    from swiftcut.doceditor.editor import DocEditor
    from swiftcut.ui_gtk import theme

    theme.install()
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    yield editor
    editor.cleanup()


def _step_box(editor):
    from swiftcut.core.step import Step
    from swiftcut.ui_gtk.doceditor.step_box import StepBox

    step = Step(typelabel="Contour")
    step.name = "Contour"
    box = StepBox(editor, step, 1)
    box.mode_tag_label.set_text("Centerline")
    box.mode_tag.set_visible(True)
    box.subtitle_label.set_text("100% power, 8.3 mm/s")
    return box


def _labels(box):
    return (box.title_label, box.mode_tag_label, box.subtitle_label)


def _allocate(widget, width):
    from gi.repository import Gtk

    height = widget.measure(Gtk.Orientation.VERTICAL, width)[1]
    widget.allocate(width, height, -1, None)


def _bounds(widget, reference):
    ok, rect = widget.compute_bounds(reference)
    assert ok
    return rect


@pytest.mark.ui
def test_a_step_row_in_the_panel_shows_every_label_whole(editor):
    from gi.repository import Gtk

    from swiftcut.ui_gtk.shared.draglist import DragListBox

    box = _step_box(editor)
    draglist = DragListBox()
    row = Gtk.ListBoxRow()
    row.set_child(box)
    draglist.add_row(row)
    window = Gtk.Window(child=draglist)

    # The list is as wide as the panel less its end margin, and the
    # list adds its drag handle and margins, as in the main window.
    _allocate(draglist, layout.OVERLAY_PANEL_WIDTH - layout.SPACE_GROUP)

    for label in _labels(box):
        natural = label.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        assert label.get_width() >= natural, label.get_text()
        assert not label.get_layout().is_ellipsized(), label.get_text()
    # The summary has the row's full width, on one line.
    assert box.subtitle_label.get_width() == box.get_width()
    assert not box.subtitle_label.get_layout().is_wrapped()
    # Labels at the start, the controls at the end of the same line.
    labels = _bounds(box.label_box, box.head)
    actions = _bounds(box.actions, box.head)
    assert labels.get_x() == 0
    assert actions.get_y() < labels.get_y() + labels.get_height()
    assert actions.get_x() + actions.get_width() == box.head.get_width()
    window.destroy()


@pytest.mark.ui
def test_a_narrow_step_row_wraps_its_controls_not_its_labels(editor):
    from gi.repository import Gtk

    box = _step_box(editor)
    window = Gtk.Window(child=box)
    labels_width = box.label_box.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
    one_line = box.measure(Gtk.Orientation.HORIZONTAL, -1)[1]

    # Room for the name and the mode but not the controls beside them,
    # and half the one-line width.
    for width in (labels_width, one_line // 2):
        assert width < one_line
        _allocate(box, width)

        labels = _bounds(box.label_box, box)
        actions = _bounds(box.actions, box)
        assert actions.get_y() >= labels.get_y() + labels.get_height()
        for label in _labels(box):
            assert not label.get_layout().is_ellipsized(), label.get_text()
    window.destroy()


def _assert_scrolls_in_its_card(scroller, content, header, panel):
    from gi.repository import Gtk

    assert isinstance(scroller, Gtk.ScrolledWindow)
    assert content.get_ancestor(Gtk.ScrolledWindow) is scroller
    assert header.get_ancestor(Gtk.ScrolledWindow) is None
    assert scroller.get_policy() == (
        Gtk.PolicyType.NEVER,
        Gtk.PolicyType.AUTOMATIC,
    )
    assert scroller.get_propagate_natural_height()

    # Before layout the header is taken as one compact row.
    panel.set_max_height(300)
    assert scroller.get_max_content_height() == (
        300 - layout.ROW_MIN_HEIGHT_COMPACT
    )

    window = Gtk.Window(child=panel)
    _allocate(panel, panel.measure(Gtk.Orientation.HORIZONTAL, -1)[1])
    assert header.get_height() > 0
    panel.set_max_height(300)
    assert scroller.get_max_content_height() == 300 - header.get_height()

    # Never less than one row.
    panel.set_max_height(0)
    assert scroller.get_max_content_height() == layout.ROW_MIN_HEIGHT_COMPACT
    window.destroy()


@pytest.mark.ui
def test_the_workflow_panel_scrolls_its_steps_inside_its_card(editor):
    from swiftcut.ui_gtk.doceditor.workflow_view import WorkflowView

    view = WorkflowView(editor, editor.doc.active_layer.workflow)

    _assert_scrolls_in_its_card(
        view.scroller, view.draglist, view.header, view
    )


@pytest.mark.ui
def test_the_properties_panel_scrolls_its_rows_inside_its_card(
    editor, monkeypatch
):
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
    panel = DocItemPropertiesWidget(editor)

    _assert_scrolls_in_its_card(
        panel.scroller,
        panel._rows_container,
        panel._main_expander.header,
        panel,
    )


@pytest.mark.ui
def test_the_sidebar_takes_the_canvas_and_caps_each_panel(monkeypatch):
    from gi.repository import Gdk, GLib

    from swiftcut.ui_gtk.mainwindow import MainWindow

    scheduled = []
    monkeypatch.setattr(
        GLib, "idle_add", lambda func, *args: scheduled.append((func, args))
    )
    pane, other = MagicMock(), MagicMock()
    window = MagicMock(_right_pane=pane, _panel_height_cap=None)
    window._set_panel_height_cap = partial(
        MainWindow._set_panel_height_cap, window
    )
    overlay = MagicMock()
    overlay.get_width.return_value = 1100
    overlay.get_height.return_value = 800

    allocation = Gdk.Rectangle()
    placed = MainWindow._on_canvas_overlay_child_position(
        window, overlay, pane, allocation
    )

    assert placed is True
    assert (allocation.x, allocation.y) == (0, 0)
    assert (allocation.width, allocation.height) == (1100, 800)
    # The panels are resized after layout, not inside it.
    window.workflowview.set_max_height.assert_not_called()
    assert len(scheduled) == 1
    func, args = scheduled[0]
    assert func(*args) == GLib.SOURCE_REMOVE
    cap = round(800 * layout.OVERLAY_PANEL_HEIGHT_FRACTION)
    window.workflowview.set_max_height.assert_called_once_with(cap)
    window.item_props_widget.set_max_height.assert_called_once_with(cap)
    # The same canvas height pushes nothing again.
    MainWindow._on_canvas_overlay_child_position(
        window, overlay, pane, Gdk.Rectangle()
    )
    assert len(scheduled) == 1
    # Every other overlay keeps GTK's own placement.
    assert (
        MainWindow._on_canvas_overlay_child_position(
            window, overlay, other, Gdk.Rectangle()
        )
        is False
    )

"""The Groups card in the layers panel.

Before the layer cards, and only while the document has a group, a
card lists each group across layers: a node per group (nested groups
nested), a row per member item with a badge in its layer's colour and
name. A click selects the whole group, a member row dragged onto a
layer card moves that item there and keeps it in its group, and a
node's menu renames, ungroups, selects or moves the whole group.
"""

import pytest

from swiftcut.core.doc import Doc
from swiftcut.core.item_group import ItemGroup
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.ui_gtk.doceditor.layers_tab import LayersTab
from swiftcut.ui_gtk.doceditor.workpiece_row import WorkpieceRow

pytestmark = pytest.mark.ui


@pytest.fixture
def tab(ui_context_initializer, ui_task_mgr):
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    yield LayersTab(editor), editor
    editor.cleanup()


def _pieces(editor, *layer_indices):
    """One piece on each of the given layers."""
    pieces = []
    for i in layer_indices:
        wp = WorkPiece(name=f"on layer {i}")
        editor.doc.layers[i].add_workpiece(wp)
        pieces.append(wp)
    return pieces


def _rows(column):
    """
    The card's rows: a node as ("node", group, name, count, indent),
    a member as ("member", item, layer name, chip classes, indent).
    """
    rows = []
    row = column.listbox.get_first_child()
    while row is not None:
        box = row.get_child()
        if row in column._row_items:
            badge = box.get_last_child()
            rows.append(
                (
                    "member",
                    column._row_items[row],
                    badge.get_last_child().get_text(),
                    badge.get_first_child().get_css_classes(),
                    box.get_margin_start(),
                )
            )
        else:
            name = box.get_first_child().get_next_sibling()
            count = box.get_last_child()
            rows.append(
                (
                    "node",
                    column._row_groups[row],
                    name.get_text(),
                    count.get_text(),
                    box.get_margin_start(),
                )
            )
        row = row.get_next_sibling()
    return rows


def _row_of(column, item):
    return next(r for r, i in column._row_items.items() if i is item)


def _chip_class(layer):
    return "group-layer-chip-" + layer.color.lstrip("#").lower()


def _column_of(tab, layer):
    return next(c for c in tab._columns if c.layer is layer)


def test_a_two_layer_group_is_one_node_with_a_badge_per_layer(tab):
    tab, editor = tab
    layers = list(editor.doc.layers)
    outline, artwork = _pieces(editor, 0, 1)
    group = editor.group.group_items([outline, artwork], name="Logo")
    column = tab.groups_column

    assert column.get_visible()
    assert tab.columns_box.get_first_child() is column
    node, *members = _rows(column)
    assert node[:4] == ("node", group, "Logo", "2")
    assert [m[1] for m in members] == [outline, artwork]
    for member, layer in zip(members, layers):
        assert member[2] == layer.name
        assert _chip_class(layer) in member[3]
        assert member[4] > node[4]
    assert _chip_class(layers[0]) != _chip_class(layers[1])
    row = _row_of(column, artwork).get_child()
    assert isinstance(row, WorkpieceRow)
    assert row.name_label.get_text() == "on layer 1"


def test_a_nested_group_is_a_node_in_its_parent(tab):
    tab, editor = tab
    a, b, c = _pieces(editor, 0, 1, 2)
    inner = editor.group.group_items([a, b], name="Inner")
    outer = editor.group.group_items([a, c], name="Outer")
    column = tab.groups_column

    rows = _rows(column)
    assert [r[:3] for r in rows] == [
        ("node", outer, "Outer"),
        ("node", inner, "Inner"),
        ("member", a, "Layer 1"),
        ("member", b, "Layer 2"),
        ("member", c, "Layer 3"),
    ]
    indents = [r[4] for r in rows]
    assert indents[0] < indents[1] == indents[4] < indents[2] == indents[3]
    assert rows[0][3] == "2"


def test_a_closed_node_stays_closed_across_rebuilds(tab):
    tab, editor = tab
    a, b, c = _pieces(editor, 0, 1, 2)
    inner = editor.group.group_items([a, b], name="Inner")
    outer = editor.group.group_items([a, c], name="Outer")
    column = tab.groups_column

    column.toggle_group(inner)
    assert [r[1] for r in _rows(column)] == [outer, inner, c]

    editor.group.rename_group(outer, "Renamed")
    editor.doc.layers[0].add_workpiece(WorkPiece(name="other"))
    assert [r[1] for r in _rows(column)] == [outer, inner, c]

    column.toggle_group(inner)
    assert [r[1] for r in _rows(column)] == [outer, inner, a, b, c]


def test_the_card_shows_only_while_there_is_a_group(tab):
    tab, editor = tab
    history = editor.history_manager
    column = tab.groups_column
    outline, artwork = _pieces(editor, 0, 1)
    assert not column.get_visible()

    group = editor.group.group_items([outline, artwork])
    assert column.get_visible()
    history.undo()
    assert not column.get_visible()
    history.redo()
    assert column.get_visible()

    editor.group.ungroup_groups([group])
    assert not column.get_visible()
    history.undo()
    assert column.get_visible()

    # A group whose items are all deleted is not shown.
    outline.parent.remove_child(outline)
    artwork.parent.remove_child(artwork)
    assert not column.get_visible()


def test_a_badge_follows_its_layers_name_and_colour(tab):
    tab, editor = tab
    layer = editor.doc.layers[1]
    outline, artwork = _pieces(editor, 0, 1)
    editor.group.group_items([outline, artwork])
    column = tab.groups_column

    editor.layer.rename_layer(layer, "Engrave")
    layer.set_color("#123456")

    member = next(r for r in _rows(column) if r[1] is artwork)
    assert member[2] == "Engrave"
    assert "group-layer-chip-123456" in member[3]


def test_dragging_a_member_onto_a_layer_card_moves_it_alone(tab, monkeypatch):
    from gi.repository import Gdk, Gtk

    tab, editor = tab
    layers = list(editor.doc.layers)
    outline, artwork = _pieces(editor, 0, 1)
    group = editor.group.group_items([outline, artwork])
    column = tab.groups_column
    groups = editor.doc.item_groups
    # A click on the row selected the whole group, on the canvas too.
    column.select_group(group)
    tab.update_row_selection({outline.uid, artwork.uid})

    values = []
    new_for_value = Gdk.ContentProvider.new_for_value

    def recording(value):
        values.append(value)
        return new_for_value(value)

    monkeypatch.setattr(Gdk.ContentProvider, "new_for_value", recording)
    row = _row_of(column, artwork)
    (source,) = [
        c for c in row.observe_controllers() if isinstance(c, Gtk.DragSource)
    ]
    source.emit("prepare", 0.0, 0.0)
    (value,) = values

    target = _column_of(tab, layers[2])
    column._on_member_drag_begin(source, None)
    assert target._on_drop(None, value, 0, 0)
    column._on_member_drag_end(source, None, False)

    assert artwork.parent is layers[2]
    assert outline.parent is layers[0]
    assert groups.parent_of(artwork.uid) is group
    assert target._ordered_items == [artwork]
    member = next(r for r in _rows(column) if r[1] is artwork)
    assert member[2] == layers[2].name
    assert _chip_class(layers[2]) in member[3]

    editor.history_manager.undo()
    assert artwork.parent is layers[1]


def test_rename_from_the_menu_is_undoable(tab):
    tab, editor = tab
    group = editor.group.group_items(_pieces(editor, 0, 1), name="Old")
    column = tab.groups_column

    dialog = column.rename_group(group)
    dialog.get_extra_child().set_text("  Logo ")
    dialog.response("save")

    assert group.name == "Logo"
    assert _rows(column)[0][2] == "Logo"
    editor.history_manager.undo()
    assert group.name == "Old"
    assert _rows(column)[0][2] == "Old"


def test_ungroup_from_the_menu_is_undoable(tab):
    tab, editor = tab
    group = editor.group.group_items(_pieces(editor, 0, 1))
    column = tab.groups_column

    column.ungroup_group(group)
    assert list(editor.doc.item_groups) == []
    assert not column.get_visible()
    editor.history_manager.undo()
    assert list(editor.doc.item_groups) == [group]
    assert column.get_visible()


def test_select_all_members_selects_the_whole_visible_group(tab):
    tab, editor = tab
    a, b, c = _pieces(editor, 0, 1, 2)
    inner = editor.group.group_items([a, b])
    editor.group.group_items([a, c])
    column = tab.groups_column
    requests = []

    def record(sender, *, items):
        requests.append(items)

    tab.select_items_requested.connect(record)
    column.select_group(inner)
    editor.doc.layers[1].set_visible(False)
    column.select_group(inner)

    # The canvas shows a grouped item as its outermost group.
    assert requests == [[a, b, c], [a, c]]
    assert tab.get_selected_items() == [a, c]


def test_move_all_to_layer_is_one_undo_step_and_keeps_the_group(tab):
    tab, editor = tab
    layers = list(editor.doc.layers)
    a, b, c = _pieces(editor, 0, 1, 2)
    inner = editor.group.group_items([a, b])
    outer = editor.group.group_items([a, c])
    layers[1].set_visible(False)
    groups = editor.doc.item_groups
    history = editor.history_manager
    entries = len(history.undo_stack)

    tab.groups_column.move_group_to_layer(outer, layers[2])

    assert [p.parent for p in (a, b, c)] == [layers[2]] * 3
    assert groups.parent_of(a.uid) is inner
    assert groups.parent_of(inner.uid) is outer
    assert len(history.undo_stack) == entries + 1
    history.undo()
    assert [p.parent for p in (a, b, c)] == layers


def test_the_menu_actions_reach_the_handlers(tab):
    from gi.repository import GLib

    tab, editor = tab
    layers = list(editor.doc.layers)
    a, b = _pieces(editor, 0, 1)
    group = editor.group.group_items([a, b])
    column = tab.groups_column
    requests = []

    def record(sender, *, items):
        requests.append(items)

    tab.select_items_requested.connect(record)
    column._menu_group = group
    column.activate_action("groups.select", None)
    column.activate_action(
        "groups.move-to-layer", GLib.Variant.new_string(layers[2].uid)
    )
    assert requests == [[a, b]]
    assert a.parent is b.parent is layers[2]

    column.activate_action("groups.ungroup", None)
    assert list(editor.doc.item_groups) == []


def test_a_new_document_brings_its_own_groups(tab):
    tab, _editor = tab
    column = tab.groups_column
    doc = Doc()
    a, b = WorkPiece(name="a"), WorkPiece(name="b")
    doc.layers[0].add_workpiece(a)
    doc.layers[1].add_workpiece(b)

    tab.set_doc(doc)
    assert not column.get_visible()
    group = ItemGroup([a.uid, b.uid], name="New")
    doc.item_groups.add(group)

    assert column.get_visible()
    assert [r[1] for r in _rows(column)] == [group, a, b]


def _settle(widget):
    from gi.repository import GLib

    context = GLib.MainContext.default()
    for _ in range(200):
        while context.pending():
            context.iteration(False)
        if widget.get_height() > 0:
            break


def _centre(widget, column):
    ok, bounds = widget.compute_bounds(column)
    assert ok
    return (
        bounds.get_x() + bounds.get_width() / 2,
        bounds.get_y() + bounds.get_height() / 2,
    )


def test_clicks_on_the_card_land_on_their_group(tab):
    from gi.repository import Gtk

    tab, editor = tab
    a, b = _pieces(editor, 0, 1)
    group = editor.group.group_items([a, b], name="Logo")
    column = tab.groups_column
    requests = []

    def record(sender, *, items):
        requests.append(items)

    tab.select_items_requested.connect(record)
    window = Gtk.Window(child=tab, default_width=900, default_height=400)
    try:
        window.present()
        _settle(column)
        _settle(column.listbox)

        column._on_pressed(None, 1, *_centre(_row_of(column, b), column))
        assert requests == [[a, b]]

        (arrow,) = column._arrows
        (right,) = [
            c
            for c in column.observe_controllers()
            if isinstance(c, Gtk.GestureClick) and c.get_button() == 3
        ]
        column._on_right_click_pressed(right, 1, *_centre(arrow, column))
        assert column._menu_group is group
        popover = column._context_popover
        assert popover is not None and popover.get_parent() is column
        popover.popdown()
        # A member row has no menu.
        column._on_right_click_pressed(
            right, 1, *_centre(_row_of(column, a), column)
        )
        assert column._context_popover is popover

        column._on_pressed(None, 1, *_centre(arrow, column))
        assert [r[1] for r in _rows(column)] == [group]
        assert requests == [[a, b]]
    finally:
        window.destroy()

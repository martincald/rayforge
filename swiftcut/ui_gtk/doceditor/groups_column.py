"""
The Groups card: each group of items across layers, its members and
the layer each one is on. It stands before the layer cards, and only
while the document has a group.
"""

from gettext import gettext as _
from typing import TYPE_CHECKING, cast

from blinker import Signal
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ...core.doc import Doc
from ...core.group import Group
from ...core.item import DocItem
from ...core.item_group import ItemGroup
from ...core.layer import Layer
from ...core.workpiece import WorkPiece
from ..icons import get_icon
from ..layout import (
    COMPACT_SPACE_CONTROL,
    COMPACT_SPACE_GROUP,
    ICON_GLYPH,
    LAYER_CARD_MAX_WIDTH,
    ROW_MIN_HEIGHT_COMPACT,
    stylesheet,
)
from ..shared.expander import css as expander_css
from ..shared.gtk import apply_css
from .group_row import GroupRow
from .layer_column import css as layer_column_css
from .workpiece_row import WorkpieceRow

if TYPE_CHECKING:
    from ...doceditor.editor import DocEditor

# The chip classes whose rule is loaded, one per colour: apply_css
# adds a provider on every call and never drops one.
_chip_classes: set[str] = set()


def _layer_of(item: DocItem) -> Layer:
    """A member is a layer's content item: its parent is its layer."""
    return cast(Layer, item.parent)


def _layer_chip(layer: Layer) -> Gtk.Widget:
    """A small dot in the layer's colour."""
    rgba = Gdk.RGBA()
    rgba.parse(layer.color)
    rgb = (rgba.red, rgba.green, rgba.blue)
    css_class = "group-layer-chip-" + "".join(
        f"{round(c * 255):02x}" for c in rgb
    )
    if css_class not in _chip_classes:
        apply_css(
            stylesheet(
                f".{css_class} {{ background-color: {rgba.to_string()}; "
                "border-radius: $radius_chip; }"
            )
        )
        _chip_classes.add(css_class)
    chip = Gtk.Box()
    chip.add_css_class(css_class)
    chip.set_size_request(COMPACT_SPACE_GROUP, COMPACT_SPACE_GROUP)
    chip.set_valign(Gtk.Align.CENTER)
    return chip


def _indent(depth: int) -> int:
    """A row's start margin: a level in lines up with the name above."""
    return COMPACT_SPACE_GROUP + depth * (ICON_GLYPH + COMPACT_SPACE_CONTROL)


class GroupsColumn(Gtk.Box):
    """
    A card like a layer's, listing the document's groups. Each
    outermost group is a node that opens on its members: a nested
    group is a node in it, an item a row with its layer's colour and
    name. A click on a node or a row selects the whole group.
    """

    def __init__(self, doc: Doc, editor: "DocEditor"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        apply_css(layer_column_css)
        apply_css(expander_css)
        self.add_css_class("layer-column")
        self.set_margin_end(COMPACT_SPACE_CONTROL)
        self.set_hexpand(False)
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.card.add_css_class("layer-card")
        self.card.set_valign(Gtk.Align.START)
        self.append(self.card)

        self.doc = doc
        self.editor = editor
        # Whether a group's node is open, by group uid, kept across
        # rebuilds: open unless closed.
        self._expanded: dict[str, bool] = {}
        # Every row's group: a node's own, a member's parent.
        self._row_groups: dict[Gtk.ListBoxRow, ItemGroup] = {}
        self._row_items: dict[Gtk.ListBoxRow, DocItem] = {}
        self._arrows: dict[Gtk.Widget, ItemGroup] = {}
        self._menu_group: ItemGroup | None = None
        self._context_popover: Gtk.PopoverMenu | None = None
        # True while a member row is dragged: the drop moves that item
        # alone, though a click on it selected its whole group.
        self.dragging = False

        self.select_items_requested = Signal()

        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=COMPACT_SPACE_CONTROL,
        )
        header.add_css_class("layer-column-header")
        title = Gtk.Label(label=_("Groups"))
        title.set_halign(Gtk.Align.START)
        title.set_hexpand(True)
        header.append(title)
        self.card.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        # As wide as its names, up to a layer card's widest: nothing
        # else in the card is wider than its title.
        scrolled.set_propagate_natural_width(True)
        scrolled.set_min_content_height(ROW_MIN_HEIGHT_COMPACT)
        scrolled.set_hexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("layer-workpiece-list")
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled.set_child(self.listbox)
        self.card.append(scrolled)

        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self._on_pressed)
        self.add_controller(click)

        right_click = Gtk.GestureClick()
        right_click.set_button(Gdk.BUTTON_SECONDARY)
        right_click.connect("pressed", self._on_right_click_pressed)
        self.add_controller(right_click)

        actions = Gio.SimpleActionGroup()
        for name, handler in (
            ("rename", self.rename_group),
            ("ungroup", self.ungroup_group),
            ("select", self.select_group),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", self._on_group_action, handler)
            actions.add_action(action)
        move = Gio.SimpleAction.new("move-to-layer", GLib.VariantType("s"))
        move.connect("activate", self._on_move_to_layer_action)
        actions.add_action(move)
        self.insert_action_group("groups", actions)

        self._connect_signals()
        self._rebuild()

    def do_measure(self, orientation, for_size):
        min_, nat, min_bl, nat_bl = super().do_measure(orientation, for_size)
        if orientation == Gtk.Orientation.HORIZONTAL:
            nat = min(nat, LAYER_CARD_MAX_WIDTH)
        return min_, nat, min_bl, nat_bl

    def set_doc(self, doc: Doc):
        self._disconnect_signals()
        self.doc = doc
        self._connect_signals()
        self._rebuild()

    def _connect_signals(self):
        self.doc.item_groups.changed.connect(self._on_doc_changed)
        self.doc.descendant_added.connect(self._on_doc_changed)
        self.doc.descendant_removed.connect(self._on_doc_changed)
        self.doc.descendant_updated.connect(self._on_descendant_updated)

    def _disconnect_signals(self):
        self.doc.item_groups.changed.disconnect(self._on_doc_changed)
        self.doc.descendant_added.disconnect(self._on_doc_changed)
        self.doc.descendant_removed.disconnect(self._on_doc_changed)
        self.doc.descendant_updated.disconnect(self._on_descendant_updated)

    def do_destroy(self):
        self._disconnect_signals()

    def _on_doc_changed(self, sender, **kwargs):
        """A group changed, or an item came, went or changed layers."""
        self._rebuild()

    def _on_descendant_updated(self, sender, *, origin, **kwargs):
        # A layer's name and colour are on its members' badges.
        if isinstance(origin, Layer):
            self._rebuild()

    def _rebuild(self):
        child = self.listbox.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.listbox.remove(child)
            child = next_child
        self._row_groups.clear()
        self._row_items.clear()
        self._arrows.clear()

        groups = self.doc.item_groups
        tops = [
            g
            for g in groups
            if groups.parent_of(g.uid) is None and groups.items_of(g)
        ]
        for group in tops:
            self._add_node(group, 0)
        self.set_visible(bool(tops))

    def _add_row(self, child: Gtk.Widget) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_child(child)
        self.listbox.append(row)
        return row

    def _add_node(self, group: ItemGroup, depth: int):
        groups = self.doc.item_groups
        members = [
            m
            for m in groups.members(group)
            if not isinstance(m, ItemGroup) or groups.items_of(m)
        ]
        expanded = self._expanded.get(group.uid, True)

        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=COMPACT_SPACE_CONTROL,
        )
        box.set_margin_start(_indent(depth))
        box.set_margin_end(COMPACT_SPACE_GROUP)
        arrow = get_icon("chevron-right-symbolic")
        arrow.add_css_class("expander-arrow")
        if expanded:
            arrow.add_css_class("rotated")
        arrow.set_valign(Gtk.Align.CENTER)
        box.append(arrow)
        name = Gtk.Label(label=group.name)
        name.set_hexpand(True)
        name.set_halign(Gtk.Align.START)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(name)
        count = Gtk.Label(label=str(len(members)))
        count.add_css_class("sc-caption")
        box.append(count)

        row = self._add_row(box)
        self._row_groups[row] = group
        self._arrows[arrow] = group
        if not expanded:
            return
        for member in members:
            if isinstance(member, ItemGroup):
                self._add_node(member, depth + 1)
            else:
                self._add_member(member, group, depth + 1)

    def _add_member(self, item: DocItem, group: ItemGroup, depth: int):
        if isinstance(item, Group):
            item_row = GroupRow(item)
        elif isinstance(item, WorkPiece):
            item_row = WorkpieceRow(item)
        else:
            return
        item_row.set_margin_start(_indent(depth))
        layer = _layer_of(item)
        badge = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=COMPACT_SPACE_CONTROL,
        )
        badge.append(_layer_chip(layer))
        layer_name = Gtk.Label(label=layer.name)
        layer_name.add_css_class("sc-caption")
        layer_name.set_ellipsize(Pango.EllipsizeMode.END)
        badge.append(layer_name)
        item_row.append(badge)

        row = self._add_row(item_row)
        self._row_groups[row] = group
        self._row_items[row] = item
        # The row's drag is a layer card row's: a drop on a layer card
        # moves the item there.
        drag_source = Gtk.DragSource()
        drag_source.set_actions(Gdk.DragAction.MOVE)
        drag_source.connect("prepare", item_row._on_drag_prepare)
        drag_source.connect("drag-begin", self._on_member_drag_begin)
        drag_source.connect("drag-end", self._on_member_drag_end)
        drag_source.connect("drag-cancel", self._on_member_drag_end)
        row.add_controller(drag_source)

    def _on_member_drag_begin(self, drag_source, drag):
        self.dragging = True

    def _on_member_drag_end(self, drag_source, drag, *args):
        self.dragging = False

    def toggle_group(self, group: ItemGroup):
        """Opens or closes a group's node."""
        self._expanded[group.uid] = not self._expanded.get(group.uid, True)
        self._rebuild()

    def _on_pressed(self, gesture, n_press, x, y):
        widget = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None and widget is not self:
            if widget in self._arrows:
                self.toggle_group(self._arrows[widget])
                return
            if isinstance(widget, Gtk.ListBoxRow):
                self.select_group(self._row_groups[widget])
                return
            widget = widget.get_parent()

    def _node_at(self, x, y) -> ItemGroup | None:
        widget = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None and widget is not self:
            if isinstance(widget, Gtk.ListBoxRow):
                if widget in self._row_items:
                    return None
                return self._row_groups.get(widget)
            widget = widget.get_parent()
        return None

    def _on_right_click_pressed(self, gesture, n_press, x, y):
        group = self._node_at(x, y)
        if group is None:
            return
        self._menu_group = group
        menu = Gio.Menu.new()
        menu.append_item(Gio.MenuItem.new(_("Rename…"), "groups.rename"))
        menu.append_item(Gio.MenuItem.new(_("Ungroup"), "groups.ungroup"))
        menu.append_item(
            Gio.MenuItem.new(_("Select All Members"), "groups.select")
        )
        layers = Gio.Menu.new()
        for layer in self.doc.layers:
            item = Gio.MenuItem.new(layer.name, None)
            item.set_action_and_target_value(
                "groups.move-to-layer", GLib.Variant.new_string(layer.uid)
            )
            layers.append_item(item)
        menu.append_submenu(_("Move All to Layer"), layers)

        if self._context_popover:
            self._context_popover.unparent()
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self)
        popover.set_has_arrow(False)
        ok, rect = gesture.get_bounding_box()
        if ok:
            popover.set_pointing_to(rect)
        self._context_popover = popover
        popover.popup()

    def _on_group_action(self, action, param, handler):
        if self._menu_group is not None:
            handler(self._menu_group)

    def _on_move_to_layer_action(self, action, param):
        uid = param.get_string()
        layer = next((la for la in self.doc.layers if la.uid == uid), None)
        if self._menu_group is not None and layer is not None:
            self.move_group_to_layer(self._menu_group, layer)

    def select_group(self, group: ItemGroup):
        """
        Selects the items of the group's outermost group, those on a
        visible layer: the canvas shows a grouped item as its whole
        group.
        """
        groups = self.doc.item_groups
        top = groups.top_of(group.uid) or group
        items = [i for i in groups.items_of(top) if _layer_of(i).visible]
        self.select_items_requested.send(self, items=items)

    def rename_group(self, group: ItemGroup) -> Adw.MessageDialog:
        """Asks for a group's new name; returns the dialog."""
        root = self.get_root()
        dialog = Adw.MessageDialog(
            transient_for=cast(Gtk.Window, root) if root else None,
            heading=_("Rename Group"),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance(
            "save", Adw.ResponseAppearance.SUGGESTED
        )
        dialog.set_default_response("cancel")

        entry = Gtk.Entry(placeholder_text=_("Group name"))
        entry.set_text(group.name)
        dialog.set_extra_child(entry)
        entry.connect("activate", lambda widget: dialog.response("save"))

        def on_response(d, response_id):
            if response_id == "save":
                name = entry.get_text().strip()
                self.editor.group.rename_group(group, name)
            d.destroy()

        dialog.connect("response", on_response)
        dialog.present()
        entry.grab_focus()
        return dialog

    def ungroup_group(self, group: ItemGroup):
        """Dissolves the group one level, in one undoable step."""
        self.editor.group.ungroup_groups([group])

    def move_group_to_layer(self, group: ItemGroup, layer: Layer):
        """
        Moves every item of the group to the layer, on a hidden layer
        too, in one undoable step. They stay in the group.
        """
        items = self.doc.item_groups.items_of(group)
        self.editor.layer.move_items_to_layer(items, layer)

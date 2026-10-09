from gettext import gettext as _
from typing import TYPE_CHECKING

from gi.repository import Gtk, Pango

from ...shared.units.formatter import format_value

if TYPE_CHECKING:
    from ...core.layer import Layer
    from ...doceditor.editor import DocEditor


class MaterialPicker(Gtk.DropDown):
    """
    A layer's Material dropdown: "Manual", then each material and
    thickness the recipes for the active machine are made for, e.g.
    "3.00 mm MDF". Picking one fills the layer's steps from its
    recipes for the active machine, in one undo step; "Manual" forgets
    it.
    """

    def __init__(self, editor: "DocEditor", layer: "Layer"):
        super().__init__()
        self.editor = editor
        self.layer = layer
        self.choices: list[tuple[str, float] | None] = []
        self.set_tooltip_text(_("Material"))

        # Labels ellipsize, so a long material name never widens the
        # layer card.
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        self.set_factory(factory)

        self._selected_handler = self.connect(
            "notify::selected", self._on_selected
        )
        self.sync()

    @staticmethod
    def _on_factory_setup(factory, item):
        label = Gtk.Label(xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        item.set_child(label)

    @staticmethod
    def _on_factory_bind(factory, item):
        item.get_child().set_text(item.get_item().get_string())

    def sync(self):
        """Lists the choices and selects the layer's material."""
        context = self.editor.context
        choices: list[tuple[str, float] | None] = [
            None,
            *context.recipe_mgr.material_choices(context.machine),
        ]
        material = self.layer.material
        if material not in choices:
            choices.append(material)
        self.handler_block(self._selected_handler)
        try:
            if choices != self.choices:
                self.choices = choices
                self.set_model(
                    Gtk.StringList.new([self._label(c) for c in choices])
                )
            self.set_selected(choices.index(material))
        finally:
            self.handler_unblock(self._selected_handler)

    def _label(self, choice: tuple[str, float] | None) -> str:
        if choice is None:
            return _("Manual")
        uid, thickness = choice
        material = self.editor.context.material_mgr.get_material(uid)
        return _("{thickness} {material}").format(
            thickness=format_value(thickness, "length"),
            material=material.name if material else uid,
        )

    def _on_selected(self, dropdown, pspec):
        index = self.get_selected()
        if index >= len(self.choices):
            return
        self.editor.step.apply_material(self.layer, self.choices[index])

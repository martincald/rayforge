"""The recipe editor's general page: name, description and color."""

from gettext import gettext as _
from typing import Any

from blinker import Signal
from gi.repository import Adw, Gtk

from .....context import get_context
from .....core.color import pick_unused_color
from ....settings.color_presets_page import _hex_to_rgba, _rgba_to_hex


class RecipeGeneralPage(Adw.PreferencesPage):
    """The recipe's name, description and color."""

    def __init__(self, recipe: Any | None = None, **kwargs):
        super().__init__(**kwargs)
        self.name_changed = Signal()
        self.submit_requested = Signal()

        group = Adw.PreferencesGroup(
            title=_("Recipe"),
            description=_(
                "A named preset of settings that can be "
                "automatically applied later."
            ),
        )
        self.add(group)

        self.name_row = Adw.EntryRow(title=_("Name"))
        if recipe:
            self.name_row.set_text(recipe.name)
        self.name_row.connect("notify::text", self._on_name_changed)
        self.name_row.connect("activate", self._on_name_activated)
        group.add(self.name_row)

        self.desc_row = Adw.EntryRow(title=_("Description"))
        if recipe:
            self.desc_row.set_text(recipe.description)
        group.add(self.desc_row)

        # A recipe without a color (new or legacy) gets an unused one.
        color = recipe.color if recipe else None
        if not color:
            recipes = get_context().recipe_mgr.get_all_recipes()
            color = pick_unused_color({r.color for r in recipes if r.color})
        color_dialog = Gtk.ColorDialog()
        color_dialog.set_with_alpha(False)
        self.color_button = Gtk.ColorDialogButton(dialog=color_dialog)
        self.color_button.set_rgba(_hex_to_rgba(color))
        color_row = Adw.ActionRow(
            title=_("Color"),
            subtitle=_("Layer color for steps using this recipe"),
        )
        color_row.add_suffix(self.color_button)
        group.add(color_row)

    def _on_name_changed(self, entry_row, _pspec):
        self.name_changed.send(self)

    def _on_name_activated(self, _entry_row):
        self.submit_requested.send(self)

    def get_name(self) -> str:
        return self.name_row.get_text().strip()

    def get_description(self) -> str:
        return self.desc_row.get_text().strip()

    def get_recipe_color(self) -> str:
        return _rgba_to_hex(self.color_button.get_rgba())

from typing import Any

from gi.repository import Adw, Gtk

from ....core.varset import (
    ChoiceVar,
    Var,
)
from .base import (
    NULL_CHOICE_LABEL,
    RowAdapter,
    escape_title,
    register_adapter,
)


@register_adapter(ChoiceVar)
class ComboAdapter(RowAdapter):
    def __init__(self, row: Adw.ComboRow, var: Var) -> None:
        super().__init__()
        self._row = row
        self._var = var
        self._row.connect(
            "notify::selected-item",
            lambda r, p: self.changed.send(self),
        )

    @classmethod
    def create(
        cls, var: Var, target_property: str
    ) -> tuple[Adw.PreferencesRow, "ComboAdapter"]:
        assert isinstance(var, ChoiceVar)
        null_label = var.null_label or NULL_CHOICE_LABEL
        choices: list[str] = (
            [null_label] + var.choices if var.allow_none else list(var.choices)
        )
        store = Gtk.StringList.new(choices)
        row = Adw.ComboRow(model=store, title=escape_title(var.label))
        if var.description:
            row.set_subtitle(var.description)
        initial_val = getattr(var, target_property)
        if initial_val:
            display_str = var.get_display_for_value(str(initial_val))
            if display_str in choices:
                row.set_selected(choices.index(display_str))
            else:
                row.set_selected(0)
        else:
            row.set_selected(0)
        return row, cls(row, var)

    def get_value(self) -> Any | None:
        selected = self._row.get_selected_item()
        display_str = ""
        if selected:
            display_str = selected.get_string()  # type: ignore

        null_label = (
            getattr(self._var, "null_label", None) or NULL_CHOICE_LABEL
        )
        if display_str == null_label:
            return None
        if isinstance(self._var, ChoiceVar):
            return self._var.get_value_for_display(display_str)
        return display_str

    def set_value(self, value: Any) -> None:
        model = self._row.get_model()
        if not isinstance(model, Gtk.StringList):
            return
        null_label = (
            getattr(self._var, "null_label", None) or NULL_CHOICE_LABEL
        )
        display_str = null_label
        if value is not None:
            if isinstance(self._var, ChoiceVar):
                display_str = self._var.get_display_for_value(
                    str(value)
                ) or str(value)
            else:
                display_str = str(value)
        for i in range(model.get_n_items()):
            if model.get_string(i) == display_str:
                self._row.set_selected(i)
                break

    def needs_rebuild(self, old_var: Var, new_var: Var) -> bool:
        if super().needs_rebuild(old_var, new_var):
            return True
        if isinstance(old_var, ChoiceVar) and isinstance(new_var, ChoiceVar):
            return old_var.choices != new_var.choices
        return False

    def update_from_var(self, var: Var):
        if var.label:
            self._row.set_title(escape_title(var.label))
        if var.description:
            self._row.set_subtitle(var.description)

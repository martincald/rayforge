from gettext import gettext as _
from typing import TYPE_CHECKING

from swiftcut.shared.util.glib import DebounceMixin
from swiftcut.ui_gtk.doceditor.post_processor.groups import (
    ExpanderHost,
    TransformerSettingsGroup,
)
from swiftcut.ui_gtk.shared.pref_rows import SpinRow

from ..transformers import MultiPassTransformer

if TYPE_CHECKING:
    from swiftcut.core.step import Step


class MultiPassSettingsGroup(DebounceMixin, TransformerSettingsGroup):
    """UI for configuring the MultiPassTransformer."""

    def __init__(
        self,
        title: str,
        transformer: MultiPassTransformer,
        page: ExpanderHost,
        *,
        step: "Step | None" = None,
        **kwargs,
    ):
        super().__init__(title, transformer, page, step=step, **kwargs)

        # Passes setting
        self.passes_row = SpinRow(
            _("Number of Passes"),
            _("How often to repeat the entire step"),
            lower=1,
            upper=100,
            value=transformer.passes,
        )
        self.add(self.passes_row)

        # Connect signals with debouncing
        self.passes_row.value_changed.connect(
            lambda r: self._debounce(self._on_passes_changed, r),
        )

    def _update_sensitivity(self) -> None:
        enabled = self._is_enabled()
        self.passes_row.set_sensitive(enabled)

    def _on_passes_changed(self, spin_row: SpinRow) -> None:
        new_value = spin_row.get_int_value()
        self.param_changed.send(
            self,
            key="passes",
            value=new_value,
            name=_("Change number of passes"),
        )

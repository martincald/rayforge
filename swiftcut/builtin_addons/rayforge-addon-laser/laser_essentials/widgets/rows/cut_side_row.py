"""Laser cut-side row widget."""

from gettext import gettext as _
from typing import Any

from swiftcut.core.cut_side import CutSide
from swiftcut.ui_gtk.doceditor.step_settings.rows import ComboRow


class CutSideRow(ComboRow):
    """A combo row bound to the step's ``cut_side`` attribute."""

    def __init__(self, editor: Any, step: Any):
        choices = [(cs.label(), cs.name) for cs in CutSide]
        super().__init__(
            editor,
            step,
            "cut_side",
            _("Cut Side"),
            choices,
        )

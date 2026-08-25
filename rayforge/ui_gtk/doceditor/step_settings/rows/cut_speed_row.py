"""Cut speed row widget."""

from gettext import gettext as _
from typing import TYPE_CHECKING, Any

from .spin_row import SpinRow

if TYPE_CHECKING:
    from rayforge.doceditor.editor import DocEditor

# Bounds are in application base units. Cutting and engraving span
# 0.1 - 1000 mm/s, which is a property of the operation rather than of
# the machine: the profile's max cut speed used to cap this row, so a
# step born under a conservative profile stayed capped for the life of
# the document.
CUT_SPEED_MIN = 6.0  # 0.1 mm/s
CUT_SPEED_MAX = 60000.0  # 1000 mm/s


class CutSpeedRow(SpinRow):
    """A spin row bound to the base ``Step.cut_speed`` attribute."""

    def __init__(
        self,
        editor: "DocEditor",
        step: Any,
        title: str = _("Cut Speed"),
    ):
        super().__init__(
            editor,
            step,
            "cut_speed",
            title,
            _("Speed of the cutting operation"),
            CUT_SPEED_MIN,
            CUT_SPEED_MAX,
            1.0,
            0,
            is_int=True,
            quantity="speed",
        )

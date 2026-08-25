"""Travel speed row widget."""

from gettext import gettext as _
from typing import TYPE_CHECKING, Any

from .spin_row import SpinRow

if TYPE_CHECKING:
    from rayforge.doceditor.editor import DocEditor

# Bounds are in application base units. Travel is limited by what the
# machine can actually rapid at, so its ceiling stays the profile's max.
TRAVEL_SPEED_MIN = 6.0  # 0.1 mm/s


class TravelSpeedRow(SpinRow):
    """A spin row bound to the base ``Step.travel_speed`` attribute."""

    def __init__(
        self,
        editor: "DocEditor",
        step: Any,
        title: str = _("Travel Speed"),
    ):
        super().__init__(
            editor,
            step,
            "travel_speed",
            title,
            _("Speed of rapid positioning moves"),
            TRAVEL_SPEED_MIN,
            float(getattr(step, "max_travel_speed", 10000.0)),
            1.0,
            0,
            is_int=True,
            quantity="speed",
        )

    def _sync_dependencies(self):
        max_speed = getattr(self.step, "max_travel_speed", None)
        if max_speed:
            self.set_range(TRAVEL_SPEED_MIN, float(max_speed))

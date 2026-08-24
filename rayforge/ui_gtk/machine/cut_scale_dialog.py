from collections.abc import Callable
from gettext import gettext as _

from gi.repository import Adw

from ..shared.pref_rows.base import SpinRow
from ..shared.pref_rows.speed_spin_row import SpeedSpinRow

# A scale cut is a marking pass, not a job: it defaults slow enough to
# leave a visible line without biting into the stock.
DEFAULT_SPEED_MM_MIN = 20 * 60


class CutScaleDialog(Adw.MessageDialog):
    """Asks for the speed and power of a bounding-box cut."""

    def __init__(
        self,
        default_power_percent: float,
        on_confirm: Callable[[int, float], None],
        **kwargs,
    ):
        super().__init__(
            heading=_("Cut Scale"),
            body=_("Cut a rectangle around the job's bounding box."),
            **kwargs,
        )
        self._on_confirm = on_confirm

        self.add_response("cancel", _("Cancel"))
        self.add_response("cut", _("Cut"))
        self.set_response_appearance("cut", Adw.ResponseAppearance.DESTRUCTIVE)
        self.set_default_response("cut")
        self.set_close_response("cancel")

        group = Adw.PreferencesGroup()

        self.speed_row = SpeedSpinRow(
            _("Speed"),
            lower=1,
            upper=60000,
            value_in_base=DEFAULT_SPEED_MM_MIN,
        )
        group.add(self.speed_row)

        self.power_row = SpinRow(
            _("Power"),
            _("Percent of full power"),
            lower=1,
            upper=100,
            value=default_power_percent,
        )
        group.add(self.power_row)

        self.set_extra_child(group)
        self.connect("response", self._on_response)

    def _on_response(self, dialog, response):
        if response != "cut":
            return
        speed = int(self.speed_row.get_value_in_base_units())
        power = self.power_row.get_value() / 100.0
        self._on_confirm(speed, power)

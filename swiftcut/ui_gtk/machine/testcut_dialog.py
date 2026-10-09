from collections.abc import Callable
from gettext import gettext as _

from gi.repository import Adw

from ...machine.cmd import TEST_CUT_SIZE_MM
from ...shared.units.formatter import format_value


class TestCutDialog(Adw.MessageDialog):
    """Asks before a test square is cut at a layer's settings."""

    def __init__(
        self,
        layer_name: str,
        speed_mm_min: float,
        power: float,
        min_power: float,
        on_cut: Callable[[], None],
        on_pick: Callable[[], None],
        **kwargs,
    ):
        """
        Args:
            layer_name: The layer whose settings the square is cut at.
            speed_mm_min: Its cut speed, in the model's base unit.
            power: Its Max Power, normalized 0-1.
            min_power: Its Min Power, normalized 0-1.
            on_cut: Called on Cut.
            on_pick: Called on Choose Spot.
        """
        super().__init__(
            heading=_("Cut a test square?"),
            # One pass: the layer's passes are not repeated.
            body=_(
                "{layer}: one pass around a {size:g} mm square at "
                "{speed}, Max Power {power}%, Min Power {min_power}%, "
                "where the canvas marks it. The laser fires; the head "
                "returns afterwards."
            ).format(
                layer=layer_name,
                size=TEST_CUT_SIZE_MM,
                speed=format_value(speed_mm_min, "speed"),
                power=round(power * 100),
                min_power=round(min_power * 100),
            ),
            **kwargs,
        )
        self._on_cut = on_cut
        self._on_pick = on_pick
        self.add_css_class("sc-sheet")

        self.add_response("cancel", _("Cancel"))
        self.add_response("pick", _("Choose Spot…"))
        self.add_response("cut", _("Cut"))
        self.set_response_appearance("cut", Adw.ResponseAppearance.DESTRUCTIVE)
        # Cancel, as in Cut Scale: Cut fires the laser at the stock,
        # which no undo reverses, so Enter must not commit it.
        self.set_default_response("cancel")
        self.set_close_response("cancel")
        self.connect("response", self._on_response)

    def _on_response(self, dialog, response):
        if response == "cut":
            self._on_cut()
        elif response == "pick":
            self._on_pick()

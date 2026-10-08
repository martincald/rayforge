import logging
from gettext import gettext as _

from gi.repository import Adw

from ..shared.pref_rows.length_spin_row import LengthSpinRow
from ..shared.preferences_page import TrackedPreferencesPage

logger = logging.getLogger(__name__)


class AdvancedPreferencesPage(TrackedPreferencesPage):
    key = "advanced"
    path_prefix = "/machine-settings/"

    def __init__(self, machine, **kwargs):
        super().__init__(
            title=_("Advanced"),
            icon_name="machine-settings-advanced-symbolic",
            **kwargs,
        )
        self.machine = machine

        path_group = Adw.PreferencesGroup(title=_("Path Processing"))
        path_group.set_description(
            _("Configure how paths are processed and optimized.")
        )
        self.add(path_group)

        self.arcs_row = Adw.SwitchRow(
            title=_("Support Arcs"),
            subtitle=_(
                "Smoother paths; turn off if the machine rejects arcs"
            ),
        )
        self.arcs_row.set_active(self.machine.supports_arcs)
        self.arcs_row.connect("notify::active", self.on_arcs_changed)
        path_group.add(self.arcs_row)

        self.arc_tolerance_row = LengthSpinRow(
            _("Arc and Curve Tolerance"),
            _("Lower is truer to the path, and much slower"),
            lower=0.001,
            upper=10.0,
            step_increment=0.001,
            digits=3,
            value_in_base=self.machine.arc_tolerance,
        )
        self.arc_tolerance_row.set_width_chars(5)
        self.arc_tolerance_row.set_sensitive(self.machine.supports_arcs)
        self.arc_tolerance_row.value_changed.connect(
            self.on_arc_tolerance_changed
        )
        path_group.add(self.arc_tolerance_row)

        homing_group = Adw.PreferencesGroup(title=_("Homing and Startup"))
        homing_group.set_description(
            _(
                "Configure homing behavior and startup settings, "
                "including automatic homing."
            )
        )
        self.add(homing_group)

        home_on_start_row = Adw.SwitchRow()
        home_on_start_row.set_title(_("Home On Start"))
        home_on_start_row.set_subtitle(
            _("Send a homing command when the application starts")
        )
        home_on_start_row.set_active(machine.home_on_start)
        home_on_start_row.connect(
            "notify::active", self.on_home_on_start_changed
        )
        homing_group.add(home_on_start_row)

    def on_arcs_changed(self, switch_row, _param):
        """Update the machine's arcs support when the value changes."""
        self.machine.set_supports_arcs(switch_row.get_active())
        self.arc_tolerance_row.set_sensitive(self.machine.supports_arcs)

    def on_arc_tolerance_changed(self, spinrow):
        """Update to machine's arc tolerance when value changes."""
        self.machine.set_arc_tolerance(spinrow.get_value_in_base_units())

    def on_home_on_start_changed(self, row, _):
        self.machine.set_home_on_start(row.get_active())

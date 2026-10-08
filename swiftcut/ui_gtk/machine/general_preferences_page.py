import logging
from gettext import gettext as _

from gi.repository import Adw

from ...context import get_context
from ...machine.driver import get_driver_cls
from ...machine.models.machine import Machine
from ..shared.pref_rows.acceleration_spin_row import AccelerationSpinRow
from ..shared.pref_rows.speed_spin_row import SpeedSpinRow
from ..shared.preferences_page import TrackedPreferencesPage
from ..varset.varsetwidget import VarSetWidget

logger = logging.getLogger(__name__)


class GeneralPreferencesPage(TrackedPreferencesPage):
    key = "general"
    path_prefix = "/machine-settings/"

    def __init__(self, machine: Machine, **kwargs):
        super().__init__(
            title=_("General"),
            icon_name="machine-settings-general-symbolic",
            **kwargs,
        )
        self.machine = machine
        self._is_initializing = True
        self._current_driver_name = self.machine.driver_name

        # Error Banner Group
        error_group = Adw.PreferencesGroup()
        self.add(error_group)

        # Configuration Error Banner
        self.error_banner = Adw.Banner()
        self.error_banner.set_use_markup(True)
        self.error_banner.set_revealed(False)
        error_group.add(self.error_banner)
        # Hide the group if the banner is not revealed to avoid extra spacing
        self.error_banner.connect(
            "notify::revealed",
            lambda banner, _: error_group.set_visible(banner.get_revealed()),
        )
        error_group.set_visible(False)

        # Group for Machine Name
        name_group = Adw.PreferencesGroup(title=_("Machine"))
        name_group.set_description(
            _("Basic machine identification and configuration.")
        )
        self.add(name_group)

        # Machine Name: read-only, the bundled machines keep theirs.
        name_row = Adw.ActionRow(title=_("Name"), subtitle=self.machine.name)
        name_group.add(name_row)

        self.driver_group = VarSetWidget(title=_("Driver Settings"))
        self.driver_group.set_description(
            _("Connection and communication settings for the machine driver.")
        )
        self.driver_group.data_changed.connect(self.on_driver_param_changed)
        self.add(self.driver_group)

        # Get the driver class from driver_name (not from driver instance
        # which may not be ready yet)
        driver_cls = None
        if self.machine.driver_name:
            driver_cls = get_driver_cls(self.machine.driver_name)

        # Perform the initial population of the driver VarSet
        if driver_cls:
            initial_var_set = driver_cls.get_setup_vars()
            initial_var_set.set_values(self.machine.driver_args)
            logger.debug(
                f"GeneralPreferences: driver_args={self.machine.driver_args}, "
                f"var_set values={initial_var_set.get_values()}"
            )
            self.driver_group.populate(initial_var_set)
        else:
            # No driver selected yet, clear the widget
            self.driver_group.clear_dynamic_rows()

        # Connect to the machine's changed signal to get updates
        self.machine.changed.connect(self._on_machine_changed)
        self.connect("destroy", self._on_destroy)

        # Group for Speeds
        speeds_group = Adw.PreferencesGroup(
            title=_("Speeds &amp; Acceleration")
        )
        speeds_group.set_description(
            _(
                "Movement parameters used for job time estimation "
                "and path optimization."
            )
        )
        self.add(speeds_group)

        # Max Travel Speed
        self.travel_speed_row = SpeedSpinRow(
            _("Max Travel Speed"),
            _("Maximum rapid movement speed"),
            upper=60000,  # Base units; 1000 mm/s
            digits=0,
        )
        self.travel_speed_row.set_value_in_base_units(
            self.machine.max_travel_speed
        )
        self.travel_speed_row.value_changed.connect(
            self.on_travel_speed_changed
        )
        speeds_group.add(self.travel_speed_row)

        # Max Cut Speed
        self.cut_speed_row = SpeedSpinRow(
            _("Max Cut Speed"),
            _("Maximum cutting speed"),
            upper=60000,  # Base units; 1000 mm/s
            digits=0,
        )
        self.cut_speed_row.set_value_in_base_units(self.machine.max_cut_speed)
        self.cut_speed_row.value_changed.connect(self.on_cut_speed_changed)
        speeds_group.add(self.cut_speed_row)

        # Acceleration
        self.acceleration_row = AccelerationSpinRow(
            _("Acceleration"),
            _("Drives time estimates and the default overscan"),
            lower=1,
            upper=100000,
            digits=0,
        )
        self.acceleration_row.set_value_in_base_units(
            self.machine.acceleration
        )
        self.acceleration_row.value_changed.connect(
            self.on_acceleration_changed
        )
        speeds_group.add(self.acceleration_row)

        # Group for Job Start
        start_group = Adw.PreferencesGroup(title=_("Job Start"))
        self.add(start_group)

        # Crawford mode is shared by every machine; the start it goes
        # back to is each machine's own.
        self.crawford_row = Adw.SwitchRow()
        self.crawford_row.set_title(_("Crawford mode"))
        self.crawford_row.set_subtitle(
            _("Start asks: from here, or where the last job started")
        )
        self.crawford_row.set_active(get_context().config.crawford_mode)
        self.crawford_row.connect(
            "notify::active", self.on_crawford_mode_changed
        )
        start_group.add(self.crawford_row)

        # Initial check for errors
        self._update_error_state()

        # Initialization is complete.
        self._is_initializing = False

    def _on_machine_changed(self, sender, **kwargs):
        """
        Handler for the machine's changed signal. This is triggered when
        the driver or its configuration changes, allowing the UI to update.
        """
        self._update_error_state()

        # ONLY repopulate the driver settings if the driver *class* has
        # actually changed. This prevents a full UI rebuild (and focus loss)
        # when just a parameter value is changed.
        if self.machine.driver_name != self._current_driver_name:
            self._current_driver_name = self.machine.driver_name
            driver_cls = self.machine.driver.__class__
            var_set = driver_cls.get_setup_vars()
            var_set.set_values(self.machine.driver_args)
            self.driver_group.populate(var_set)

    def _on_destroy(self, *args):
        """Disconnects signals to prevent memory leaks."""
        self.machine.changed.disconnect(self._on_machine_changed)

    def _update_error_state(self):
        """Shows or hides the error banner based on all possible errors."""
        errors = []
        if self.machine.precheck_error:
            errors.append(
                _("<b>Configuration required:</b> {error}").format(
                    error=self.machine.precheck_error
                )
            )
        if self.machine.driver and self.machine.driver.state.error:
            errors.append(
                _("<b>Error:</b> {error}").format(
                    error=self.machine.driver.state.error.title
                )
            )

        if errors:
            full_error_msg = " \n".join(errors)
            self.error_banner.set_title(full_error_msg)
            self.error_banner.set_revealed(True)
        else:
            self.error_banner.set_revealed(False)

    def on_driver_param_changed(self, sender, **kwargs):
        if self._is_initializing:
            return
        # Merged, not replaced: args set elsewhere (the Device page's
        # connection and USB device) are not in this VarSet.
        values = {**self.machine.driver_args, **self.driver_group.get_values()}
        self.machine.set_driver_args(values)

    def on_travel_speed_changed(self, row: SpeedSpinRow):
        """Update the max travel speed when the value changes."""
        if self._is_initializing:
            return
        value = row.get_value_in_base_units()
        self.machine.set_max_travel_speed(int(value))

    def on_cut_speed_changed(self, row: SpeedSpinRow):
        """Update the max cut speed when the value changes."""
        if self._is_initializing:
            return
        value = row.get_value_in_base_units()
        self.machine.set_max_cut_speed(int(value))

    def on_acceleration_changed(self, row: AccelerationSpinRow):
        """Update the acceleration when the value changes."""
        if self._is_initializing:
            return
        value = row.get_value_in_base_units()
        self.machine.set_acceleration(int(value))

    def on_crawford_mode_changed(self, row, _param):
        """Turn the Start sheet on or off."""
        get_context().config.set_crawford_mode(row.get_active())

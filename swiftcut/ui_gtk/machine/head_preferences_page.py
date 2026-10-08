from gettext import gettext as _

from gi.repository import Adw, Gdk, Gtk

from ...machine.models.laser import LaserHead
from ...machine.models.machine import Machine
from ..shared.pref_rows.base import SpinRow
from ..shared.pref_rows.length_spin_row import LengthSpinRow
from ..shared.pref_rows.speed_spin_row import SpeedSpinRow
from ..shared.preferences_page import TrackedPreferencesPage


class LaserHeadDetailWidget:
    """Owns the PreferencesGroups for editing a LaserHead."""

    def __init__(self):
        self._head: LaserHead | None = None
        self._handler_ids = {}

        self.properties_group = Adw.PreferencesGroup(
            title=_("Laser Properties"),
            description=_("Configure the selected laser head."),
        )
        self.frame_group = Adw.PreferencesGroup(
            title=_("Framing"),
            description=_(
                "Settings for the frame outline operation that "
                "traces the job boundary."
            ),
        )
        self.groups: list[Adw.PreferencesGroup] = [
            self.properties_group,
            self.frame_group,
        ]
        self._build_ui()

    def _build_ui(self):
        """Builds the laser-specific rows."""
        self.name_row = Adw.EntryRow(title=_("Name"))
        self._handler_ids["name"] = self.name_row.connect(
            "changed", self._on_name_changed
        )
        self.properties_group.add(self.name_row)

        self.focus_power_row = SpinRow(
            _("Focus Power"),
            _("Power value in percent to use when focusing. 0 to disable"),
            upper=100,
            step_increment=0.1,
            digits=2,
            value=0,
        )
        self.focus_power_row.value_changed.connect(
            self._on_focus_power_changed
        )
        self.properties_group.add(self.focus_power_row)

        self.spot_size_x_row = LengthSpinRow(
            _("Spot Size X"),
            _("Size of the laser spot in the X direction"),
            lower=0.01,
            upper=10.0,
            step_increment=0.01,
            page_increment=0.05,
            value_in_base=0.1,
        )
        self.spot_size_x_row.value_changed.connect(self._on_spot_size_changed)
        self.properties_group.add(self.spot_size_x_row)

        self.spot_size_y_row = LengthSpinRow(
            _("Spot Size Y"),
            _("Size of the laser spot in the Y direction"),
            lower=0.01,
            upper=10.0,
            step_increment=0.01,
            page_increment=0.05,
            value_in_base=0.1,
        )
        self.spot_size_y_row.value_changed.connect(self._on_spot_size_changed)
        self.properties_group.add(self.spot_size_y_row)

        self.cut_color_button = Gtk.ColorButton()
        self.cut_color_button.set_size_request(32, 32)
        self.cut_color_row = Adw.ActionRow(
            title=_("Cut Color"),
            subtitle=_("Color for cutting operations"),
            activatable_widget=self.cut_color_button,
        )
        self.cut_color_row.add_suffix(self.cut_color_button)
        self._handler_ids["cut_color"] = self.cut_color_button.connect(
            "color-set", self._on_cut_color_changed
        )
        self.properties_group.add(self.cut_color_row)

        self.raster_color_button = Gtk.ColorButton()
        self.raster_color_button.set_size_request(32, 32)
        self.raster_color_row = Adw.ActionRow(
            title=_("Raster Color"),
            subtitle=_("Color for engraving/raster operations"),
            activatable_widget=self.raster_color_button,
        )
        self.raster_color_row.add_suffix(self.raster_color_button)
        self._handler_ids["raster_color"] = self.raster_color_button.connect(
            "color-set", self._on_raster_color_changed
        )
        self.properties_group.add(self.raster_color_row)

        self.frame_power_row = SpinRow(
            _("Frame Power"),
            _("Power value in percent to use when framing. 0 to disable"),
            upper=100,
            step_increment=0.1,
            digits=2,
            value=0,
        )
        self.frame_power_row.value_changed.connect(
            self._on_frame_power_changed
        )
        self.frame_group.add(self.frame_power_row)

        self.frame_speed_row = SpeedSpinRow(
            _("Frame Speed"),
            _("0 uses the machine's max travel speed"),
            upper=60000,
            digits=0,
        )
        self.frame_speed_row.value_changed.connect(
            self._on_frame_speed_changed
        )
        self.frame_group.add(self.frame_speed_row)

        self.frame_repeat_row = SpinRow(
            _("Repeat Count"),
            _("Number of times to trace the frame outline"),
            lower=1,
            upper=100,
            page_increment=5,
            value=1,
        )
        self.frame_repeat_row.value_changed.connect(
            self._on_frame_repeat_changed
        )
        self.frame_group.add(self.frame_repeat_row)

        self.frame_corner_pause_row = SpinRow(
            _("Pause at Corners"),
            _("Pause at each corner of the frame; 0 disables"),
            upper=10,
            step_increment=0.1,
            digits=1,
            value=0,
        )
        self.frame_corner_pause_row.value_changed.connect(
            self._on_frame_corner_pause_changed
        )
        self.frame_group.add(self.frame_corner_pause_row)

    def set_head(self, head: LaserHead | None):
        """Syncs the laser rows with the given head."""
        self._head = head
        if head is None:
            for group in self.groups:
                group.set_visible(False)
            return
        for group in self.groups:
            group.set_visible(True)

        # Block handlers to prevent feedback loop
        self.name_row.handler_block(self._handler_ids["name"])
        self.cut_color_button.handler_block(self._handler_ids["cut_color"])
        self.raster_color_button.handler_block(
            self._handler_ids["raster_color"]
        )

        self.name_row.set_text(head.name)
        self.focus_power_row.set_value(head.focus_power_percent * 100)
        spot_x, spot_y = head.spot_size_mm
        self.spot_size_x_row.set_value_in_base_units(spot_x)
        self.spot_size_y_row.set_value_in_base_units(spot_y)
        self._set_color_button(self.cut_color_button, head.cut_color)
        self._set_color_button(self.raster_color_button, head.raster_color)
        self.frame_power_row.set_value(head.frame_power_percent * 100)
        self.frame_speed_row.set_value_in_base_units(head.frame_speed)
        self.frame_repeat_row.set_value(head.frame_repeat_count)
        self.frame_corner_pause_row.set_value(head.frame_corner_pause)

        # Unblock handlers
        self.name_row.handler_unblock(self._handler_ids["name"])
        self.cut_color_button.handler_unblock(self._handler_ids["cut_color"])
        self.raster_color_button.handler_unblock(
            self._handler_ids["raster_color"]
        )

    def _on_name_changed(self, entry_row):
        """Update the name of the selected laser."""
        if self._head:
            self._head.set_name(entry_row.get_text())

    def _on_frame_power_changed(self, spinrow):
        """Update the frame power of the selected laser."""
        if self._head:
            self._head.set_frame_power(spinrow.get_value() / 100)

    def _on_focus_power_changed(self, spinrow):
        """Update the focus power of the selected laser."""
        if self._head:
            self._head.set_focus_power(spinrow.get_value() / 100)

    def _on_spot_size_changed(self, spinrow):
        """Update the spot size of the selected laser."""
        if not self._head:
            return
        x = self.spot_size_x_row.get_value_in_base_units()
        y = self.spot_size_y_row.get_value_in_base_units()
        self._head.set_spot_size(x, y)

    def _set_color_button(self, button: Gtk.ColorButton, hex_color: str):
        """Set the color button from a hex color string."""
        rgba = Gdk.RGBA()
        if not rgba.parse(hex_color):
            rgba.parse("#ff00ff")
        button.set_rgba(rgba)

    def _get_hex_color(self, button: Gtk.ColorButton) -> str:
        """Get the hex color string from a color button."""
        rgba = button.get_rgba()
        r = int(rgba.red * 255)
        g = int(rgba.green * 255)
        b = int(rgba.blue * 255)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _on_cut_color_changed(self, button: Gtk.ColorButton):
        """Update the cut color of the selected laser."""
        if self._head:
            self._head.set_cut_color(self._get_hex_color(button))

    def _on_raster_color_changed(self, button: Gtk.ColorButton):
        """Update the raster color of the selected laser."""
        if self._head:
            self._head.set_raster_color(self._get_hex_color(button))

    def _on_frame_speed_changed(self, spinrow):
        """Update the frame speed of the selected laser."""
        if not self._head:
            return
        value = self.frame_speed_row.get_value_in_base_units()
        self._head.set_frame_speed(int(value))

    def _on_frame_repeat_changed(self, spinrow):
        """Update the frame repeat count of the selected laser."""
        if self._head:
            self._head.set_frame_repeat_count(spinrow.get_int_value())

    def _on_frame_corner_pause_changed(self, spinrow):
        """Update the frame corner pause of the selected laser."""
        if self._head:
            self._head.set_frame_corner_pause(spinrow.get_value())


class HeadPreferencesPage(TrackedPreferencesPage):
    """Machine settings page for the machine's laser head."""

    key = "heads"
    path_prefix = "/machine-settings/"

    def __init__(self, machine: Machine, **kwargs):
        super().__init__(
            title=_("Heads"),
            icon_name="settings-symbolic",
            **kwargs,
        )
        self.machine = machine

        self.laser_widget = LaserHeadDetailWidget()
        for group in self.laser_widget.groups:
            self.add(group)
        self.laser_widget.set_head(machine.get_default_laser_head())

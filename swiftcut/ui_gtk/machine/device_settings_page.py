import logging
import sys
from datetime import datetime
from gettext import gettext as _
from typing import cast

from blinker import Signal
from gi.repository import Adw, Gdk, GLib, Gtk

from ... import config
from ...context import get_context
from ...logging_setup import get_current_log_file
from ...machine.driver.driver import (
    DeviceStatus,
    ResourceBusyError,
)
from ...machine.driver.ruida.ruida_driver import RuidaDriver
from ...machine.transport.transport import TransportStatus
from ..icons import get_icon
from ..layout import SPACE_CONTROL
from ..shared.preferences_page import TrackedPreferencesPage
from ..varset.varsetwidget import VarSet, VarSetWidget

# Windows Firewall silently dropping the Ruida response-port UDP
# datagrams looks identical to a wrong-port misconfiguration: a clean
# timeout with no exception. Shown verbatim in the connection error
# state so the owner can self-diagnose without reading logs.
FIREWALL_NOTE = _(
    "Windows Firewall may be blocking SwiftCut.exe - allow it for "
    "private networks"
)

DIAGNOSTICS_REFRESH_INTERVAL_SECONDS = 2

logger = logging.getLogger(__name__)


class DeviceSettingsPage(TrackedPreferencesPage):
    """
    A preferences page for reading and writing device settings.
    """

    key = "device"
    path_prefix = "/machine-settings/"

    def __init__(self, machine, **kwargs):
        super().__init__(
            title=_("Device"),
            icon_name="hardware-symbolic",
            **kwargs,
        )
        logger.debug("__init__")
        self.machine = machine
        self._current_error = None
        self._is_updating_from_model = False
        self._varset_widgets = []
        self._error_timeout_id = 0
        self._warning_rows = []
        self._dismissed_warnings = set()
        self._not_connected_warning_dismissed = False
        self._is_busy = False

        self.show_toast = Signal()

        # Create a single main group for all static content
        self.main_group = Adw.PreferencesGroup()
        self.add(self.main_group)
        self._main_group_title = _("Device Settings")
        self._main_group_desc = _(
            "Read or apply settings directly to the device."
        )

        # Create header controls once and store them
        self.spinner = Gtk.Spinner()
        self.read_button = Gtk.Button(child=get_icon("refresh-symbolic"))
        self.read_button.set_tooltip_text(_("Read from Device"))
        self.read_button.connect("clicked", self._on_read_clicked)
        self.header_box = Gtk.Box(spacing=SPACE_CONTROL)
        self.header_box.append(self.spinner)
        self.header_box.append(self.read_button)
        self.main_group.set_header_suffix(self.header_box)

        # Banners
        self.unsupported_banner = Adw.Banner(
            title=_(
                "The current driver does not support reading device settings."
            )
        )
        self.main_group.add(self.unsupported_banner)

        # One-time offer to copy device settings over from a
        # pre-rebrand "rayforge" config dir, for the case where the
        # automatic startup migration (swiftcut/config.py) found the
        # swiftcut config dir already populated and left it alone
        # rather than risk overwriting it. Copy-only, never clobbers
        # an existing machine profile; see config.import_legacy_config.
        self.import_legacy_banner = Adw.Banner(
            title=_(
                "A Rayforge configuration from before the rename was"
                " found. Import its device settings?"
            ),
            button_label=_("Import settings from Rayforge"),
        )
        self.import_legacy_banner.connect(
            "button-clicked", self._on_import_legacy_clicked
        )
        self.main_group.add(self.import_legacy_banner)

        # Error row with copy and close buttons
        self.error_row = Adw.ActionRow(use_markup=True, activatable=False)
        self.error_row.add_prefix(get_icon("error-symbolic"))
        self.error_row.add_css_class("error")

        copy_button = Gtk.Button(child=get_icon("copy-symbolic"))
        copy_button.set_tooltip_text(_("Copy Error Details"))
        copy_button.add_css_class("flat")
        copy_button.set_valign(Gtk.Align.CENTER)
        copy_button.connect("clicked", self._on_copy_error_clicked)
        self.error_row.add_suffix(copy_button)

        error_close_button = Gtk.Button(child=get_icon("close-symbolic"))
        error_close_button.set_tooltip_text(_("Dismiss Error"))
        error_close_button.add_css_class("flat")
        error_close_button.set_valign(Gtk.Align.CENTER)
        error_close_button.connect("clicked", self._on_error_dismissed)
        self.error_row.add_suffix(error_close_button)
        self.main_group.add(self.error_row)

        # Firewall hint, shown alongside the error row while the
        # connection is in the ERROR state. Windows-only: the message
        # names a Windows-specific mechanism.
        self.firewall_row = Adw.ActionRow(
            title=FIREWALL_NOTE, activatable=False
        )
        self.firewall_row.add_prefix(get_icon("warning-symbolic"))
        self.main_group.add(self.firewall_row)

        # Dismissible warning rows
        items = [
            _(
                "Editing these values can be dangerous and may render your"
                " machine inoperable!"
            ),
            _(
                "The device may restart or temporarily disconnect after a"
                " setting is changed."
            ),
        ]
        for item in items:
            warning_row = Adw.ActionRow(title=item, activatable=False)
            warning_row.add_prefix(get_icon("warning-symbolic"))
            warning_row.add_css_class("warning")

            close_button = Gtk.Button(child=get_icon("close-symbolic"))
            close_button.set_tooltip_text(_("Dismiss Warning"))
            close_button.add_css_class("flat")
            close_button.set_valign(Gtk.Align.CENTER)
            close_button.connect(
                "clicked", self._on_warning_dismissed, warning_row
            )
            warning_row.add_suffix(close_button)
            self.main_group.add(warning_row)
            self._warning_rows.append(warning_row)

        # A group and row to prompt the user to load settings
        self.prompt_group = Adw.PreferencesGroup()
        prompt_row = Adw.ActionRow(
            title=_(
                "Click the refresh button to load settings from the device."
            ),
            activatable=False,
        )
        prompt_row.add_prefix(get_icon("info-symbolic"))
        self.prompt_group.add(prompt_row)
        self.add(self.prompt_group)

        # Diagnostics: resolved driver, connection endpoints, whether
        # the response port bound, last traffic timestamps, and the
        # log file path. Lets the owner self-diagnose a connection
        # failure without needing an agent to read logs.
        self.diag_group = Adw.PreferencesGroup(title=_("Diagnostics"))
        self.diag_driver_row = Adw.ActionRow(title=_("Driver"))
        self.diag_host_row = Adw.ActionRow(title=_("Host"))
        self.diag_port_row = Adw.ActionRow(title=_("Main Port"))
        self.diag_jog_port_row = Adw.ActionRow(title=_("Jog Port"))
        self.diag_response_port_row = Adw.ActionRow(title=_("Response Port"))
        self.diag_response_bound_row = Adw.ActionRow(
            title=_("Response Port Bound")
        )
        self.diag_enq_row = Adw.ActionRow(title=_("Last ENQ Sent"))
        self.diag_ack_row = Adw.ActionRow(title=_("Last ACK Received"))
        # USB fields (package U3): shown instead of the UDP endpoint
        # rows above when the driver's connection is "usb". ENQ/ACK
        # above are transport-agnostic and stay shown for USB too.
        self.diag_usb_backend_row = Adw.ActionRow(title=_("USB Backend"))
        self.diag_usb_device_row = Adw.ActionRow(title=_("USB Device"))
        self.diag_usb_bytes_sent_row = Adw.ActionRow(title=_("Bytes Sent"))
        self.diag_usb_bytes_received_row = Adw.ActionRow(
            title=_("Bytes Received")
        )
        self.diag_log_row = Adw.ActionRow(title=_("Log File"))

        # Profile sanity: flags a Ruida profile whose ports drifted
        # from the ilab-614 defaults (see the silent-timeout
        # investigation this closes). The check only ever logs and
        # shows this notice; this button is the one and only place
        # that rewrites the file, and only on an explicit click.
        self.diag_port_warning_row = Adw.ActionRow(
            title=_("Ports do not match the ilab-614 defaults"),
            activatable=False,
        )
        self.diag_port_warning_row.add_prefix(get_icon("warning-symbolic"))
        reset_ports_button = Gtk.Button(label=_("Reset ports to defaults"))
        reset_ports_button.add_css_class("flat")
        reset_ports_button.set_valign(Gtk.Align.CENTER)
        reset_ports_button.connect(
            "clicked", self._on_reset_ruida_ports_clicked
        )
        self.diag_port_warning_row.add_suffix(reset_ports_button)

        # Kept as its own list (rather than folded into the udp/usb
        # split below) because it is the exact set an earlier package
        # already wrote tests against, asserting it is shown as a
        # whole for a UDP driver and hidden as a whole for a driver
        # with no get_diagnostics().
        self._driver_specific_diag_rows = [
            self.diag_host_row,
            self.diag_port_row,
            self.diag_jog_port_row,
            self.diag_response_port_row,
            self.diag_response_bound_row,
            self.diag_enq_row,
            self.diag_ack_row,
        ]
        self._udp_only_diag_rows = [
            self.diag_host_row,
            self.diag_port_row,
            self.diag_jog_port_row,
            self.diag_response_port_row,
            self.diag_response_bound_row,
        ]
        self._usb_diag_rows = [
            self.diag_usb_backend_row,
            self.diag_usb_device_row,
            self.diag_usb_bytes_sent_row,
            self.diag_usb_bytes_received_row,
        ]
        all_rows = [
            self.diag_driver_row,
            *self._udp_only_diag_rows,
            *self._usb_diag_rows,
            self.diag_enq_row,
            self.diag_ack_row,
        ]
        for row in all_rows:
            self.diag_group.add(row)
        self.diag_group.add(self.diag_port_warning_row)
        self.diag_group.add(self.diag_log_row)
        self.add(self.diag_group)
        self._diagnostics_timeout_id = GLib.timeout_add_seconds(
            DIAGNOSTICS_REFRESH_INTERVAL_SECONDS, self._on_diagnostics_timeout
        )

        # Signal Connections & Initial State
        self.machine.changed.connect(self._on_machine_config_changed)
        get_context().config.changed.connect(self._on_machine_config_changed)
        self.machine.connection_status_changed.connect(
            self._on_connection_status_changed
        )
        self.machine.state_changed.connect(self._on_state_changed)
        self.machine.settings_updated.connect(self._on_settings_op_success)
        self.machine.setting_applied.connect(self._on_setting_applied)
        self.machine.settings_error.connect(self._on_settings_op_error)
        self.connect("destroy", self.on_destroy)

        self._update_ui_state()
        logger.debug("__init__ finished.")

    def on_destroy(self, _widget):
        logger.debug("on_destroy: Disconnecting signals.")
        self.machine.changed.disconnect(self._on_machine_config_changed)
        get_context().config.changed.disconnect(
            self._on_machine_config_changed
        )
        self.machine.connection_status_changed.disconnect(
            self._on_connection_status_changed
        )
        self.machine.state_changed.disconnect(self._on_state_changed)
        self.machine.settings_updated.disconnect(self._on_settings_op_success)
        self.machine.setting_applied.disconnect(self._on_setting_applied)
        self.machine.settings_error.disconnect(self._on_settings_op_error)
        if self._error_timeout_id > 0:
            GLib.source_remove(self._error_timeout_id)
        if self._diagnostics_timeout_id > 0:
            GLib.source_remove(self._diagnostics_timeout_id)
            self._diagnostics_timeout_id = 0

    def _on_machine_config_changed(self, sender, **kwargs):
        logger.debug("_on_machine_config_changed: Rebuilding UI.")
        if self.machine.id not in get_context().machine_mgr.machines:
            logger.debug("_on_machine_config_changed: Machine removed.")
            return
        self._not_connected_warning_dismissed = False
        for widget in self._varset_widgets:
            self.remove(widget)
        self._varset_widgets.clear()
        self._update_ui_state()

    def _on_connection_status_changed(self, sender, **kwargs):
        logger.debug("_on_connection_status_changed: Updating UI.")
        self._not_connected_warning_dismissed = False
        self._update_ui_state()

    def _on_state_changed(self, sender, state, **kwargs):
        logger.debug("_on_state_changed: Updating UI.")
        self._update_ui_state()

    def _rebuild_settings_widgets(self, var_sets: list[VarSet]):
        for widget in self._varset_widgets:
            self.remove(widget)
        self._varset_widgets.clear()

        if not var_sets:
            return

        for var_set in var_sets:
            widget = VarSetWidget(explicit_apply=True)
            widget.set_title(GLib.markup_escape_text(var_set.title or ""))
            if var_set.description:
                widget.set_description(
                    GLib.markup_escape_text(var_set.description)
                )
            widget.populate(var_set)
            widget.data_changed.connect(self._on_setting_apply)
            self.add(widget)
            self._varset_widgets.append(widget)
        logger.debug(f"Created {len(self._varset_widgets)} widgets.")

    def _update_ui_state(self):
        logger.debug(f"_update_ui_state: Starting (is_busy={self._is_busy}).")
        if self.machine.id not in get_context().machine_mgr.machines:
            logger.debug("_update_ui_state: Machine removed, skipping.")
            return
        is_supported = self.machine.driver.supports_settings
        is_connected = self.machine.is_connected()
        is_running = self.machine.device_state.status == DeviceStatus.RUN
        has_settings_to_show = is_supported and len(self._varset_widgets) > 0

        # Control banners
        self.unsupported_banner.set_revealed(not is_supported)
        self.import_legacy_banner.set_revealed(
            config.should_offer_legacy_import(
                config.LEGACY_CONFIG_DIR, config.CONFIG_DIR
            )
        )

        # Control the state of the single main group
        self.main_group.set_title(
            self._main_group_title if is_supported else ""
        )
        self.main_group.set_description(
            self._main_group_desc if is_supported else ""
        )
        self.header_box.set_visible(is_supported)

        for row in self._warning_rows:
            row.set_visible(
                is_supported and row not in self._dismissed_warnings
            )

        has_op_error = self._current_error is not None
        is_not_connected_state = (
            is_supported
            and not is_connected
            and not self._not_connected_warning_dismissed
        )

        # The error row now also shows connection status.
        self.error_row.set_visible(has_op_error or is_not_connected_state)
        if has_op_error:
            self.error_row.set_title(_("Operation failed"))
            self.error_row.set_subtitle(self._current_error or "")
        elif is_not_connected_state:
            self.error_row.set_title(_("Machine Not Connected"))
            self.error_row.set_subtitle(_("The machine is not connected."))

        self.firewall_row.set_visible(
            sys.platform == "win32"
            and self.machine.connection_status == TransportStatus.ERROR
        )

        # The main group is visible if any of its contents are.
        is_any_warning_visible = any(
            row.get_visible() for row in self._warning_rows
        )
        self.main_group.set_visible(
            self.unsupported_banner.get_revealed()
            or self.import_legacy_banner.get_revealed()
            or self.error_row.get_visible()
            or is_any_warning_visible
            or has_settings_to_show
        )

        # Control visibility of the dynamic settings widgets
        for widget in self._varset_widgets:
            widget.set_visible(has_settings_to_show)

        # Control visibility of prompt group
        show_prompt = (
            is_supported
            and not has_settings_to_show
            and not self._is_busy
            and not self.error_row.get_visible()
        )
        self.prompt_group.set_visible(show_prompt)

        if self._is_busy:
            self.spinner.start()
            self.read_button.set_sensitive(False)
        else:
            self.spinner.stop()
            self.read_button.set_sensitive(is_connected and not is_running)

        for widget in self._varset_widgets:
            widget.set_apply_buttons_sensitive(
                is_connected and not is_running and not self._is_busy
            )
        self._update_diagnostics()
        logger.debug("_update_ui_state: Finished.")

    def _on_diagnostics_timeout(self):
        if self.machine.id not in get_context().machine_mgr.machines:
            return GLib.SOURCE_REMOVE
        self._update_diagnostics()
        return GLib.SOURCE_CONTINUE

    @staticmethod
    def _format_timestamp(value: float | None) -> str:
        if value is None:
            return _("Never")
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")

    def _update_diagnostics(self):
        """Refreshes the read-only Diagnostics group."""
        driver = self.machine.driver
        self.diag_driver_row.set_subtitle(type(driver).__name__)

        get_diagnostics = getattr(driver, "get_diagnostics", None)
        diagnostics = get_diagnostics() if callable(get_diagnostics) else None
        is_usb = (
            diagnostics is not None
            and getattr(diagnostics, "connection", "udp") == "usb"
        )
        is_udp = diagnostics is not None and not is_usb

        for row in self._udp_only_diag_rows:
            row.set_visible(is_udp)
        for row in self._usb_diag_rows:
            row.set_visible(is_usb)
        for row in (self.diag_enq_row, self.diag_ack_row):
            row.set_visible(diagnostics is not None)

        if diagnostics is not None:
            na = _("N/A")
            self.diag_host_row.set_subtitle(diagnostics.host or na)
            self.diag_port_row.set_subtitle(
                str(diagnostics.port) if diagnostics.port else na
            )
            self.diag_jog_port_row.set_subtitle(
                str(diagnostics.jog_port) if diagnostics.jog_port else na
            )
            self.diag_response_port_row.set_subtitle(
                str(diagnostics.response_port)
            )
            if diagnostics.response_port_bound is None:
                bound_text = _("Not yet attempted")
            elif diagnostics.response_port_bound:
                bound_text = _("Yes")
            elif diagnostics.response_port_error:
                bound_text = _("No: {error}").format(
                    error=diagnostics.response_port_error
                )
            else:
                bound_text = _("No")
            self.diag_response_bound_row.set_subtitle(bound_text)
            self.diag_enq_row.set_subtitle(
                self._format_timestamp(diagnostics.last_enq_sent_at)
            )
            self.diag_ack_row.set_subtitle(
                self._format_timestamp(diagnostics.last_ack_received_at)
            )
            self.diag_usb_backend_row.set_subtitle(
                getattr(diagnostics, "usb_backend", None) or na
            )
            self.diag_usb_device_row.set_subtitle(
                getattr(diagnostics, "usb_device", None) or na
            )
            self.diag_usb_bytes_sent_row.set_subtitle(
                str(getattr(diagnostics, "usb_bytes_sent", 0))
            )
            self.diag_usb_bytes_received_row.set_subtitle(
                str(getattr(diagnostics, "usb_bytes_received", 0))
            )

        # No UDP ports are in play over USB, so the ilab-614 port
        # sanity notice would have nothing meaningful to compare.
        is_usb_profile = self.machine.driver_args.get("connection") == "usb"
        port_mismatches = (
            RuidaDriver.port_mismatches(self.machine.driver_args)
            if self.machine.driver_name == "RuidaDriver"
            and not is_usb_profile
            else {}
        )
        self.diag_port_warning_row.set_visible(bool(port_mismatches))
        if port_mismatches:
            details = ", ".join(
                f"{field}: {actual} (expected {expected})"
                for field, (actual, expected) in port_mismatches.items()
            )
            self.diag_port_warning_row.set_subtitle(details)

        log_file = get_current_log_file()
        self.diag_log_row.set_subtitle(str(log_file) if log_file else _("N/A"))

    def _on_settings_op_success(self, sender, var_sets: list[VarSet]):
        logger.debug("Success signal received with var_sets (from read).")

        scrolled_window = self.get_ancestor(Gtk.ScrolledWindow)
        adj = (
            cast(Gtk.ScrolledWindow, scrolled_window).get_vadjustment()
            if scrolled_window
            else None
        )
        scroll_value = (
            adj.get_value() if adj and self._varset_widgets else None
        )

        self._is_busy = False
        self._clear_error_state()

        self._rebuild_settings_widgets(var_sets)
        self._update_ui_state()

        if adj and scroll_value is not None:

            def restore_scroll():
                max_scroll = adj.get_upper() - adj.get_page_size()
                if scroll_value <= max_scroll:
                    adj.set_value(scroll_value)
                return GLib.SOURCE_REMOVE

            GLib.idle_add(restore_scroll)

    def _on_setting_applied(self, sender):
        """Handles the successful application of a single setting."""
        logger.debug("Success signal received for applying setting.")
        self._is_busy = False
        self._clear_error_state()
        self.show_toast.send(self, message=_("Setting applied successfully."))
        self._update_ui_state()

    def _on_settings_op_error(self, sender, error):
        logger.debug(f"Error signal received: {error}")
        self._is_busy = False
        # Clear any stale settings from the UI by passing an empty list
        self._rebuild_settings_widgets([])

        # Friendly error message for resource busy
        if isinstance(error, ResourceBusyError):
            msg = _("Cannot connect: Used by '{machine}'").format(
                machine=error.owner_name
            )
            self._show_error(msg)
        else:
            self._show_error(str(error))

        self._update_ui_state()

    def _on_setting_apply(self, sender: VarSetWidget, key: str):
        self._not_connected_warning_dismissed = False
        if self._is_busy:
            return
        if self._is_updating_from_model:
            return

        new_value = sender.get_values().get(key)
        if new_value is None:
            return

        logger.debug(f"_on_setting_apply: Applying key '{key}'.")
        self._is_busy = True
        self._clear_error_state()
        self._update_ui_state()
        self.machine.apply_setting(key, new_value)

    def _on_read_clicked(self, _button=None):
        self._not_connected_warning_dismissed = False
        if self._is_busy:
            return

        logger.debug("_on_read_clicked: Read button clicked.")
        self._is_busy = True
        self._clear_error_state()
        self._update_ui_state()
        self.machine.refresh_settings()

    def _on_warning_dismissed(self, _button, row_to_dismiss):
        self._dismissed_warnings.add(row_to_dismiss)
        row_to_dismiss.set_visible(False)
        self._update_ui_state()

    def _on_error_dismissed(self, _button):
        """Hides the error row and cancels the auto-hide timer."""
        # If the reason for the error row is the connection status,
        # mark it as dismissed by the user.
        if not self.machine.is_connected():
            self._not_connected_warning_dismissed = True

        self._clear_error_state()
        self._update_ui_state()

    def _on_copy_error_clicked(self, _button):
        """Copies the current error message to the clipboard."""
        if self._current_error:
            clipboard = self.get_clipboard()
            provider = Gdk.ContentProvider.new_for_value(self._current_error)
            clipboard.set_content(provider)

    def _on_import_legacy_clicked(self, _banner):
        """
        Handler for the "Import settings from Rayforge" banner button.

        Copy-only and non-destructive: `config.import_legacy_config`
        never overwrites anything already present in the swiftcut
        config dir, so an existing/active machine profile is never
        clobbered - a same-named legacy file is simply skipped. Any
        new machine files it does copy in are picked up immediately
        via `load_new_machines` without disturbing already-loaded
        machines. Writes a migration marker, so the banner will not be
        offered again regardless of whether anything new was found.
        """
        logger.info("Importing legacy config from Rayforge.")
        copied = config.import_legacy_config(
            config.LEGACY_CONFIG_DIR, config.CONFIG_DIR
        )
        get_context().machine_mgr.load_new_machines()
        self._update_ui_state()
        if copied:
            self.show_toast.send(self, message=_("Settings imported."))
        else:
            self.show_toast.send(self, message=_("Nothing new to import."))

    def _on_reset_ruida_ports_clicked(self, _button):
        """
        Handler for the Diagnostics group's "Reset ports to defaults"
        button. This is the only place a Ruida profile's ports are
        ever rewritten: the sanity check that surfaces the notice
        never touches the file on its own.
        """
        logger.info(
            f"Resetting Ruida ports to defaults for '{self.machine.name}'."
        )
        new_args = {**self.machine.driver_args, **RuidaDriver.expected_ports()}
        self.machine.set_driver_args(new_args)
        self._update_ui_state()
        self.show_toast.send(self, message=_("Ports reset to defaults."))

    def _on_activate_clicked(self, _banner):
        """Handler for the 'Activate Machine' button."""
        logger.debug(f"Activating machine: {self.machine.name}")
        get_context().config.set_machine(self.machine)
        self.show_toast.send(self, message=_("Machine activated."))

    def _on_error_timeout(self):
        self._clear_error_state()
        self._update_ui_state()
        return GLib.SOURCE_REMOVE

    def _clear_error_state(self):
        if self._error_timeout_id > 0:
            GLib.source_remove(self._error_timeout_id)
            self._error_timeout_id = 0
        self._current_error = None

    def _show_error(self, error_message: str):
        logger.debug(f"_show_error: Displaying '{error_message}'.")
        self._clear_error_state()
        self._current_error = error_message
        self._update_ui_state()
        self._error_timeout_id = GLib.timeout_add_seconds(
            8, self._on_error_timeout
        )

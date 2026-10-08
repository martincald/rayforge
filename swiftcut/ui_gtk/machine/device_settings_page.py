import logging
import sys
from datetime import datetime
from gettext import gettext as _
from typing import cast

from blinker import Signal
from gi.repository import Adw, GLib, Gtk

from ...context import get_context
from ...logging_setup import get_current_log_file
from ...machine.driver.ruida.ruida_driver import RuidaDriver
from ...machine.driver.ruida.ruida_usb_transport import list_usb_devices
from ...machine.transport.transport import TransportStatus
from ..icons import get_icon
from ..shared.preferences_page import TrackedPreferencesPage

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
    A preferences page for the device connection and its diagnostics.
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

        self.show_toast = Signal()

        # Create a single main group for all static content
        self.main_group = Adw.PreferencesGroup()
        self.add(self.main_group)

        # Firewall hint, shown while the connection is in the ERROR
        # state. Windows-only: the message names a Windows-specific
        # mechanism.
        self.firewall_row = Adw.ActionRow(
            title=FIREWALL_NOTE, activatable=False
        )
        self.firewall_row.add_prefix(get_icon("warning-symbolic"))
        self.main_group.add(self.firewall_row)

        # Connection (Ruida only): Ethernet or USB, and which FTDI
        # device over USB. A change rewrites the profile's driver args,
        # which rebuilds the driver on the new transport; no restart.
        self.connection_group = Adw.PreferencesGroup(title=_("Connection"))
        self.connection_row = Adw.ComboRow(
            title=_("Connection"),
            model=Gtk.StringList.new([_("Ethernet"), _("USB")]),
        )
        self.connection_row.connect(
            "notify::selected", self._on_connection_selected
        )
        self.connection_group.add(self.connection_row)
        self.usb_device_row = Adw.ComboRow(
            title=_("USB Device"),
            subtitle=_("Automatic uses the only FTDI device found"),
            model=Gtk.StringList.new([]),
        )
        refresh_usb_button = Gtk.Button(child=get_icon("refresh-symbolic"))
        refresh_usb_button.set_tooltip_text(_("Refresh USB Devices"))
        refresh_usb_button.add_css_class("flat")
        refresh_usb_button.set_valign(Gtk.Align.CENTER)
        refresh_usb_button.connect(
            "clicked", self._on_refresh_usb_devices_clicked
        )
        self.usb_device_row.add_suffix(refresh_usb_button)
        self.usb_device_row.connect(
            "notify::selected", self._on_usb_device_selected
        )
        self.connection_group.add(self.usb_device_row)
        self.add(self.connection_group)
        # The last enumeration, and the usb_serial each dropdown entry
        # stands for ("" is Automatic).
        self._usb_devices = []
        self._usb_device_serials: list[str] = []
        self._is_syncing_connection = False

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
        # rows above when the driver's connection is "usb". The ACK
        # row stays shown for USB too; ENQ is the UDP keepalive only.
        self.diag_usb_backend_row = Adw.ActionRow(title=_("USB Backend"))
        self.diag_usb_port_row = Adw.ActionRow(title=_("USB Port"))
        self.diag_usb_device_row = Adw.ActionRow(title=_("USB Device"))
        self.diag_usb_handshake_row = Adw.ActionRow(title=_("USB Handshake"))
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
            self.diag_usb_port_row,
            self.diag_usb_device_row,
            self.diag_usb_handshake_row,
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
        self.connect("destroy", self.on_destroy)

        if (
            self.machine.driver_name == "RuidaDriver"
            and self.machine.driver_args.get("connection") == "usb"
        ):
            self._refresh_usb_devices()
        self._sync_connection_group()
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
        if self._diagnostics_timeout_id > 0:
            GLib.source_remove(self._diagnostics_timeout_id)
            self._diagnostics_timeout_id = 0

    def _on_machine_config_changed(self, sender, **kwargs):
        logger.debug("_on_machine_config_changed: Rebuilding UI.")
        if self.machine.id not in get_context().machine_mgr.machines:
            logger.debug("_on_machine_config_changed: Machine removed.")
            return
        self._sync_connection_group()
        self._update_ui_state()

    def _on_connection_status_changed(self, sender, **kwargs):
        logger.debug("_on_connection_status_changed: Updating UI.")
        self._update_ui_state()

    def _on_state_changed(self, sender, state, **kwargs):
        logger.debug("_on_state_changed: Updating UI.")
        self._update_ui_state()

    def _update_ui_state(self):
        logger.debug("_update_ui_state: Starting.")
        if self.machine.id not in get_context().machine_mgr.machines:
            logger.debug("_update_ui_state: Machine removed, skipping.")
            return

        self.firewall_row.set_visible(
            sys.platform == "win32"
            and self.machine.connection_status == TransportStatus.ERROR
        )

        # The main group is visible if any of its contents are.
        self.main_group.set_visible(self.firewall_row.get_visible())

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

    @staticmethod
    def _format_usb_handshake(diagnostics) -> str:
        ok = getattr(diagnostics, "usb_handshake_ok", None)
        if ok is None:
            return _("Not yet attempted")
        if not ok:
            return _("No reply to the card ID read")
        card_id = getattr(diagnostics, "card_id", None)
        if card_id is None:
            return _("Handshake ok (ACK, no card ID)")
        return _("Handshake ok, card ID 0x{card_id:08X} ({model})").format(
            card_id=card_id,
            model=getattr(diagnostics, "model_name", None)
            or _("unknown model"),
        )

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
        self.diag_enq_row.set_visible(is_udp)
        self.diag_ack_row.set_visible(diagnostics is not None)

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
            self.diag_usb_port_row.set_subtitle(
                getattr(diagnostics, "usb_port", None) or na
            )
            self.diag_usb_device_row.set_subtitle(
                getattr(diagnostics, "usb_device", None) or na
            )
            self.diag_usb_handshake_row.set_subtitle(
                self._format_usb_handshake(diagnostics)
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

    def _refresh_usb_devices(self):
        """Enumerates the FTDI devices the profile's USB backend sees."""
        backend = RuidaDriver._resolve_usb_backend(
            self.machine.driver_args.get("usb_backend", "auto")
        )
        self._usb_devices = list_usb_devices(backend)

    def _sync_connection_group(self):
        """
        Shows the profile's connection and USB pin. Never writes them
        back: the handlers ignore changes made while syncing.
        """
        is_ruida = self.machine.driver_name == "RuidaDriver"
        self.connection_group.set_visible(is_ruida)
        if not is_ruida:
            return
        is_usb = self.machine.driver_args.get("connection") == "usb"
        pin = self.machine.driver_args.get("usb_serial") or ""

        labels = [_("Automatic")]
        serials = [""]
        for device in self._usb_devices:
            labels.append(f"{device.description} ({device.serial})")
            serials.append(device.serial)
        if pin not in serials:
            # Keep a pinned device that is unplugged selectable.
            labels.append(_("{serial} (not found)").format(serial=pin))
            serials.append(pin)

        self._is_syncing_connection = True
        try:
            self.connection_row.set_selected(1 if is_usb else 0)
            if serials != self._usb_device_serials:
                model = cast(Gtk.StringList, self.usb_device_row.get_model())
                model.splice(0, model.get_n_items(), labels)
                self._usb_device_serials = serials
            self.usb_device_row.set_selected(serials.index(pin))
        finally:
            self._is_syncing_connection = False
        self.usb_device_row.set_visible(is_usb)

    def _set_driver_arg(self, key: str, value: str):
        """Writes one driver arg; the driver is rebuilt on the change."""
        if self.machine.driver_args.get(key) == value:
            return
        self.machine.set_driver_args({**self.machine.driver_args, key: value})

    def _on_connection_selected(self, row, _pspec):
        if self._is_syncing_connection:
            return
        connection = "usb" if row.get_selected() == 1 else "udp"
        if connection == "usb":
            self._refresh_usb_devices()
        self._set_driver_arg("connection", connection)
        self._sync_connection_group()

    def _on_usb_device_selected(self, row, _pspec):
        if self._is_syncing_connection:
            return
        index = row.get_selected()
        if 0 <= index < len(self._usb_device_serials):
            self._set_driver_arg("usb_serial", self._usb_device_serials[index])

    def _on_refresh_usb_devices_clicked(self, _button):
        self._refresh_usb_devices()
        self._sync_connection_group()

    def _on_activate_clicked(self, _banner):
        """Handler for the 'Activate Machine' button."""
        logger.debug(f"Activating machine: {self.machine.name}")
        get_context().config.set_machine(self.machine)
        self.show_toast.send(self, message=_("Machine activated."))

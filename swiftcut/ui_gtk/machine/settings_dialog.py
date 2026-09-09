from gettext import gettext as _

from gi.repository import Adw, Gtk

from ...machine.driver import (
    DRIVER_MATURITY_LABELS,
    DriverMaturity,
    get_driver_cls,
)
from ...machine.models.machine import Machine
from ..icons import get_icon
from ..layout import SPACE_CONTROL, SPACE_GROUP
from ..shared.gtk import apply_css
from ..shared.patched_dialog_window import PatchedDialogWindow
from .advanced_preferences_page import AdvancedPreferencesPage
from .capabilities_page import CapabilitiesPage
from .device_settings_page import DeviceSettingsPage
from .general_preferences_page import GeneralPreferencesPage
from .hardware_page import HardwarePage
from .head_preferences_page import HeadPreferencesPage
from .hooks_macros_page import HooksMacrosPage
from .maintenance_page import MaintenancePage
from .nogo_zones_page import NogoZonesPage
from .rotary_module_page import RotaryModulePage

apply_css("""
.maturity-warning {
    background-color: alpha(@warning_color, 0.15);
    padding: 12px 24px;
}
""")


class MachineSettingsDialog(PatchedDialogWindow):
    def __init__(
        self,
        *,
        machine: Machine,
        transient_for=None,
        initial_page: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        if transient_for:
            self.set_transient_for(transient_for)
        self.machine = machine
        self._row_to_page_name = {}
        self._initial_page = initial_page
        if machine.name:
            self.set_title(
                _("{machine_name} - Machine Settings").format(
                    machine_name=machine.name
                )
            )
        else:
            self.set_title(_("Machine Settings"))
        self.set_default_size(800, 800)

        # --- Layout ---
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # Main layout container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(main_box)

        # Header bar
        header_bar = Adw.HeaderBar()
        main_box.append(header_bar)

        # Maturity warning banner
        self.maturity_banner = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=SPACE_GROUP,
            hexpand=True,
        )
        self.maturity_banner.add_css_class("maturity-warning")
        self._maturity_icon = get_icon("warning-symbolic")
        self._maturity_icon.add_css_class("warning")
        self._maturity_label = Gtk.Label(wrap=True, xalign=0, hexpand=True)
        self._maturity_label.add_css_class("warning-label")

        self.maturity_banner.append(self._maturity_icon)
        self.maturity_banner.append(self._maturity_label)
        self.maturity_banner.set_visible(False)
        main_box.append(self.maturity_banner)

        # Navigation Split View for sidebar and content
        split_view = Adw.NavigationSplitView(vexpand=True)
        main_box.append(split_view)

        # Sidebar
        self.sidebar_list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.SINGLE,
            css_classes=["navigation-sidebar"],
        )
        sidebar_page = Adw.NavigationPage.new(
            self.sidebar_list, _("Categories")
        )
        split_view.set_sidebar(sidebar_page)

        # Content Stack
        self.content_stack = Gtk.Stack()

        # --- Page 1: General ---
        general_page = GeneralPreferencesPage(machine=self.machine)
        self.content_stack.add_titled(general_page, "general", _("General"))

        # --- Page 2: Hardware ---
        hardware_page = HardwarePage(machine=self.machine)
        self.content_stack.add_titled(hardware_page, "hardware", _("Hardware"))

        # --- Page 3: Advanced ---
        advanced_page = AdvancedPreferencesPage(machine=self.machine)
        self.content_stack.add_titled(advanced_page, "advanced", _("Advanced"))

        # --- Page 5: Hooks & Macros ---
        hooks_macros_page = HooksMacrosPage(machine=self.machine)
        self.content_stack.add_titled(
            hooks_macros_page, "hooks-macros", _("Hooks & Macros")
        )

        # --- Page 6: Device ---
        device_page = DeviceSettingsPage(machine=self.machine)
        device_page.show_toast.connect(self._on_show_toast)
        self.content_stack.add_titled(device_page, "device", _("Device"))

        # --- Page 7: Heads ---
        heads_page = HeadPreferencesPage(machine=self.machine)
        self.content_stack.add_titled(heads_page, "heads", _("Heads"))

        # --- Page 8: Rotary Module ---
        rotary_module_page = RotaryModulePage(machine=self.machine)
        self.content_stack.add_titled(
            rotary_module_page, "rotary-module", _("Rotary Module")
        )

        # --- Page 9: No-Go Zones ---
        nogo_zones_page = NogoZonesPage(machine=self.machine)
        self.content_stack.add_titled(
            nogo_zones_page, "nogo-zones", _("No-Go Zones")
        )

        # --- Page 11: Maintenance ---
        maintenance_page = MaintenancePage(machine=self.machine)
        self.content_stack.add_titled(
            maintenance_page, "maintenance", _("Maintenance")
        )

        # --- Page 12: Capabilities ---
        capabilities_page = CapabilitiesPage(machine=self.machine)
        self.content_stack.add_titled(
            capabilities_page, "capabilities", _("Capabilities")
        )

        # Create the content's NavigationPage wrapper
        pages = self.content_stack.get_pages()
        first_stack_page = pages.get_item(0)  # type: ignore
        initial_title = first_stack_page.get_title()
        self.content_page = Adw.NavigationPage.new(
            self.content_stack, initial_title
        )
        split_view.set_content(self.content_page)

        # Populate sidebar with rows
        self._add_sidebar_row(
            _("General"), "machine-settings-general-symbolic", "general"
        )
        self._add_sidebar_row(_("Hardware"), "hardware-symbolic", "hardware")
        self._add_sidebar_row(
            _("Advanced"), "machine-settings-advanced-symbolic", "advanced"
        )
        self._add_sidebar_row(
            _("Hooks & Macros"), "code-symbolic", "hooks-macros"
        )
        self._add_sidebar_row(_("Device"), "settings-symbolic", "device")
        self._add_sidebar_row(_("Heads"), "laser-on-symbolic", "heads")
        self._add_sidebar_row(
            _("Rotary Module"), "rotary-symbolic", "rotary-module"
        )
        self._add_sidebar_row(
            _("No-Go Zones"), "action-unavailable-symbolic", "nogo-zones"
        )
        self._add_sidebar_row(
            _("Maintenance"), "timer-symbolic", "maintenance"
        )
        self._add_sidebar_row(
            _("Capabilities"), "settings-symbolic", "capabilities"
        )

        # Connect sidebar selection
        self.sidebar_list.connect("row-selected", self._on_row_selected)

        self.connect("destroy", self._on_destroy)

        # React to driver changes (e.g. maturity banner)
        self.machine.changed.connect(self._on_machine_changed)

        # Initial population of the maturity banner
        self._update_maturity_banner()

        # Select the specified page or first row by default
        if self._initial_page:
            for row, page_name in self._row_to_page_name.items():
                if page_name == self._initial_page:
                    self.sidebar_list.select_row(row)
                    break
        else:
            self.sidebar_list.select_row(self.sidebar_list.get_row_at_index(0))

    def _on_machine_changed(self, sender=None, **kwargs):
        self._update_maturity_banner()

    def _update_maturity_banner(self):
        maturity = DriverMaturity.STABLE
        if self.machine.driver_name:
            driver_cls = get_driver_cls(self.machine.driver_name)
            maturity = driver_cls.maturity
        label = DRIVER_MATURITY_LABELS.get(maturity, "")
        if label:
            self._maturity_label.set_text(label)
            self.maturity_banner.set_visible(True)
        else:
            self.maturity_banner.set_visible(False)

    def _add_sidebar_row(
        self, label_text: str, icon_name: str, page_name: str
    ):
        """Adds a row to the sidebar with an icon and label."""
        row = Gtk.ListBoxRow()
        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=SPACE_GROUP,
            margin_start=SPACE_GROUP,
            margin_end=SPACE_GROUP,
            margin_top=SPACE_CONTROL,
            margin_bottom=SPACE_CONTROL,
        )
        icon = get_icon(icon_name)
        label = Gtk.Label(label=label_text, xalign=0)
        box.append(icon)
        box.append(label)
        row.set_child(box)
        self._row_to_page_name[row] = page_name
        self.sidebar_list.append(row)

    def _on_row_selected(self, listbox, row):
        """Handler for when a row is selected in the sidebar."""
        if row:
            page_name = self._row_to_page_name[row]
            self.content_stack.set_visible_child_name(page_name)
            child = self.content_stack.get_child_by_name(page_name)
            if child:
                stack_page = self.content_stack.get_page(child)
                if stack_page:
                    title = stack_page.get_title()
                    if title:
                        self.content_page.set_title(title)

    def _on_show_toast(self, sender, message: str):
        """
        Handler to show the toast when requested by the child page.
        """
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=5))

    def _on_destroy(self, *args):
        """Disconnects signals to prevent memory leaks."""
        self.machine.changed.disconnect(self._on_machine_changed)

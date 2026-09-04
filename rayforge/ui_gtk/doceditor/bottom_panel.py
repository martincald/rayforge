import logging
from collections.abc import Callable
from gettext import gettext as _
from typing import TYPE_CHECKING

from blinker import Signal
from gi.repository import Adw, Gtk
from raygeo.ops.axis import Axis

from ...logging_setup import ui_log_event_received
from ...machine.cmd import MachineCmd
from ...machine.driver.dummy import NoDeviceDriver
from ...machine.models.machine import Machine, StartCorner
from ...shared.gcodeedit.viewer import GcodeViewer
from ...shared.tasker import task_mgr
from ..doceditor.layers_tab import LayersTab
from ..layout import (
    PANEL_MAX_WIDTH,
    SPACE_GROUP,
    axis_button,
    format_position,
    icon_button,
    suffix_box,
)
from ..machine.console import Console
from ..machine.jog_widget import DEFAULT_JOG_SPEED_BASE, JogWidget
from ..machine.laser_control_widget import LaserControlWidget
from ..machine.wcs_dialog import WcsDialog
from ..shared.dock_item import DockItem
from ..shared.dock_layout import DockLayout
from ..shared.gtk import apply_css
from ..shared.pref_rows.length_spin_row import LengthSpinRow
from ..shared.pref_rows.speed_spin_row import SpeedSpinRow
from ..shared.responsive_box import ResponsiveBox
from .asset_browser import AssetBrowser

if TYPE_CHECKING:
    from ...doceditor.editor import DocEditor

logger = logging.getLogger(__name__)

# The jog widget carries its speed in this display unit.

controls_css = """
preferencesgroup.compact list {
    margin-left: 0;
    margin-right: 0;
}
"""

apply_css(controls_css)


class BottomPanel(Gtk.Box):
    def __init__(
        self,
        machine: Machine | None,
        doc_editor: "DocEditor",
        machine_cmd: MachineCmd | None = None,
        **kwargs,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kwargs)
        self.add_css_class("sc-dock")

        self.notification_requested = Signal()
        self.click_to_zero_mode_changed = Signal()
        self.tab_changed = Signal()
        self.layout_changed = Signal()
        self.edit_item_requested = Signal()
        self.select_items_requested = Signal()
        self.machine = machine
        self.machine_cmd = machine_cmd
        self.doc = None
        self._edit_dialog = None
        self._click_to_zero_mode = False
        self._updating_wcs_ui = False
        self._active_layer = None
        self._get_bounds_callback: (
            Callable[[], tuple[float, float, float, float] | None] | None
        ) = None

        self.console = Console()
        self.console.set_hexpand(True)
        self.console.set_vexpand(True)
        if machine:
            self.console.set_machine(machine)
        self.console.command_submitted.connect(self._on_command_submitted)

        ui_log_event_received.connect(self.console.on_log_received)

        self.layers_tab = LayersTab(doc_editor)
        self.layers_tab.edit_item_requested.connect(
            self._on_layers_tab_edit_item
        )
        self.layers_tab.select_items_requested.connect(
            self._on_layers_tab_select_items
        )

        self.asset_browser = AssetBrowser(doc_editor)

        self.gcode_viewer = GcodeViewer()
        self.gcode_viewer.set_margin_start(0)
        self.gcode_viewer.set_margin_end(0)
        self.gcode_viewer.set_margin_top(SPACE_GROUP)
        self.gcode_viewer.set_margin_bottom(SPACE_GROUP)

        self.jog_widget = JogWidget()
        if machine and machine_cmd:
            self.jog_widget.set_machine(machine, machine_cmd)

        self.laser_control = LaserControlWidget()
        if machine and machine_cmd:
            self.laser_control.set_machine(machine, machine_cmd)

        self._laser_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._laser_box.set_margin_start(SPACE_GROUP)
        self._laser_box.set_margin_end(SPACE_GROUP)
        self._laser_box.set_margin_top(SPACE_GROUP)
        self._laser_box.set_margin_bottom(SPACE_GROUP)
        self._laser_box.set_vexpand(True)
        self._laser_box.set_hexpand(False)
        self._laser_box.set_halign(Gtk.Align.START)
        self._laser_box.append(self.laser_control)
        self._jog_laser_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_GROUP
        )
        self._jog_laser_box.append(self.jog_widget)
        self._jog_laser_box.set_vexpand(True)

        self._controls_widget = ResponsiveBox()
        self._controls_widget.set_halign(Gtk.Align.FILL)
        self._controls_widget.set_vexpand(True)
        self._controls_widget.set_valign(Gtk.Align.FILL)
        self._controls_widget.set_margin_start(SPACE_GROUP)
        self._controls_widget.set_margin_end(SPACE_GROUP)
        self._controls_widget.set_margin_top(SPACE_GROUP)
        self._controls_widget.set_margin_bottom(SPACE_GROUP)

        if machine:
            self._setup_wcs_controls()
            self._connect_machine_signals()
            # Clamped, so the group stops at a readable width instead
            # of stretching to the panel edge and leaving 100-140px of
            # nothing between every label and its controls.
            clamp = Adw.Clamp(
                maximum_size=PANEL_MAX_WIDTH,
                tightening_threshold=PANEL_MAX_WIDTH,
                child=self.wcs_group,
            )
            self._controls_widget.set_children(clamp, self._jog_laser_box)
        else:
            self._controls_widget.set_children(self._jog_laser_box)

        self.dock_layout = DockLayout(orientation=Gtk.Orientation.HORIZONTAL)
        self.dock_layout.layout_changed.connect(self._on_dock_layout_changed)
        self.dock_layout.tab_changed.connect(self._on_dock_tab_changed)

        self._register_items()
        self._build_default_layout()
        self.append(self.dock_layout)

    def _register_items(self):
        self.dock_layout.register_item(
            DockItem(
                name="layers",
                icon_name="layers-symbolic",
                widget=self.layers_tab,
                label=_("Layers"),
            )
        )
        self.dock_layout.register_item(
            DockItem(
                name="assets",
                icon_name="image-x-generic-symbolic",
                widget=self.asset_browser,
                label=_("Assets"),
            )
        )
        self.dock_layout.register_item(
            DockItem(
                name="gcode",
                icon_name="gcode-symbolic",
                widget=self.gcode_viewer,
                label=_("G-code Viewer"),
            )
        )
        self.dock_layout.register_item(
            DockItem(
                name="console",
                icon_name="terminal-symbolic",
                widget=self.console,
                label=_("Console"),
            )
        )
        self.dock_layout.register_item(
            DockItem(
                name="controls",
                icon_name="jog-symbolic",
                widget=self._controls_widget,
                label=_("Controls"),
                expands=False,
            )
        )
        self.dock_layout.register_item(
            DockItem(
                name="laser",
                icon_name="laser-on-symbolic",
                widget=self._laser_box,
                label=_("Laser"),
                expands=False,
            )
        )

    def _build_default_layout(self):
        tabs_area = self.dock_layout.add_area()
        tabs_area.add_item(self.dock_layout.get_item("layers"))
        tabs_area.add_item(self.dock_layout.get_item("assets"))
        tabs_area.add_item(self.dock_layout.get_item("gcode"))
        tabs_area.add_item(self.dock_layout.get_item("console"))

        controls_area = self.dock_layout.add_area()
        controls_area.add_item(self.dock_layout.get_item("controls"))
        controls_area.add_item(self.dock_layout.get_item("laser"))

        self.dock_layout.set_default_item_buddy("laser", "controls")

    def to_dict(self):
        return {
            "visible": self.get_visible(),
            "areas": self.dock_layout.get_layout()["areas"],
        }

    def from_dict(self, data):
        if not data:
            return
        visible = data.get("visible", False)
        self.set_visible(visible)
        areas = data.get("areas")
        if areas:
            self.dock_layout.apply_layout({"areas": areas})

    def is_item_visible(self, name):
        area = self.dock_layout.find_item_area(name)
        if area is None:
            return False
        active = area.get_active_item()
        return active == name

    def _on_dock_layout_changed(self, sender):
        self.layout_changed.send(self)

    def _on_dock_tab_changed(self, sender, *, name):
        self.tab_changed.send(self, name=name)

    def set_doc(self, doc):
        self._disconnect_layer_signals()
        self.doc = doc
        self.asset_browser.set_doc(doc)
        self.layers_tab.set_doc(doc)
        if doc:
            doc.active_layer_changed.connect(self._on_active_layer_changed)
            self._connect_layer_signals()
        if self.machine:
            self._update_wcs_ui()

    def _on_layers_tab_edit_item(self, sender, **kwargs):
        self.edit_item_requested.send(sender, **kwargs)

    def _on_layers_tab_select_items(self, sender, **kwargs):
        self.select_items_requested.send(sender, **kwargs)

    def update_layer_selection(self, selected_uids: set):
        self.layers_tab.update_row_selection(selected_uids)

    def _on_active_layer_changed(self, sender):
        self._disconnect_layer_signals()
        self._connect_layer_signals()
        if self.machine:
            self._update_wcs_ui()

    def _connect_layer_signals(self):
        if self.doc and self.doc.active_layer:
            self._active_layer = self.doc.active_layer
            self._active_layer.updated.connect(self._on_layer_updated)

    def _disconnect_layer_signals(self):
        if self._active_layer:
            self._active_layer.updated.disconnect(self._on_layer_updated)
            self._active_layer = None

    def _on_layer_updated(self, sender):
        if self.machine:
            self._update_wcs_ui()

    def _on_command_submitted(self, sender, command: str, machine: Machine):
        async def send_command(ctx):
            try:
                await machine.run_raw(command)
            except Exception as e:  # noqa: BLE001 - fire-and-forget task
                logger.error(str(e), extra={"log_category": "ERROR"})

        task_mgr.add_coroutine(send_command)

    def _setup_wcs_controls(self):
        self.wcs_group = Adw.PreferencesGroup()
        self.wcs_group.add_css_class("compact")
        self.wcs_group.add_css_class("sc-panel")

        if self.machine:
            self.wcs_list = self.machine.supported_wcs
        else:
            self.wcs_list = []
        self._wcs_model = Gtk.StringList.new(self.wcs_list)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_wcs_factory_setup)
        factory.connect("bind", self._on_wcs_factory_bind)

        self.wcs_row = Adw.ComboRow(
            model=self._wcs_model,
            factory=factory,
            use_subtitle=True,
        )
        self.wcs_row.connect(
            "notify::selected", self._on_wcs_selection_changed
        )
        self.wcs_group.add(self.wcs_row)

        self.offsets_row = Adw.ActionRow(title=_("Current Offsets"))

        self.edit_offsets_btn = icon_button(
            "edit-symbolic", _("Edit Offsets Manually")
        )
        self.edit_offsets_btn.connect("clicked", self._on_edit_offsets_clicked)
        self.wcs_row.add_suffix(suffix_box(self.edit_offsets_btn))

        # The row used to be "Current Position" and carry the position
        # in its subtitle, which made it the second of three readouts
        # on this panel. The readout is the jog widget's now; what is
        # left here is what the row's buttons always did.
        self.position_row = Adw.ActionRow(title=_("Move To"))
        self.wcs_group.add(self.position_row)

        self.move_ll_btn = icon_button(
            "bottom-left-symbolic",
            _("Move to Lower-Left of Selection or Workarea"),
        )
        self.move_ll_btn.connect("clicked", self._on_move_to_position, "ll")

        self.move_center_btn = icon_button(
            "center-symbolic",
            _("Move to Center of Selection or Workarea"),
        )
        self.move_center_btn.connect(
            "clicked", self._on_move_to_position, "center"
        )

        self.move_ur_btn = icon_button(
            "top-right-symbolic",
            _("Move to Upper-Right of Selection or Workarea"),
        )
        self.move_ur_btn.connect("clicked", self._on_move_to_position, "ur")

        self.move_origin_btn = icon_button(
            "goto-origin-symbolic", _("Move to Origin of Active WCS")
        )
        self.move_origin_btn.connect("clicked", self._on_move_to_wcs_zero)

        self.position_row.add_suffix(
            suffix_box(
                self.move_ll_btn,
                self.move_center_btn,
                self.move_ur_btn,
                self.move_origin_btn,
            )
        )

        self._setup_start_corner_row()

        self.zero_row = Adw.ActionRow(title=_("Zero Axes"))
        self.wcs_group.add(self.zero_row)

        self.zero_x_btn = axis_button(
            _("X"), _("Set current X position as 0 for active WCS")
        )
        self.zero_x_btn.connect("clicked", self._on_zero_axis_clicked, Axis.X)

        self.zero_y_btn = axis_button(
            _("Y"), _("Set current Y position as 0 for active WCS")
        )
        self.zero_y_btn.connect("clicked", self._on_zero_axis_clicked, Axis.Y)

        self.zero_z_btn = axis_button(
            _("Z"), _("Set current Z position as 0 for active WCS")
        )
        self.zero_z_btn.connect("clicked", self._on_zero_axis_clicked, Axis.Z)

        self.zero_here_btn = icon_button(
            "zero-here-symbolic", _("Set Work Zero at Current Position")
        )
        self.zero_here_btn.connect(
            "clicked", self._on_zero_axis_clicked, Axis.X | Axis.Y | Axis.Z
        )

        self.click_to_zero_btn = icon_button(
            "crosshairs-symbolic", _("Click Canvas to Set Work Zero")
        )
        self.click_to_zero_btn.connect(
            "clicked", self._on_click_to_zero_toggled
        )

        self.zero_row.add_suffix(
            suffix_box(
                self.zero_x_btn,
                self.zero_y_btn,
                self.zero_z_btn,
                self.zero_here_btn,
                self.click_to_zero_btn,
            )
        )

        # Neither row carries a caption: "Speed" only restated the
        # label, and "Distance in machine units" named no unit. The
        # unit is in the field, once, for every unit-aware row.
        self.speed_row = SpeedSpinRow(
            _("Jog Speed"),
            lower=1,
            upper=60000,
            value_in_base=DEFAULT_JOG_SPEED_BASE,
        )
        self.speed_row.value_changed.connect(self._on_speed_changed)
        self.wcs_group.add(self.speed_row)

        self.distance_row = LengthSpinRow(
            _("Jog Distance"),
            lower=0.1,
            upper=1000,
            value_in_base=10.0,
        )
        self.distance_row.value_changed.connect(self._on_distance_changed)
        self.wcs_group.add(self.distance_row)

        self._update_wcs_ui()

    def _setup_start_corner_row(self):
        """Four toggles saying which corner of the job the head is on.

        The job is placed so the selected corner of its bounding box
        lands where the head already is, so the operator parks on a
        corner of the stock and names it rather than computing an
        offset.
        """
        self.start_corner_row = Adw.ActionRow(title=_("Start Corner"))
        # Short enough to stay on one line at the panel's width; the
        # long form wrapped to three and made this the tallest row in
        # the group.
        self.start_corner_row.set_subtitle(
            _("The head is on this corner of the job")
        )
        self.wcs_group.add(self.start_corner_row)

        self._start_corner_buttons: dict[StartCorner, Gtk.ToggleButton] = {}
        buttons = (
            (StartCorner.TOP_LEFT, "top-left-symbolic", _("Top Left")),
            (StartCorner.TOP_RIGHT, "top-right-symbolic", _("Top Right")),
            (
                StartCorner.BOTTOM_LEFT,
                "bottom-left-symbolic",
                _("Bottom Left"),
            ),
            (
                StartCorner.BOTTOM_RIGHT,
                "bottom-right-symbolic",
                _("Bottom Right"),
            ),
        )
        corner_buttons = []
        for corner, icon_name, label in buttons:
            button = icon_button(icon_name, label, toggle=True)
            button.connect("toggled", self._on_start_corner_toggled, corner)
            corner_buttons.append(button)
            self._start_corner_buttons[corner] = button
        self.start_corner_row.add_suffix(suffix_box(*corner_buttons))

        self._update_start_corner_buttons()

    def _on_start_corner_toggled(self, button, corner: "StartCorner"):
        """Adopt a corner, and keep exactly one of the four active.

        Untoggling the active corner would leave the job with no
        stated placement, so the press is simply put back.
        """
        if not button.get_active():
            if self.machine and self.machine.start_corner == corner:
                button.set_active(True)
            return
        if self.machine:
            self.machine.set_start_corner(corner)
        self._update_start_corner_buttons()

    def _update_start_corner_buttons(self):
        """Show the profile's corner, without re-entering the handler."""
        if not self.machine:
            return
        active = self.machine.start_corner
        for corner, button in self._start_corner_buttons.items():
            button.handler_block_by_func(self._on_start_corner_toggled)
            button.set_active(corner == active)
            button.handler_unblock_by_func(self._on_start_corner_toggled)

    def _on_speed_changed(self, row):
        # Both the row and the jog widget speak application base
        # units. Converting to the display unit and back used to
        # quantise every setting to whole mm/s.
        self.jog_widget.set_jog_speed(self.speed_row.get_value_in_base_units())

    def _on_distance_changed(self, row):
        self.jog_widget.jog_distance = (
            self.distance_row.get_value_in_base_units()
        )

    def _connect_machine_signals(self):
        if self.machine:
            self.machine.wcs_updated.connect(self._on_wcs_updated)
            self.machine.state_changed.connect(self._on_machine_state_changed)
            self.machine.changed.connect(self._on_wcs_updated)

    def _disconnect_machine_signals(self):
        if self.machine:
            self.machine.wcs_updated.disconnect(self._on_wcs_updated)
            self.machine.state_changed.disconnect(
                self._on_machine_state_changed
            )
            self.machine.changed.disconnect(self._on_wcs_updated)

    def set_machine(
        self,
        machine: Machine | None,
        machine_cmd: MachineCmd | None = None,
    ):
        self._disconnect_machine_signals()

        self.machine = machine
        self.machine_cmd = machine_cmd

        self.console.set_machine(machine)

        if self.machine:
            self._connect_machine_signals()
            self._update_wcs_ui()

        if self.machine and self.machine_cmd:
            self.jog_widget.set_machine(self.machine, self.machine_cmd)
            self.laser_control.set_machine(self.machine, self.machine_cmd)

    def _on_wcs_selection_changed(self, combo_row, _pspec):
        if self._updating_wcs_ui:
            return
        if not self.machine:
            return
        machine = self.machine
        idx = combo_row.get_selected()
        if 0 <= idx < len(self.wcs_list):
            wcs = self.wcs_list[idx]
            if machine.active_wcs != wcs:
                task_mgr.add_coroutine(
                    lambda ctx, w=wcs: machine.switch_active_wcs(w),
                    key=(machine.id, "select-wcs"),
                )

    def _on_zero_axis_clicked(self, button, axis):
        if not self.machine:
            return
        machine = self.machine
        task_mgr.add_coroutine(lambda ctx: machine.set_work_origin_here(axis))

    def set_click_to_zero_mode(self, active: bool):
        if self._click_to_zero_mode != active:
            self._click_to_zero_mode = active
            self._update_wcs_ui()
            self.click_to_zero_mode_changed.send(self, active=active)

    def set_get_bounds_callback(
        self,
        callback: Callable[[], tuple[float, float, float, float] | None]
        | None,
    ):
        self._get_bounds_callback = callback

    def update_position_menu_sensitivity(self):
        if not self.machine:
            return
        is_dummy = isinstance(self.machine.driver, NoDeviceDriver)
        is_connected = self.machine.is_connected()
        is_active = is_connected or is_dummy

        has_bounds = (
            self._get_bounds_callback is not None
            and self._get_bounds_callback() is not None
        )
        self.move_ll_btn.set_sensitive(has_bounds and is_active)
        self.move_center_btn.set_sensitive(has_bounds and is_active)
        self.move_ur_btn.set_sensitive(has_bounds and is_active)
        self.move_origin_btn.set_sensitive(is_active)

    def _on_move_to_position(self, button, position: str):
        if not self.machine or not self.machine_cmd:
            return
        if not self._get_bounds_callback:
            return

        bounds = self._get_bounds_callback()
        if not bounds:
            return

        min_x, min_y, max_x, max_y = bounds

        if position == "ll":
            world_x, world_y = min_x, min_y
        elif position == "center":
            world_x, world_y = (min_x + max_x) / 2, (min_y + max_y) / 2
        elif position == "ur":
            world_x, world_y = max_x, max_y
        else:
            return

        panel = self.machine.panel
        machine_x, machine_y = panel.world_point_to_machine(world_x, world_y)
        wcs_offset = self.machine.get_active_wcs_offset()
        x_off, y_off, _ = panel.get_command_offset(
            wcs_offset=wcs_offset,
            wcs_is_workarea_origin=self.machine.wcs_origin_is_workarea_origin,
        )
        self.machine_cmd.move_to(
            self.machine, machine_x - x_off, machine_y - y_off
        )

    def _on_move_to_wcs_zero(self, button):
        if not self.machine or not self.machine_cmd:
            return
        self.machine_cmd.move_to(self.machine, 0.0, 0.0)

    def _on_click_to_zero_toggled(self, button):
        self.set_click_to_zero_mode(not self._click_to_zero_mode)

    def _on_edit_offsets_clicked(self, button):
        if not self.machine:
            return

        root = self.get_root()
        self._edit_dialog = WcsDialog(
            machine=self.machine,
            transient_for=root if isinstance(root, Gtk.Window) else None,
        )
        self._edit_dialog.connect(
            "destroy", lambda *_: setattr(self, "_edit_dialog", None)
        )
        self._edit_dialog.present()

    def _on_wcs_updated(self, machine):
        self._update_wcs_ui()

    def _on_machine_state_changed(self, machine, state):
        self._update_wcs_ui()
        self.console.on_machine_state_changed(machine, state)

    def _on_wcs_factory_setup(self, factory, list_item):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        name_label = Gtk.Label(xalign=0)
        subtitle_label = Gtk.Label(xalign=0)
        subtitle_label.add_css_class("dim-label")
        box.append(name_label)
        box.append(subtitle_label)
        list_item.set_child(box)

    def _on_wcs_factory_bind(self, factory, list_item):
        idx = list_item.get_position()
        if idx < 0 or idx >= len(self.wcs_list):
            return
        wcs_name = self.wcs_list[idx]
        box = list_item.get_child()
        name_label = box.get_first_child()
        subtitle_label = name_label.get_next_sibling()
        if self.machine:
            label = self.machine.get_wcs_label(wcs_name)
            if label:
                name_label.set_label(f"{wcs_name} ({label})")
            else:
                name_label.set_label(wcs_name)
            off = self.machine.get_wcs_offset(wcs_name)
            subtitle_label.set_label(
                f"X: {off[0]:.2f} Y: {off[1]:.2f} Z: {off[2]:.2f}"
            )
            subtitle_label.set_visible(True)
        else:
            name_label.set_label(wcs_name)
            subtitle_label.set_visible(False)

    def _update_wcs_ui(self):
        if not self.machine:
            return

        hide_wcs_controls = self.machine.wcs_origin_is_workarea_origin
        self.wcs_row.set_visible(not hide_wcs_controls)
        self.zero_row.set_visible(not hide_wcs_controls)
        self._update_start_corner_buttons()

        layer_has_wcs = (
            self.doc and self.doc.active_layer and self.doc.active_layer.wcs
        )
        self.wcs_row.set_sensitive(not layer_has_wcs)
        if layer_has_wcs:
            self.wcs_row.set_tooltip_text(
                _(
                    "Overridden by the current layer. "
                    "Change it in the layer settings."
                )
            )
        else:
            self.wcs_row.set_tooltip_text("")

        current_wcs = self.machine.active_wcs
        if current_wcs in self.wcs_list:
            idx = self.wcs_list.index(current_wcs)
            if self.wcs_row.get_selected() != idx:
                self._updating_wcs_ui = True
                self.wcs_row.set_selected(idx)
                self._updating_wcs_ui = False

        wcs_label = self.machine.get_wcs_label(current_wcs)
        if wcs_label:
            title = f"{current_wcs} ({wcs_label})"
        else:
            title = current_wcs
        self.wcs_row.set_title(title)

        # Offsets are a different quantity from position, but they are
        # read the same way, so they are written the same way.
        off_x, off_y, off_z = self.machine.get_active_wcs_offset()
        self.wcs_row.set_subtitle(
            f"{format_position(off_x, off_y)}  Z {off_z:.1f}"
        )

        n = self._wcs_model.get_n_items()
        for i in range(n):
            self._wcs_model.items_changed(i, 1, 1)

        is_dummy = isinstance(self.machine.driver, NoDeviceDriver)
        is_connected = self.machine.is_connected()
        is_active = is_connected or is_dummy

        is_mcs = current_wcs == self.machine.machine_space_wcs
        can_zero = is_active and not is_mcs
        can_manual = not is_mcs

        self.zero_x_btn.set_sensitive(can_zero)
        self.zero_y_btn.set_sensitive(can_zero)
        self.zero_z_btn.set_sensitive(can_zero)
        self.zero_here_btn.set_sensitive(can_zero)
        self.edit_offsets_btn.set_sensitive(can_manual)

        self.update_position_menu_sensitivity()

        if is_mcs:
            msg = _(
                "Offsets cannot be set in Machine Coordinate Mode ({wcs})"
            ).format(wcs=self.machine.machine_space_wcs_display_name)
        elif not is_active:
            msg = _("Machine must be connected to set Zero Here")
        else:
            msg = _("Set current position as 0")

        self.zero_here_btn.set_tooltip_text(msg)

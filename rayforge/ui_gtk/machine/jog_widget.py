from gettext import gettext as _

from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk
from raygeo.ops.axis import Axis

from ...machine.cmd import MachineCmd
from ...machine.models.machine import JogDirection, Machine
from ...shared.units.definitions import Unit, get_unit
from ..icons import get_icon
from .cut_scale_dialog import CutScaleDialog

# The widget carries its jog speed in the display unit; drivers take
# application base units, so it converts at that one boundary.
_JOG_SPEED_UNIT: Unit = get_unit("mm/s")  # type: ignore[assignment]

# The hold jog speed is driver state, so it is pushed when the control
# settles rather than on every keystroke.
_JOG_SPEED_DEBOUNCE_MS = 300

# How long an arrow must stay down before it counts as a hold. A
# shorter press is a click, and moves exactly one step instead.
_HOLD_START_DELAY_MS = 200

_GAP = 12
_SPACING = 6
_ROWS = 5
_MAX_HEIGHT = _ROWS * 60 + (_ROWS - 1) * _SPACING


class JogWidget(Gtk.Widget):
    """Widget for manually jogging the machine."""

    def __init__(self, show_actions: bool = True, **kwargs):
        super().__init__(**kwargs)

        self._jog_grid = Gtk.Grid()
        self._jog_grid.set_parent(self)
        self._jog_grid.set_row_spacing(_SPACING)
        self._jog_grid.set_column_spacing(_SPACING)
        self._jog_grid.set_row_homogeneous(True)
        self._jog_grid.set_column_homogeneous(True)

        self._show_actions = show_actions

        self._action_grid = Gtk.Grid()
        self._action_grid.set_parent(self)
        self._action_grid.set_row_spacing(_SPACING)
        self._action_grid.set_row_homogeneous(True)
        self._action_grid.set_visible(show_actions)

        self.machine: Machine | None = None
        self.machine_cmd: MachineCmd | None = None
        self.jog_speed = 100  # mm/s
        self.jog_distance = 10.0
        self._buttons = []
        self._scaling = False
        self._keys_down: set[tuple[str, int]] = set()
        self._button_directions: dict[
            Gtk.Button, tuple[JogDirection, ...]
        ] = {}
        self._jog_speed_timeout_id: int | None = None
        self._hold_timeout_id: int | None = None
        self._root_active_handler: int | None = None

        self.set_focusable(True)

        def create_button(icon_name, tooltip, label=None):
            button = Gtk.Button()
            button.set_size_request(60, 60)
            button.set_tooltip_text(tooltip)
            icon = get_icon(icon_name)
            if label is None:
                button.set_child(icon)
            else:
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                box.set_halign(Gtk.Align.CENTER)
                box.set_valign(Gtk.Align.CENTER)
                caption = Gtk.Label(label=label)
                caption.add_css_class("caption")
                box.append(icon)
                box.append(caption)
                button.set_child(box)
            button.set_hexpand(True)
            button.set_vexpand(True)
            self._buttons.append(button)
            return button

        # Row 0: NW - N - NE
        self.north_west_btn = create_button(
            "arrow-north-west-symbolic", _("Move North-West")
        )
        self._attach_hold(
            self.north_west_btn, JogDirection.WEST, JogDirection.NORTH
        )
        self._jog_grid.attach(self.north_west_btn, 0, 0, 1, 1)

        self.north_btn = create_button("arrow-north-symbolic", _("Move North"))
        self._attach_hold(self.north_btn, JogDirection.NORTH)
        self._jog_grid.attach(self.north_btn, 1, 0, 1, 1)

        self.north_east_btn = create_button(
            "arrow-north-east-symbolic", _("Move North-East")
        )
        self._attach_hold(
            self.north_east_btn, JogDirection.EAST, JogDirection.NORTH
        )
        self._jog_grid.attach(self.north_east_btn, 2, 0, 1, 1)

        # Row 1: W - Home - E
        self.west_btn = create_button(
            "arrow-west-symbolic", _("Move West (Left)")
        )
        self._attach_hold(self.west_btn, JogDirection.WEST)
        self._jog_grid.attach(self.west_btn, 0, 1, 1, 1)

        self.home_all_btn = create_button(
            "home-symbolic", _("Home machine"), label=_("Home")
        )
        self.home_all_btn.connect("clicked", self._on_home_all_clicked)
        self._jog_grid.attach(self.home_all_btn, 1, 1, 1, 1)

        self.east_btn = create_button(
            "arrow-east-symbolic", _("Move East (Right)")
        )
        self._attach_hold(self.east_btn, JogDirection.EAST)
        self._jog_grid.attach(self.east_btn, 2, 1, 1, 1)

        # Row 2: SW - S - SE
        self.south_west_btn = create_button(
            "arrow-south-west-symbolic", _("Move South-West")
        )
        self._attach_hold(
            self.south_west_btn, JogDirection.WEST, JogDirection.SOUTH
        )
        self._jog_grid.attach(self.south_west_btn, 0, 2, 1, 1)

        self.south_btn = create_button("arrow-south-symbolic", _("Move South"))
        self._attach_hold(self.south_btn, JogDirection.SOUTH)
        self._jog_grid.attach(self.south_btn, 1, 2, 1, 1)

        self.south_east_btn = create_button(
            "arrow-south-east-symbolic", _("Move South-East")
        )
        self._attach_hold(
            self.south_east_btn, JogDirection.EAST, JogDirection.SOUTH
        )
        self._jog_grid.attach(self.south_east_btn, 2, 2, 1, 1)

        # Row 3: the two scale actions, side by side.
        self.go_scale_btn = create_button(
            "frame-symbolic",
            _("Traverse the job outline with the laser off"),
            label=_("Go Scale"),
        )
        self._go_scale_caption = self._button_caption(self.go_scale_btn)
        self.go_scale_btn.connect("clicked", self._on_go_scale_clicked)

        self.cut_scale_btn = create_button(
            "frame-symbolic",
            _("Cut a rectangle around the job outline"),
            label=_("Cut Scale"),
        )
        self.cut_scale_btn.connect("clicked", self._on_cut_scale_clicked)

        scale_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=_SPACING
        )
        scale_box.set_homogeneous(True)
        scale_box.append(self.go_scale_btn)
        scale_box.append(self.cut_scale_btn)
        self._jog_grid.attach(scale_box, 0, 3, 3, 1)

        # Row 4: position readout.
        self.position_label = Gtk.Label(label=self._format_position(None))
        self.position_label.add_css_class("numeric")
        self.position_label.set_halign(Gtk.Align.START)
        self.position_label.set_hexpand(True)

        status_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=_SPACING
        )
        status_box.set_valign(Gtk.Align.CENTER)
        status_box.append(self.position_label)
        self._jog_grid.attach(status_box, 0, 4, 3, 1)

        # Action column (separate grid for extra gap)
        self.start_btn = create_button("send-symbolic", _("Start job"))
        self.start_btn.add_css_class("suggested-action")
        self.start_btn.connect("clicked", self._on_start_clicked)
        self._action_grid.attach(self.start_btn, 0, 0, 1, 1)

        self.pause_btn = create_button("pause-symbolic", _("Pause job"))
        self.pause_btn.connect("clicked", self._on_pause_clicked)
        self._action_grid.attach(self.pause_btn, 0, 1, 1, 1)

        self.stop_btn = create_button("stop-symbolic", _("Stop job"))
        self.stop_btn.add_css_class("destructive-action")
        self.stop_btn.connect("clicked", self._on_stop_clicked)
        self._action_grid.attach(self.stop_btn, 0, 2, 1, 1)

        self.z_plus_btn = create_button(
            "arrow-z-up-symbolic", _("Increase Z-Distance")
        )
        self._attach_hold(self.z_plus_btn, JogDirection.UP)
        self._action_grid.attach(self.z_plus_btn, 0, 3, 1, 1)

        self.z_minus_btn = create_button(
            "arrow-z-down-symbolic", _("Decrease Z-Distance")
        )
        self._attach_hold(self.z_minus_btn, JogDirection.DOWN)
        self._action_grid.attach(self.z_minus_btn, 0, 4, 1, 1)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        # A held jog key must never outlive the widget being usable.
        self.connect("map", self._on_mapped)
        self.connect("unmap", self._on_unmapped)

        self._update_button_sensitivity()

    @staticmethod
    def _button_caption(button) -> Gtk.Label:
        """The caption label of a button built with a label."""
        box = button.get_child()
        return next(c for c in box if isinstance(c, Gtk.Label))

    def _attach_hold(self, button, *directions: JogDirection):
        """
        Drive a jog button by press and release instead of by click.

        The button's own "clicked" signal is left unconnected: a click
        would double up with the gesture. Drivers without press-and-hold
        support fall back to a step jog on release.
        """
        self._button_directions[button] = directions

        gesture = Gtk.GestureClick()
        # Capture phase, so the press is seen before the button's own
        # internal click gesture can claim the sequence.
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesture.connect("pressed", self._on_jog_pressed, directions)
        gesture.connect("released", self._on_jog_released, directions)
        gesture.connect("cancel", self._on_jog_cancelled, directions)
        button.add_controller(gesture)

        # Dragging off the button must stop the motion too.
        motion = Gtk.EventControllerMotion()
        motion.connect("leave", self._on_jog_leave, directions)
        button.add_controller(motion)

    @staticmethod
    def _calc_grid_widths(height):
        cell_h = (height - (_ROWS - 1) * _SPACING) / _ROWS
        jog_w = 3 * cell_h + 2 * _SPACING
        act_w = cell_h
        return jog_w, act_w

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.WIDTH_FOR_HEIGHT

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            h = for_size if for_size > 0 else _MAX_HEIGHT
            jog_w, act_w = self._calc_grid_widths(h)
            total = int(jog_w)
            if self._show_actions:
                total += _GAP + int(act_w)
            return (total, total, -1, -1)
        m = self._jog_grid.measure(orientation, for_size)
        return (m[0], min(m[1], _MAX_HEIGHT), -1, -1)

    def do_size_allocate(self, width, height, baseline):
        jog_w, act_w = self._calc_grid_widths(height)

        if self._show_actions:
            total_needed = jog_w + _GAP + act_w
            if width > total_needed:
                extra = width - total_needed
                jog_w += extra * 3 / 4
                act_w += extra / 4
            act_w = int(act_w)
        else:
            jog_w = width

        jog_w = int(jog_w)

        self._jog_grid.allocate(jog_w, height, baseline, None)

        if self._show_actions:
            transform = Gsk.Transform().translate(
                Graphene.Point().init(jog_w + _GAP, 0)
            )
            self._action_grid.allocate(act_w, height, baseline, transform)
        else:
            self._action_grid.allocate(0, 0, -1, None)

    def set_machine(
        self, machine: Machine | None, machine_cmd: MachineCmd | None
    ):
        """Set the machine this widget controls."""
        if self.machine:
            self.machine.state_changed.disconnect(
                self._on_machine_state_changed
            )
            self.machine.connection_status_changed.disconnect(
                self._on_connection_status_changed
            )
            self.machine.changed.disconnect(self._on_machine_changed)
        if self.machine_cmd:
            self.machine_cmd.document_settled.disconnect(
                self._on_document_settled
            )

        self._release_all_jog_keys()

        self.machine = machine
        self.machine_cmd = machine_cmd
        if self.machine_cmd:
            self.machine_cmd.document_settled.connect(
                self._on_document_settled
            )

        if self.machine:
            self.machine.state_changed.connect(self._on_machine_state_changed)
            self.machine.connection_status_changed.connect(
                self._on_connection_status_changed
            )
            self.machine.changed.connect(self._on_machine_changed)

        self._update_button_sensitivity()
        self._update_limit_status()
        self._update_position()

    def _on_machine_changed(self, sender, **kwargs):
        self._update_button_sensitivity()
        self._update_limit_status()

    def _jog_deltas(self, *directions: JogDirection) -> dict[Axis, float]:
        """Aggregate native-axis deltas for one or more visual
        directions."""
        if not self.machine:
            return {}
        deltas: dict[Axis, float] = {}
        for direction in directions:
            for axis, delta in self.machine.panel.calculate_jog(
                direction, self.jog_distance
            ).items():
                deltas[axis] = deltas.get(axis, 0.0) + delta
        return deltas

    def _can_jog_direction(self, direction: JogDirection) -> bool:
        """Whether the machine can jog every axis a direction drives."""
        if not self.machine:
            return False
        return all(
            self.machine.can_jog(axis) for axis in self._jog_deltas(direction)
        )

    def _update_button_sensitivity(self):
        """Update button sensitivity based on machine capabilities."""
        # Default all buttons to disabled
        self.east_btn.set_sensitive(False)
        self.west_btn.set_sensitive(False)
        self.north_btn.set_sensitive(False)
        self.south_btn.set_sensitive(False)
        self.north_east_btn.set_sensitive(False)
        self.north_west_btn.set_sensitive(False)
        self.south_east_btn.set_sensitive(False)
        self.south_west_btn.set_sensitive(False)
        self.z_plus_btn.set_sensitive(False)
        self.z_minus_btn.set_sensitive(False)
        self.home_all_btn.set_sensitive(False)
        self.go_scale_btn.set_sensitive(False)
        self.cut_scale_btn.set_sensitive(False)
        self.start_btn.set_sensitive(False)
        self.pause_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(False)

        # Only enable buttons if machine exists, is connected
        if self.machine is None or not self.machine.is_connected():
            return

        # Jog buttons - a direction is joggable when every native axis it
        # drives is supported (under rotation a visual axis may map to
        # the orthogonal native axis)
        can_jog_east = self._can_jog_direction(JogDirection.EAST)
        can_jog_west = self._can_jog_direction(JogDirection.WEST)
        can_jog_north = self._can_jog_direction(JogDirection.NORTH)
        can_jog_south = self._can_jog_direction(JogDirection.SOUTH)
        self.east_btn.set_sensitive(can_jog_east)
        self.west_btn.set_sensitive(can_jog_west)
        self.north_btn.set_sensitive(can_jog_north)
        self.south_btn.set_sensitive(can_jog_south)

        # Diagonal buttons - need both cardinal directions
        self.north_east_btn.set_sensitive(can_jog_east and can_jog_north)
        self.north_west_btn.set_sensitive(can_jog_west and can_jog_north)
        self.south_east_btn.set_sensitive(can_jog_east and can_jog_south)
        self.south_west_btn.set_sensitive(can_jog_west and can_jog_south)

        self.z_plus_btn.set_sensitive(self._can_jog_direction(JogDirection.UP))
        self.z_minus_btn.set_sensitive(
            self._can_jog_direction(JogDirection.DOWN)
        )

        self.home_all_btn.set_sensitive(True)
        self._update_scale_buttons()

        # Job controls - always enabled when connected
        self.start_btn.set_sensitive(True)
        self.pause_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(True)

        self._update_limit_status()

    def _update_limit_status(self):
        """Update button styling based on whether jog would exceed limits."""
        if not self.machine or not self.machine.is_connected():
            return

        machine = self.machine

        buttons = [
            self.east_btn,
            self.west_btn,
            self.north_btn,
            self.south_btn,
            self.z_plus_btn,
            self.z_minus_btn,
            self.north_east_btn,
            self.north_west_btn,
            self.south_east_btn,
            self.south_west_btn,
        ]
        for button in buttons:
            button.remove_css_class("warning")
            button.remove_css_class("destructive-action")

        if not machine.soft_limits_enabled:
            return

        def exceeds(*directions: JogDirection) -> bool:
            if not self.machine:
                return False
            return any(
                self.machine.would_jog_exceed_limits(axis, delta)
                for axis, delta in self._jog_deltas(*directions).items()
            )

        if exceeds(JogDirection.EAST):
            self.east_btn.add_css_class("warning")
        if exceeds(JogDirection.WEST):
            self.west_btn.add_css_class("warning")
        if exceeds(JogDirection.NORTH):
            self.north_btn.add_css_class("warning")
        if exceeds(JogDirection.SOUTH):
            self.south_btn.add_css_class("warning")
        if exceeds(JogDirection.UP):
            self.z_plus_btn.add_css_class("warning")
        if exceeds(JogDirection.DOWN):
            self.z_minus_btn.add_css_class("warning")

        # Diagonal buttons
        if exceeds(JogDirection.EAST, JogDirection.NORTH):
            self.north_east_btn.add_css_class("warning")
        if exceeds(JogDirection.WEST, JogDirection.NORTH):
            self.north_west_btn.add_css_class("warning")
        if exceeds(JogDirection.EAST, JogDirection.SOUTH):
            self.south_east_btn.add_css_class("warning")
        if exceeds(JogDirection.WEST, JogDirection.SOUTH):
            self.south_west_btn.add_css_class("warning")

    def _hold_jog_supported(self) -> bool:
        """Whether the connected driver jogs while a key is held."""
        if not self.machine or not self.machine.is_connected():
            return False
        driver = self.machine.driver
        return bool(driver) and driver.can_hold_jog()

    def _jog_keys(self, *directions: JogDirection) -> list[tuple[str, int]]:
        """Native axis/sign pairs for one or more visual directions."""
        keys = []
        for axis, delta in self._jog_deltas(*directions).items():
            if delta and axis.name:
                keys.append((axis.name.lower(), 1 if delta > 0 else -1))
        return keys

    def _press_jog_key(self, key: tuple[str, int]):
        if key in self._keys_down:
            return
        if not self.machine or not self.machine_cmd:
            return
        self._keys_down.add(key)
        self.machine_cmd.jog_key_down(self.machine, key[0], key[1])

    def _release_jog_key(self, key: tuple[str, int]):
        if key not in self._keys_down:
            return
        self._keys_down.discard(key)
        if self.machine and self.machine_cmd:
            self.machine_cmd.jog_key_up(self.machine, key[0], key[1])

    def _release_all_jog_keys(self):
        """
        Release every key this widget believes is held down.

        Called from every path where a key-up could otherwise be lost:
        pointer leave, gesture cancel, unmap, and window focus loss.
        """
        self._cancel_pending_hold()
        keys = sorted(self._keys_down)
        self._keys_down.clear()
        if not self.machine or not self.machine_cmd:
            return
        for axis, direction in keys:
            self.machine_cmd.jog_key_up(self.machine, axis, direction)
        # Sweep whatever the driver still believes is held, in case the
        # two views of the held keys ever drift apart.
        self.machine_cmd.release_all_jog_keys(self.machine)

    def _cancel_pending_hold(self) -> bool:
        """Drop an armed hold. True when one was still pending."""
        if self._hold_timeout_id is None:
            return False
        GLib.source_remove(self._hold_timeout_id)
        self._hold_timeout_id = None
        return True

    def _start_hold(self, directions: tuple[JogDirection, ...]):
        """Hand the held directions to the driver's repeat jog."""
        self._hold_timeout_id = None
        for key in self._jog_keys(*directions):
            self._press_jog_key(key)
        return GLib.SOURCE_REMOVE

    def _on_jog_pressed(self, gesture, n_press, x, y, directions):
        if not self._hold_jog_supported():
            return
        self._cancel_pending_hold()
        self._hold_timeout_id = GLib.timeout_add(
            _HOLD_START_DELAY_MS, self._start_hold, directions
        )

    def _on_jog_released(self, gesture, n_press, x, y, directions):
        # A press too short to become a hold is a click: one step of the
        # step-size control. Drivers without hold support always land
        # here, which keeps step jog working for them.
        if self._cancel_pending_hold() or not self._hold_jog_supported():
            self._perform_visual_jog(*directions)
            return
        for key in self._jog_keys(*directions):
            self._release_jog_key(key)

    def _on_jog_cancelled(self, gesture, sequence, directions):
        self._cancel_pending_hold()
        for key in self._jog_keys(*directions):
            self._release_jog_key(key)

    def _on_jog_leave(self, controller, directions):
        self._cancel_pending_hold()
        for key in self._jog_keys(*directions):
            self._release_jog_key(key)

    def _on_mapped(self, widget):
        root = self.get_root()
        if not isinstance(root, Gtk.Window):
            return
        if self._root_active_handler is None:
            self._root_active_handler = root.connect(
                "notify::is-active", self._on_root_active_changed
            )

    def _on_unmapped(self, widget):
        root = self.get_root()
        if isinstance(root, Gtk.Window) and self._root_active_handler:
            root.disconnect(self._root_active_handler)
        self._root_active_handler = None
        self._release_all_jog_keys()

    def _on_root_active_changed(self, root, pspec):
        if not root.is_active():
            self._release_all_jog_keys()

    def set_jog_speed(self, speed_mm_s: int):
        """Set the jog speed in mm/s and push it to the driver."""
        self.jog_speed = int(speed_mm_s)
        if self._jog_speed_timeout_id is not None:
            GLib.source_remove(self._jog_speed_timeout_id)
        self._jog_speed_timeout_id = GLib.timeout_add(
            _JOG_SPEED_DEBOUNCE_MS, self._commit_jog_speed
        )

    def _commit_jog_speed(self):
        """Push the settled jog speed to the driver."""
        self._jog_speed_timeout_id = None
        if self._hold_jog_supported() and self.machine and self.machine_cmd:
            self.machine_cmd.set_jog_speed(
                self.machine,
                int(_JOG_SPEED_UNIT.to_base(self.jog_speed)),
            )
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _format_position(pos) -> str:
        """Render a machine position, or dashes where it is unknown."""

        def axis(value) -> str:
            return "—" if value is None else f"{value:.1f}"

        x, y = (pos[0], pos[1]) if pos else (None, None)
        return f"X {axis(x)}  Y {axis(y)}"

    def _update_position(self):
        """Show the last polled machine position."""
        pos = self.machine.device_state.machine_pos if self.machine else None
        self.position_label.set_label(self._format_position(pos))

    def _on_machine_state_changed(self, machine, state):
        """Handle machine state changes to update limit status."""
        self._update_limit_status()
        self._update_position()

    def _on_connection_status_changed(self, sender, **kwargs):
        """Handle connection status changes to update button sensitivity."""
        if self.machine and not self.machine.is_connected():
            # Nothing can be sent any more; the driver releases its own
            # held keys as it tears the transports down.
            self._cancel_pending_hold()
            self._keys_down.clear()
        self._update_button_sensitivity()

    def _perform_jog(self, deltas: dict[Axis, float]):
        """
        Helper to jog multiple axes simultaneously by sending a single
        command dictionary.
        """
        if not self.machine or not self.machine_cmd:
            return

        if deltas:
            # jog_speed is in display units; Driver.jog takes base
            # units.
            self.machine_cmd.jog(
                self.machine,
                deltas,
                int(_JOG_SPEED_UNIT.to_base(self.jog_speed)),
            )

    def _perform_visual_jog(self, *directions: JogDirection):
        """Jog according to one or more visual directions."""
        if not self.machine:
            return
        self._perform_jog(self._jog_deltas(*directions))

    def _on_x_plus_clicked(self, button):
        """Handle Right (East) button click."""
        self._perform_visual_jog(JogDirection.EAST)

    def _on_x_minus_clicked(self, button):
        """Handle Left (West) button click."""
        self._perform_visual_jog(JogDirection.WEST)

    def _on_y_plus_clicked(self, button):
        """Handle Away (North) button click."""
        self._perform_visual_jog(JogDirection.NORTH)

    def _on_y_minus_clicked(self, button):
        """Handle Toward (South) button click."""
        self._perform_visual_jog(JogDirection.SOUTH)

    def _on_z_plus_clicked(self, button):
        """Handle Up button click."""
        self._perform_visual_jog(JogDirection.UP)

    def _on_z_minus_clicked(self, button):
        """Handle Down button click."""
        self._perform_visual_jog(JogDirection.DOWN)

    def _on_x_plus_y_plus_clicked(self, button):
        """Handle Right-Away diagonal button click."""
        self._perform_visual_jog(JogDirection.EAST, JogDirection.NORTH)

    def _on_x_minus_y_plus_clicked(self, button):
        """Handle Left-Away diagonal button click."""
        self._perform_visual_jog(JogDirection.WEST, JogDirection.NORTH)

    def _on_x_plus_y_minus_clicked(self, button):
        """Handle Right-Toward diagonal button click."""
        self._perform_visual_jog(JogDirection.EAST, JogDirection.SOUTH)

    def _on_x_minus_y_minus_clicked(self, button):
        """Handle Left-Toward diagonal button click."""
        self._perform_visual_jog(JogDirection.WEST, JogDirection.SOUTH)

    def _can_run_scale(self) -> bool:
        """Whether a scale run could be started right now."""
        if not self.machine or not self.machine.is_connected():
            return False
        return bool(self.machine_cmd and self.machine_cmd.has_job_ops)

    def _update_scale_buttons(self):
        """Reflect the running state in the two scale buttons."""
        if self._scaling:
            self._go_scale_caption.set_label(_("Stop"))
            self.go_scale_btn.set_tooltip_text(_("Stop the running scale"))
            self.go_scale_btn.add_css_class("destructive-action")
            self.go_scale_btn.set_sensitive(True)
            self.cut_scale_btn.set_sensitive(False)
            return

        self._go_scale_caption.set_label(_("Go Scale"))
        self.go_scale_btn.set_tooltip_text(
            _("Traverse the job outline with the laser off")
        )
        self.go_scale_btn.remove_css_class("destructive-action")
        can_run = self._can_run_scale()
        self.go_scale_btn.set_sensitive(can_run)
        self.cut_scale_btn.set_sensitive(can_run)

    def _on_go_scale_clicked(self, button):
        """Handle Go Scale: start, or stop while running."""
        if not self.machine or not self.machine_cmd:
            return

        if self._scaling:
            self.machine_cmd.cancel_job(self.machine)
            return

        self._scaling = True
        self._update_scale_buttons()
        self.machine_cmd.run_go_scale(
            self.machine, on_done=self._on_scale_done
        )

    def _on_cut_scale_clicked(self, button):
        """Handle Cut Scale: ask for speed and power, then cut."""
        if not self.machine or not self.machine_cmd or self._scaling:
            return

        machine = self.machine
        machine_cmd = self.machine_cmd

        def confirm(speed: int, power: float):
            self._scaling = True
            self._update_scale_buttons()
            machine_cmd.run_cut_scale(
                machine, speed, power, on_done=self._on_scale_done
            )

        dialog = CutScaleDialog(
            machine_cmd.first_layer_power() * 100.0, confirm
        )
        root = self.get_root()
        if isinstance(root, Gtk.Window):
            dialog.set_transient_for(root)
        dialog.present()

    def _on_scale_done(self):
        """The scale run finished, was cancelled, or failed."""
        self._scaling = False
        self._update_scale_buttons()

    def _on_document_settled(self, sender, **kwargs):
        """A document with no ops has no outline to scale."""
        self._update_scale_buttons()

    def _on_home_all_clicked(self, button):
        """Handle Home machine button click."""
        if self.machine and self.machine_cmd:
            self.machine_cmd.home(self.machine)

    def _on_start_clicked(self, button):
        """Handle Start button click."""
        if self.machine and self.machine_cmd:
            self.machine_cmd.run_send_job(self.machine)

    def _on_pause_clicked(self, button):
        """Handle Pause button click."""
        if self.machine and self.machine_cmd:
            self.machine_cmd.set_hold(self.machine, True)

    def _on_stop_clicked(self, button):
        """Handle Stop button click."""
        if self.machine and self.machine_cmd:
            self.machine_cmd.cancel_job(self.machine)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press events for cursor key jogging."""
        if not self.machine or not self.machine.is_connected():
            return False

        # Map cursor keys to jog actions
        if keyval == Gdk.KEY_Up:
            self._on_y_plus_clicked(None)  # Away
            return True
        elif keyval == Gdk.KEY_Down:
            self._on_y_minus_clicked(None)  # Toward
            return True
        elif keyval == Gdk.KEY_Left:
            self._on_x_minus_clicked(None)  # Left
            return True
        elif keyval == Gdk.KEY_Right:
            self._on_x_plus_clicked(None)  # Right
            return True
        elif keyval == Gdk.KEY_Page_Up:
            self._on_z_plus_clicked(None)  # Up
            return True
        elif keyval == Gdk.KEY_Page_Down:
            self._on_z_minus_clicked(None)  # Down
            return True

        return False

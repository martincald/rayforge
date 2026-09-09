from gettext import gettext as _
from typing import TYPE_CHECKING

from blinker import Signal
from gi.repository import Gtk, Pango

from ...context import get_context
from ...core.step import Step
from ...core.undo.property_cmd import ChangePropertyCommand
from ..layout import SPACE_CONTROL, SPACE_GROUP, SPACE_TIGHT, icon_button
from ..shared.number_badge import NumberBadge
from ..shared.tag import TagWidget
from .step_settings.dialog import StepSettingsDialog

if TYPE_CHECKING:
    from ...doceditor.editor import DocEditor


class StepBox(Gtk.Box):
    def __init__(
        self,
        editor: "DocEditor",
        step: Step,
        step_number: int = 0,
    ):
        super(
            ).__init__(orientation=Gtk.Orientation.HORIZONTAL,
            spacing=SPACE_GROUP,
        )
        self.set_margin_start(SPACE_TIGHT)
        self.set_margin_end(SPACE_TIGHT)
        self.set_margin_top(SPACE_TIGHT)
        self.set_margin_bottom(SPACE_TIGHT)
        self.editor = editor
        self.doc = editor.doc
        self.step = step
        self.step_number = step_number
        self.delete_clicked = Signal()

        self.badge = NumberBadge(step_number)
        self.badge.set_valign(Gtk.Align.CENTER)
        self.append(self.badge)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.set_hexpand(True)
        content.set_valign(Gtk.Align.CENTER)
        self.append(content)

        title_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=SPACE_CONTROL,
        )
        content.append(title_row)

        self.title_label = Gtk.Label(xalign=0)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.set_max_width_chars(40)
        self.title_label.set_hexpand(True)
        title_row.append(self.title_label)

        self.mode_tag = TagWidget(active=False)
        self.mode_tag_label = Gtk.Label()
        self.mode_tag.append(self.mode_tag_label)
        title_row.append(self.mode_tag)

        self.subtitle_label = Gtk.Label(xalign=0)
        self.subtitle_label.add_css_class("sc-caption")
        self.subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.subtitle_label.set_max_width_chars(40)
        self.subtitle_label.set_hexpand(True)
        content.append(self.subtitle_label)

        self.visibility_switch = Gtk.Switch()
        self.visibility_switch.set_active(step.visible)
        self.visibility_switch.set_valign(Gtk.Align.CENTER)
        self.append(self.visibility_switch)
        self.visibility_switch.connect("state-set", self.on_switch_state_set)

        button = icon_button("settings-symbolic", _("Step settings"))
        self.append(button)
        button.connect("clicked", self.on_button_properties_clicked)

        button = icon_button("delete-symbolic", _("Delete this step"))
        self.append(button)
        button.connect("clicked", self.on_button_delete_clicked)

        self.step.updated.connect(self.on_step_changed)
        self.step.visibility_changed.connect(self.on_step_changed)
        get_context().config.changed.connect(self.on_step_changed)
        self.on_step_changed(self.step)

    def do_destroy(self):
        """Overrides GObject.Object.do_destroy to disconnect signals."""
        self.step.updated.disconnect(self.on_step_changed)
        self.step.visibility_changed.disconnect(self.on_step_changed)
        get_context().config.changed.disconnect(self.on_step_changed)

    def set_step_number(self, number: int):
        self.step_number = number
        self.badge.set_number(number)

    def on_step_changed(self, sender, **kwargs):
        self.title_label.set_text(self.step.name)
        self.subtitle_label.set_text(self.step.get_summary())

        mode = self.step.get_operation_mode_short()
        if mode:
            self.mode_tag.set_visible(True)
            self.mode_tag_label.set_text(mode)
        else:
            self.mode_tag.set_visible(False)

        is_visible = self.step.visible
        self.visibility_switch.set_active(is_visible)
        self.badge.set_dimmed(not is_visible)
        self._update_badge_color()

    def _update_badge_color(self):
        if not self.step.visible:
            self.badge.set_color(None)
            return

        machine = get_context().machine
        if not machine or not machine.heads:
            self.badge.set_color(None)
            return
        head = self.step.get_selected_head(machine)
        color = self.step.get_operation_color(head) if head else None
        self.badge.set_color(color)

    def on_switch_state_set(self, switch, state):
        command = ChangePropertyCommand(
            target=self.step,
            property_name="visible",
            new_value=state,
            setter_method_name="set_visible",
            name=_("Toggle step visibility"),
        )
        self.doc.history_manager.execute(command)

    def on_button_properties_clicked(self, button):
        StepSettingsDialog.present_for_step(
            self.editor, self.step, self.get_root()
        )

    def on_button_delete_clicked(self, button):
        self.delete_clicked.send(self, step=self.step)

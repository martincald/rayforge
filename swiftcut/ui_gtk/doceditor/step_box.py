from gettext import gettext as _
from typing import TYPE_CHECKING

from blinker import Signal
from gi.repository import Adw, Gtk, Pango

from ...context import get_context
from ...core.step import Step
from ...core.undo.property_cmd import ChangePropertyCommand
from ..layout import COMPACT_SPACE_CONTROL, icon_button
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
        # The head line is one compact row and the summary sits under
        # it: the row's own height already leaves air below the name.
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.editor = editor
        self.doc = editor.doc
        self.step = step
        self.step_number = step_number
        self.delete_clicked = Signal()

        # The name and its mode at the start, the step's controls at the
        # end. Too narrow for both, the controls wrap onto a line of
        # their own instead of cutting the name short.
        self.head = Adw.WrapBox(
            child_spacing=COMPACT_SPACE_CONTROL,
            line_spacing=COMPACT_SPACE_CONTROL,
            justify=Adw.JustifyMode.SPREAD,
            justify_last_line=True,
        )
        self.append(self.head)

        self.label_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=COMPACT_SPACE_CONTROL,
        )
        self.label_box.set_valign(Gtk.Align.CENTER)
        self.head.append(self.label_box)

        self.badge = NumberBadge(step_number)
        self.badge.set_valign(Gtk.Align.CENTER)
        self.label_box.append(self.badge)

        # A renamed step can be long: it wraps rather than overflow.
        self.title_label = Gtk.Label(xalign=0)
        self.title_label.set_wrap(True)
        self.title_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.label_box.append(self.title_label)

        self.mode_tag = TagWidget(active=False)
        self.mode_tag.set_valign(Gtk.Align.CENTER)
        self.mode_tag_label = Gtk.Label()
        self.mode_tag.append(self.mode_tag_label)
        self.label_box.append(self.mode_tag)

        # On a line of its own, the controls stay at the end, in the
        # same column as every other step's.
        self.actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=COMPACT_SPACE_CONTROL,
        )
        self.actions.set_halign(Gtk.Align.END)
        self.head.append(self.actions)

        self.visibility_switch = Gtk.Switch()
        self.visibility_switch.set_active(step.visible)
        self.visibility_switch.set_valign(Gtk.Align.CENTER)
        self.actions.append(self.visibility_switch)
        self.visibility_switch.connect("state-set", self.on_switch_state_set)

        button = icon_button("settings-symbolic", _("Step settings"))
        self.actions.append(button)
        button.connect("clicked", self.on_button_properties_clicked)

        button = icon_button("delete-symbolic", _("Delete this step"))
        self.actions.append(button)
        button.connect("clicked", self.on_button_delete_clicked)

        # The summary has the row's whole width, and wraps rather than
        # being cut short.
        self.subtitle_label = Gtk.Label(xalign=0)
        self.subtitle_label.add_css_class("sc-caption")
        self.subtitle_label.set_hexpand(True)
        self.subtitle_label.set_wrap(True)
        self.subtitle_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.append(self.subtitle_label)

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

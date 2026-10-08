from gettext import gettext as _

from gi.repository import Adw, Gtk

from ...machine.cmd import MachineCmd
from ...machine.models.machine import Machine


class LaserControlWidget(Gtk.Box):
    """Widget for the controller's own Z focus routine."""

    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kwargs)

        self.machine: Machine | None = None
        self.machine_cmd: MachineCmd | None = None

        self._group = Adw.PreferencesGroup()
        self._group.add_css_class("compact")

        self._focus_btn = Gtk.Button(label=_("Focus"))
        self._focus_btn.set_valign(Gtk.Align.CENTER)
        self._focus_btn.set_tooltip_text(
            _("Run the controller's Z focus routine")
        )
        self._focus_btn.set_action_name("win.machine-focus-z")
        self._focus_row = Adw.ActionRow(title=_("Focus Z"))
        self._focus_row.set_subtitle(_("The controller's own Z focus"))
        self._focus_row.add_suffix(self._focus_btn)
        self._group.add(self._focus_row)

        self.append(self._group)

    def set_machine(
        self, machine: Machine | None, machine_cmd: MachineCmd | None
    ):
        self.machine = machine
        self.machine_cmd = machine_cmd

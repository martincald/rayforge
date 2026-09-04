from gi.repository import Adw, Gdk, Gtk

from .keyboard import is_primary_modifier

"""
PatchedDialogWindow:
A replacement for Adw.Window that fixes wrong window
being focused when a dialog is closed on windows.
See:
https://bugzilla.gnome.org/show_bug.cgi?id=112404
& https://gitlab.gnome.org/GNOME/gtk/-/issues/7313
"""


class PatchedDialogWindow(Adw.Window):
    def __init__(self, skip_usage_tracking: bool = False, **kwargs):
        super().__init__(**kwargs)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape or (
            is_primary_modifier(state) and keyval == Gdk.KEY_w
        ):
            self.close()
            return True
        return False

    def do_close_request(self, *args) -> bool:
        parent = self.get_transient_for()
        # Focus the original parent
        if parent:
            parent.present()
        # Let GTK close the window
        return False


class PatchedMessageDialog(Adw.MessageDialog):
    def __init__(self, skip_usage_tracking: bool = False, **kwargs):
        super().__init__(**kwargs)

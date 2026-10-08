from gettext import gettext as _

from gi.repository import Adw, Gtk

from ..context import get_context
from ..core.config import Config
from .layout import SPACE_CONTROL, SPACE_GROUP, SPACE_PAGE
from .machine.connection_status_widget import ConnectionStatusWidget
from .shared.patched_dialog_window import PatchedDialogWindow


def should_show_getting_started(config: Config, scripted: bool) -> bool:
    """
    Whether the first-run guide opens by itself as the window maps.

    Once, until it is closed; never in a scripted run (--uiscript,
    --exit), which nobody is there to close.
    """
    return not (
        scripted
        or config.getting_started_seen
        or get_context().exit_after_settle
    )


class GettingStartedWindow(PatchedDialogWindow):
    """
    The first-run guide: connect the laser, open or draw something,
    then Go Scale and Start. Closing it, however it is closed, marks
    it seen.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title(_("Getting Started"))
        self.set_default_size(440, -1)

        # The live state of the active machine; a machine switch
        # rebinds it.
        self.connection_status = ConnectionStatusWidget()
        self._bound_machine = None
        self._bind_machine()
        get_context().config.changed.connect(self._on_config_changed)

        self.open_button = Gtk.Button(label=_("Open…"))
        self.open_button.set_halign(Gtk.Align.START)
        self.open_button.connect("clicked", self._on_open_clicked)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_GROUP
        )
        content.set_margin_start(SPACE_PAGE)
        content.set_margin_end(SPACE_PAGE)
        content.set_margin_top(SPACE_GROUP)
        content.set_margin_bottom(SPACE_PAGE)
        content.append(
            self._card(
                _("1. Connect by USB"),
                _(
                    "Plug the laser's USB cable into this computer and "
                    "switch the laser on. SwiftCut connects by itself."
                ),
                self.connection_status,
            )
        )
        content.append(
            self._card(
                _("2. Open or draw something"),
                _(
                    "Open an SVG or DXF drawing, or draw your own in the "
                    "Sketcher (Object > New Sketch)."
                ),
                self.open_button,
            )
        )
        content.append(
            self._card(
                _("3. Press Go Scale, then Start"),
                _(
                    "Go Scale traces the outline of your design with the "
                    "laser off, so you can check where it will cut. Then "
                    "press Start to run the job."
                ),
            )
        )

        done = Gtk.Button(label=_("Got It"))
        done.add_css_class("suggested-action")
        done.set_halign(Gtk.Align.END)
        done.connect("clicked", lambda button: self.close())
        content.append(done)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        toolbar_view.set_content(content)
        self.set_content(toolbar_view)

        self.connect("close-request", self._on_close_request)

    @staticmethod
    def _card(
        title: str, body: str, widget: Gtk.Widget | None = None
    ) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("card")
        inner = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_CONTROL
        )
        inner.set_margin_start(SPACE_GROUP)
        inner.set_margin_end(SPACE_GROUP)
        inner.set_margin_top(SPACE_GROUP)
        inner.set_margin_bottom(SPACE_GROUP)
        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class("sc-title")
        inner.append(heading)
        text = Gtk.Label(label=body, xalign=0, wrap=True)
        inner.append(text)
        if widget is not None:
            inner.append(widget)
        card.append(inner)
        return card

    def _bind_machine(self):
        machine = get_context().config.machine
        if machine is self._bound_machine:
            return
        self._bound_machine = machine
        self.connection_status.set_machine(machine)

    def _on_config_changed(self, sender, **kwargs):
        self._bind_machine()

    def _on_open_clicked(self, button):
        # The guide is not inside the main window, so its actions are
        # reached through the window it belongs to.
        parent = self.get_transient_for()
        if parent is not None:
            parent.activate_action("win.import", None)

    def _on_close_request(self, window) -> bool:
        get_context().config.set_getting_started_seen(True)
        get_context().config.changed.disconnect(self._on_config_changed)
        self.connection_status.set_machine(None)
        self._bound_machine = None
        return False

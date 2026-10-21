from gettext import gettext as _
from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk

from ...context import get_context
from ...core.config import TOUR_COMPLETED, TOUR_SEEN
from ..layout import SPACE_GROUP, SPACE_PAGE
from ..shared.patched_dialog_window import PatchedDialogWindow
from .content import TOURS

if TYPE_CHECKING:
    from ..mainwindow import MainWindow

_STATES = {
    TOUR_COMPLETED: _("Completed"),
    TOUR_SEEN: _("Skipped part way"),
}


class ToursWindow(PatchedDialogWindow):
    """
    Help > Tours: every guided tour, how far it got, and a Start that
    closes this list and plays it over the main window.
    """

    def __init__(self, win: "MainWindow", **kwargs):
        super().__init__(**kwargs)
        self._win = win
        self.set_title(_("Tours"))
        self.set_default_size(420, -1)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.list.set_margin_start(SPACE_PAGE)
        self.list.set_margin_end(SPACE_PAGE)
        self.list.set_margin_top(SPACE_GROUP)
        self.list.set_margin_bottom(SPACE_PAGE)
        self.start_buttons: dict[str, Gtk.Button] = {}
        tours = get_context().config.tours
        for tour in TOURS.values():
            row = Adw.ActionRow(
                title=tour.title,
                subtitle=_STATES.get(tours.get(tour.id), _("Not taken yet")),
            )
            start = Gtk.Button(label=_("Start"), valign=Gtk.Align.CENTER)
            start.connect("clicked", self._on_start_clicked, tour.id)
            row.add_suffix(start)
            self.start_buttons[tour.id] = start
            self.list.append(row)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        toolbar_view.set_content(self.list)
        self.set_content(toolbar_view)

    def _on_start_clicked(self, button, tour_id: str):
        self.close()
        self._win.activate_action(
            "win.start-tour", GLib.Variant.new_string(tour_id)
        )

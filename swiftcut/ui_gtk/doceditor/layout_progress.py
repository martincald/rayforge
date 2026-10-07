from gettext import gettext as _

from gi.repository import Gtk

from ...doceditor.layout_cmd import AUTO_LAYOUT_KEY
from ..layout import SPACE_CONTROL, SPACE_GROUP


class LayoutProgress(Gtk.Box):
    """
    A running Auto Layout's progress and a Cancel button for it. Hidden
    while no Auto Layout runs.
    """

    def __init__(self, task_mgr):
        super().__init__(spacing=SPACE_CONTROL)
        self.task_mgr = task_mgr
        self.set_margin_start(SPACE_GROUP)
        self.set_valign(Gtk.Align.CENTER)

        label = Gtk.Label(label=_("Auto Layout"))
        label.add_css_class("sc-caption")
        self.append(label)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_valign(Gtk.Align.CENTER)
        self.progress_bar.set_size_request(120, -1)
        self.append(self.progress_bar)

        self.cancel_button = Gtk.Button(label=_("Cancel"))
        self.cancel_button.set_tooltip_text(
            _("Stop the Auto Layout without moving anything")
        )
        self.cancel_button.connect("clicked", self._on_cancel_clicked)
        self.append(self.cancel_button)

        self.set_visible(False)
        self.task_mgr.tasks_updated.connect(self._on_tasks_updated)

    def _on_tasks_updated(self, sender, tasks, progress):
        task = next((t for t in tasks if t.key == AUTO_LAYOUT_KEY), None)
        self.set_visible(task is not None)
        if task is not None:
            self.progress_bar.set_fraction(task.get_progress())

    def _on_cancel_clicked(self, button):
        self.task_mgr.cancel_task(AUTO_LAYOUT_KEY)

from collections.abc import Callable
from gettext import gettext as _
from gettext import ngettext
from typing import TYPE_CHECKING, Any

from gi.repository import Adw, Gtk, Pango

from ...context import get_context
from ...doceditor.job_history import JobHistoryEntry
from ...shared.units.formatter import format_value
from ...shared.util.time_format import format_clock
from ..layout import (
    SPACE_CONTROL,
    SPACE_GROUP,
    SPACE_PAGE,
    SPACE_TIGHT,
    scaled,
)
from ..shared.patched_dialog_window import PatchedDialogWindow

if TYPE_CHECKING:
    from ...machine.models.machine import Machine
    from ..mainwindow import MainWindow

# The stored thumbnail is up to 200 px; the list shows it smaller.
THUMBNAIL_SIZE = scaled(96)


def step_summary(layer: str, step: dict[str, Any]) -> str:
    """One step of a recorded job, as the list shows it."""
    parts = [f"{layer}: {step['type']}", format_value(step["speed"], "speed")]
    if "power" in step:
        parts.append(_("Max {p}%").format(p=round(step["power"] * 100)))
    if "min_power" in step:
        parts.append(_("Min {p}%").format(p=round(step["min_power"] * 100)))
    if "passes" in step:
        passes = step["passes"]
        parts.append(
            ngettext("{n} pass", "{n} passes", passes).format(n=passes)
        )
    return " · ".join(parts)


class JobHistoryWindow(PatchedDialogWindow):
    """
    Machine > Job History: the active machine's last jobs, newest
    first, to load again or run again.
    """

    def __init__(self, win: "MainWindow", **kwargs):
        super().__init__(**kwargs)
        self._win = win
        self._history = win.job_history
        self._machine: Machine | None = None
        self._run_buttons: list[tuple[JobHistoryEntry, Gtk.Button]] = []
        self.set_title(_("Job History"))
        self.set_default_size(560, 640)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.list.set_valign(Gtk.Align.START)
        self.list.set_margin_start(SPACE_PAGE)
        self.list.set_margin_end(SPACE_PAGE)
        self.list.set_margin_top(SPACE_GROUP)
        self.list.set_margin_bottom(SPACE_PAGE)
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(self.list)

        self.empty = Adw.StatusPage(
            title=_("No Jobs Yet"),
            description=_("Jobs run on this machine show up here."),
        )
        self.stack = Gtk.Stack()
        self.stack.add_named(scrolled, "list")
        self.stack.add_named(self.empty, "empty")

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        toolbar_view.set_content(self.stack)
        self.set_content(toolbar_view)

        get_context().config.changed.connect(self._on_config_changed)
        self._history.changed.connect(self._on_history_changed)
        win.machine_cmd.job_state_changed.connect(self._on_job_state_changed)
        self.connect("close-request", self._on_close_request)
        self._bind_machine()
        self.refresh()

    def refresh(self):
        """Lists the active machine's jobs again."""
        self.list.remove_all()
        self._run_buttons = []
        machine = self._machine
        entries = self._history.entries(machine.name) if machine else []
        for entry in entries:
            self.list.append(self._row(entry))
        self.stack.set_visible_child_name("list" if entries else "empty")
        self._update_run_buttons()

    def _row(self, entry: JobHistoryEntry) -> Gtk.Widget:
        box = Gtk.Box(spacing=SPACE_GROUP)
        box.set_margin_start(SPACE_GROUP)
        box.set_margin_end(SPACE_GROUP)
        box.set_margin_top(SPACE_GROUP)
        box.set_margin_bottom(SPACE_GROUP)

        if entry.thumbnail_path is not None:
            thumbnail = Gtk.Picture.new_for_filename(str(entry.thumbnail_path))
            thumbnail.set_content_fit(Gtk.ContentFit.CONTAIN)
        else:
            thumbnail = Gtk.Box()
        thumbnail.set_size_request(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        thumbnail.set_valign(Gtk.Align.START)
        box.append(thumbnail)

        info = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=SPACE_TIGHT,
            hexpand=True,
        )
        title = Gtk.Label(label=entry.document, xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class("sc-title")
        info.append(title)
        facts = [
            entry.date.astimezone().strftime("%Y-%m-%d %H:%M"),
            format_clock(entry.duration_s),
            entry.machine,
        ]
        if entry.stopped:
            facts.append(_("Stopped"))
        caption = Gtk.Label(label=" · ".join(facts), xalign=0)
        caption.add_css_class("sc-caption")
        info.append(caption)
        for layer in entry.layers:
            for step in layer.get("steps", []):
                label = Gtk.Label(
                    label=step_summary(layer["name"], step),
                    xalign=0,
                    wrap=True,
                )
                info.append(label)
        box.append(info)

        buttons = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_CONTROL
        )
        buttons.set_valign(Gtk.Align.CENTER)
        load = Gtk.Button(label=_("Load"))
        load.connect("clicked", self._on_load_clicked, entry)
        buttons.append(load)
        run_again = Gtk.Button(label=_("Run Again"))
        run_again.connect("clicked", self._on_run_again_clicked, entry)
        buttons.append(run_again)
        self._run_buttons.append((entry, run_again))
        box.append(buttons)

        return Gtk.ListBoxRow(activatable=False, child=box)

    def _update_run_buttons(self):
        """Run Again: connected, idle, and on the machine it ran on."""
        machine = self._machine
        ready = (
            machine is not None
            and machine.is_connected()
            and not self._win.machine_cmd.is_job_running
        )
        for entry, button in self._run_buttons:
            button.set_sensitive(
                ready and machine is not None and entry.machine == machine.name
            )

    def _bind_machine(self) -> bool:
        """Follows the active machine; whether it changed."""
        machine = get_context().config.machine
        if machine is self._machine:
            return False
        if self._machine is not None:
            self._machine.connection_status_changed.disconnect(
                self._on_connection_status_changed
            )
        self._machine = machine
        if machine is not None:
            machine.connection_status_changed.connect(
                self._on_connection_status_changed
            )
        return True

    def _on_config_changed(self, sender, **kwargs):
        if self._bind_machine():
            self.refresh()
        else:
            self._update_run_buttons()

    def _on_history_changed(self, sender, *, machine: str):
        if self._machine is not None and machine == self._machine.name:
            self.refresh()

    def _on_connection_status_changed(self, machine, **kwargs):
        self._update_run_buttons()

    def _on_job_state_changed(self, sender):
        self._update_run_buttons()

    def _load(self, entry: JobHistoryEntry, then: Callable[[], None]):
        """Loads the job; a job run from it keeps the entry's name."""

        def loaded():
            self._win.job_history_recorder.copy_loaded(entry.document)
            then()

        self._win.project_cmd.load_project_copy(
            entry.project_path, then=loaded
        )

    def _on_load_clicked(self, button, entry: JobHistoryEntry):
        self._load(entry, self.close)

    def _on_run_again_clicked(self, button, entry: JobHistoryEntry):
        def start():
            self.close()
            self._win.start_when_settled()

        self._load(entry, start)

    def _on_close_request(self, window) -> bool:
        get_context().config.changed.disconnect(self._on_config_changed)
        self._history.changed.disconnect(self._on_history_changed)
        self._win.machine_cmd.job_state_changed.disconnect(
            self._on_job_state_changed
        )
        if self._machine is not None:
            self._machine.connection_status_changed.disconnect(
                self._on_connection_status_changed
            )
            self._machine = None
        return False

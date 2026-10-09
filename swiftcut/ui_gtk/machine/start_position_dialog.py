import logging
from collections.abc import Callable
from gettext import gettext as _

from blinker import Signal
from gi.repository import Adw, Gtk

from ...context import get_context
from ...machine.models.machine import Machine

logger = logging.getLogger(__name__)

# Runs a Start: with None from the head's current position, or with a
# machine-space (x, y) in mm, from the last job's start position.
StartRun = Callable[[tuple[float, float] | None], None]

# Sent on the main thread just before a chosen Start runs, from the
# toolbar or the jog panel alike, with the window it was asked from as
# sender and machine=. Watching only, for the job history: a watcher
# that fails never stops the Start, and a Start that is refused still
# goes on to be refused.
start_chosen = Signal()


class StartPositionDialog(Adw.MessageDialog):
    """Asks whether a job starts here or where the last job started."""

    def __init__(
        self,
        last_job_start: tuple[float, float] | None,
        on_start: StartRun,
        **kwargs,
    ):
        super().__init__(
            heading=_("Start the job from where?"),
            body=_(
                "From the head's current position, or from where the "
                "last job started: the head moves there first. The "
                "laser fires."
            ),
            **kwargs,
        )
        self._last_job_start = last_job_start
        self._on_start = on_start
        self.add_css_class("sc-sheet")

        self.add_response("cancel", _("Cancel"))
        self.add_response("current", _("Start from current position"))
        self.add_response("last", _("Start from last job's start position"))
        for response in ("current", "last"):
            self.set_response_appearance(
                response, Adw.ResponseAppearance.DESTRUCTIVE
            )
        self.set_response_enabled("last", last_job_start is not None)
        # Cancel, as in Cut Scale: either start fires the laser, so
        # Enter must not commit one.
        self.set_default_response("cancel")
        self.set_close_response("cancel")
        self.connect("response", self._on_response)

    def _on_response(self, dialog, response):
        if response == "current":
            self._on_start(None)
        elif response == "last":
            self._on_start(self._last_job_start)


def request_start(
    parent: Gtk.Widget | None, machine: Machine, run: StartRun
):
    """
    The one way into a Start, from the toolbar or the jog panel.

    With Crawford mode off, this is Start as it always was: run(None),
    straight away and with no sheet. With it on, the sheet asks first.
    """

    def start(start_at: tuple[float, float] | None):
        try:
            start_chosen.send(parent, machine=machine)
        except Exception:
            logger.exception("A Start watcher failed")
        run(start_at)

    if not get_context().config.crawford_mode:
        start(None)
        return
    dialog = StartPositionDialog(machine.last_job_start, start)
    if isinstance(parent, Gtk.Window):
        dialog.set_transient_for(parent)
    dialog.present()

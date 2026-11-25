from gettext import gettext as _

from gi.repository import Adw

from ...machine.driver.dummy import NoDeviceDriver
from ...machine.models.machine import Machine
from ...machine.transport import TransportStatus


class ReconnectBanner:
    """
    Its banner is the one message shown while the active machine's
    driver retries its connection (Adw.Banner is final, so this owns
    one rather than being one). Each retry runs CONNECTING, ERROR,
    CLOSING, DISCONNECTED and SLEEPING; the message appears on the
    first ERROR or SLEEPING and stays through the cycle. CONNECTED
    (sent once the controller has answered, see MachineController)
    hides it, and so does DISCONNECTED once the controller has
    stopped connecting (a disconnect, release or shutdown). A machine
    on NoDeviceDriver never shows it.
    """

    def __init__(self):
        self.banner = Adw.Banner(
            title=_("Laser disconnected. Retrying…"), use_markup=False
        )
        self.machine: Machine | None = None

    def set_machine(self, machine: Machine | None):
        """Follows machine's connection, starting from its status now."""
        if machine is self.machine:
            return
        if self.machine:
            self.machine.connection_status_changed.disconnect(
                self._on_connection_status_changed
            )
        self.machine = machine
        self.banner.set_revealed(False)
        if machine:
            machine.connection_status_changed.connect(
                self._on_connection_status_changed
            )
            self._update(machine.connection_status)

    def _on_connection_status_changed(
        self,
        machine: Machine,
        status: TransportStatus,
        message: str | None = None,
    ):
        self._update(status)

    def _update(self, status: TransportStatus):
        machine = self.machine
        if machine is None or isinstance(machine.driver, NoDeviceDriver):
            self.banner.set_revealed(False)
        elif status in (TransportStatus.ERROR, TransportStatus.SLEEPING):
            self.banner.set_revealed(True)
        elif status == TransportStatus.CONNECTED or (
            status == TransportStatus.DISCONNECTED
            and not machine.controller.connect_requested
        ):
            self.banner.set_revealed(False)

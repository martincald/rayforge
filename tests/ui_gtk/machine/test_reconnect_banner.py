"""
The one "disconnected, retrying" message, driven by the connection
statuses a Ruida driver sends while its device is away.
"""

import time

import pytest
from gi.repository import GLib

from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.machine.models.machine import Machine
from swiftcut.machine.transport import TransportStatus
from swiftcut.ui_gtk.machine.reconnect_banner import ReconnectBanner

pytestmark = pytest.mark.ui

#: One retry, as the Ruida driver sends it with the USB device away:
#: its transport closes twice between the ERROR and the SLEEPING.
RETRY = (
    TransportStatus.CONNECTING,
    TransportStatus.ERROR,
    TransportStatus.CLOSING,
    TransportStatus.DISCONNECTED,
    TransportStatus.CLOSING,
    TransportStatus.DISCONNECTED,
    TransportStatus.SLEEPING,
)


def _machine(context, ruida: bool = True) -> Machine:
    """
    A machine whose controller holds a Ruida driver it has asked to
    connect, or the NoDeviceDriver it starts on. Nothing is set up or
    connected.
    """
    machine = Machine(context)
    context.machine_mgr.add_machine(machine)
    controller = machine.controller
    if ruida:
        controller.driver = RuidaDriver(context, machine)
        controller._connecting_driver = controller.driver
    return machine


def _send(machine: Machine, status: TransportStatus) -> None:
    machine.set_connection_status(status)
    machine.connection_status_changed.send(machine, status=status)


def test_one_message_from_the_first_error_until_connected(
    ui_context_initializer,
):
    machine = _machine(ui_context_initializer)
    banner = ReconnectBanner()
    banner.set_machine(machine)

    _send(machine, TransportStatus.CONNECTING)
    assert not banner.banner.get_revealed()

    shown = []
    for status in RETRY[1:] + RETRY + RETRY:
        _send(machine, status)
        shown.append(banner.banner.get_revealed())
    assert all(shown)
    assert len(shown) == 20

    _send(machine, TransportStatus.CONNECTING)
    assert banner.banner.get_revealed()
    _send(machine, TransportStatus.CONNECTED)
    assert not banner.banner.get_revealed()


def test_it_says_the_laser_is_disconnected_and_retrying(
    ui_context_initializer,
):
    banner = ReconnectBanner()

    assert banner.banner.get_title() == "Laser disconnected. Retrying…"
    assert not banner.banner.get_use_markup()
    assert banner.banner.get_button_label() in (None, "")


def test_disconnected_hides_it_once_the_controller_stops_connecting(
    ui_context_initializer,
):
    machine = _machine(ui_context_initializer)
    banner = ReconnectBanner()
    banner.set_machine(machine)
    _send(machine, TransportStatus.ERROR)
    assert banner.banner.get_revealed()

    # What disconnect(), release() and shutdown() do first.
    machine.controller._connecting_driver = None
    _send(machine, TransportStatus.CLOSING)
    assert banner.banner.get_revealed()
    _send(machine, TransportStatus.DISCONNECTED)

    assert not banner.banner.get_revealed()


def test_a_machine_on_no_device_driver_never_shows_it(
    ui_context_initializer,
):
    machine = _machine(ui_context_initializer, ruida=False)
    banner = ReconnectBanner()
    banner.set_machine(machine)

    for status in RETRY + RETRY:
        _send(machine, status)
        assert not banner.banner.get_revealed()


def test_it_starts_from_the_machine_status_now(ui_context_initializer):
    machine = _machine(ui_context_initializer)
    machine.set_connection_status(TransportStatus.SLEEPING)
    banner = ReconnectBanner()

    banner.set_machine(machine)

    assert banner.banner.get_revealed()


def test_a_machine_switch_hides_it_and_the_same_machine_keeps_it(
    ui_context_initializer,
):
    retrying = _machine(ui_context_initializer)
    other = _machine(ui_context_initializer)
    banner = ReconnectBanner()
    banner.set_machine(retrying)
    _send(retrying, TransportStatus.ERROR)

    banner.set_machine(retrying)
    assert banner.banner.get_revealed()

    banner.set_machine(other)
    assert not banner.banner.get_revealed()
    _send(retrying, TransportStatus.SLEEPING)
    assert not banner.banner.get_revealed()

    banner.set_machine(None)
    assert not banner.banner.get_revealed()


def _iterate(seconds: float) -> None:
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        context.iteration(False)
        time.sleep(0.01)


def test_a_silent_controller_keeps_the_message_through_its_retries(
    ui_context_initializer,
):
    """
    The port opens on every retry and the controller never answers:
    the driver's statuses, through the controller that forwards them,
    never hide the message.
    """
    machine = _machine(ui_context_initializer)
    banner = ReconnectBanner()
    banner.set_machine(machine)
    controller, driver = machine.controller, machine.driver
    assert not driver.is_connected

    def driver_sends(status):
        controller._on_driver_connection_status_changed(driver, status=status)
        _iterate(0.05)

    driver_sends(TransportStatus.ERROR)
    for _ in range(3):
        for status in (
            TransportStatus.CONNECTING,
            TransportStatus.CONNECTED,
            TransportStatus.ERROR,
            TransportStatus.CLOSING,
            TransportStatus.DISCONNECTED,
            TransportStatus.SLEEPING,
        ):
            driver_sends(status)
            assert banner.banner.get_revealed(), status
    assert not machine.is_connected()

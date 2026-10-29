"""
The jog panel to the controller, end to end (MOTION_AUDIT.md MOT-05).

The widget's own press, timer and release handlers drive a real
MachineCmd, whose task manager runs a real RuidaDriver and RuidaClient
against a fake controller that logs every command. The fake's D9 10
puts the head on its target at once, like the simulator's, so a
runaway shows up as a D9 10 target far from where the head was last
read, not as motion. A slow main loop is modelled by firing the hold
timer by hand before the release arrives.
"""

import asyncio
import threading
import time
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch

import gi
import pytest
from blinker import Signal

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GLib  # noqa: E402

from swiftcut.machine.cmd import MachineCmd  # noqa: E402
from swiftcut.machine.driver.ruida.ruida_client import (  # noqa: E402
    RuidaClient,
)
from swiftcut.machine.driver.ruida.ruida_driver import (  # noqa: E402
    RuidaDriver,
)
from swiftcut.machine.driver.ruida.ruida_util import (  # noqa: E402
    decode35,
    encode35,
)
from swiftcut.machine.models.machine import (  # noqa: E402
    JogDirection,
    Machine,
)
from swiftcut.machine.transport import TransportStatus  # noqa: E402

HEAD = (100000, 100000)
# The longest move a hold may command past the last read position.
HOLD_STEP_MAX_UM = 5000
STOP = b"\xd8\x01"
X_ADDRESS, Y_ADDRESS = 0x0421, 0x0431
KEY_UP = "key-up"
EAST = (JogDirection.EAST,)


class FakeController:
    """
    A RuidaTransport stand-in with a controller behind it.

    The log holds every command in the order it reached the wire and,
    between them, each position reply as it was delivered. Replies can
    be held back (a slow controller), a D9 write can be held up (a slow
    USB write, which keeps the client's send lock), the head can be
    kept from arriving, and D8 01 can be dropped (a controller it does
    not brake).
    """

    def __init__(self):
        self.decoded_received = Signal()
        self.status_changed = Signal()
        self.is_connected = True
        self.position = HEAD
        self.log: list = []
        self.drop_stop = False
        self.hold_replies = False
        self.hold_moves = False
        self.frozen = False
        self.target = HEAD
        self.replies_held = threading.Event()
        self.move_held = threading.Event()
        self._held: list[bytes] = []
        self._gate: asyncio.Event | None = None

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def send_command(self, command: bytes):
        if command[:2] == b"\xd9\x10" and self.hold_moves:
            self.move_held.set()
            await self._open().wait()
        if command == STOP and self.drop_stop:
            return
        self.log.append(command)
        if command[:2] == b"\xd9\x10":
            self.target = (decode35(command[3:8]), decode35(command[8:13]))
            if not self.frozen:
                self.position = self.target
        elif command[:2] == b"\xda\x00":
            self._answer(command)

    def _open(self) -> asyncio.Event:
        if self._gate is None:
            self._gate = asyncio.Event()
        return self._gate

    def _answer(self, command: bytes) -> None:
        address = (command[2] << 8) | command[3]
        value = {X_ADDRESS: self.position[0], Y_ADDRESS: self.position[1]}
        reply = b"\xda\x01" + command[2:4] + encode35(value.get(address, 0))
        if self.hold_replies:
            self._held.append(reply)
            self.replies_held.set()
            return
        asyncio.get_running_loop().call_soon(partial(self._deliver, reply))

    def _deliver(self, reply: bytes) -> None:
        self.log.append(("reply", (reply[2] << 8) | reply[3], reply[4:9]))
        self.decoded_received.send(self, data=reply)

    def release(self, loop) -> None:
        """Let held replies and writes through, from the test thread."""
        loop.call_soon_threadsafe(self._release)

    def _release(self) -> None:
        self.hold_replies = False
        self.hold_moves = False
        self._open().set()
        for reply in self._held:
            asyncio.get_running_loop().call_soon(partial(self._deliver, reply))
        self._held.clear()

    def arrive(self) -> None:
        """Put a frozen head on the target it was last sent to."""
        self.frozen = False
        self.position = self.target


def moves(log) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Each D9 10 target, paired with the head as last read before it."""
    read = {X_ADDRESS: HEAD[0], Y_ADDRESS: HEAD[1]}
    found = []
    for entry in log:
        if isinstance(entry, tuple):
            _, address, value = entry
            if address in read:
                read[address] = decode35(value)
        elif isinstance(entry, bytes) and entry[:2] == b"\xd9\x10":
            target = (decode35(entry[3:8]), decode35(entry[8:13]))
            found.append((target, (read[X_ADDRESS], read[Y_ADDRESS])))
    return found


def reach(target: tuple[int, int], read: tuple[int, int]) -> int:
    """How far a target lies from the position last read, per axis."""
    return max(abs(target[0] - read[0]), abs(target[1] - read[1]))


def moves_after(log, marker) -> list:
    """The D9 10 commands logged after the first marker."""
    if marker not in log:
        return []
    return [
        e
        for e in log[log.index(marker) :]
        if isinstance(e, bytes) and e[:2] == b"\xd9\x10"
    ]


def _until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.002)


def _settle(rig) -> None:
    """Wait for every task, and the driver's own hold sequence, to end."""
    _until(lambda: not rig.tm.has_tasks())
    hold = getattr(rig.driver, "_hold_task", None)
    _until(lambda: hold is None or hold.done())
    _until(lambda: not rig.tm.has_tasks())


def _press(widget, directions=EAST):
    widget._on_jog_pressed(None, 1, 0.0, 0.0, directions)


def _release(widget, directions=EAST):
    widget._on_jog_released(None, 1, 0.0, 0.0, directions)


def _timer_fires(widget, directions=EAST):
    """What GLib does when the hold timer comes due."""
    source_id = widget._pending_holds.get(directions)
    if widget._start_hold(directions) == GLib.SOURCE_REMOVE:
        GLib.source_remove(source_id)


@pytest.fixture
def rig(ui_context_initializer, ui_task_mgr, monkeypatch):
    from swiftcut.ui_gtk.machine.jog_widget import JogWidget

    monkeypatch.setattr(RuidaDriver, "JOG_SETTLE_POLL_INTERVAL", 0.005)
    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    ui_context_initializer.machine_mgr.add_machine(machine)
    machine.connection_status = TransportStatus.CONNECTED

    driver = RuidaDriver(ui_context_initializer, machine)
    fake = FakeController()
    client = RuidaClient(fake)
    client.position_updated.connect(driver._on_position_updated)
    driver._client = client
    # Where the connection loop's position poll leaves the cache.
    driver._last_known_pos = HEAD
    plain_key_up = driver.jog_key_up

    async def marked_key_up(axis, direction):
        fake.log.append(KEY_UP)
        await plain_key_up(axis, direction)

    driver.jog_key_up = marked_key_up
    machine_cmd = MachineCmd(
        SimpleNamespace(
            task_manager=ui_task_mgr,
            document_settled=Signal(),
            notification_requested=Signal(),
            doc=SimpleNamespace(has_result=lambda: False),
        )
    )

    with (
        patch.object(machine.controller, "driver", driver),
        patch.object(type(machine), "is_connected", return_value=True),
    ):
        widget = JogWidget()
        widget.set_machine(machine, machine_cmd)
        rig = SimpleNamespace(
            widget=widget,
            driver=driver,
            fake=fake,
            machine=machine,
            machine_cmd=machine_cmd,
            tm=ui_task_mgr,
        )
        _settle(rig)
        yield rig

        fake.release(ui_task_mgr.loop)
        widget._cancel_pending_hold()
        _settle(rig)
    asyncio.run_coroutine_threadsafe(
        driver.cleanup(), ui_task_mgr.loop
    ).result(5)


@pytest.mark.ui
def test_a_short_click_moves_one_step(rig):
    """(a) A press released before the hold timer is one step."""
    _press(rig.widget)
    _release(rig.widget)
    _settle(rig)

    assert [t for t, _ in moves(rig.fake.log)] == [(90000, 100000)]


@pytest.mark.ui
def test_a_click_the_hold_timer_beat_moves_one_step(rig):
    """
    (a') A slow main loop runs the hold timer before the release it has
    queued: the button is already up, so it is still a click, and moves
    one step of the step-size control.
    """
    with patch.object(
        rig.widget, "_pointer_button_down", return_value=False, create=True
    ):
        _press(rig.widget)
        _timer_fires(rig.widget)
        _release(rig.widget)
        _settle(rig)

    assert [t for t, _ in moves(rig.fake.log)] == [(90000, 100000)]


@pytest.mark.ui
@pytest.mark.parametrize("stop", ["sent", "dropped"])
def test_a_hold_commands_only_short_moves(rig, stop):
    """
    (b) Hold, then release. No move reaches further than one hold step
    past where the head was last read, and nothing moves after the
    release -- also when the controller ignores D8 01, so correctness
    does not rest on it.
    """
    rig.fake.drop_stop = stop == "dropped"
    _press(rig.widget)
    _timer_fires(rig.widget)
    _until(lambda: moves(rig.fake.log))
    time.sleep(0.05)
    _release(rig.widget)
    _settle(rig)

    found = moves(rig.fake.log)
    assert found
    assert all(target[1] == HEAD[1] for target, _ in found)
    assert max(reach(t, r) for t, r in found) <= HOLD_STEP_MAX_UM
    assert moves_after(rig.fake.log, KEY_UP) == []
    assert rig.driver._jog_busy is False


@pytest.mark.ui
def test_a_click_during_a_hold_adds_no_move(rig):
    """(c) An arrow key pressed while a button is held is ignored."""
    _press(rig.widget)
    _timer_fires(rig.widget)
    _until(lambda: moves(rig.fake.log))
    rig.widget._on_key_pressed(None, Gdk.KEY_Up, 0, 0)
    rig.widget._on_key_released(None, Gdk.KEY_Up, 0, 0)
    _until(lambda: not rig.tm.has_tasks())
    _release(rig.widget)
    _settle(rig)

    found = moves(rig.fake.log)
    assert all(target[1] == HEAD[1] for target, _ in found)
    assert max(reach(t, r) for t, r in found) <= HOLD_STEP_MAX_UM


@pytest.mark.ui
def test_a_press_in_a_step_settle_window_adds_no_move(rig):
    """
    (d) A press that turns into a hold while a step is still settling,
    then is released, is ignored: the step stays the only move.
    """
    rig.fake.frozen = True
    _press(rig.widget)
    _release(rig.widget)
    _until(lambda: moves(rig.fake.log) and rig.driver._jog_busy)
    _press(rig.widget)
    _timer_fires(rig.widget)
    _release(rig.widget)
    _until(lambda: KEY_UP in rig.fake.log)
    rig.fake.arrive()
    _settle(rig)

    assert [t for t, _ in moves(rig.fake.log)] == [(90000, 100000)]
    assert STOP not in rig.fake.log


@pytest.mark.ui
def test_a_release_while_the_hold_waits_on_a_read_moves_nothing(rig):
    """
    (e) The release lands while the hold's first position read is still
    unanswered: no move may follow the release.
    """
    rig.driver._last_known_pos = None
    rig.fake.hold_replies = True
    _press(rig.widget)
    _timer_fires(rig.widget)
    _until(rig.fake.replies_held.is_set)
    _release(rig.widget)
    _until(lambda: KEY_UP in rig.fake.log)
    rig.fake.release(rig.tm.loop)
    _settle(rig)

    assert moves(rig.fake.log) == []
    assert rig.driver._jog_busy is False


@pytest.mark.ui
def test_a_release_while_a_move_is_being_written_bounds_it(rig):
    """
    (e) The release lands while the hold's move is still being written:
    that move goes out ahead of the stop, so it alone decides how far
    the head runs. It must be one hold step, not the bed.
    """
    rig.fake.hold_moves = True
    _press(rig.widget)
    _timer_fires(rig.widget)
    _until(rig.fake.move_held.is_set)
    _release(rig.widget)
    _until(lambda: KEY_UP in rig.fake.log)
    rig.fake.release(rig.tm.loop)
    _settle(rig)

    found = moves(rig.fake.log)
    assert len(found) == 1
    assert reach(*found[0]) <= HOLD_STEP_MAX_UM
    assert moves_after(rig.fake.log, STOP) == []


@pytest.mark.ui
def test_a_key_up_never_starts_before_its_key_down(rig):
    """
    (f) The two are unkeyed tasks, but both reach the loop through
    call_soon_threadsafe with the same number of hops, so they start in
    the order the widget sent them.
    """
    started = []

    async def down(axis, direction):
        started.append("down")

    async def up(axis, direction):
        started.append("up")

    rig.driver.jog_key_down = down
    rig.driver.jog_key_up = up
    for _ in range(50):
        rig.machine_cmd.jog_key_down(rig.machine, "x", 1)
        rig.machine_cmd.jog_key_up(rig.machine, "x", 1)
    _settle(rig)

    assert started == ["down", "up"] * 50


@pytest.mark.ui
def test_an_arrow_key_moves_one_step_however_long_it_is_held(rig):
    """The keyboard has no hold: auto-repeat counts once."""
    for _ in range(5):
        rig.widget._on_key_pressed(None, Gdk.KEY_Right, 0, 0)
    rig.widget._on_key_released(None, Gdk.KEY_Right, 0, 0)
    _settle(rig)

    assert [t for t, _ in moves(rig.fake.log)] == [(90000, 100000)]

"""
No traffic but the job while it runs (MOTION_AUDIT.md, 2026-10-29).

Position reads interleaved with a running job have locked the real
controller up. These tests run the driver's connection loop against a
fake controller, park a background position poll on the wire at the
moment a job starts, and record every command the driver sends.
"""

import asyncio
from functools import partial

import pytest
from blinker import Signal
from raygeo.ops import Ops

from swiftcut.core.doc import Doc
from swiftcut.machine.driver.ruida import ruida_driver as driver_mod
from swiftcut.machine.driver.ruida.ruida_client import (
    JOB_CHUNK_MAX_BYTES,
    RuidaClient,
    build_datagrams,
    split_commands,
)
from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.machine.driver.ruida.ruida_encoder import commands_to_rd_bytes
from swiftcut.machine.driver.ruida.ruida_util import encode35
from swiftcut.machine.models.machine import Machine
from swiftcut.pipeline.encoder.base import EncodedOutput, MachineCodeOpMap

X_ADDRESS, Y_ADDRESS, Z_ADDRESS = 0x0421, 0x0431, 0x0441
HEAD_BEFORE = (100000, 200000)
HEAD_AFTER = (150000, 250000)
# Status reads the controller answers "running" before the bit clears.
RUNNING_READS = 6
STATUS_RUNNING, STATUS_IDLE = 21, 22
# Recorded where the loop polls the ref point mode, which is no read
# on the wire but must not happen during a job either.
REF_MODE_POLL = "ref-mode poll"
PLAIN_JOB = b"".join([b"\x88" + bytes(10)] * 150)  # two chunks


class FakeController:
    """
    A RuidaTransport stand-in with a controller behind it.

    Every command is recorded in the order it was sent; replies arrive
    on a later loop iteration, the way a datagram's answer does. The
    first status read answered idle after a job chunk is the
    completion read.
    """

    def __init__(self, status_address: int):
        self.decoded_received = Signal()
        self.status_changed = Signal()
        self.is_connected = True
        self.sent: list[bytes | str] = []
        self.position = HEAD_BEFORE
        self.status_address = status_address
        self.job_status_reads = 0
        self.job_started = False
        self.completion_index: int | None = None
        # Set to park the next X read's reply until `release`.
        self.hold_next_x = False
        self.x_parked = asyncio.Event()
        self.release = asyncio.Event()
        self.parked_reply: asyncio.Task | None = None

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def send_command(self, command: bytes):
        self.sent.append(command)
        self._answer(command)

    async def stream_command(self, chunk: bytes, should_stop) -> bool:
        self.sent.append(chunk)
        self._answer(chunk)
        return True

    def _reply(self, data: bytes) -> None:
        asyncio.get_running_loop().call_soon(
            partial(self.decoded_received.send, self, data=data)
        )

    def _answer(self, command: bytes) -> None:
        if command == b"\xce":
            self._reply(b"\xcc")
            return
        if len(command) != 4 or command[:2] != b"\xda\x00":
            self.job_started = True
            self._reply(b"\xcc")
            return
        address = (command[2] << 8) | command[3]
        reply = b"\xda\x01" + command[2:]
        if address == X_ADDRESS:
            reply += encode35(self.position[0])
            if self.hold_next_x:
                self.hold_next_x = False
                self.x_parked.set()
                self.parked_reply = asyncio.create_task(
                    self._reply_after_release(reply)
                )
                return
        elif address == Y_ADDRESS:
            reply += encode35(self.position[1])
        elif address == self.status_address:
            reply += encode35(self._status())
        else:
            reply += encode35(0)
        self._reply(reply)

    def _status(self) -> int:
        if not self.job_started or self.completion_index is not None:
            return STATUS_IDLE
        self.job_status_reads += 1
        if self.job_status_reads <= RUNNING_READS:
            return STATUS_RUNNING
        self.completion_index = len(self.sent) - 1
        self.position = HEAD_AFTER
        return STATUS_IDLE

    async def _reply_after_release(self, reply: bytes) -> None:
        await self.release.wait()
        self._reply(reply)


async def _until(predicate, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.01)


def _connected_driver(lite_context, connection: str):
    """A RuidaDriver wired to a FakeController, as _setup_udp wires."""
    driver = RuidaDriver(lite_context, Machine(lite_context))
    fake = FakeController(driver.MACHINE_STATUS_ADDRESS)
    client = RuidaClient(fake)
    client.state_changed.connect(driver._on_state_changed)
    client.position_updated.connect(driver._on_position_updated)
    driver._connection = connection
    driver.host = "fake-controller"
    driver._ruida_transport = fake
    driver._client = client
    driver._init_coordinate_systems()

    plain_ref_mode = client.get_ref_point_mode

    async def recorded_ref_mode():
        fake.sent.append(REF_MODE_POLL)
        return await plain_ref_mode()

    client.get_ref_point_mode = recorded_ref_mode
    return driver, fake, client


@pytest.mark.asyncio
@pytest.mark.parametrize("connection", ["udp", "usb"])
async def test_nothing_but_the_job_goes_out_while_it_runs(
    lite_context, monkeypatch, connection
):
    """
    From the first job chunk until the status read that finds the
    job-running bit clear, the wire carries job chunks and status
    reads only: no position read, no ENQ, no ref-mode poll -- even
    though a position poll was mid-read when Start arrived. Then one
    position read resyncs the head, and the poller resumes.
    """
    for name in (
        "KEEPALIVE_INTERVAL",
        "USB_KEEPALIVE_INTERVAL",
        "POSITION_POLL_INTERVAL",
        "STATUS_POLL_INTERVAL",
    ):
        monkeypatch.setattr(RuidaDriver, name, 0.05)
    monkeypatch.setattr(RuidaDriver, "LOOP_TICK_INTERVAL", 0.01)
    monkeypatch.setattr(
        driver_mod,
        "build_rd_bytes",
        lambda ops, machine, doc: commands_to_rd_bytes([PLAIN_JOB]),
    )
    chunks = build_datagrams(split_commands(PLAIN_JOB), JOB_CHUNK_MAX_BYTES)
    assert len(chunks) == 2

    driver, fake, client = _connected_driver(lite_context, connection)
    read_x, read_y, read_z, read_status = (
        client._build_read_memory(address)
        for address in (
            X_ADDRESS,
            Y_ADDRESS,
            Z_ADDRESS,
            driver.MACHINE_STATUS_ADDRESS,
        )
    )
    finished: list[tuple] = []
    driver.job_finished.connect(
        lambda sender: finished.append(
            (driver._last_known_pos, len(fake.sent))
        ),
        weak=False,
    )
    encoded = EncodedOutput(
        text="",
        op_map=MachineCodeOpMap.from_lists([], []),
        driver_data={},
    )
    try:
        await driver._connect_implementation()
        await _until(lambda: driver.is_connected)
        await _until(lambda: driver._card_info_task.done())
        await _until(lambda: fake.sent.count(read_x) >= 2)

        # Park the next position poll on the wire, then press Start.
        fake.hold_next_x = True
        await asyncio.wait_for(fake.x_parked.wait(), 2.0)
        run = asyncio.create_task(driver.run(encoded, Doc(), Ops()))
        # Longer than the 0.2 s run() used to wait before its first
        # chunk.
        await asyncio.sleep(0.3)
        fake.release.set()
        await asyncio.wait_for(run, 5.0)
        assert finished
        end = finished[0][1]
        await _until(lambda: read_x in fake.sent[end:])
    finally:
        await driver.cleanup()

    sent = fake.sent
    first_chunk = sent.index(chunks[0])
    completion = fake.completion_index
    assert completion is not None
    during = sent[first_chunk : completion + 1]

    assert [c for c in sent if c in chunks] == chunks
    assert [c for c in during if c not in chunks and c != read_status] == []
    for unwanted in (
        read_x,
        read_y,
        read_z,
        client._build_keep_alive(),
        REF_MODE_POLL,
    ):
        assert unwanted not in during
    assert during[-1] == read_status

    # One position read after the job, and the head is where it said.
    last_known_pos, end = finished[0]
    assert sent[completion + 1 : end] == [read_x, read_y]
    assert last_known_pos == HEAD_AFTER
    # Then the poller is back.
    assert read_x in sent[end:]

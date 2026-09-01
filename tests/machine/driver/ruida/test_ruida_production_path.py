"""A two-step job, generated and sent the way the app does it.

Every test here builds a real document, lets the real Pipeline
generate it -- the intent, raygeo's cache and intent diff, the job
artifact -- and encodes the artifact's ops with build_rd_bytes, the
call RuidaDriver.run and export_rd make. Nothing synthesises ops.

The document is the one the session logs show producing a one-part
.rd from a two-step layer: an engrave and a cut, on a head left at
the model's default tool number. The pipeline's encode node died on
the second part, the failure was logged and nothing more, and the
send transmitted the artifact of the previous, single-step document.
"""

import asyncio

import pytest
import pytest_asyncio

from rayforge.core.doc import Doc
from rayforge.machine.driver.ruida.ruida_encoder import (
    RD_MAGIC,
    RuidaEncoder,
    build_rd_bytes,
)
from rayforge.machine.driver.ruida.ruida_util import (
    build_swizzle_lut,
    decode35,
    encode14,
)
from rayforge.pipeline.pipeline import Pipeline

from test_ruida_multistep_job import (
    CUT_POWER,
    CUT_UM_S,
    ENGRAVE_POWER,
    ENGRAVE_UM_S,
    _blocks,
    _doc_with_two_steps,
    _part_powers,
    _part_speeds,
    _payloads,
)

# 20 mm/s and 30 mm/s, as the model stores them and the wire wants.
EDITED_CUT_MM_MIN = 1200
EDITED_CUT_UM_S = 20000
REEDITED_CUT_MM_MIN = 1800
REEDITED_CUT_UM_S = 30000

EDITED_ENGRAVE_POWER = 0.35

HEADER_POWER_OPCODES = (b"\xc6\x31", b"\xc6\x32", b"\xc6\x41", b"\xc6\x42")


@pytest.fixture(autouse=True)
def _zero_debounce(zero_debounce_delay):
    """Rebuild on the next main-loop turn instead of 200 ms later."""


@pytest_asyncio.fixture
async def production(
    task_mgr,
    context_initializer,
    test_machine_and_config,
    engrave_step_class,
    contour_step_class,
):
    """The reported document on its pipeline, ready to be sent."""
    machine, _config = test_machine_and_config
    # The reported machine names the Ruida driver and no G-code
    # dialect, which is what makes the pipeline's encode node run the
    # driver's encoder. Its head keeps the model's default tool number.
    machine.driver_name = "RuidaDriver"
    machine.dialect_uid = None
    machine.hydrate()
    doc = Doc()
    engrave, cut = _doc_with_two_steps(
        doc, context_initializer, engrave_step_class, contour_step_class
    )
    pipeline = Pipeline(
        doc, task_mgr, context_initializer.artifact_store, machine
    )

    yield pipeline, doc, machine, engrave, cut

    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)
    pipeline.shutdown()


def _commands(blob: bytes) -> list[bytes]:
    """Unswizzle a job blob and split it into commands."""
    _swizzle, unswizzle = build_swizzle_lut(RD_MAGIC)
    decoded = bytes(unswizzle[b] for b in blob)
    commands: list[bytes] = []
    current = bytearray()
    for b in decoded:
        if b & 0x80 and current:
            commands.append(bytes(current))
            current = bytearray()
        current.append(b)
    commands.append(bytes(current))
    return commands


async def _send(pipeline, machine, doc) -> list[bytes]:
    """What a send transmits: the job artifact through build_rd_bytes.

    Nothing waits for the pipeline first. Asking for the artifact is
    what the send does, and what it hands back has to be the current
    document's job whether or not a rebuild is under way.
    """
    handle = await asyncio.wait_for(
        pipeline.generate_job_artifact_async(), timeout=30
    )
    with pipeline.artifact_store.checkout_handle(handle) as artifact:
        assert artifact is not None
        blob = build_rd_bytes(artifact.ops, machine, doc)
    return _commands(blob)


def _cut_moves(block: list[bytes]) -> list[bytes]:
    return [
        c for c in block if c[:1] in (b"\xa8", b"\xa9", b"\xaa", b"\xab")
    ]


def _modulations(block: list[bytes]) -> list[bytes]:
    """C7 immediate power: only raster rows modulate per sample."""
    return [c for c in block if c[:1] == b"\xc7"]


def _block_speed(block: list[bytes]) -> int:
    return decode35(_payloads(block, b"\xc9\x02")[0])


def _power14(power: float) -> bytes:
    return encode14(int(power * 16383))


def _assert_two_parts_each_with_its_own_settings(commands):
    assert [p[0] for p in _payloads(commands, b"\xca\x02")] == [0, 1]
    assert _payloads(commands, b"\xca\x22") == [b"\x01"]
    assert _part_speeds(commands) == {0: ENGRAVE_UM_S, 1: CUT_UM_S}
    expected = {0: _power14(ENGRAVE_POWER), 1: _power14(CUT_POWER)}
    for opcode in HEADER_POWER_OPCODES:
        assert _part_powers(commands, opcode) == expected

    engrave_block, cut_block = _blocks(commands)
    assert _block_speed(engrave_block) == ENGRAVE_UM_S
    assert _modulations(engrave_block)
    assert _block_speed(cut_block) == CUT_UM_S
    assert 4 <= len(_cut_moves(cut_block)) <= 5
    assert not _modulations(cut_block)


def _assert_one_part_the_cut(commands):
    assert [p[0] for p in _payloads(commands, b"\xca\x02")] == [0]
    assert _payloads(commands, b"\xca\x22") == [b"\x00"]
    assert _part_speeds(commands) == {0: CUT_UM_S}
    for opcode in HEADER_POWER_OPCODES:
        assert _part_powers(commands, opcode) == {0: _power14(CUT_POWER)}

    (block,) = _blocks(commands)
    assert _block_speed(block) == CUT_UM_S
    assert 4 <= len(_cut_moves(block)) <= 5
    assert not _modulations(block)


class TestTwoStepsBecomeTwoParts:
    """The blob binds each step's geometry to that step's settings."""

    @pytest.mark.asyncio
    async def test_each_part_carries_its_own_settings_and_geometry(
        self, production
    ):
        pipeline, doc, machine, _engrave, _cut = production

        commands = await _send(pipeline, machine, doc)

        _assert_two_parts_each_with_its_own_settings(commands)

    @pytest.mark.asyncio
    async def test_the_default_tool_number_is_laser_1_in_every_part(
        self, production
    ):
        """A head at tool number 0 is the first laser, in both parts.

        The encoder used to read the number as Ruida's own, so the
        default head was laser 0 and the second part's CA 10 needed
        a byte of -1. That is the ValueError the logs show on every
        two-step build.
        """
        pipeline, doc, machine, _engrave, _cut = production

        blocks = _blocks(await _send(pipeline, machine, doc))

        assert len(blocks) == 2
        for block in blocks:
            assert _payloads(block, b"\xca\x10") == [b"\x00"]
            assert b"\xca\x01\x10" in block


class TestTogglingAStep:
    """Hiding and showing a step changes the job, and only the job."""

    @pytest.mark.asyncio
    async def test_disabling_the_engrave_leaves_the_cut_as_the_cut(
        self, production
    ):
        pipeline, doc, machine, engrave, _cut = production
        _assert_two_parts_each_with_its_own_settings(
            await _send(pipeline, machine, doc)
        )

        engrave.set_visible(False)

        _assert_one_part_the_cut(await _send(pipeline, machine, doc))

    @pytest.mark.asyncio
    async def test_re_enabling_the_engrave_brings_its_part_back(
        self, production
    ):
        pipeline, doc, machine, engrave, _cut = production
        first = await _send(pipeline, machine, doc)
        engrave.set_visible(False)
        _assert_one_part_the_cut(await _send(pipeline, machine, doc))

        engrave.set_visible(True)

        again = await _send(pipeline, machine, doc)
        _assert_two_parts_each_with_its_own_settings(again)
        assert again == first

    @pytest.mark.asyncio
    async def test_a_send_right_after_the_toggle_gets_the_rebuilt_job(
        self, production
    ):
        """The send does not get the artifact the toggle made stale.

        A raster takes seconds to rebuild, and the send used to hand
        out whatever artifact was on hand, so a job sent in that
        window was the document before the toggle.
        """
        pipeline, doc, machine, engrave, _cut = production
        _assert_two_parts_each_with_its_own_settings(
            await _send(pipeline, machine, doc)
        )

        engrave.set_visible(False)
        assert pipeline.is_busy

        _assert_one_part_the_cut(await _send(pipeline, machine, doc))

    @pytest.mark.asyncio
    async def test_deleting_the_work_leaves_no_job_on_offer(
        self, production
    ):
        """A document with nothing to cut has no job, not the old one."""
        pipeline, doc, machine, _engrave, _cut = production
        _assert_two_parts_each_with_its_own_settings(
            await _send(pipeline, machine, doc)
        )

        layer = doc.active_layer
        for workpiece in list(layer.all_workpieces):
            layer.remove_workpiece(workpiece)

        with pytest.raises(RuntimeError, match="no visible steps"):
            await asyncio.wait_for(
                pipeline.generate_job_artifact_async(), timeout=30
            )
        await _settle(pipeline)
        assert pipeline.get_existing_job_handle() is None


async def _settle(pipeline) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 30.0
    while pipeline.is_busy and loop.time() < deadline:
        await asyncio.sleep(0.05)
    assert not pipeline.is_busy


class TestEditingAStep:
    """An edit invalidates the cache down to the blob."""

    @pytest.mark.asyncio
    async def test_a_new_cut_speed_reaches_the_next_send(self, production):
        pipeline, doc, machine, _engrave, cut = production
        _assert_two_parts_each_with_its_own_settings(
            await _send(pipeline, machine, doc)
        )

        cut.set_cut_speed(EDITED_CUT_MM_MIN)

        commands = await _send(pipeline, machine, doc)
        assert _part_speeds(commands) == {
            0: ENGRAVE_UM_S,
            1: EDITED_CUT_UM_S,
        }
        _engrave_block, cut_block = _blocks(commands)
        assert _block_speed(cut_block) == EDITED_CUT_UM_S
        assert 4 <= len(_cut_moves(cut_block)) <= 5

    @pytest.mark.asyncio
    async def test_a_new_engrave_power_reaches_the_next_send(
        self, production
    ):
        pipeline, doc, machine, engrave, _cut = production
        _assert_two_parts_each_with_its_own_settings(
            await _send(pipeline, machine, doc)
        )

        engrave.set_power(EDITED_ENGRAVE_POWER)

        commands = await _send(pipeline, machine, doc)
        assert _part_powers(commands, b"\xc6\x32")[0] == _power14(
            EDITED_ENGRAVE_POWER
        )
        assert _part_powers(commands, b"\xc6\x31")[0] == _power14(
            engrave.min_power
        )
        engrave_block, _cut_block = _blocks(commands)
        assert _payloads(engrave_block, b"\xc6\x02") == [
            _power14(EDITED_ENGRAVE_POWER)
        ]


def _explode(self, ops, machine, doc):
    raise ValueError("bytes must be in range(0, 256)")


class TestAFailedEncodeIsNotCoveredByTheLastGoodJob:
    """The reported failure: the encode node dies, the send goes on.

    The pipeline encodes the job once at generation time, and used to
    log that failure and nothing else. The artifact of the previous
    generation stayed on offer, so the send transmitted a job the
    document no longer described -- the one-part .rd from a two-step
    layer.
    """

    @pytest.mark.asyncio
    async def test_the_send_gets_the_encoder_error_not_the_old_job(
        self, production, monkeypatch
    ):
        pipeline, doc, machine, _engrave, cut = production
        _assert_two_parts_each_with_its_own_settings(
            await _send(pipeline, machine, doc)
        )
        monkeypatch.setattr(RuidaEncoder, "encode", _explode)

        cut.set_cut_speed(EDITED_CUT_MM_MIN)

        with pytest.raises(RuntimeError, match="bytes must be in range"):
            await asyncio.wait_for(
                pipeline.generate_job_artifact_async(), timeout=30
            )
        assert pipeline.get_existing_job_handle() is None

    @pytest.mark.asyncio
    async def test_the_next_good_generation_is_handed_out_again(
        self, production, monkeypatch
    ):
        pipeline, doc, machine, _engrave, cut = production
        await _send(pipeline, machine, doc)
        monkeypatch.setattr(RuidaEncoder, "encode", _explode)
        cut.set_cut_speed(EDITED_CUT_MM_MIN)
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(
                pipeline.generate_job_artifact_async(), timeout=30
            )
        monkeypatch.undo()

        cut.set_cut_speed(REEDITED_CUT_MM_MIN)

        commands = await _send(pipeline, machine, doc)
        assert _part_speeds(commands) == {
            0: ENGRAVE_UM_S,
            1: REEDITED_CUT_UM_S,
        }

"""Time ops generation and Ruida encode on the real production path.

Deliberately NOT named ``test_*.py``: ``testpaths`` in pyproject.toml
includes ``tests``, so a matching name would join the default suite and
move the baseline. pytest still collects a file that is named
explicitly, so this runs as::

    python -m pytest tests/perf/perf_encode.py -q -s

It reuses the suite's own fixtures rather than rebuilding the context,
and it runs the same three calls a send runs
(test_ruida_production_path.py:106-120), so the number is the
production path's and not a re-implementation of it:

    handle = await pipeline.generate_job_artifact_async()
    with pipeline.artifact_store.checkout_handle(handle) as artifact:
        blob = build_rd_bytes(artifact.ops, machine, doc)

The two halves are timed separately so a regression can be attributed
to ops generation or to the encoder.
"""

import asyncio
import json
import statistics
import time
from pathlib import Path

import pytest

from swiftcut.core.doc import Doc
from swiftcut.core.workpiece import WorkPiece
from swiftcut.image import import_file
from swiftcut.machine.driver.ruida.ruida_encoder import build_rd_bytes
from swiftcut.pipeline.pipeline import Pipeline

HERE = Path(__file__).parent
OUT = HERE.parent.parent / "build" / "perf"
RUNS = 3

# The generated assets are laid out far larger than the conftest
# machine's 200x150 bed, and an off-bed job is a different code path.
# The bed is widened to fit instead of shrinking the assets, so the
# segment counts the audit quotes stay exactly as generated.
BED_MM = (4000.0, 4000.0)


def _load(doc, context, contour_cls, asset):
    """Put one imported asset on the active layer, under one cut step."""
    payload = import_file(HERE / asset)
    assert payload is not None and payload.items, f"{asset} did not import"

    layer = doc.active_layer
    assert layer.workflow is not None
    layer.workflow.set_steps([])
    doc.add_asset(payload.source)

    pieces = 0
    for item in payload.items:
        if isinstance(item, WorkPiece):
            layer.add_workpiece(item)
            pieces += 1
        else:
            for child in getattr(item, "children", []):
                if isinstance(child, WorkPiece):
                    layer.add_workpiece(child)
                    pieces += 1
    assert pieces, f"{asset} produced no workpieces"

    cut = contour_cls.create(context, name="cut")
    cut.set_cut_speed(1000)
    cut.set_power(0.6)
    cut.set_min_power(0.6)
    layer.workflow.add_step(cut)
    return pieces


@pytest.mark.asyncio
@pytest.mark.parametrize("asset", ["small.svg", "large.dxf", "raster.png"])
async def test_measure(
    asset,
    task_mgr,
    context_initializer,
    test_machine_and_config,
    contour_step_class,
):
    machine, _config = test_machine_and_config
    # Ruida with no dialect is what makes the pipeline's encode node run
    # the driver's encoder rather than the G-code branch
    # (intent_builder.py:815).
    machine.driver_name = "RuidaDriver"
    machine.dialect_uid = None
    machine.set_axis_extents(*BED_MM)
    machine.hydrate()

    doc = Doc()
    pieces = _load(doc, context_initializer, contour_step_class, asset)
    pipeline = Pipeline(
        doc, task_mgr, context_initializer.artifact_store, machine
    )

    ops_ms, enc_ms, blob_len, op_count = [], [], 0, 0
    try:
        for _ in range(RUNS):
            t0 = time.perf_counter()
            handle = await asyncio.wait_for(
                pipeline.generate_job_artifact_async(), timeout=300
            )
            t1 = time.perf_counter()
            with pipeline.artifact_store.checkout_handle(handle) as art:
                assert art is not None
                t1 = time.perf_counter()
                blob = build_rd_bytes(art.ops, machine, doc)
                t2 = time.perf_counter()
                blob_len = len(blob)
                op_count = len(art.ops)
            ops_ms.append((t1 - t0) * 1000.0)
            enc_ms.append((t2 - t1) * 1000.0)
    finally:
        await asyncio.to_thread(task_mgr.wait_until_settled, 10000)
        pipeline.shutdown()

    # Ops generation is cached per unchanged document, so only the
    # FIRST call builds anything: a measured run of
    # [232.8, 0.036, 0.013] ms is a 232.8 ms build followed by two cache
    # hits, and its median would report 0.036 ms of work that never
    # happened. Cold and cached are therefore two named metrics. The
    # encoder has no such cache - its samples agree run to run - so it
    # keeps an honest median.
    record = {
        "asset": asset,
        "workpieces": pieces,
        "ops_cold_ms": ops_ms[0],
        "ops_cached_ms": (
            statistics.median(ops_ms[1:]) if len(ops_ms) > 1 else None
        ),
        "encode_ms": statistics.median(enc_ms),
        "ops_samples": ops_ms,
        "encode_samples": enc_ms,
        "op_count": op_count,
        "rd_bytes": blob_len,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "encode.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    print("\nPERFENCODE " + json.dumps(record))

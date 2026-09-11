"""How ops generation scales with DXF segment count.

Written because `large.dxf` (20 000 segments) did not merely run slowly
in `perf_encode.py` - it exhausted system memory and the run was killed.
A single re-run would have told us nothing except that it fails again,
so this walks the size up instead and records where the curve turns.

Not named ``test_*.py`` for the same reason as perf_encode.py: it must
not join the default suite. Run explicitly::

    python -m pytest tests/perf/perf_dxf_scaling.py -q -s

Each size runs with its own wall-clock budget and its own peak-RSS
reading, and the module stops escalating as soon as one size blows
either budget - so it characterises the limit without reproducing the
out-of-memory kill.
"""

import asyncio
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import time
from pathlib import Path

import ezdxf
import pytest

from swiftcut.core.doc import Doc
from swiftcut.core.workpiece import WorkPiece
from swiftcut.image import import_file
from swiftcut.machine.driver.ruida.ruida_encoder import build_rd_bytes
from swiftcut.pipeline.pipeline import Pipeline

OUT = Path(__file__).parent.parent.parent / "build" / "perf"
SIZES = [int(x) for x in os.environ.get(
    "PERF_SIZES", "250,500,1000,2000,4000,8000").split(",")]
BUDGET_S = 120.0
BUDGET_RSS_MB = 3000.0
BED_MM = tuple(
    float(x) for x in os.environ.get("PERF_BED", "4000,4000").split(",")
)

_state = {"stop": False}


class _Counters(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.GetCurrentProcess.restype = wt.HANDLE
_k32.GetCurrentProcess.argtypes = []
_psapi.GetProcessMemoryInfo.restype = wt.BOOL
_psapi.GetProcessMemoryInfo.argtypes = [
    wt.HANDLE,
    ctypes.POINTER(_Counters),
    wt.DWORD,
]


def _mem():
    c = _Counters()
    c.cb = ctypes.sizeof(c)
    if not _psapi.GetProcessMemoryInfo(
        _k32.GetCurrentProcess(), ctypes.byref(c), c.cb
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return c.WorkingSetSize / (1024 * 1024), c.PeakWorkingSetSize / (
        1024 * 1024
    )


def _make_dxf(path, segments):
    """Same star geometry as make_assets.py, at an arbitrary size."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.add("CUT", color=7)
    per_poly, cols, spacing = 40, 50, 12.0
    for n in range(max(1, segments // per_poly)):
        cx = 10.0 + spacing * (n % cols)
        cy = 10.0 + spacing * (n // cols)
        verts = []
        for i in range(per_poly):
            angle = math.pi * i / (per_poly // 2) - math.pi / 2
            r = 5.0 if i % 2 == 0 else 2.2
            verts.append(
                (cx + r * math.cos(angle), cy + r * math.sin(angle))
            )
        msp.add_lwpolyline(verts, close=True, dxfattribs={"layer": "CUT"})
    doc.saveas(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("segments", SIZES)
async def test_scaling(
    segments,
    tmp_path,
    task_mgr,
    context_initializer,
    test_machine_and_config,
    contour_step_class,
):
    if _state["stop"]:
        pytest.skip("a smaller size already exceeded the budget")

    path = tmp_path / f"scale_{segments}.dxf"
    _make_dxf(path, segments)

    machine, _config = test_machine_and_config
    machine.driver_name = "RuidaDriver"
    machine.dialect_uid = None
    machine.set_axis_extents(*BED_MM)
    machine.hydrate()

    payload = import_file(path)
    assert payload is not None and payload.items

    doc = Doc()
    layer = doc.active_layer
    assert layer.workflow is not None
    layer.workflow.set_steps([])
    doc.add_asset(payload.source)
    for item in payload.items:
        if isinstance(item, WorkPiece):
            layer.add_workpiece(item)
        else:
            for child in getattr(item, "children", []):
                if isinstance(child, WorkPiece):
                    layer.add_workpiece(child)
    cut = contour_step_class.create(context_initializer, name="cut")
    cut.set_cut_speed(1000)
    cut.set_power(0.6)
    layer.workflow.add_step(cut)

    pipeline = Pipeline(
        doc, task_mgr, context_initializer.artifact_store, machine
    )
    rec = {"segments": segments}
    try:
        before, _ = _mem()
        t0 = time.perf_counter()
        try:
            handle = await asyncio.wait_for(
                pipeline.generate_job_artifact_async(), timeout=BUDGET_S
            )
        except asyncio.TimeoutError:
            rec["result"] = f"TIMEOUT after {BUDGET_S:.0f}s"
            _state["stop"] = True
        else:
            ops_ms = (time.perf_counter() - t0) * 1000.0
            with pipeline.artifact_store.checkout_handle(handle) as art:
                t1 = time.perf_counter()
                blob = build_rd_bytes(art.ops, machine, doc)
                enc_ms = (time.perf_counter() - t1) * 1000.0
                rec.update(
                    ops_ms=round(ops_ms, 1),
                    encode_ms=round(enc_ms, 2),
                    op_count=len(art.ops),
                    rd_bytes=len(blob),
                    result="ok",
                )
        rss, peak = _mem()
        rec["rss_mb"] = round(rss, 1)
        rec["peak_rss_mb"] = round(peak, 1)
        rec["rss_delta_mb"] = round(rss - before, 1)
        if peak > BUDGET_RSS_MB:
            _state["stop"] = True
            rec["result"] = rec.get("result", "ok") + " (OVER RSS BUDGET)"
    finally:
        await asyncio.to_thread(task_mgr.wait_until_settled, 15000)
        pipeline.shutdown()

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "dxf_scaling.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    print("\nPERFSCALE " + json.dumps(rec))

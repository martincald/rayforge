"""Measure the performance baseline described in docs/PERF_AUDIT.md.

Run from the repo root, on an otherwise idle machine::

    python scripts/perf/measure.py            # everything
    python scripts/perf/measure.py cold import bundle

Every metric is the median of ``RUNS`` runs, each in a fresh process so
one run cannot warm a cache for the next - these are deliberately COLD
numbers, which is what a user importing their first file of a session
actually pays. Results land in ``build/perf/results.json``.

Deliberate substitutions on this machine, both recorded in the audit:
``py-spy`` is not installed and the box is offline, so the startup
profile uses ``python -X importtime``; ``psutil`` is likewise absent, so
memory comes from the Win32 ``GetProcessMemoryInfo`` via ctypes and CPU
from PowerShell's ``Get-Process``.
"""

import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PERF_DIR = ROOT / "tests" / "perf"
RUNS = 3

PYTHON = sys.executable
# The isolated config keeps the measurement off the developer's own
# machine profile, and off the real laser: tests/config selects
# NoDeviceDriver. It is COPIED rather than used in place, because the
# app rewrites its config directory on exit - pointing it straight at
# tests/config silently edits tracked fixtures (observed: it dropped
# show_camera/check_for_app_updates and added cut_scale_*).
CONFIG_TEMPLATE = ROOT / "tests" / "config"


def _env(extra=None):
    env = dict(os.environ)
    # PREPEND, never setdefault: .msys2_env already exports a PYTHONPATH
    # pointing at the mingw site-packages, so setdefault silently leaves
    # the repo root off and the child cannot import swiftcut at all.
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{ROOT}{os.pathsep}{existing}" if existing else str(ROOT)
    )
    if extra:
        env.update(extra)
    return env


def _median(values):
    return statistics.median(values) if values else float("nan")


def _fresh_config(scratch):
    """A throwaway copy of tests/config, remade for every launch."""
    target = scratch / "config"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(CONFIG_TEMPLATE, target)
    return target


# --------------------------------------------------------------- cold


def cold_start(scratch):
    """Process spawn -> main window mapped, in seconds.

    There is no splash outside a PyInstaller bundle (app.py:172-186
    only closes one if ``pyi_splash`` imports), so from source the
    honest equivalent of "splash shown" is the spawn itself. The
    uiscript stamps ``time.time()`` from the window's map handler and
    quits, so the delta is spawn -> first frame on screen.
    """
    mark = scratch / "mapped.stamp"
    samples = []
    for _ in range(RUNS):
        if mark.exists():
            mark.unlink()
        started = time.time()
        proc = subprocess.run(
            [
                PYTHON,
                "-m",
                "swiftcut.app",
                "--config",
                str(_fresh_config(scratch)),
                "--uiscript",
                str(ROOT / "scripts" / "perf" / "mark_mapped.py"),
            ],
            cwd=ROOT,
            env=_env({"PERF_MARK_FILE": str(mark)}),
            capture_output=True,
            timeout=300,
        )
        if not mark.exists():
            tail = proc.stderr.decode("utf-8", "replace")[-2000:]
            raise RuntimeError(f"window never mapped:\n{tail}")
        samples.append(float(mark.read_text(encoding="utf-8")) - started)
    return {"cold_start_s": _median(samples), "samples": samples}


def import_time_profile(scratch):
    """`-X importtime` on a startup that quits at first paint.

    Stands in for the py-spy startup record the brief asks for. The
    output is the full import tree; the caller keeps the heaviest
    cumulative entries.
    """
    mark = scratch / "mapped.stamp"
    proc = subprocess.run(
        [
            PYTHON,
            "-X",
            "importtime",
            "-m",
            "swiftcut.app",
            "--config",
            str(_fresh_config(scratch)),
            "--uiscript",
            str(ROOT / "scripts" / "perf" / "mark_mapped.py"),
        ],
        cwd=ROOT,
        env=_env({"PERF_MARK_FILE": str(mark)}),
        capture_output=True,
        timeout=300,
    )
    rows = []
    for line in proc.stderr.decode("utf-8", "replace").splitlines():
        if not line.startswith("import time:"):
            continue
        body = line[len("import time:") :].strip()
        parts = body.split("|")
        if len(parts) != 3:
            continue
        try:
            cumulative = int(parts[1].strip())
        except ValueError:
            continue
        rows.append((cumulative, parts[2].strip()))
    rows.sort(reverse=True)
    out = scratch / "importtime.txt"
    out.write_text(
        "\n".join(f"{us:>10} us  {name}" for us, name in rows[:60]),
        encoding="utf-8",
    )
    return {"top_imports": rows[:25], "written_to": str(out)}


# ------------------------------------------------------------- assets

# Run in a child so each measurement starts with a cold module cache
# and its own address space, which is what makes the RSS number mean
# anything.
_ASSET_CHILD = r"""
import ctypes, ctypes.wintypes as wt, json, sys, time, warnings
warnings.filterwarnings("ignore")

class _Counters(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]

# argtypes/restype are load-bearing, not decoration: without them
# ctypes passes the HANDLE as a 32-bit int on win64, the call fails and
# WorkingSetSize reads back 0. Observed exactly that before this was set.
_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.GetCurrentProcess.restype = wt.HANDLE
_k32.GetCurrentProcess.argtypes = []
_psapi.GetProcessMemoryInfo.restype = wt.BOOL
_psapi.GetProcessMemoryInfo.argtypes = [
    wt.HANDLE, ctypes.POINTER(_Counters), wt.DWORD]

def rss():
    c = _Counters(); c.cb = ctypes.sizeof(c)
    if not _psapi.GetProcessMemoryInfo(
            _k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return c.WorkingSetSize

name, mode = sys.argv[1], sys.argv[2]
from pathlib import Path
from swiftcut.image import import_file
from swiftcut.core.vectorization_spec import TraceSpec

# A raster's DEFAULT spec is TraceSpec(threshold=1.0), and
# trace_surface short-circuits on exactly that value: it returns the
# image's bounding rectangle without ever calling vtracer
# (base_importer.py:322-328 -> tracing.py:589). Timing the default
# therefore measures PNG decode and nothing else - 122 ms here against
# 637 ms for a real trace. So a raster is two named metrics, each with
# an explicit spec, and never the implicit default.
SPECS = {
    "decode": TraceSpec(threshold=1.0, auto_threshold=False),
    "trace": TraceSpec(threshold=0.5, auto_threshold=True),
    "vector": None,
}

p = Path(name)
base_rss = rss()
t = time.perf_counter()
payload = import_file(p, vectorization_spec=SPECS[mode])
elapsed = time.perf_counter() - t
items = len(payload.items) if payload else 0
print("PERFJSON" + json.dumps({
    "import_s": elapsed, "items": items,
    "rss_after": rss(), "rss_before": base_rss}))
"""


# (asset, mode) pairs. Every run is a fresh process, so these are cold
# numbers: each one pays raygeo/ezdxf/vtracer import once, which is what
# a user importing their first file actually pays.
ASSET_MODES = (
    ("small.svg", "vector"),
    ("large.dxf", "vector"),
    ("raster.png", "decode"),
    ("raster.png", "trace"),
)


def asset_imports(scratch):
    child = scratch / "_asset_child.py"
    child.write_text(_ASSET_CHILD, encoding="utf-8")
    out = {}
    for name, mode in ASSET_MODES:
        label = name if mode == "vector" else f"{name}:{mode}"
        path = PERF_DIR / name
        if not path.exists():
            out[label] = {
                "error": "asset missing; run tests/perf/make_assets.py"
            }
            continue
        times, rss_after = [], []
        for _ in range(RUNS):
            proc = subprocess.run(
                [PYTHON, str(child), str(path), mode],
                cwd=ROOT,
                env=_env(),
                capture_output=True,
                timeout=900,
            )
            stdout = proc.stdout.decode("utf-8", "replace")
            line = next(
                (
                    ln
                    for ln in stdout.splitlines()
                    if ln.startswith("PERFJSON")
                ),
                None,
            )
            if line is None:
                tail = proc.stderr.decode("utf-8", "replace")[-1500:]
                out[label] = {"error": tail}
                break
            data = json.loads(line[len("PERFJSON") :])
            times.append(data["import_s"])
            rss_after.append(data["rss_after"])
        else:
            out[label] = {
                "import_s": _median(times),
                "rss_after_mb": _median(rss_after) / (1024 * 1024),
                "samples": times,
            }
    return out


# ------------------------------------------------------------- bundle


def bundle(_scratch):
    dist = ROOT / "dist" / "SwiftCut"
    if not dist.is_dir():
        return {"error": "dist/SwiftCut not built"}
    total, count = 0, 0
    for path in dist.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
            count += 1
    installers = sorted((ROOT / "dist").glob("*installer*.exe"))
    return {
        "bytes": total,
        "mb": total / (1024 * 1024),
        "files": count,
        "installer_mb": (
            installers[-1].stat().st_size / (1024 * 1024)
            if installers
            else None
        ),
    }


STEPS = {
    "cold": cold_start,
    "importtime": import_time_profile,
    "import": asset_imports,
    "bundle": bundle,
}


def main(argv):
    wanted = argv[1:] or list(STEPS)
    scratch = ROOT / "build" / "perf"
    scratch.mkdir(parents=True, exist_ok=True)
    results = {}
    for key in wanted:
        if key not in STEPS:
            print(f"unknown step {key!r}; known: {', '.join(STEPS)}")
            return 2
        print(f"--- {key} ---", flush=True)
        results[key] = STEPS[key](scratch)
        print(json.dumps(results[key], indent=2, default=str), flush=True)
    # Merge rather than overwrite, so re-running one step does not
    # discard the other steps' numbers.
    store = scratch / "results.json"
    merged = {}
    if store.exists():
        try:
            merged = json.loads(store.read_text(encoding="utf-8"))
        except ValueError:
            merged = {}
    merged.update(results)
    store.write_text(
        json.dumps(merged, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nwrote {scratch / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

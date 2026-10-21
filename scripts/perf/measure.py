"""Measure the performance table of docs/PERF_AUDIT_M1.md.

Run from the repo root, on an otherwise idle machine, plugged in::

    pixi run bench                      # every step, then the table
    python scripts/perf/measure.py cold canvas report

Each step runs ``RUNS`` (3, or $PERF_RUNS) fresh processes and reports
the median; frame times are pooled over the runs and reported as p50
and p95. Results merge into ``build/perf/results.json`` (re-running one
step keeps the others' numbers) and ``report`` prints the table.

Every app launch gets a throwaway copy of tests/config (NoDeviceDriver,
never the real laser) and goes through scripts/perf/launch.py, which
moves the single-instance guard off the owner's port. A launch prunes
the session logs to the newest five, so the owner's logs are copied
aside before the first launch and put back after the last.
"""

import json
import math
import os
import shutil
import socket
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path

import yaml
from platformdirs import user_log_dir

sys.path.insert(0, str(Path(__file__).resolve().parent))
import procstat

ROOT = Path(__file__).resolve().parent.parent.parent
PERF_DIR = ROOT / "tests" / "perf"
SCRIPTS = ROOT / "scripts" / "perf"
LAUNCHER = SCRIPTS / "launch.py"
SIMULATOR = (
    ROOT / "tests" / "machine" / "driver" / "ruida" / "simulator_app.py"
)
# The built bundle; $PERF_APP points at one built elsewhere (a worktree).
APP_BUNDLE = Path(os.environ.get("PERF_APP", ROOT / "dist" / "SwiftCut.app"))
RUNS = int(os.environ.get("PERF_RUNS", "3"))
IDLE_S = float(os.environ.get("PERF_IDLE_S", "60"))
SOAK_MIN = float(os.environ.get("PERF_SOAK_MIN", "10"))
FRAMES = int(os.environ.get("PERF_FRAMES", "240"))

PYTHON = sys.executable
# Copied, never used in place: the app rewrites its config directory on
# exit, and pointing it at tests/config edits tracked fixtures.
CONFIG_TEMPLATE = ROOT / "tests" / "config"
# The machine tests/config makes active.
ACTIVE_MACHINE = "2f8f7281-9982-4473-a9b0-d72ff48630c2"
# The ilab-614 bed, in mm, which the bench machine is given.
BED_MM = (1400.0, 900.0)
GUARD_PORT = 51987


def _env(extra=None):
    env = dict(os.environ)
    # Prepend, never setdefault: an inherited PYTHONPATH would otherwise
    # leave the repo root off and the child could not import swiftcut.
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{ROOT}{os.pathsep}{existing}" if existing else str(ROOT)
    )
    env.setdefault("PERF_GUARD_PORT", "51999")
    if extra:
        env.update(extra)
    return env


def _median(values):
    return statistics.median(values) if values else float("nan")


def _pct(values, q):
    """The q-quantile (0..1) of values, linearly interpolated."""
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * q
    lo = math.floor(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _fresh_config(scratch, name="config", simulator=False):
    """
    A throwaway copy of tests/config, its active machine given the
    ilab-614 bed: the assets are larger than the fixture's 140 x 140 mm,
    and an oversized import stops on a "scale to fit?" question. With
    simulator, that machine is a Ruida on UDP at 127.0.0.1, where the
    simulator listens.
    """
    target = scratch / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(CONFIG_TEMPLATE, target)
    path = target / "machines" / f"{ACTIVE_MACHINE}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["machine"]["axis_extents"] = list(BED_MM)
    for axis in data["machine"]["axes"]["configs"]:
        if axis["letter"] in "XY":
            axis["extents"] = [0, BED_MM["XY".index(axis["letter"])]]
    if simulator:
        data["machine"]["driver"] = "RuidaDriver"
        data["machine"]["driver_args"] = {
            "connection": "udp",
            "host": "127.0.0.1",
            "port": 50200,
            "jog_port": 50207,
        }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return target


def _app_cmd(config, uiscript, files=()):
    return [
        PYTHON,
        str(LAUNCHER),
        "--config",
        str(config),
        "--uiscript",
        str(uiscript),
        *map(str, files),
    ]


def _run_uiscript(scratch, script, extra, timeout=900):
    """Launches the app with a uiscript; returns the JSON it wrote."""
    out = scratch / "uiscript.json"
    if out.exists():
        out.unlink()
    try:
        proc = subprocess.run(
            _app_cmd(_fresh_config(scratch), SCRIPTS / script),
            cwd=ROOT,
            env=_env({"PERF_OUT": str(out), **extra}),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        stderr = proc.stderr
    except subprocess.TimeoutExpired as e:
        stderr = e.stderr or b"(timed out)"
    if not out.exists():
        tail = stderr.decode("utf-8", "replace")[-3000:]
        raise RuntimeError(f"{script} wrote no result:\n{tail}")
    return json.loads(out.read_text(encoding="utf-8"))


class _KeepLogs:
    """Puts back the session logs a run of launches prunes."""

    def __init__(self, scratch):
        self.dir = Path(
            user_log_dir(
                "SwiftCut" if sys.platform == "darwin" else "swiftcut"
            )
        )
        self.saved = scratch / "saved-logs"

    def __enter__(self):
        if self.saved.exists():
            shutil.rmtree(self.saved)
        if self.dir.is_dir():
            shutil.copytree(self.dir, self.saved)
        return self

    def __exit__(self, *exc):
        if not self.saved.is_dir():
            return
        for log in self.saved.iterdir():
            if not (self.dir / log.name).exists():
                shutil.copy2(log, self.dir / log.name)


# --------------------------------------------------------------- cold


def cold_start(scratch):
    """
    Process spawn -> main window mapped, and spawn -> splash up, in s.

    One launch is made and discarded first: after an edit the first
    launch rewrites the bytecode of every touched module (20 s was
    seen once), which is a one-off, not a start.
    """
    mark = scratch / "mapped.stamp"
    splash_mark = scratch / "splash.stamp"
    samples, splash_samples = [], []
    for n in range(RUNS + 1):
        for stamp in (mark, splash_mark):
            if stamp.exists():
                stamp.unlink()
        started = time.time()
        proc = subprocess.run(
            _app_cmd(_fresh_config(scratch), SCRIPTS / "mark_mapped.py"),
            cwd=ROOT,
            env=_env(
                {
                    "PERF_MARK_FILE": str(mark),
                    "PERF_SPLASH_MARK_FILE": str(splash_mark),
                }
            ),
            capture_output=True,
            timeout=300,
            check=False,
        )
        if not mark.exists():
            tail = proc.stderr.decode("utf-8", "replace")[-2000:]
            raise RuntimeError(f"window never mapped:\n{tail}")
        if n == 0:
            continue
        samples.append(float(mark.read_text(encoding="utf-8")) - started)
        if splash_mark.exists():
            shown = float(splash_mark.read_text(encoding="utf-8"))
            splash_samples.append(shown - started)
    return {
        "cold_start_s": _median(samples),
        "samples": samples,
        "splash_s": _median(splash_samples),
        "splash_samples": splash_samples,
    }


def import_time_profile(scratch):
    """`-X importtime` of a start that quits at first paint."""
    mark = scratch / "mapped.stamp"
    proc = subprocess.run(
        [PYTHON, "-X", "importtime"]
        + _app_cmd(_fresh_config(scratch), SCRIPTS / "mark_mapped.py")[1:],
        cwd=ROOT,
        env=_env({"PERF_MARK_FILE": str(mark)}),
        capture_output=True,
        timeout=300,
        check=False,
    )
    rows = []
    for line in proc.stderr.decode("utf-8", "replace").splitlines():
        if not line.startswith("import time:"):
            continue
        parts = line[len("import time:") :].split("|")
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
        "\n".join(f"{us:>10} us  {name}" for us, name in rows[:80]),
        encoding="utf-8",
    )
    return {"top_imports": rows[:25], "written_to": str(out)}


# ------------------------------------------------------------- assets

# Run in a child, so each measurement starts with a cold module cache
# and its own address space; that is what makes the memory mean
# anything.
_ASSET_CHILD = r"""
import json, os, sys, time, warnings, zipfile
warnings.filterwarnings("ignore")
sys.path.insert(0, sys.argv[3])
import procstat

name, mode = sys.argv[1], sys.argv[2]
from pathlib import Path

if mode == "project":
    # What File > Open does before the editor takes the document
    # (file_cmd.load_project_from_path), with the addons loaded first as
    # they are in the app, untimed.
    from swiftcut.context import get_context
    get_context().addon_mgr
    from swiftcut.core.doc import Doc

    def load(p):
        with zipfile.ZipFile(p) as zf:
            doc = Doc.from_dict(json.loads(zf.read("project.json")))
        return doc.all_workpieces
else:
    from swiftcut.image import import_file
    from swiftcut.core.vectorization_spec import TraceSpec

    # A raster's DEFAULT spec is TraceSpec(threshold=1.0), which
    # trace_surface short-circuits to the bounding rectangle: timing it
    # measures the PNG decode only. So a raster is two named metrics.
    SPECS = {
        "decode": TraceSpec(threshold=1.0, auto_threshold=False),
        "trace": TraceSpec(threshold=0.5, auto_threshold=True),
        "vector": None,
    }

    def load(p):
        payload = import_file(p, vectorization_spec=SPECS[mode])
        return payload.items if payload else []

# What the app has loaded by the time a user can open a file: the
# window maps, then swiftcut.warm_up loads what startup deferred (at
# baseline these loaded with the modules above, before the timer too).
from swiftcut.warm_up import warm_up
warm_up()

before = procstat.sample(os.getpid())
t = time.perf_counter()
items = load(Path(name))
elapsed = time.perf_counter() - t
after = procstat.sample(os.getpid())
print("PERFJSON" + json.dumps({
    "import_s": elapsed, "items": len(items),
    "rss_after": after["rss"], "footprint_after": after["footprint"],
    "rss_before": before["rss"]}))
"""

ASSET_MODES = (
    ("small.svg", "vector"),
    ("large.dxf", "vector"),
    ("raster.png", "decode"),
    ("raster.png", "trace"),
    ("forty.ryp", "project"),
    ("two_layer.ryp", "project"),
)


def asset_imports(scratch):
    child = scratch / "_asset_child.py"
    child.write_text(_ASSET_CHILD, encoding="utf-8")
    out = {}
    for name, mode in ASSET_MODES:
        label = name if mode in ("vector", "project") else f"{name}:{mode}"
        path = PERF_DIR / name
        if not path.exists():
            out[label] = {"error": "asset missing; see tests/perf"}
            continue
        times, rss, footprint = [], [], []
        for _ in range(RUNS):
            proc = subprocess.run(
                [PYTHON, str(child), str(path), mode, str(SCRIPTS)],
                cwd=ROOT,
                env=_env(
                    {
                        "RAYFORGE_CONFIG_DIR": str(
                            _fresh_config(scratch, "import-config")
                        )
                    }
                ),
                capture_output=True,
                timeout=900,
                check=False,
            )
            line = next(
                (
                    ln
                    for ln in proc.stdout.decode("utf-8", "replace").split(
                        "\n"
                    )
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
            rss.append(data["rss_after"])
            footprint.append(data["footprint_after"])
        else:
            out[label] = {
                "import_s": _median(times),
                "rss_after_mb": _median(rss) / 2**20,
                "footprint_after_mb": _median(footprint) / 2**20,
                "samples": times,
            }
    return out


# -------------------------------------------------------------- encode


def _pytest(args, timeout=1800):
    proc = subprocess.run(
        [PYTHON, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider"] + args,
        cwd=ROOT,
        env=_env(),
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    text = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        raise RuntimeError(f"pytest {args} failed:\n{text[-3000:]}")
    return text


def encode(_scratch):
    """
    Ops generation (cold: the first build of the document) and Ruida
    encode per asset, on the send path (tests/perf/perf_encode.py), one
    fresh pytest process per run.
    """
    records = {}
    for _ in range(RUNS):
        text = _pytest(["tests/perf/perf_encode.py"])
        for line in text.splitlines():
            if line.startswith("PERFENCODE "):
                rec = json.loads(line[len("PERFENCODE ") :])
                records.setdefault(rec["asset"], []).append(rec)
    return {
        asset: {
            "ops_cold_ms": _median([r["ops_cold_ms"] for r in recs]),
            "encode_ms": _median([r["encode_ms"] for r in recs]),
            "ops_cold_samples": [r["ops_cold_ms"] for r in recs],
            "encode_samples": [r["encode_ms"] for r in recs],
            "op_count": recs[0]["op_count"],
            "rd_bytes": recs[0]["rd_bytes"],
        }
        for asset, recs in records.items()
    }


def layout(_scratch):
    """
    Auto Layout of the 40-piece benchmark (tests/perf/perf_auto_layout,
    forty-40: the pieces of tests/perf/forty.ryp). time is the first
    layout after launch (its worker pool starts cold), warm a second
    one; stall is the longest the event loop standing in for the main
    loop was blocked meanwhile.
    """
    keys = ("time", "warm", "stall", "warm_stall")
    runs = []
    for _ in range(RUNS):
        text = _pytest(
            ["tests/perf/perf_auto_layout.py", "-k", "test_layout and forty"]
        )
        line = next(ln for ln in text.splitlines() if ln.startswith("RESULT"))
        fields = dict(
            f.split("=", 1) for f in line.split() if "=" in f and "[" not in f
        )
        runs.append(
            {
                k: float(fields[k].rstrip("ms").rstrip("s"))
                * (0.001 if fields[k].endswith("ms") else 1.0)
                for k in keys
            }
        )
    return {f"{k}_s": _median([r[k] for r in runs]) for k in keys} | {
        "runs": runs
    }


# -------------------------------------------------------------- canvas

GESTURES = ("pan", "zoom", "pan_zoomed")
CANVAS_SCENES = (
    ("large.dxf", False),
    ("forty.ryp", True),
)


def _frames(runs, key):
    pooled = [ms for r in runs for ms in r[key]["frame_ms"]]
    intervals = [ms for r in runs for ms in r[key]["interval_ms"]]
    tail = [ms for r in runs for ms in r[key]["tail_frame_ms"]]
    return {
        "p50_ms": _pct(pooled, 0.5),
        "p95_ms": _pct(pooled, 0.95),
        "max_ms": max(pooled) if pooled else float("nan"),
        "frames": len(pooled),
        "interval_p95_ms": _pct(intervals, 0.95),
        # Intervals over 1.5 vsyncs at 60 Hz: a frame was missed.
        "missed": sum(1 for ms in intervals if ms > 25.0),
        "tail_max_ms": max(tail) if tail else 0.0,
        "per_run_p95_ms": [_pct(r[key]["frame_ms"], 0.95) for r in runs],
    }


def _canvas_runs(scratch, scene, select, extra=None):
    runs = []
    for _ in range(RUNS):
        env = {"PERF_SCENE": str(PERF_DIR / scene), "PERF_FRAMES": str(FRAMES)}
        if select:
            env["PERF_SELECT_ALL"] = "1"
        runs.append(
            _run_uiscript(scratch, "ui_canvas.py", env | (extra or {}))
        )
    first = runs[0]
    return {
        "renderer": first["renderer"],
        "scale_factor": first["scale_factor"],
        "canvas_px": first["canvas_px"],
        "selected": first["selected"],
        **{g: _frames(runs, g) for g in GESTURES},
    }


def canvas(scratch):
    """
    Pan and zoom frame times, before-paint to after-paint on the
    window's frame clock, pooled over the runs (scripts/perf/ui_canvas).
    """
    return {
        f"{scene}{'+selected' if select else ''}": _canvas_runs(
            scratch, scene, select
        )
        for scene, select in CANVAS_SCENES
    }


def renderers(scratch):
    """The large.dxf canvas run under each GSK renderer on offer."""
    out = {}
    for name in ("default", "cairo", "opengl", "vulkan"):
        extra = {} if name == "default" else {"GSK_RENDERER": name}
        try:
            out[name] = _canvas_runs(scratch, "large.dxf", False, extra)
        except RuntimeError as e:
            out[name] = {"error": str(e)[-500:]}
    return out


SHAPES_SCENES = ("many_shapes.dxf", "large.dxf")
SHAPES_GESTURES = ("pan", "pan_selected", "zoom", "drag")


def shapes(scratch):
    """
    Individual-shape import of SHAPES_SCENES and the canvas with those
    pieces loaded (scripts/perf/ui_shapes): import and settle time,
    the longest main-thread stall during the import, pan/zoom/drag
    frames, on_motion cost and fine hit tests, idle CPU.
    """
    out = {}
    for scene in SHAPES_SCENES:
        runs = [
            _run_uiscript(
                scratch,
                "ui_shapes.py",
                {
                    "PERF_SCENE": str(PERF_DIR / scene),
                    "PERF_FRAMES": str(FRAMES),
                },
            )
            for _ in range(RUNS)
        ]
        stalls = [ms for r in runs for ms in r["import"]["interval_ms"]]
        first = runs[0]
        out[scene] = {
            "pieces": first["import"]["pieces"],
            "renderer": first["renderer"],
            "scale_factor": first["scale_factor"],
            "imported_s": _median([r["import"]["imported_s"] for r in runs]),
            "settled_s": _median([r["import"]["settled_s"] for r in runs]),
            "stall_ms": _median(
                [r["import"]["longest_stall_ms"] for r in runs]
            ),
            "import_interval_p95_ms": _pct(stalls, 0.95),
            **{g: _frames(runs, g) for g in SHAPES_GESTURES},
            "hit": {
                k: _median([r["hit"][k] for r in runs])
                for k in (
                    "motion_ms_p50",
                    "motion_ms_p95",
                    "fine_tests_mean",
                    "fine_tests_max",
                )
            },
            "idle_cpu_pct": _median([r["idle"]["cpu_pct"] for r in runs]),
            "runs": [
                {
                    "imported_s": r["import"]["imported_s"],
                    "settled_s": r["import"]["settled_s"],
                    "stall_ms": r["import"]["longest_stall_ms"],
                    "hit": r["hit"],
                    "idle": r["idle"],
                }
                for r in runs
            ],
        }
    return out


def preview(scratch):
    """Job preview of two_layer.ryp at x16 (scripts/perf/ui_preview)."""
    runs = [
        _run_uiscript(
            scratch,
            "ui_preview.py",
            {
                "PERF_SCENE": str(PERF_DIR / "two_layer.ryp"),
                "PERF_FRAMES": str(FRAMES),
            },
        )
        for _ in range(RUNS)
    ]
    return {
        "preview_ready_s": _median([r["preview_ready_s"] for r in runs]),
        "segments": runs[0]["segments"],
        "job_s": runs[0]["total_s"],
        "play": _frames(runs, "play"),
        "scrub": _frames(runs, "scrub"),
    }


# ---------------------------------------------------------------- idle


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _top_power(pid, seconds):
    """
    Activity Monitor's energy figure (top's POWER) for one pid, once a
    second over `seconds`. top is setuid root, which a sandboxed process
    may not exec; under sandbox-exec, $PERF_TOP_DIR names a directory a
    sampler outside the sandbox serves (scripts/perf/top_sampler.sh).
    """
    if sys.platform != "darwin":
        return None
    argv = [
        "top",
        "-l",
        str(int(seconds) + 1),
        "-s",
        "1",
        "-pid",
        str(pid),
        "-stats",
        "pid,cpu,idlew,power",
    ]
    try:
        out = subprocess.run(
            argv, capture_output=True, text=True, check=False
        ).stdout
    except PermissionError:
        out = _top_via_sampler(pid, seconds)
        if out is None:
            return None
    power = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == str(pid):
            try:
                power.append(float(parts[3]))
            except ValueError:
                pass
    # The first sample has no interval behind it.
    return power[1:]


def _top_via_sampler(pid, seconds):
    """top's output for pid, from the sampler outside the sandbox."""
    folder = os.environ.get("PERF_TOP_DIR")
    if not folder:
        return None
    request = Path(folder) / "request"
    result = Path(folder) / "result"
    if result.exists():
        result.unlink()
    request.write_text(f"{pid} {int(seconds) + 1}", encoding="utf-8")
    deadline = time.monotonic() + seconds + 30
    while not result.exists():
        if time.monotonic() > deadline:
            return None
        time.sleep(0.2)
    # The sampler renames the finished file into place.
    return result.read_text(encoding="utf-8")


class _App:
    """An app launched to sit idle, measured from outside."""

    def __init__(self, scratch, simulator, scene, minimize=False):
        self.out = scratch / "idle.json"
        if self.out.exists():
            self.out.unlink()
        extra = {"PERF_OUT": str(self.out)}
        if scene:
            extra["PERF_SCENE"] = str(PERF_DIR / scene)
        if simulator:
            extra["PERF_WAIT_CONNECTED"] = "1"
        if minimize:
            extra["PERF_MINIMIZE"] = "1"
        # Open for the app's life; close() closes it.
        self.log = open(scratch / "idle-app.log", "wb")  # noqa: SIM115
        self.proc = subprocess.Popen(
            _app_cmd(
                _fresh_config(scratch, simulator=simulator),
                SCRIPTS / "ui_idle.py",
            ),
            cwd=ROOT,
            env=_env(extra),
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

    def wait_ready(self, timeout=300):
        deadline = time.monotonic() + timeout
        while not self.out.exists():
            if self.proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("the idle app never got ready")
            time.sleep(0.2)
        return json.loads(self.out.read_text(encoding="utf-8"))

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


class _Simulator:
    def __init__(self, scratch):
        self.log = open(scratch / "simulator.log", "wb")  # noqa: SIM115
        self.proc = subprocess.Popen(
            [PYTHON, str(SIMULATOR), "--host", "127.0.0.1"],
            cwd=ROOT,
            env=_env(),
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def _window(pid, seconds):
    """CPU, wakeups and energy of a process tree over seconds."""
    a = procstat.sample_tree(pid)
    t0 = time.monotonic()
    power = _top_power(pid, seconds)
    if power is None:
        time.sleep(seconds)
    elapsed = time.monotonic() - t0
    b = procstat.sample_tree(pid)
    both = [p for p in b if p in a]
    cpu = sum(b[p]["cpu_s"] - a[p]["cpu_s"] for p in both)
    main = b[pid]
    wakeups = None
    if main["idle_wakeups"] is not None:
        wakeups = sum(
            (b[p]["idle_wakeups"] + b[p]["interrupt_wakeups"])
            - (a[p]["idle_wakeups"] + a[p]["interrupt_wakeups"])
            for p in both
        )
    return {
        "cpu_pct": 100.0 * cpu / elapsed,
        "wakeups_per_s": wakeups / elapsed if wakeups is not None else None,
        "energy": _median(power) if power else None,
        "processes": len(b),
        "footprint_mb": sum(b[p]["footprint"] for p in b) / 2**20,
        "main_footprint_mb": main["footprint"] / 2**20,
    }


IDLE_VARIANTS = {
    "connected": {"simulator": True, "scene": "large.dxf"},
    "disconnected": {"simulator": False, "scene": "large.dxf"},
    "hidden": {"simulator": True, "scene": "large.dxf", "minimize": True},
}


def idle(scratch):
    """
    IDLE_S of idle per variant, after the app is up and settled: CPU %
    and wakeups/s of the app's process tree (never the simulator's),
    and top's POWER, which is Activity Monitor's Energy Impact.
    """
    if not _port_free(50200):
        return {"error": "UDP/TCP 50200 is taken; is a simulator running?"}
    out = {}
    for name, variant in IDLE_VARIANTS.items():
        runs = []
        for _ in range(RUNS):
            sim = _Simulator(scratch) if variant["simulator"] else None
            app = _App(scratch, **variant)
            try:
                ready = app.wait_ready()
                time.sleep(5.0)
                runs.append(_window(app.proc.pid, IDLE_S) | ready)
            finally:
                app.close()
                if sim:
                    sim.close()
        out[name] = {
            k: _median([r[k] for r in runs if r[k] is not None])
            for k in ("cpu_pct", "wakeups_per_s", "energy", "footprint_mb")
        } | {"connected": runs[0]["connected"], "runs": runs}
    return out


def soak(scratch):
    """
    Memory over SOAK_MIN minutes idle, connected to the simulator with
    large.dxf open: the footprint of the process tree every 30 s.
    """
    runs = []
    for _ in range(int(os.environ.get("PERF_SOAK_RUNS", "1"))):
        sim = _Simulator(scratch)
        app = _App(scratch, simulator=True, scene="large.dxf")
        try:
            app.wait_ready()
            time.sleep(5.0)
            series = []
            t0 = time.monotonic()
            while True:
                tree = procstat.sample_tree(app.proc.pid)
                series.append(
                    (
                        time.monotonic() - t0,
                        sum(s["footprint"] for s in tree.values()) / 2**20,
                        tree[app.proc.pid]["footprint"] / 2**20,
                        tree[app.proc.pid]["rss"] / 2**20,
                    )
                )
                if series[-1][0] >= SOAK_MIN * 60:
                    break
                time.sleep(30.0)
        finally:
            app.close()
            sim.close()
        first, last = series[0], series[-1]
        runs.append(
            {
                "minutes": last[0] / 60,
                "footprint_start_mb": first[1],
                "footprint_end_mb": last[1],
                "growth_mb": last[1] - first[1],
                "main_rss_start_mb": first[3],
                "main_rss_end_mb": last[3],
                "series": series,
            }
        )
    return {
        k: _median([r[k] for r in runs])
        for k in ("footprint_start_mb", "footprint_end_mb", "growth_mb")
    } | {"runs": runs}


# --------------------------------------------------------- arm64 audit

_CPU = {0x0100000C: "arm64", 0x01000007: "x86_64", 7: "i386", 12: "arm"}


def macho_archs(path):
    """The architectures of a Mach-O file; None if it is not one."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
            if len(head) < 8:
                return None
            magic = struct.unpack(">I", head[:4])[0]
            if magic in (0xCAFEBABE, 0xCAFEBABF):
                n = struct.unpack(">I", head[4:])[0]
                if n > 30:  # a Java class file shares this magic
                    return None
                size = 20 if magic == 0xCAFEBABE else 32
                archs = []
                for _ in range(n):
                    entry = fh.read(size)
                    cpu = struct.unpack(">i", entry[:4])[0]
                    archs.append(_CPU.get(cpu & 0xFFFFFFFF, hex(cpu)))
                return archs
            if magic in (0xCFFAEDFE, 0xCEFAEDFE):
                cpu = struct.unpack("<I", head[4:])[0]
                return [_CPU.get(cpu, hex(cpu))]
    except OSError:
        return None
    return None


def _arch_scan(root):
    """
    The Mach-O files under root, by architecture: libraries by suffix,
    and any executable file (a Mach-O has no suffix to go by).
    """
    counts, foreign = {}, []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = Path(dirpath) / name
            if path.is_symlink() or (
                path.suffix not in (".so", ".dylib")
                and not os.access(path, os.X_OK)
            ):
                continue
            archs = macho_archs(path)
            if archs is None:
                continue
            key = "+".join(sorted(set(archs)))
            counts[key] = counts.get(key, 0) + 1
            if "arm64" not in archs:
                foreign.append(str(path.relative_to(root)))
    return {"by_arch": counts, "without_arm64": foreign[:50]}


def arch(_scratch):
    """Every Mach-O in the environment and the bundle, by architecture."""
    prefix = Path(sys.prefix)
    out = {
        "python": {
            "machine": os.uname().machine,
            "executable": sys.executable,
            "archs": macho_archs(Path(sys.executable).resolve()),
        },
        "env": _arch_scan(prefix),
    }
    if sys.platform == "darwin":
        translated = subprocess.run(
            ["sysctl", "-n", "sysctl.proc_translated"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        out["python"]["rosetta"] = translated == "1"
    if APP_BUNDLE.is_dir():
        out["bundle"] = _arch_scan(APP_BUNDLE)
    return out


# -------------------------------------------------------------- bundle


def bundle(scratch):
    """The built .app: its size, and its start against a source start."""
    if not APP_BUNDLE.is_dir():
        return {"error": "dist/SwiftCut.app not built (pixi run build-mac)"}
    total, count = 0, 0
    for path in APP_BUNDLE.rglob("*"):
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
            count += 1
    out = {"mb": total / 2**20, "files": count}
    dmg = APP_BUNDLE.parent / "SwiftCut.dmg"
    if dmg.exists():
        out["dmg_mb"] = dmg.stat().st_size / 2**20
    if not _port_free(GUARD_PORT):
        out["launch"] = {"error": "SwiftCut is running; bundle start skipped"}
        return out
    exe = APP_BUNDLE / "Contents" / "MacOS" / "SwiftCut"
    mark, splash_mark = scratch / "mapped.stamp", scratch / "splash.stamp"
    samples, splash = [], []
    for n in range(RUNS + 1):
        for stamp in (mark, splash_mark):
            if stamp.exists():
                stamp.unlink()
        started = time.time()
        subprocess.run(
            [
                str(exe),
                "--config",
                str(_fresh_config(scratch)),
                "--uiscript",
                str(SCRIPTS / "mark_mapped.py"),
            ],
            env=dict(
                os.environ,
                PERF_MARK_FILE=str(mark),
                PERF_SPLASH_MARK_FILE=str(splash_mark),
            ),
            capture_output=True,
            timeout=300,
            check=False,
        )
        if n == 0 or not mark.exists():
            continue
        samples.append(float(mark.read_text(encoding="utf-8")) - started)
        if splash_mark.exists():
            splash.append(
                float(splash_mark.read_text(encoding="utf-8")) - started
            )
    out["launch"] = {
        "cold_start_s": _median(samples),
        "samples": samples,
        "splash_s": _median(splash),
    }
    return out


# -------------------------------------------------------------- report


def _f(value, fmt="{:.2f}"):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return fmt.format(value)


def report(_scratch, results=None):
    """The P0 table, as markdown, from build/perf/results.json."""
    r = results or json.loads(
        (ROOT / "build" / "perf" / "results.json").read_text("utf-8")
    )
    rows = []

    def row(metric, value, note=""):
        rows.append(f"| {metric} | {value} | {note} |")

    if "cold" in r:
        c = r["cold"]
        row(
            "a) cold start, spawn -> window mapped",
            f"{_f(c['cold_start_s'])} s",
        )
        row("a) cold start, spawn -> splash up", f"{_f(c['splash_s'])} s")

    def entries(step):
        """A step's per-item results, without its measured_at stamp."""
        return [
            (k, v) for k, v in r.get(step, {}).items() if isinstance(v, dict)
        ]

    for label, v in entries("import"):
        row(
            f"b) import {label}",
            f"{_f(v.get('import_s'), '{:.3f}')} s",
            f"footprint {_f(v.get('footprint_after_mb'), '{:.0f}')} MB",
        )
    for asset, v in entries("encode"):
        row(f"c) ops {asset} (cold)", f"{_f(v['ops_cold_ms'], '{:.0f}')} ms")
        row(
            f"c) Ruida encode {asset}",
            f"{_f(v['encode_ms'], '{:.1f}')} ms",
            f"{v['op_count']} ops, {v['rd_bytes']} B",
        )
    for scene, v in entries("canvas"):
        if "error" in v:
            continue
        for g in GESTURES:
            row(
                f"d) {scene} {g}",
                f"p50 {_f(v[g]['p50_ms'], '{:.1f}')} / "
                f"p95 {_f(v[g]['p95_ms'], '{:.1f}')} ms",
                f"{v['renderer']} x{v['scale_factor']}, "
                f"{v[g]['missed']} missed of {v[g]['frames']}",
            )
    if "layout" in r:
        v = r["layout"]
        row(
            "e) auto-layout 40 pieces",
            f"{_f(v['time_s'])} s",
            f"warm {_f(v['warm_s'])} s, longest stall "
            f"{_f(v['stall_s'] * 1000, '{:.0f}')} ms",
        )
    if "preview" in r:
        v = r["preview"]
        row("f) preview ready", f"{_f(v['preview_ready_s'])} s")
        for k in ("play", "scrub"):
            row(
                f"f) preview {k}",
                f"p50 {_f(v[k]['p50_ms'], '{:.1f}')} / "
                f"p95 {_f(v[k]['p95_ms'], '{:.1f}')} ms",
                f"{v[k]['missed']} missed of {v[k]['frames']}",
            )
    for scene, v in entries("shapes"):
        name = f"{scene} ({v['pieces']} pieces)"
        row(
            f"j) import {name}",
            f"{_f(v['imported_s'])} s",
            f"settled {_f(v['settled_s'])} s, longest stall "
            f"{_f(v['stall_ms'], '{:.0f}')} ms",
        )
        for g in SHAPES_GESTURES:
            row(
                f"j) {scene} {g}",
                f"p50 {_f(v[g]['p50_ms'], '{:.1f}')} / "
                f"p95 {_f(v[g]['p95_ms'], '{:.1f}')} ms",
                f"{v['renderer']} x{v['scale_factor']}, "
                f"{v[g]['missed']} missed of {v[g]['frames']}",
            )
        hit = v["hit"]
        row(
            f"j) {scene} hit test per motion",
            f"p50 {_f(hit['motion_ms_p50'])} / "
            f"p95 {_f(hit['motion_ms_p95'])} ms",
            f"fine tests mean {_f(hit['fine_tests_mean'], '{:.0f}')}, "
            f"max {_f(hit['fine_tests_max'], '{:.0f}')}",
        )
        row(f"j) {scene} idle", f"{_f(v['idle_cpu_pct'])} % CPU")
    for name, v in entries("idle"):
        if "error" in v:
            continue
        row(
            f"g) idle {name}",
            f"{_f(v['cpu_pct'])} % CPU",
            f"{_f(v['wakeups_per_s'], '{:.0f}')} wakeups/s, "
            f"energy {_f(v['energy'], '{:.1f}')}",
        )
    if "soak" in r:
        v = r["soak"]
        row(
            "h) footprint over idle soak",
            f"{_f(v['footprint_start_mb'], '{:.0f}')} -> "
            f"{_f(v['footprint_end_mb'], '{:.0f}')} MB",
            f"growth {_f(v['growth_mb'], '{:+.1f}')} MB",
        )
    if "bundle" in r and "mb" in r["bundle"]:
        v = r["bundle"]
        row(
            "i) .app size",
            f"{_f(v['mb'], '{:.0f}')} MB",
            f"{v['files']} files",
        )
        launch = v.get("launch", {})
        if "cold_start_s" in launch:
            row("i) .app start -> window", f"{_f(launch['cold_start_s'])} s")
    table = "| metric | median | note |\n| --- | --- | --- |\n" + "\n".join(
        rows
    )
    print(table)
    return {"markdown": table}


STEPS = {
    "arch": arch,
    "cold": cold_start,
    "importtime": import_time_profile,
    "import": asset_imports,
    "encode": encode,
    "layout": layout,
    "canvas": canvas,
    "shapes": shapes,
    "preview": preview,
    "idle": idle,
    "soak": soak,
    "bundle": bundle,
    "renderers": renderers,
    "report": report,
}
# `pixi run bench` with no arguments: the P0 table. renderers is the P1
# comparison, run on its own.
DEFAULT = [s for s in STEPS if s != "renderers"]


def main(argv):
    wanted = argv[1:] or DEFAULT
    scratch = ROOT / "build" / "perf"
    scratch.mkdir(parents=True, exist_ok=True)
    store = scratch / "results.json"
    merged = {}
    if store.exists():
        try:
            merged = json.loads(store.read_text(encoding="utf-8"))
        except ValueError:
            merged = {}
    for key in wanted:
        if key not in STEPS:
            print(f"unknown step {key!r}; known: {', '.join(STEPS)}")
            return 2
    with _KeepLogs(scratch):
        for key in wanted:
            print(f"--- {key} ---", flush=True)
            if key == "report":
                report(scratch, merged)
                continue
            merged[key] = STEPS[key](scratch)
            merged[key]["measured_at"] = time.strftime("%Y-%m-%d %H:%M")
            print(json.dumps(merged[key], default=str)[:2000], flush=True)
            # Written after every step, so an interrupted run keeps
            # what it measured.
            store.write_text(
                json.dumps(merged, indent=2, default=str), encoding="utf-8"
            )
    print(f"\nwrote {store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

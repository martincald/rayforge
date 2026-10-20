"""Per-process CPU time, wakeups and memory, without psutil.

macOS reads ``proc_pid_rusage`` from libproc, the counters Activity
Monitor itself shows: ``phys_footprint`` is its Memory column and
``pkg_idle_wkups`` its Idle Wake Ups. No root is needed for a process
of the same user. Linux reads /proc and has no wakeup counter. Windows
keeps the Win32 working set the first audit (docs/PERF_AUDIT.md) used.

Importable from a measured child (``sample(os.getpid())``) and from the
harness alike; standard library only, so importing it moves nothing.
"""

import ctypes
import os
import subprocess
import sys

_RUSAGE_INFO_V2 = 2


class _RusageInfoV2(ctypes.Structure):
    _fields_ = [
        ("uuid", ctypes.c_uint8 * 16),
        ("user_time", ctypes.c_uint64),
        ("system_time", ctypes.c_uint64),
        ("pkg_idle_wkups", ctypes.c_uint64),
        ("interrupt_wkups", ctypes.c_uint64),
        ("pageins", ctypes.c_uint64),
        ("wired_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("phys_footprint", ctypes.c_uint64),
        ("proc_start_abstime", ctypes.c_uint64),
        ("proc_exit_abstime", ctypes.c_uint64),
        ("child_user_time", ctypes.c_uint64),
        ("child_system_time", ctypes.c_uint64),
        ("child_pkg_idle_wkups", ctypes.c_uint64),
        ("child_interrupt_wkups", ctypes.c_uint64),
        ("child_pageins", ctypes.c_uint64),
        ("child_elapsed_abstime", ctypes.c_uint64),
        ("diskio_bytesread", ctypes.c_uint64),
        ("diskio_byteswritten", ctypes.c_uint64),
    ]


class _Timebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


_libproc = None
_ns_per_tick = 1.0
if sys.platform == "darwin":
    _libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    _libproc.proc_pid_rusage.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(_RusageInfoV2),
    ]
    _libproc.proc_pid_rusage.restype = ctypes.c_int
    # On Apple Silicon the rusage times are mach ticks, not ns
    # (24 MHz: 125/3 ns a tick); on Intel the ratio is 1/1.
    _libsys = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    _tb = _Timebase()
    _libsys.mach_timebase_info(ctypes.byref(_tb))
    _ns_per_tick = _tb.numer / _tb.denom


def sample(pid: int) -> dict:
    """
    Cumulative counters of one process: cpu_s (user + system),
    idle_wakeups and interrupt_wakeups (None off macOS), and rss and
    footprint in bytes (footprint is rss off macOS).
    """
    if _libproc is not None:
        info = _RusageInfoV2()
        if _libproc.proc_pid_rusage(pid, _RUSAGE_INFO_V2, ctypes.byref(info)):
            raise OSError(ctypes.get_errno(), f"proc_pid_rusage({pid})")
        return {
            "cpu_s": (info.user_time + info.system_time) * _ns_per_tick / 1e9,
            "idle_wakeups": info.pkg_idle_wkups,
            "interrupt_wakeups": info.interrupt_wkups,
            "rss": info.resident_size,
            "footprint": info.phys_footprint,
        }
    if sys.platform.startswith("linux"):
        with open(f"/proc/{pid}/stat") as fh:
            fields = fh.read().rsplit(")", 1)[1].split()
        ticks = os.sysconf("SC_CLK_TCK")
        with open(f"/proc/{pid}/statm") as fh:
            pages = int(fh.read().split()[1])
        rss = pages * os.sysconf("SC_PAGE_SIZE")
        return {
            "cpu_s": (int(fields[11]) + int(fields[12])) / ticks,
            "idle_wakeups": None,
            "interrupt_wakeups": None,
            "rss": rss,
            "footprint": rss,
        }
    if sys.platform == "win32":
        rss = _win32_working_set()
        return {
            "cpu_s": None,
            "idle_wakeups": None,
            "interrupt_wakeups": None,
            "rss": rss,
            "footprint": rss,
        }
    raise NotImplementedError(sys.platform)


def _win32_working_set() -> int:
    """The current process's working set (the first audit's metric)."""
    assert sys.platform == "win32"
    import ctypes.wintypes as wt

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

    # argtypes/restype are load-bearing: without them ctypes passes the
    # HANDLE as a 32-bit int on win64 and WorkingSetSize reads back 0.
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wt.HANDLE
    k32.GetCurrentProcess.argtypes = []
    psapi.GetProcessMemoryInfo.restype = wt.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [
        wt.HANDLE,
        ctypes.POINTER(_Counters),
        wt.DWORD,
    ]
    counters = _Counters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(
        k32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.WorkingSetSize


def tree(pid: int) -> list[int]:
    """The process and all its descendants (macOS and Linux)."""
    pids, todo = [], [pid]
    while todo:
        current = todo.pop()
        pids.append(current)
        out = subprocess.run(
            ["pgrep", "-P", str(current)],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        todo.extend(int(p) for p in out.split())
    return pids


def sample_tree(pid: int) -> dict[int, dict]:
    """sample() of the process and each live descendant, by pid."""
    samples = {}
    for p in tree(pid):
        try:
            samples[p] = sample(p)
        except OSError:
            pass  # exited between listing and sampling
    return samples

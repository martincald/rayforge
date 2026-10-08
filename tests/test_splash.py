"""
The macOS splash (swiftcut.splash): spawned before GTK, closed on the
main window's map and on every early exit, never fatal.

PyObjC, Popen and the watchdog threads are faked, so these run on any
platform and never put a window on screen. app.py is checked through
its syntax tree: importing it has process-wide side effects (locale,
gettext, LANGUAGE).
"""

import ast
import ctypes
import os
import runpy
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from swiftcut import splash

ROOT = Path(__file__).resolve().parent.parent
APP_PY = ROOT / "swiftcut" / "app.py"
RTHOOK = ROOT / "scripts" / "mac" / "pyi_rth_splash.py"
SPEC = ROOT / "SwiftCut.macos.spec"


@pytest.fixture(autouse=True)
def no_splash_left(monkeypatch):
    monkeypatch.setattr(splash, "_proc", None)


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "swiftcut_splash.png"
    path.write_bytes(b"png")
    return path


@pytest.fixture
def popen(monkeypatch):
    """A recording Popen on a fake darwin."""
    fake = MagicMock(name="Popen")
    monkeypatch.setattr(splash.subprocess, "Popen", fake)
    monkeypatch.setattr(sys, "platform", "darwin")
    return fake


# ------------------------------------------------------------- spawn


def test_spawn_does_nothing_off_macos(popen, image, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    splash.spawn(image)

    popen.assert_not_called()
    assert splash._proc is None


def test_spawn_does_nothing_without_the_image(popen, tmp_path):
    splash.spawn(tmp_path / "missing.png")

    popen.assert_not_called()
    assert splash._proc is None


def test_spawn_from_source_runs_the_module(popen, image, monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    splash.spawn(image)

    popen.assert_called_once_with(
        [sys.executable, "-m", "swiftcut.splash", str(image)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert splash._proc is popen.return_value


def test_spawn_in_the_bundle_relaunches_with_the_flag(
    popen, image, monkeypatch
):
    monkeypatch.setattr(sys, "_MEIPASS", "/bundle", raising=False)

    splash.spawn(image)

    argv = popen.call_args.args[0]
    assert argv == [sys.executable, "--swiftcut-splash", str(image)]


def test_a_second_spawn_while_one_is_up_starts_nothing(popen, image):
    splash.spawn(image)
    splash.spawn(image)

    popen.assert_called_once()


def test_spawn_failure_is_swallowed(popen, image):
    popen.side_effect = OSError("no fork")

    splash.spawn(image)

    assert splash._proc is None


# ------------------------------------------------------------- close


def test_close_terminates_once_and_is_idempotent(monkeypatch):
    proc = MagicMock(name="proc")
    monkeypatch.setattr(splash, "_proc", proc)

    splash.close()
    splash.close()

    proc.terminate.assert_called_once_with()
    proc.wait.assert_called_once_with(timeout=1)
    proc.stdin.close.assert_called_once_with()
    assert splash._proc is None


def test_close_without_a_splash_does_nothing():
    splash.close()

    assert splash._proc is None


def test_close_failure_is_swallowed_and_stdin_still_closes(monkeypatch):
    proc = MagicMock(name="proc")
    proc.terminate.side_effect = ProcessLookupError()
    monkeypatch.setattr(splash, "_proc", proc)

    splash.close()

    proc.stdin.close.assert_called_once_with()
    assert splash._proc is None


# --------------------------------------------------------------- run


@pytest.fixture
def threads(monkeypatch):
    """The watchdog threads, recorded rather than started."""
    fake = MagicMock(name="threading")
    monkeypatch.setattr(splash, "threading", fake)
    return fake


@pytest.fixture
def appkit(monkeypatch, threads):
    """Fake AppKit classes, handed out by a fake objc.lookUpClass. The
    framework load is recorded as appkit.load."""
    fake = MagicMock(name="AppKit")
    _image(fake).size.return_value = (480.0, 320.0)
    fake.objc.lookUpClass.side_effect = lambda name: getattr(fake, name)
    monkeypatch.setitem(sys.modules, "objc", fake.objc)
    monkeypatch.setattr(ctypes.cdll, "LoadLibrary", fake.load)
    return fake


def _image(appkit):
    alloc = appkit.NSImage.alloc.return_value
    return alloc.initWithContentsOfFile_.return_value


def _window(appkit):
    alloc = appkit.NSWindow.alloc.return_value
    return alloc.initWithContentRect_styleMask_backing_defer_


def test_run_without_the_image_never_touches_appkit(appkit, threads, tmp_path):
    assert splash.run([str(tmp_path / "missing.png")]) == 1
    assert splash.run([]) == 1

    assert appkit.mock_calls == []
    assert threads.mock_calls == []


def test_run_loads_only_appkit_and_the_classes_it_uses(appkit, image):
    splash.run([str(image)])

    appkit.load.assert_called_once_with(
        "/System/Library/Frameworks/AppKit.framework/AppKit"
    )
    looked_up = {c.args[0] for c in appkit.objc.lookUpClass.call_args_list}
    assert looked_up == {
        "NSApplication",
        "NSImage",
        "NSWindow",
        "NSColor",
        "NSImageView",
    }


def test_run_shows_a_borderless_floating_window_without_focus(appkit, image):
    assert splash.run([str(image)]) == 0

    nsapp = appkit.NSApplication.sharedApplication.return_value
    nsapp.setActivationPolicy_.assert_called_once_with(1)  # no Dock tile
    _window(appkit).assert_called_once_with(
        ((0, 0), (480.0, 320.0)), 0, 2, False
    )
    window = _window(appkit).return_value
    window.setOpaque_.assert_called_once_with(False)
    window.setLevel_.assert_called_once_with(3)
    window.center.assert_called_once_with()
    window.orderFrontRegardless.assert_called_once_with()
    window.makeKeyAndOrderFront_.assert_not_called()
    nsapp.activateIgnoringOtherApps_.assert_not_called()
    nsapp.run.assert_called_once_with()


def test_run_starts_the_eof_watchdog_and_the_time_cap(appkit, threads, image):
    splash.run([str(image)])

    threads.Thread.assert_called_once_with(
        target=splash._exit_on_eof, daemon=True
    )
    threads.Thread.return_value.start.assert_called_once_with()
    threads.Timer.assert_called_once_with(60, os._exit, args=(0,))
    cap = threads.Timer.return_value
    assert cap.daemon is True
    cap.start.assert_called_once_with()


def test_run_stamps_the_moment_the_window_is_up(
    appkit, image, tmp_path, monkeypatch
):
    mark = tmp_path / "splash.stamp"
    monkeypatch.setenv("PERF_SPLASH_MARK_FILE", str(mark))
    before = time.time()

    splash.run([str(image)])

    assert before <= float(mark.read_text(encoding="utf-8")) <= time.time()


def test_run_with_an_unreadable_image_shows_nothing(appkit, image):
    alloc = appkit.NSImage.alloc.return_value
    alloc.initWithContentsOfFile_.return_value = None

    assert splash.run([str(image)]) == 1
    appkit.NSWindow.alloc.assert_not_called()


def test_the_child_exits_when_its_stdin_closes():
    """The splash dies with the app: EOF on stdin ends the process."""
    code = textwrap.dedent(
        """
        import threading, time
        from swiftcut import splash
        threading.Thread(target=splash._exit_on_eof, daemon=True).start()
        time.sleep(30)
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, cwd=ROOT
    )
    assert proc.stdin is not None
    proc.stdin.close()

    assert proc.wait(timeout=20) == 0


def test_the_child_exits_when_its_stdin_is_unreadable():
    """A splash that cannot read stdin cannot see the app go away, so
    it exits at once rather than outliving it."""
    code = textwrap.dedent(
        """
        import os, threading, time
        from swiftcut import splash
        os.close(0)
        threading.Thread(target=splash._exit_on_eof, daemon=True).start()
        time.sleep(30)
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, cwd=ROOT
    )

    assert proc.wait(timeout=20) == 0


# --------------------------------------------------- frozen dispatch


@pytest.fixture
def run(monkeypatch):
    fake = MagicMock(name="run", return_value=0)
    monkeypatch.setattr(splash, "run", fake)
    return fake


@pytest.fixture
def spawn(monkeypatch):
    """A recording spawn, in a fake bundle."""
    fake = MagicMock(name="spawn")
    monkeypatch.setattr(splash, "spawn", fake)
    monkeypatch.setattr(sys, "_MEIPASS", "/bundle", raising=False)
    return fake


def _exec_rthook(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", argv)
    return runpy.run_path(str(RTHOOK))


def test_rthook_runs_the_splash_for_the_flag_and_exits(
    run, spawn, monkeypatch
):
    with pytest.raises(SystemExit) as exit_info:
        _exec_rthook(["SwiftCut", "--swiftcut-splash", "x.png"], monkeypatch)

    run.assert_called_once_with(["x.png"])
    assert exit_info.value.code == 0
    spawn.assert_not_called()


def test_rthook_splash_child_failure_exits_quietly(spawn, monkeypatch):
    monkeypatch.setattr(
        splash, "run", MagicMock(side_effect=RuntimeError("no AppKit"))
    )
    with pytest.raises(SystemExit) as exit_info:
        _exec_rthook(["SwiftCut", "--swiftcut-splash", "x.png"], monkeypatch)

    assert exit_info.value.code == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["SwiftCut"],
        ["SwiftCut", "drawing.svg"],
        ["SwiftCut", "--uiscript", "x.py"],
    ],
)
def test_rthook_spawns_the_splash_for_an_app_launch(
    argv, run, spawn, monkeypatch
):
    _exec_rthook(argv, monkeypatch)

    spawn.assert_called_once_with(Path("/bundle") / "swiftcut_splash.png")
    run.assert_not_called()


@pytest.mark.parametrize(
    "argv",
    [
        ["SwiftCut", "--multiprocessing-fork", "tracker_fd=5"],
        ["SwiftCut", "-B", "-c", "from multiprocessing import x"],
        ["SwiftCut", "-m", "module"],
        ["SwiftCut", "-h"],
        ["SwiftCut", "--help"],
        ["SwiftCut", "--version"],
        ["SwiftCut", "drawing.svg", "--swiftcut-splash"],
    ],
)
def test_rthook_spawns_nothing_for_workers_helpers_help_or_version(
    argv, run, spawn, monkeypatch
):
    _exec_rthook(argv, monkeypatch)

    spawn.assert_not_called()
    run.assert_not_called()


def test_rthook_spawn_failure_is_swallowed(run, spawn, monkeypatch):
    spawn.side_effect = RuntimeError("no splash")

    _exec_rthook(["SwiftCut"], monkeypatch)

    spawn.assert_called_once()


def test_rthook_leaves_nothing_in_the_namespace_app_py_shares(
    run, spawn, monkeypatch
):
    hook_globals = _exec_rthook(["SwiftCut"], monkeypatch)

    assert "_pyi_rthook" not in hook_globals


def test_the_hooks_splash_is_the_one_main_and_the_map_see(
    popen, image, monkeypatch
):
    """In the bundle the hook spawns the splash; main()'s spawn then
    starts no second one, and the map's close takes the hook's down."""
    monkeypatch.setattr(sys, "_MEIPASS", str(image.parent), raising=False)

    _exec_rthook(["SwiftCut"], monkeypatch)
    splash.spawn(image)  # main()

    popen.assert_called_once()
    argv = popen.call_args.args[0]
    assert argv == [sys.executable, "--swiftcut-splash", str(image)]
    splash.close()  # _close_splash, from the main window's map
    popen.return_value.terminate.assert_called_once_with()


def test_the_splash_hook_runs_before_every_other_runtime_hook():
    tree = ast.parse(SPEC.read_text())
    hooks = next(
        kw.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "runtime_hooks"
    )
    assert isinstance(hooks, ast.List)
    first = hooks.elts[0]
    assert isinstance(first, ast.Constant)
    assert first.value == "scripts/mac/pyi_rth_splash.py"


# ------------------------------------------------------ app.py wiring


def _function(name):
    tree = ast.parse(APP_PY.read_text())
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _is_splash_call(node, attr):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "splash"
    )


def _lines_of(node, attr):
    return [
        n.lineno
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and _is_splash_call(n, attr)
    ]


def test_main_spawns_the_splash_before_importing_gtk():
    main = _function("main")
    gi_import = min(
        n.lineno
        for n in ast.walk(main)
        if isinstance(n, ast.Import) and n.names[0].name == "gi"
    )

    spawns = _lines_of(main, "spawn")

    assert len(spawns) == 1
    assert spawns[0] < gi_import


def test_main_shows_no_splash_for_help_or_version():
    main = _function("main")
    guard = next(
        n
        for n in ast.walk(main)
        if isinstance(n, ast.If) and _lines_of(n, "spawn")
    )

    flags = {
        n.value
        for n in ast.walk(guard.test)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }

    assert flags == {"-h", "--help", "--version"}


def test_the_window_map_closes_the_splash_on_macos_too():
    """_close_splash (the map handler's call) closes it before its
    darwin early return."""
    close_splash = _function("_close_splash")
    darwin_return = next(
        n.lineno
        for n in ast.walk(close_splash)
        if isinstance(n, ast.If) and isinstance(n.body[0], ast.Return)
    )

    closes = _lines_of(close_splash, "close")

    assert closes and closes[0] < darwin_return
    mapped = _function("_on_window_mapped")
    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_close_splash"
        for n in ast.walk(mapped)
    )


def test_an_unhandled_exception_closes_the_splash():
    assert _lines_of(_function("handle_exception"), "close")


def test_a_second_instance_closes_its_splash_before_returning():
    main = _function("main")
    second = next(
        n
        for n in ast.walk(main)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.UnaryOp)
        and "acquire" in ast.unparse(n.test)
    )

    assert _lines_of(second, "close")
    assert isinstance(second.body[-1], ast.Return)


def test_a_startup_with_no_window_closes_the_splash():
    main = _function("main")
    no_window = next(
        n
        for n in ast.walk(main)
        if isinstance(n, ast.If) and ast.unparse(n.test) == "app.win is None"
    )

    assert _lines_of(no_window, "close")

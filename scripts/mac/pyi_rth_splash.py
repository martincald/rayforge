# PyInstaller runtime hook: the macOS splash, before anything else.
#
# Custom runtime hooks run before PyInstaller's own and before app.py,
# so this is the bundle's first Python. An app launch spawns the
# splash child here (swiftcut.splash.spawn); app.main() then finds it
# up and spawns no second one, and the main window's map closes it.
# The child is this same executable with --swiftcut-splash, which this
# hook routes straight to swiftcut.splash.run: it skips the setuptools
# import, the GdkPixbuf loader cache (a temp file it would leak when
# terminated) and all of the app's startup. Multiprocessing workers
# and helpers and -h/--help/--version pass through untouched. Any
# failure only means no splash.
#
# The hooks share __main__'s namespace with app.py, hence the function.


def _pyi_rthook():
    import sys

    if sys.argv[1:2] == ["--swiftcut-splash"]:
        try:
            from swiftcut.splash import run

            code = run(sys.argv[2:])
        except Exception:  # noqa: BLE001
            # A broken splash must not raise PyInstaller's error dialog.
            code = 1
        sys.exit(code)

    no_splash = {
        "--swiftcut-splash",
        "--multiprocessing-fork",
        "-c",
        "-m",
        "-h",
        "--help",
        "--version",
    }
    if no_splash & set(sys.argv[1:]):
        return
    try:
        from pathlib import Path

        from swiftcut import splash

        splash.spawn(Path(sys._MEIPASS) / "swiftcut_splash.png")
    except Exception:  # noqa: BLE001, S110 - no splash, never a crash
        pass


_pyi_rthook()
del _pyi_rthook

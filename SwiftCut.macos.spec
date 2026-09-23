# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import gi as _gi_hooks

# conda-forge (pixi) typelibs name their libraries bare, e.g.
# "libgio-2.0.0.dylib", and PyInstaller resolves a bare name only
# through DYLD_LIBRARY_PATH - which, exported, would also hand every
# library the build's helper processes load the environment's copy
# (cv2 then fails on iconv). Instead the environment's lib/ goes on
# pathex, which PyInstaller adds to that search for the typelibs'
# libraries only, and the GI hooks' own lookup is pointed at it.
_pathex = ['.']
_binaries = []
if os.path.isdir(os.path.join(sys.prefix, 'conda-meta')):
    _pathex.append(os.path.join(sys.prefix, 'lib'))
    # pyvips loads libvips by name at runtime, so nothing points
    # PyInstaller at it; the Windows build adds its DLL the same way.
    _libvips = os.path.join(sys.prefix, 'lib', 'libvips.42.dylib')
    _binaries.append((_libvips, '.'))
    _find_library = _gi_hooks.findSystemLibrary

    def _find_in_env(name):
        path = os.path.join(sys.prefix, 'lib', name)
        return path if os.path.isfile(path) else _find_library(name)

    _gi_hooks.findSystemLibrary = _find_in_env

hiddenimports = ['gi._gi_cairo', 'cairosvg']
hiddenimports += collect_submodules('swiftcut.ui_gtk.canvas2d')
hiddenimports += collect_submodules('swiftcut.ui_gtk.canvas2d.elements')
hiddenimports += collect_submodules('swiftcut.ui_gtk.shared')
hiddenimports += collect_submodules('swiftcut.image')
hiddenimports += collect_submodules('swiftcut.core')
hiddenimports.append('swiftcut.ui_gtk.canvas2d.elements.workpiece')

# Use modern .icon (via Assets.car) when available, fall back to .icns.
_use_car = os.path.exists('Assets.car')
_icon = None if _use_car else 'swiftcut.icns'

_datas = [
    ('swiftcut/version.txt', 'swiftcut'),
    ('swiftcut/resources', 'swiftcut/resources'),
    ('swiftcut/locale', 'swiftcut/locale'),
    ('swiftcut/builtin_addons', 'swiftcut/builtin_addons'),
]
if _use_car:
    _datas.append(('Assets.car', '.'))

a = Analysis(
    ['swiftcut/app.py'],
    pathex=_pathex,
    binaries=_binaries,
    datas=_datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],
    hooksconfig={
        'gi': {
            'module-versions': {
                'Gtk': '4.0',
                'Adw': '1',
            },
        },
    },
    runtime_hooks=['scripts/mac/pyi_rth_cffi_bundle.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SwiftCut',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[_icon] if _icon else [],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SwiftCut',
)
app = BUNDLE(
    coll,
    name='SwiftCut.app',
    icon=_icon,
    bundle_identifier='org.ilab.SwiftCut',
    info_plist={
        **({'CFBundleIconName': 'swiftcut'} if _use_car else {}),
        'CFBundleName': 'SwiftCut',
        'CFBundleDisplayName': 'SwiftCut',
        'NSHighResolutionCapable': True,
        # Asked the first time the app reaches the cutter over UDP;
        # without it macOS 15+ silently blocks local-network traffic.
        'NSLocalNetworkUsageDescription': (
            'SwiftCut talks to the laser cutter on the local network'
        ),
        'LSMinimumSystemVersion': '12.0',
    },
)

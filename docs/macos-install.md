# SwiftCut on macOS

## Installing

1. Open `SwiftCut.dmg`.
2. Drag **SwiftCut** onto the **Applications** folder beside it.
3. Eject the disk image and start SwiftCut from Applications or
   Launchpad.

### The first launch: Gatekeeper

SwiftCut is signed ad hoc, not with an Apple Developer ID, and it is
not notarized yet. macOS therefore refuses the first launch of a copy
downloaded from the internet with *"Apple could not verify “SwiftCut”
is free of malware"*. You allow it once; after that it starts
normally.

**macOS 14 Sonoma and earlier.** In Applications, right-click (or
Control-click) SwiftCut, choose **Open**, then **Open** again in the
dialog.

**macOS 15 Sequoia and later.** Right-click → Open no longer offers a
way past this dialog. Instead:

1. Double-click SwiftCut and dismiss the dialog with **Done**.
2. Open **System Settings → Privacy & Security** and scroll to the
   **Security** section. It says *"“SwiftCut” was blocked to protect
   your Mac"*.
3. Click **Open Anyway**, confirm with your password or Touch ID, and
   click **Open Anyway** once more in the dialog that follows.

Either way, the first time SwiftCut reaches the laser cutter macOS
asks whether it may find devices on your local network. Answer
**Allow**: without it the controller never replies. The choice can be
changed later in **System Settings → Privacy & Security → Local
Network**.

## Where SwiftCut keeps things

| What | Where |
| --- | --- |
| Settings, machines, recipes | `~/Library/Application Support/swiftcut/` |
| Logs | `~/Library/Logs/SwiftCut/` |

## Building the app and the disk image

```bash
pixi run build-mac
```

This produces `dist/SwiftCut.app` and `dist/SwiftCut.dmg` from the
pixi environment, which already carries GTK 4, libadwaita, PyGObject
and every other dependency (`scripts/mac/mac_build.sh --pixi --all`).
PyInstaller, the one tool the environment lacks, is installed into
`build/mac-pyinstaller-<version>/` and run on the environment's own
interpreter, so it bundles exactly what the app runs on. The app is
signed ad hoc (`codesign --force --deep -s -`), because Apple Silicon
does not run unsigned code at all; notarization is not done yet.

Three things the build repairs after PyInstaller, all in
`scripts/mac/mac_build.sh`: the opencv-python and Pillow wheels carry
older copies of glib, harfbuzz and a dozen other libraries, which it
replaces with the environment's; it adds any library those need that
PyInstaller did not collect; and it makes every bundled `.mo` newer
than its `.po`, or the first launch would recompile them inside the
signed bundle. libvips, which pyvips opens by name at runtime, is
added by the spec and found through `scripts/mac/pyi_rth_cffi_bundle.py`.

The interactive `scripts/mac/mac_build.sh` with no flags still builds
from the Homebrew environment that `scripts/mac/mac_setup.sh`
prepares.

### Checking a build

```bash
scripts/mac/mac_verify_bundle.sh dist/SwiftCut.app
```

It fails if any library in the bundle points outside it (into pixi,
Homebrew or a venv), if the signature does not verify, if the app does
not stay up when started with an environment stripped of everything a
developer shell adds, or if that launch wrote into the bundle and
broke its seal.

`spctl -a -vv dist/SwiftCut.app` answers **rejected** for this build.
That is Gatekeeper's verdict on any app that is not notarized, and is
what the first-launch step above gets past; a *"sealed resource is
missing or invalid"* answer instead means the bundle was modified
after signing.

# Deploying SwiftCut with an MDM

For school IT. SwiftCut ships as one installer package that any Mac
MDM (Intune, Jamf, Kandji, Mosyle or another) can push. It installs
silently and replaces any older SwiftCut in place.

## The package

| | |
| --- | --- |
| File | `SwiftCut-<version>.pkg`, from the GitHub Release (with `SHA256SUMS`) or `pixi run release` |
| Check | `shasum -a 256 SwiftCut-<version>.pkg` matches the release's sha256 |
| Bundle id | `org.ilab.SwiftCut` (never changes) |
| Package id (receipt) | `org.ilab.SwiftCut` |
| Version | `CFBundleShortVersionString` = `<version>` (MAJOR.MINOR.PATCH); `CFBundleVersion` = build number |
| Installs | `/Applications/SwiftCut.app`, owned by root:wheel |
| Version file | `/Library/Application Support/SwiftCut/installed_version` |
| Requires | an Apple Silicon Mac, macOS 12 or later; Installer refuses it elsewhere |

## What an install does

- It needs no user interaction and is safe with nobody logged in. It
  runs as root and never launches the app.
- It quits a running SwiftCut: politely first, by force after 5
  seconds. **A laser job that is running stops**, so push outside lab
  hours.
- It removes the old `/Applications/SwiftCut.app` completely, then
  installs the new one. Each user's profiles, recipes and job history
  in `~/Library/Application Support/swiftcut` are never touched.
- It writes the installed version to
  `/Library/Application Support/SwiftCut/installed_version`.

## Updating

Push a higher-version package. It replaces the app in place and
keeps user data. A package refuses to install over a **newer**
SwiftCut. Reinstalling the same version is allowed. For an emergency
rollback, the developer builds the older version with
`ALLOW_DOWNGRADE=1`, which makes `SwiftCut-<version>-rollback.pkg`.
That package installs over anything.

## Detection

Any of these tell you which version a Mac has:

```sh
defaults read /Applications/SwiftCut.app/Contents/Info CFBundleShortVersionString
cat "/Library/Application Support/SwiftCut/installed_version"
pkgutil --pkg-info org.ilab.SwiftCut
```

A check that passes only when version `X.Y.Z` is installed (for
Kandji/Iru audit scripts, Jamf extension attributes or any custom
compliance check):

```sh
[ "$(defaults read /Applications/SwiftCut.app/Contents/Info \
    CFBundleShortVersionString 2>/dev/null)" = "X.Y.Z" ]
```

## Per tool

**Microsoft Intune.** Apps → All apps → Create → macOS → **macOS app
(PKG)**. This installs through the Intune management agent and
accepts unsigned packages. Detection: Included apps
`org.ilab.SwiftCut` with the version, **Ignore app version: No**, so
a new version is installed wherever the version differs. The
**Line-of-business app** type needs a package signed with a Developer
ID Installer certificate. Use it only once SwiftCut is signed (see
below).

**Jamf Pro.** Upload under Settings → Computer management → Packages,
then add the package to a policy (Packages tab). Scope the policy to
a Smart Computer Group of lab Macs whose Application Title
`SwiftCut.app` has an Application Version that is not the new
version, and have the policy update inventory. An extension attribute
can report `installed_version`. Packages delivered by Apple's MDM
install command rather than the Jamf agent (PreStage enrollment
packages) need a signed package.

**Kandji (Iru).** Library → Custom App → upload the package. Choose
**Audit and enforce**, with the check above as the audit script, so
Macs without that version get it at their next check-in. Or choose
**Install once per device**.

**Mosyle.** Management → Install PKG: upload the package, then create
a profile and assign the device group. Check that the bundle id and
version Mosyle reads from the upload are `org.ilab.SwiftCut` and the
new version, and correct them if not. Whether the delivery method you
pick accepts an unsigned package is Mosyle's call: if it refuses one,
use a signed build.

**Any other MDM.** Upload the package as a macOS package (PKG) app,
target the lab Macs, and detect it by bundle id `org.ilab.SwiftCut`
and version, or with the check above. Tools whose own agent runs the
installer can usually take an unsigned package; tools that install
through Apple's MDM install command need a signed one.

**Apple Business Manager.** It does not push packages itself: it
assigns the lab Macs to your MDM, which installs the package as
above. If you use Apple's built-in device management (Apple Business),
packages go through Apple's MDM install command, which requires a
Developer ID signed package served over HTTPS. That route needs the
school's Developer ID.

## Signing

Today's packages are unsigned, and the app inside is signed ad hoc.
That is enough for the agent-based routes above.

An app installed by Installer carries no quarantine flag, so macOS
should not show the "Apple could not verify SwiftCut" dialog at its
first launch. `sudo bash scripts/test_pkg.sh` reports whether the
installed app is quarantined on a test Mac. If students do see the
dialog: on macOS 14 and earlier, right-click SwiftCut and choose
Open, once. On macOS 15 and later, go to System Settings → Privacy &
Security → Open Anyway (see `docs/macos-install.md`).

A Developer ID from the school removes all of this and opens the
signed-only routes (Intune line-of-business, Apple's MDM install
command), with no other change. The same build command then signs
and notarizes, given these environment variables (or the GitHub
secrets listed in `.github/workflows/release-pkg.yml`):

```sh
export DEVELOPER_ID_APP="Developer ID Application: <name> (<team>)"
export DEVELOPER_ID_INSTALLER="Developer ID Installer: <name> (<team>)"
export NOTARY_KEYCHAIN_PROFILE=<profile from xcrun notarytool store-credentials>
pixi run build-pkg
```

## For the developer

| Command | Does |
| --- | --- |
| `pixi run build-pkg` | builds the app, the DMG and `dist/SwiftCut-<version>.pkg` from `VERSION` |
| `pixi run release patch\|minor\|major` | bumps `VERSION`, adds the CHANGELOG entry, commits, tags `v<version>`, builds, and prints the PKG path and sha256 |
| `git push origin HEAD v<version>` | GitHub Actions builds, tests and publishes the release (`release-pkg.yml`) |
| `bash scripts/test_pkg.sh [PKG] [unsigned\|signed]` | checks the package; with `sudo` it also installs it over an older, the same and a newer SwiftCut, then restores the Mac |

The build refuses a `VERSION` that is not newer than the latest
release tag, unless the commit being built is that tag. After a
release, bump before the next build.

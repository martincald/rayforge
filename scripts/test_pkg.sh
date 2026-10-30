#!/usr/bin/env bash
# Checks a SwiftCut package the way an MDM installs it.
#
#   bash scripts/test_pkg.sh [PKG] [unsigned|signed]
#   sudo bash scripts/test_pkg.sh [PKG] [unsigned|signed]
#
# PKG defaults to the newest dist/SwiftCut-<version>.pkg and the mode
# to unsigned. As any user it checks what the package is: one
# component installing org.ilab.SwiftCut at /Applications and nowhere
# else, root:wheel, the architecture, boot volume and macOS gates, the
# logic of the downgrade gate, and the signature state the mode
# expects. As root it also installs the package: over an older
# SwiftCut.app, over itself, refused under a newer one, and a rollback
# build (ALLOW_DOWNGRADE=1) over that newer one. Quit SwiftCut first.
# Afterwards the Mac is as it was: an app that was in /Applications is
# put back, and the test's install, receipt and version file are gone.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG=${1:-$(ls -t "$ROOT"/dist/SwiftCut-*.pkg 2>/dev/null | \
    grep -v -- -rollback | head -1)}
MODE=${2:-unsigned}
APP=/Applications/SwiftCut.app
VERSION_FILE="/Library/Application Support/SwiftCut/installed_version"
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
STALE=Contents/Resources/stale-file-from-an-old-layout
FAILED=0

pass() { echo "  ok    $1"; }
fail() { echo "  FAIL  $1"; FAILED=1; }
check() {
    local what=$1
    shift
    if "$@"; then pass "$what"; else fail "$what"; fi
}
plist() { /usr/libexec/PlistBuddy -c "Print :$2" "$1/Contents/Info.plist"; }
older_than() {
    local major minor patch
    IFS=. read -r major minor patch <<<"$1"
    if (( patch > 0 )); then echo "$major.$minor.$((patch - 1))"
    elif (( minor > 0 )); then echo "$major.$((minor - 1)).0"
    elif (( major > 0 )); then echo "$((major - 1)).0.0"
    fi
}
finish() {
    echo
    if (( FAILED == 0 )); then echo "All checks passed."; exit 0; fi
    echo "Some checks FAILED."
    exit 1
}

if [ ! -f "$PKG" ] || { [ "$MODE" != unsigned ] && [ "$MODE" != signed ]; }
then
    echo "Usage: [sudo] bash scripts/test_pkg.sh [PKG] [unsigned|signed]" >&2
    exit 1
fi
WORK=$(mktemp -d "${TMPDIR:-/tmp}/swiftcut-test-pkg.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

echo "== $PKG ($MODE)"
pkgutil --expand-full "$PKG" "$WORK/x" >/dev/null
DIST="$WORK/x/Distribution"
COMP="$WORK/x/SwiftCut-component.pkg"
NEW_APP="$COMP/Payload/SwiftCut.app"
VERSION=$(plist "$NEW_APP" CFBundleShortVersionString)
ROLLBACK=0
grep -q "var ALLOW_DOWNGRADE = true;" "$DIST" && ROLLBACK=1

echo "== What the package is (SwiftCut $VERSION)"
check "the bundle id is org.ilab.SwiftCut" \
    [ "$(plist "$NEW_APP" CFBundleIdentifier)" = org.ilab.SwiftCut ]
for attribute in 'identifier="org.ilab.SwiftCut"' "version=\"$VERSION\"" \
        'install-location="/Applications"' 'relocatable="false"'; do
    check "its receipt has $attribute" grep -q "$attribute" "$COMP/PackageInfo"
done
check "Installer looks for no other copy to upgrade" \
    grep -q "<relocate/>" "$COMP/PackageInfo"
check "the only version gate is the distribution's" \
    grep -q "<bundle-version/>" "$COMP/PackageInfo"
check "every payload file is root:wheel" \
    [ -z "$(lsbom -p UG "$COMP/Bom" | grep -v $'^root\twheel$')" ]
for script in preinstall postinstall; do
    check "it runs a $script script" [ -x "$COMP/Scripts/$script" ]
done
ARCHS=$(lipo -archs "$NEW_APP/Contents/MacOS/SwiftCut" | tr ' ' ',')
check "it installs only on $ARCHS Macs" \
    grep -q "hostArchitectures=\"$ARCHS\"" "$DIST"
check "it installs only on the boot volume" grep -q \
    'enable_anywhere="false" enable_currentUserHome="false" enable_localSystem="true"' \
    "$DIST"
MIN_OS=$(plist "$NEW_APP" LSMinimumSystemVersion)
check "it needs macOS $MIN_OS, as the app does" \
    grep -q "<os-version min=\"$MIN_OS\"/>" "$DIST"

# The installation check's own JavaScript, run by osascript against a
# stand-in for Installer's system object: this tests the script's
# logic, not Installer.
CHECK=$(sed -n 's/.*<installation-check script="\([^"]*\)".*/\1/p' "$DIST")
SCRIPT=$(awk '/<!\[CDATA\[/ { inside = 1; next } /\]\]>/ { inside = 0 }
    inside' "$DIST")
gate() {
    osascript -l JavaScript -e "
var installed = '$1';
var my = {result: {}};
var system = {
    files: {
        bundleAtPath: function (path) {
            return installed ? {CFBundleShortVersionString: installed} : null;
        }
    },
    compareVersions: function (a, b) {
        var x = a.split('.').map(Number), y = b.split('.').map(Number);
        for (var i = 0; i < 3; i++) {
            if (x[i] != y[i]) return x[i] < y[i] ? -1 : 1;
        }
        return 0;
    }
};
$SCRIPT
String($CHECK);"
}
OLDER=$(older_than "$VERSION")
NEWER="$(( ${VERSION%%.*} + 1 )).0.0"
check "the gate lets it install where there is no SwiftCut" \
    [ "$(gate "")" = true ]
if [ -n "$OLDER" ]; then
    check "the gate lets it replace SwiftCut $OLDER" \
        [ "$(gate "$OLDER")" = true ]
fi
check "the gate lets it reinstall over itself" \
    [ "$(gate "$VERSION")" = true ]
if (( ROLLBACK == 1 )); then
    check "the gate lets this rollback build replace SwiftCut $NEWER" \
        [ "$(gate "$NEWER")" = true ]
else
    check "the gate refuses to replace SwiftCut $NEWER" \
        [ "$(gate "$NEWER")" = false ]
fi

echo "== Signature ($MODE)"
SIGNATURE=$(pkgutil --check-signature "$PKG" 2>&1)
ASSESSMENT=$(spctl -a -vv -t install "$PKG" 2>&1)
APP_SIGNATURE=$(codesign -dv "$NEW_APP" 2>&1)
if [ "$MODE" = signed ]; then
    check "the package is signed with a Developer ID" grep -q \
        "signed by a developer certificate issued by Apple for distribution" \
        <<<"$SIGNATURE"
    check "the package is notarized" grep -q \
        "Notarization: trusted by the Apple notary service" <<<"$SIGNATURE"
    check "Gatekeeper accepts the package" grep -q \
        "source=Notarized Developer ID" <<<"$ASSESSMENT"
    check "the notarization ticket is stapled" \
        xcrun stapler validate -q "$PKG"
    check "the app is signed with a Developer ID" grep -q \
        "^Authority=Developer ID Application" <<<"$APP_SIGNATURE"
    check "the app has the hardened runtime" grep -q \
        "flags=.*runtime" <<<"$APP_SIGNATURE"
else
    check "the package has no signature" grep -q \
        "Status: no signature" <<<"$SIGNATURE"
    check "Gatekeeper rejects the package" grep -q \
        "source=no usable signature" <<<"$ASSESSMENT"
    check "the app is not signed with a Developer ID" \
        [ -z "$(grep "^Authority=Developer ID" <<<"$APP_SIGNATURE")" ]
fi
check "the app's signature verifies" \
    codesign --verify --deep --strict "$NEW_APP"

if [ "$(id -u)" != 0 ]; then
    echo
    echo "== Install checks: not run, they need root:"
    echo "   sudo bash scripts/test_pkg.sh $PKG $MODE"
    finish
fi

echo "== Installing (as root)"
USER_NAME=${SUDO_USER:-}
if [ -z "$USER_NAME" ] || [ "$USER_NAME" = root ]; then
    echo "Run it through sudo, as the user whose data must survive." >&2
    exit 1
fi
if pgrep -x SwiftCut >/dev/null; then
    echo "Quit SwiftCut first: the install would quit it, and the" \
        "settings it saves on quitting would change the data this" \
        "test checks." >&2
    exit 1
fi
USER_HOME=$(dscl . -read "/Users/$USER_NAME" NFSHomeDirectory | \
    awk '{ print $2 }')
USER_DATA="$USER_HOME/Library/Application Support/swiftcut"
data_hash() {
    if [ -d "$USER_DATA" ]; then
        (cd "$USER_DATA" && find . -type f -print0 | sort -z | \
            xargs -0 shasum -a 256 | shasum -a 256)
    else
        echo absent
    fi
}

# What the Mac had, for restore.
mkdir "$WORK/saved"
[ -e "$APP" ] && mv "$APP" "$WORK/saved/SwiftCut.app"
[ -f "$VERSION_FILE" ] && cp "$VERSION_FILE" "$WORK/saved/installed_version"
HAD_RECEIPT=0
pkgutil --pkg-info org.ilab.SwiftCut >/dev/null 2>&1 && HAD_RECEIPT=1
restore() {
    [ -e "$APP" ] && "$LSREGISTER" -u "$APP" >/dev/null 2>&1
    rm -rf "$APP"
    if [ -e "$WORK/saved/SwiftCut.app" ]; then
        mv "$WORK/saved/SwiftCut.app" "$APP"
    fi
    if [ -f "$WORK/saved/installed_version" ]; then
        cp "$WORK/saved/installed_version" "$VERSION_FILE"
    else
        rm -f "$VERSION_FILE"
        rmdir "$(dirname "$VERSION_FILE")" 2>/dev/null
    fi
    if (( HAD_RECEIPT == 0 )); then
        pkgutil --forget org.ilab.SwiftCut >/dev/null 2>&1
    fi
    rm -rf "$WORK"
}
trap restore EXIT
DATA_BEFORE=$(data_hash)

# An app as a drag install leaves it: the user's, with a file the new
# bundle does not have.
put_app() {
    rm -rf "$APP"
    ditto "$NEW_APP" "$APP"
    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $1" \
        "$APP/Contents/Info.plist"
    touch "$APP/$STALE"
    chown -R "$USER_NAME":staff "$APP"
}
install_pkg() {
    installer -pkg "$1" -target / >"$WORK/installer.log" 2>&1
}
refuses() { ! install_pkg "$1"; }
installed() {
    local what=$1
    check "SwiftCut $VERSION is installed" \
        [ "$(plist "$APP" CFBundleShortVersionString 2>/dev/null)" = \
        "$VERSION" ]
    check "no file of the $what survived" [ ! -e "$APP/$STALE" ]
    check "there is one SwiftCut in /Applications" [ "$(find /Applications \
        -maxdepth 1 -iname 'SwiftCut*.app' | wc -l | tr -d ' ')" = 1 ]
    check "it is root:wheel" [ -z "$(find "$APP" \
        \( ! -user root -o ! -group wheel \) -print -quit)" ]
    check "only root can write to it" \
        [ -z "$(find "$APP" ! -type l -perm +022 -print -quit)" ]
    check "it holds no AppleDouble files" \
        [ -z "$(find "$APP" -name '._*' -print -quit)" ]
    check "its signature verifies" codesign --verify --deep --strict "$APP"
    check "installed_version says $VERSION" \
        [ "$(cat "$VERSION_FILE" 2>/dev/null)" = "$VERSION" ]
    check "the receipt says $VERSION" [ "$(pkgutil --pkg-info \
        org.ilab.SwiftCut | awk '/^version:/ { print $2 }')" = "$VERSION" ]
    check "the user's SwiftCut data is untouched" \
        [ "$(data_hash)" = "$DATA_BEFORE" ]
}

if [ -n "$OLDER" ]; then
    echo "-- over SwiftCut $OLDER"
    put_app "$OLDER"
    check "the installer succeeds" install_pkg "$PKG"
    installed "older bundle"
else
    echo "-- over SwiftCut older than $VERSION"
    fail "no version is older than $VERSION: test a bumped build"
    rm -rf "$APP"
    check "the installer succeeds on a Mac without SwiftCut" \
        install_pkg "$PKG"
fi

echo "-- over itself"
touch "$APP/$STALE"
check "the installer succeeds" install_pkg "$PKG"
installed "bundle it replaced"

echo "-- under SwiftCut $NEWER"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $NEWER" \
    "$APP/Contents/Info.plist"
touch "$APP/$STALE"
if (( ROLLBACK == 1 )); then
    check "the rollback build installs" install_pkg "$PKG"
    installed "newer bundle"
else
    check "the installer refuses" refuses "$PKG"
    sed 's/^/        /' "$WORK/installer.log"
    check "SwiftCut $NEWER is still there" [ "$(plist "$APP" \
        CFBundleShortVersionString)" = "$NEWER" ]
    check "and untouched" [ -e "$APP/$STALE" ]

    echo "-- a rollback build under SwiftCut $NEWER"
    ALLOW_DOWNGRADE=1 bash "$ROOT/scripts/mac/mac_pkg.sh" "$NEW_APP" \
        "$WORK/rollback" >/dev/null
    check "the rollback build installs" \
        install_pkg "$WORK/rollback/SwiftCut-$VERSION-rollback.pkg"
    installed "newer bundle"
fi

echo "-- what Gatekeeper sees on the installed app"
if xattr -p com.apple.quarantine "$APP" >/dev/null 2>&1; then
    echo "  info  it is quarantined: Gatekeeper assesses its first launch"
else
    echo "  info  it is not quarantined: no Gatekeeper prompt at launch"
fi
echo "  info  spctl: $(spctl -a -t exec "$APP" 2>&1 | tr '\n' ' ')"
finish

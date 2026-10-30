#!/usr/bin/env bash
# Packages a built SwiftCut.app as SwiftCut-<version>.pkg, the
# installer an MDM pushes to the lab Macs (docs/deploy/mdm.md).
#
#   scripts/mac/mac_pkg.sh [APP] [OUT_DIR]
#
# APP defaults to dist/SwiftCut.app and OUT_DIR to dist. The version is
# the bundle's CFBundleShortVersionString, which mac_build.sh took from
# VERSION. ALLOW_DOWNGRADE=1 makes an emergency rollback package,
# SwiftCut-<version>-rollback.pkg, that also installs over a newer one.
#
# With DEVELOPER_ID_APP and DEVELOPER_ID_INSTALLER set (and the app
# built with DEVELOPER_ID_APP, which mac_build.sh signs it with), the
# package is signed, notarized with the notarytool keychain profile
# named by NOTARY_KEYCHAIN_PROFILE, and stapled. Without them it is
# unsigned.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP=${1:-dist/SwiftCut.app}
OUT_DIR=${2:-dist}
ALLOW_DOWNGRADE=${ALLOW_DOWNGRADE:-0}
PLIST="$APP/Contents/Info.plist"

if [ ! -f "$PLIST" ]; then
    echo "No app bundle at $APP: run 'pixi run build-mac' first." >&2
    exit 1
fi
VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" \
    "$PLIST")
BUNDLE_ID=$(/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$PLIST")
if [ "$BUNDLE_ID" != org.ilab.SwiftCut ]; then
    echo "$APP is $BUNDLE_ID, not org.ilab.SwiftCut." >&2
    exit 1
fi

SIGNED=0
if [ -n "${DEVELOPER_ID_APP:-}${DEVELOPER_ID_INSTALLER:-}" ]; then
    if [ -z "${DEVELOPER_ID_APP:-}" ] || \
       [ -z "${DEVELOPER_ID_INSTALLER:-}" ] || \
       [ -z "${NOTARY_KEYCHAIN_PROFILE:-}" ]; then
        echo "A signed package needs DEVELOPER_ID_APP," \
            "DEVELOPER_ID_INSTALLER and NOTARY_KEYCHAIN_PROFILE." >&2
        exit 1
    fi
    APP_SIGNATURE=$(codesign -dv "$APP" 2>&1)
    if ! grep -q "^Authority=Developer ID Application" <<<"$APP_SIGNATURE"
    then
        echo "$APP is not signed with a Developer ID: build it with" \
            "DEVELOPER_ID_APP set." >&2
        exit 1
    fi
    SIGNED=1
fi

PKG="$OUT_DIR/SwiftCut-$VERSION.pkg"
DOWNGRADE_JS=false
if [ "$ALLOW_DOWNGRADE" = 1 ]; then
    PKG="$OUT_DIR/SwiftCut-$VERSION-rollback.pkg"
    DOWNGRADE_JS=true
fi
# Installer refuses the package on a Mac whose CPU the app cannot run
# on: the pixi build is arm64 only.
ARCHS=$(lipo -archs "$APP/Contents/MacOS/SwiftCut" | tr ' ' ',')

WORK=$(mktemp -d "${TMPDIR:-/tmp}/swiftcut-pkg.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
mkdir "$WORK/root"
ditto "$APP" "$WORK/root/SwiftCut.app"

# Installed at /Applications/SwiftCut.app and nowhere else: not
# relocatable, or Installer would "upgrade" whichever copy with this
# bundle id it finds first (a build in dist/, one in Downloads). And no
# version check of its own: distribution.xml's is the only gate, so a
# rollback package never skips the payload after preinstall removed the
# app.
pkgbuild --analyze --root "$WORK/root" "$WORK/component.plist" >/dev/null
if plutil -extract 0.ChildBundles raw "$WORK/component.plist" \
        >/dev/null 2>&1; then
    echo "SwiftCut.app now nests bundles: set their component flags" \
        "here too." >&2
    exit 1
fi
plutil -replace 0.BundleIsRelocatable -bool NO "$WORK/component.plist"
plutil -replace 0.BundleIsVersionChecked -bool NO "$WORK/component.plist"

pkgbuild --quiet --root "$WORK/root" \
    --component-plist "$WORK/component.plist" \
    --identifier org.ilab.SwiftCut --version "$VERSION" \
    --install-location /Applications \
    --scripts "$HERE/pkg/scripts" \
    "$WORK/SwiftCut-component.pkg"

sed -e "s/@VERSION@/$VERSION/g" -e "s/@ARCHS@/$ARCHS/g" \
    -e "s/@ALLOW_DOWNGRADE@/$DOWNGRADE_JS/g" \
    "$HERE/pkg/distribution.xml" > "$WORK/distribution.xml"
mkdir -p "$OUT_DIR"
rm -f "$PKG"
productbuild --quiet --distribution "$WORK/distribution.xml" \
    --package-path "$WORK" "$WORK/SwiftCut.pkg"

if (( SIGNED == 1 )); then
    productsign --timestamp --sign "$DEVELOPER_ID_INSTALLER" \
        "$WORK/SwiftCut.pkg" "$PKG"
    xcrun notarytool submit "$PKG" \
        --keychain-profile "$NOTARY_KEYCHAIN_PROFILE" \
        --wait --output-format plist > "$WORK/notary.plist"
    STATUS=$(plutil -extract status raw "$WORK/notary.plist")
    if [ "$STATUS" != Accepted ]; then
        cat "$WORK/notary.plist" >&2
        echo "Notarization of $PKG: $STATUS" >&2
        rm -f "$PKG"
        exit 1
    fi
    xcrun stapler staple "$PKG"
else
    mv "$WORK/SwiftCut.pkg" "$PKG"
    echo "warning: DEVELOPER_ID_APP and DEVELOPER_ID_INSTALLER are not" \
        "set, so $PKG is unsigned."
fi

echo "$PKG"
shasum -a 256 "$PKG"

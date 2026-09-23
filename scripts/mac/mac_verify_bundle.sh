#!/usr/bin/env bash
# Check that dist/SwiftCut.app depends on nothing outside itself.
#
# 1. Every Mach-O in the bundle may only reference libraries inside the
#    bundle (@rpath / @loader_path / @executable_path) or the OS
#    (/usr/lib, /System). A path into Homebrew, pixi or a venv works on
#    the build machine and nowhere else.
# 2. The bundle's signature verifies.
# 3. The app starts with an environment stripped of everything a
#    developer shell adds (no pixi, no Homebrew, no DYLD_*, no GI_*),
#    and stays up for LAUNCH_SECONDS.
# 4. The launch left the signature intact.
set -uo pipefail

APP=${1:-dist/SwiftCut.app}
LAUNCH_SECONDS=${LAUNCH_SECONDS:-20}
FAILED=0

echo "== Foreign library references in $APP"
foreign=$(find "$APP" -type f \( -perm -u+x -o -name "*.dylib" -o -name "*.so" \) \
    -print0 | xargs -0 file 2>/dev/null | grep "Mach-O" | cut -d: -f1 | \
    while read -r bin; do
        otool -L "$bin" 2>/dev/null | tail -n +2 | awk '{print $1}' | \
            grep -v -E '^(@rpath|@loader_path|@executable_path)/|^/usr/lib/|^/System/' | \
            sed "s|^|$bin -> |"
    done)
if [ -n "$foreign" ]; then
    echo "$foreign"
    FAILED=1
else
    echo "none"
fi

echo "== Signature"
if ! codesign --verify --deep --strict "$APP"; then
    FAILED=1
else
    echo "valid"
fi

echo "== Launch with a stripped environment (${LAUNCH_SECONDS}s)"
LOG=$(mktemp)
env -i HOME="$HOME" USER="$USER" LOGNAME="${LOGNAME:-$USER}" \
    TMPDIR="${TMPDIR:-/tmp}" PATH=/usr/bin:/bin:/usr/sbin:/sbin \
    "$APP/Contents/MacOS/SwiftCut" >"$LOG" 2>&1 &
PID=$!
sleep "$LAUNCH_SECONDS"
if kill -0 "$PID" 2>/dev/null; then
    echo "still running after ${LAUNCH_SECONDS}s (pid $PID)"
    kill "$PID" 2>/dev/null
    wait "$PID" 2>/dev/null
else
    wait "$PID"
    status=$?
    echo "exited early with status $status"
    FAILED=1
fi
if grep -E -i "Traceback|Error loading|Library not loaded|GLib-GIO-ERROR|Namespace .* not available" "$LOG"; then
    FAILED=1
fi
cp "$LOG" "${VERIFY_LOG:-/dev/null}" 2>/dev/null; rm -f "$LOG"

echo "== Signature after the launch"
# An app that writes into its own bundle breaks its seal, and
# Gatekeeper then refuses it on the next assessment.
if ! codesign --verify --deep --strict "$APP"; then
    FAILED=1
else
    echo "still valid"
fi

exit $FAILED

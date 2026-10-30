#!/usr/bin/env bash
# `pixi run release patch|minor|major`: bumps VERSION, adds the
# CHANGELOG.md entry, commits and tags v<version> (scripts/version.py),
# then builds the app, the DMG and the PKG (signed when the Developer
# ID variables of scripts/mac/mac_pkg.sh are set) and prints the PKG's
# path and sha256. Pushing the tag is left to you:
#   git push origin HEAD v<version>
set -euo pipefail

LEVEL=${1:?usage: pixi run release patch|minor|major}
python scripts/version.py bump --changelog "$LEVEL"
bash scripts/mac/mac_build.sh --pixi --all
bash scripts/mac/mac_pkg.sh

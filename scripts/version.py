"""SwiftCut's version: the VERSION file at the repository root.

    python scripts/version.py check
    python scripts/version.py build-number
    python scripts/version.py bump patch|minor|major [--changelog]

VERSION is MAJOR.MINOR.PATCH and nothing more: it becomes the bundle's
CFBundleShortVersionString, which macOS, the Installer and every MDM
compare as three integers.

`check` runs before every build. VERSION must be newer than every v*
tag, unless v<VERSION> is the tag on HEAD: the release build itself,
or a rollback rebuild of an older release. A build from commits after
a release therefore fails until the next bump, so no package carries a
released number with code that release did not have.

`build-number` is the number of commits up to HEAD, the bundle's
CFBundleVersion: it only grows along the release branch, and fits the
16-bit fields of the Windows version resource.

`bump` writes the next version to VERSION, commits it (with a
CHANGELOG.md entry when asked) and tags that commit v<version>. It
refuses while tracked files have uncommitted changes, which the tag
would not contain.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_RE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
# Conventional commit types that make a changelog line, and where.
CHANGELOG_SECTIONS = {"feat": "Added", "perf": "Changed", "fix": "Fixed"}
COMMIT_RE = re.compile(r"(\w+)(?:\([^)]*\))?!?: (.+)")


class VersionError(Exception):
    pass


def parse(text: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.fullmatch(text)
    if not match:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def read_version(root: Path) -> tuple[str, tuple[int, int, int]]:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    numbers = parse(version)
    if numbers is None:
        raise VersionError(f"VERSION {version!r} is not MAJOR.MINOR.PATCH")
    return version, numbers


def release_tags(root: Path) -> dict[tuple[int, int, int], str]:
    """Every v<MAJOR.MINOR.PATCH> tag, by its numbers."""
    tags = {}
    for tag in git(root, "tag", "--list", "v*").splitlines():
        numbers = parse(tag[1:])
        if numbers is not None:
            tags[numbers] = tag
    return tags


def check(root: Path) -> str:
    """The version to build, or VersionError saying why not."""
    version, numbers = read_version(root)
    tags = release_tags(root)
    if numbers in tags:
        tagged = git(root, "rev-list", "-n", "1", tags[numbers])
        if tagged != git(root, "rev-parse", "HEAD"):
            raise VersionError(
                f"{version} was released as {tags[numbers]} at "
                f"{tagged[:9]}, and HEAD has commits it did not: bump "
                "VERSION (pixi run version-bump patch|minor|major)"
            )
    elif tags and numbers < max(tags):
        raise VersionError(
            f"VERSION {version} is older than the latest release "
            f"{tags[max(tags)]}"
        )
    return version


def build_number(root: Path) -> int:
    return int(git(root, "rev-list", "--count", "HEAD"))


def changelog_entry(root: Path, version: str) -> str:
    """The CHANGELOG.md entry for version: the feat, perf and fix
    commits since the previous release tag."""
    tags = release_tags(root)
    lines = [f"## {version}", ""]
    if not tags:
        return "\n".join(lines + ["First versioned SwiftCut release.", ""])
    since = tags[max(tags)]
    subjects = git(root, "log", "--no-merges", "--format=%s", f"{since}..")
    sections: dict[str, list[str]] = {
        title: [] for title in ("Added", "Changed", "Fixed")
    }
    for subject in subjects.splitlines():
        match = COMMIT_RE.fullmatch(subject)
        if match and match.group(1) in CHANGELOG_SECTIONS:
            title = CHANGELOG_SECTIONS[match.group(1)]
            sections[title].append(f"- {match.group(2)}")
    if not any(sections.values()):
        sections["Changed"].append("- No user-facing changes")
    for title, items in sections.items():
        if items:
            lines += [f"### {title}", "", *items, ""]
    return "\n".join(lines)


def add_changelog_entry(root: Path, version: str) -> None:
    """Puts the entry above the newest one in CHANGELOG.md."""
    path = root / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^## ", text, re.MULTILINE)
    at = match.start() if match else len(text)
    entry = changelog_entry(root, version)
    path.write_text(text[:at] + entry + "\n" + text[at:], encoding="utf-8")


def bump(root: Path, level: str, changelog: bool = False) -> str:
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise VersionError(
            "tracked files have uncommitted changes; commit or stash them "
            "first, or the release tag would not contain them"
        )
    _, (major, minor, patch) = read_version(root)
    numbers = {
        "major": (major + 1, 0, 0),
        "minor": (major, minor + 1, 0),
        "patch": (major, minor, patch + 1),
    }[level]
    version = ".".join(str(part) for part in numbers)
    tags = release_tags(root)
    if tags and numbers <= max(tags):
        raise VersionError(
            f"{version} is not newer than the latest release {tags[max(tags)]}"
        )
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    paths = ["VERSION"]
    if changelog:
        add_changelog_entry(root, version)
        paths.append("CHANGELOG.md")
    git(root, "commit", "-m", f"chore(release): v{version}", "--", *paths)
    git(root, "tag", "-a", f"v{version}", "-m", f"SwiftCut {version}")
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="validate VERSION for a build")
    commands.add_parser("build-number", help="print the build number")
    bump_parser = commands.add_parser("bump", help="bump, commit and tag")
    bump_parser.add_argument("level", choices=["patch", "minor", "major"])
    bump_parser.add_argument(
        "--changelog", action="store_true", help="add a CHANGELOG.md entry"
    )
    args = parser.parse_args()
    try:
        if args.command == "check":
            print(check(ROOT))
        elif args.command == "build-number":
            print(build_number(ROOT))
        else:
            print(bump(ROOT, args.level, args.changelog))
    except VersionError as error:
        sys.exit(f"version: {error}")


if __name__ == "__main__":
    main()

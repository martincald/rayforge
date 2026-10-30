"""SwiftCut's version has one source, the VERSION file, and builds and
releases go through scripts/version.py, which these tests run against
throwaway git repositories."""

import importlib.util
import subprocess
from pathlib import Path

import pytest
import tomllib

import swiftcut

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


version_script = _load(ROOT / "scripts" / "version.py")


def test_version_is_major_minor_patch():
    assert version_script.parse(VERSION) is not None


def test_the_app_reports_the_version_file():
    assert swiftcut.__version__ == VERSION


def test_the_package_metadata_comes_from_the_version_file():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dynamic = pyproject["tool"]["setuptools"]["dynamic"]
    assert dynamic["version"] == {"file": ["VERSION"]}
    assert "include VERSION" in (ROOT / "MANIFEST.in").read_text()


def test_the_windows_version_resource_carries_the_version():
    win_version_info = _load(ROOT / "scripts" / "win" / "win_version_info.py")
    text = win_version_info.version_info_text(VERSION)
    assert f"StringStruct('ProductVersion', '{VERSION}')" in text
    assert f"StringStruct('FileVersion', '{VERSION}')" in text


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repository with VERSION 1.0.0 and a CHANGELOG.md, and no
    user or system git config (no hooks, no commit signing)."""
    for key in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(key, "/dev/null")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "VERSION").write_text("1.0.0\n")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\nIntro.\n\n## 0.9.0\n\n- Old entry\n"
    )
    _commit(tmp_path, "chore: start")
    return tmp_path


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--allow-empty", "-m", message)


def _set_version(root: Path, version: str) -> None:
    (root / "VERSION").write_text(version + "\n")
    _commit(root, f"chore: {version}")


@pytest.mark.parametrize("text", ["1.0", "v1.0.0", "1.0.0-rc.1", "01.0.0"])
def test_check_refuses_anything_but_major_minor_patch(repo, text):
    _set_version(repo, text)
    with pytest.raises(version_script.VersionError, match="MAJOR.MINOR"):
        version_script.check(repo)


def test_check_passes_with_no_release_yet(repo):
    assert version_script.check(repo) == "1.0.0"


def test_check_passes_on_the_release_tag_itself(repo):
    _git(repo, "tag", "v1.0.0")
    assert version_script.check(repo) == "1.0.0"


def test_check_refuses_commits_after_a_release_until_a_bump(repo):
    _git(repo, "tag", "v1.0.0")
    _commit(repo, "feat: something new")
    with pytest.raises(version_script.VersionError, match="bump VERSION"):
        version_script.check(repo)
    _set_version(repo, "1.0.1")
    assert version_script.check(repo) == "1.0.1"


def test_check_refuses_a_version_older_than_the_latest_release(repo):
    _git(repo, "tag", "v1.0.0")
    _set_version(repo, "1.2.0")
    _git(repo, "tag", "v1.2.0")
    _set_version(repo, "1.1.0")
    with pytest.raises(version_script.VersionError, match="v1.2.0"):
        version_script.check(repo)


def test_check_compares_versions_as_numbers_not_text(repo):
    _set_version(repo, "1.9.0")
    _git(repo, "tag", "v1.9.0")
    _set_version(repo, "1.10.0")
    assert version_script.check(repo) == "1.10.0"


def test_check_passes_a_rollback_rebuild_of_an_older_release(repo):
    _git(repo, "tag", "v1.0.0")
    _set_version(repo, "1.1.0")
    _git(repo, "tag", "v1.1.0")
    _git(repo, "checkout", "-q", "v1.0.0")
    assert version_script.check(repo) == "1.0.0"


def test_the_build_number_grows_with_every_commit(repo):
    before = version_script.build_number(repo)
    _commit(repo, "fix: one more")
    assert version_script.build_number(repo) == before + 1


@pytest.mark.parametrize(
    "level, expected",
    [("patch", "1.0.1"), ("minor", "1.1.0"), ("major", "2.0.0")],
)
def test_bump_writes_commits_and_tags_the_next_version(repo, level, expected):
    assert version_script.bump(repo, level) == expected
    assert (repo / "VERSION").read_text() == expected + "\n"
    assert _git(repo, "log", "-1", "--format=%s") == (
        f"chore(release): v{expected}"
    )
    assert _git(repo, "rev-list", "-n", "1", f"v{expected}") == _git(
        repo, "rev-parse", "HEAD"
    )
    assert _git(repo, "status", "--porcelain") == ""
    assert version_script.check(repo) == expected


def test_bump_refuses_uncommitted_changes_to_tracked_files(repo):
    (repo / "CHANGELOG.md").write_text("edited")
    with pytest.raises(version_script.VersionError, match="uncommitted"):
        version_script.bump(repo, "patch")
    assert (repo / "VERSION").read_text() == "1.0.0\n"
    assert _git(repo, "tag", "--list") == ""


def test_the_first_changelog_entry_says_it_is_the_first(repo):
    version_script.bump(repo, "minor", changelog=True)
    text = (repo / "CHANGELOG.md").read_text()
    assert text.startswith(
        "# Changelog\n\nIntro.\n\n## 1.1.0\n\n"
        "First versioned SwiftCut release.\n\n## 0.9.0\n"
    )


def test_a_changelog_entry_lists_the_changes_since_the_last_release(repo):
    _git(repo, "tag", "v1.0.0")
    _commit(repo, "feat(import): SVG layers import as groups")
    _commit(repo, "fix: the head returns home")
    _commit(repo, "docs: a typo")
    _commit(repo, "perf(canvas): fewer redraws")
    version_script.bump(repo, "minor", changelog=True)
    text = (repo / "CHANGELOG.md").read_text()
    entry = text[text.index("## 1.1.0") : text.index("## 0.9.0")]
    assert entry == (
        "## 1.1.0\n\n"
        "### Added\n\n- SVG layers import as groups\n\n"
        "### Changed\n\n- fewer redraws\n\n"
        "### Fixed\n\n- the head returns home\n\n"
    )
    assert "CHANGELOG.md" not in _git(repo, "status", "--porcelain")

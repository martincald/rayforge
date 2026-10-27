"""SwiftCut credits its author in the license, the packaging and the
build scripts, always spelled the same way.

The author line of the About dialog, the Tours window and the window
title are tested with the windows themselves.
"""

import hashlib
import importlib.util
import runpy
import unicodedata
from pathlib import Path

import pytest

from swiftcut import const

ROOT = Path(__file__).resolve().parent.parent
NAME = "Martín Calderón"
RAYFORGE_LINE = "Copyright (c) 2025 Samuel Abels (Rayforge)"
SWIFTCUT_LINE = f"Copyright (c) 2026 {NAME} (SwiftCut modifications)"
# The MIT text LICENSE held before the copyright lines were added.
MIT_SHA256 = "f9c4c77baa3828004ee54b8a4f2db2e88ed44a6237a493965bf551fac0fcb62d"


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _line_with(relative: str, needle: str) -> str:
    return next(
        line for line in _text(relative).splitlines() if needle in line
    )


def _version_info_module():
    path = ROOT / "scripts" / "win" / "win_version_info.py"
    spec = importlib.util.spec_from_file_location("win_version_info", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_name_is_written_precomposed():
    assert unicodedata.is_normalized("NFC", NAME)
    assert const.AUTHOR == NAME


def test_license_credits_both_authors_above_the_unchanged_mit_text():
    data = (ROOT / "LICENSE").read_bytes()
    header = f"{SWIFTCUT_LINE}\n{RAYFORGE_LINE}\n\n".encode()

    assert data.startswith(header)
    assert hashlib.sha256(data[len(header) :]).hexdigest() == MIT_SHA256


def test_notice_names_both_authors_and_points_at_the_license():
    notice = _text("NOTICE")

    assert notice.startswith("SwiftCut\n")
    assert SWIFTCUT_LINE in notice
    assert RAYFORGE_LINE in notice
    assert "based on Rayforge" in notice
    assert "MIT License; see LICENSE." in notice


def test_readme_license_section_credits_both_authors():
    section = _text("README.md").split("## License", 1)[1]

    assert SWIFTCUT_LINE in section
    assert RAYFORGE_LINE in section
    assert "**MIT License**" in section


def test_project_metadata_lists_the_author_first():
    authors = _text("pyproject.toml").split("authors = [", 1)[1].splitlines()

    assert authors[1].strip() == f'{{ name="{NAME}" }},'
    assert authors[2].strip().startswith('{ name="Samuel Abels"')


def test_macos_bundle_carries_the_copyright():
    line = _line_with("SwiftCut.macos.spec", "NSHumanReadableCopyright")

    assert f"© 2026 {NAME}" in line


@pytest.mark.parametrize(
    "relative",
    [
        "scripts/mac/mac_build.sh",
        ".github/workflows/build-macos-universal.yml",
    ],
)
def test_the_disk_image_volume_names_the_author(relative):
    line = _line_with(relative, "-volname")

    assert f'-volname "SwiftCut by {NAME}"' in line


def test_splash_credits_the_author_under_the_wordmark():
    assert f'CREDIT = "by {NAME}"' in _text("scripts/win/win_create_splash.py")


def test_windows_version_resource_credits_the_author():
    module = _version_info_module()

    text = module.version_info_text("1.2.3")

    assert f"StringStruct('CompanyName', '{NAME}')" in text
    assert f"StringStruct('LegalCopyright', '© 2026 {NAME}')" in text
    assert "StringStruct('ProductName', 'SwiftCut')" in text
    assert "StringStruct('FileDescription', 'SwiftCut')" in text
    assert "StringStruct('OriginalFilename', 'SwiftCut.exe')" in text
    assert "StringStruct('FileVersion', '1.2.3')" in text
    assert "StringStruct('ProductVersion', '1.2.3')" in text
    assert "filevers=(1, 2, 3, 0)" in text
    assert "prodvers=(1, 2, 3, 0)" in text


@pytest.mark.parametrize(
    ("version", "numbers"),
    [
        ("1.2.3", (1, 2, 3, 0)),
        ("1.2.3.4", (1, 2, 3, 4)),
        ("0.0.0+gabc1234", (0, 0, 0, 0)),
        ("2.4.6-12-gdeadbee", (2, 4, 6, 0)),
        ("7", (7, 0, 0, 0)),
        ("dev", (0, 0, 0, 0)),
    ],
)
def test_version_resource_numbers_follow_the_version_string(version, numbers):
    assert _version_info_module().numeric_version(version) == numbers


def test_version_resource_is_written_as_utf8(tmp_path, monkeypatch):
    out = tmp_path / "version_info.txt"
    monkeypatch.setattr("sys.argv", ["win_version_info.py", "1.2.3", str(out)])

    runpy.run_path(
        str(ROOT / "scripts" / "win" / "win_version_info.py"),
        run_name="__main__",
    )

    assert NAME in out.read_text(encoding="utf-8")

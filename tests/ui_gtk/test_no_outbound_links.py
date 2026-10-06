"""Grep gate: the UI carries no outbound links.

SwiftCut ships without donate, website, update or purchase links, and
nothing in the UI opens a browser. Four rules, one test each:

1. No "patreon" (any case) in swiftcut/ui_gtk/**/*.py or in the raw
   bytes of any file under swiftcut/resources/.
2. No "http://" or "https://" (any case) inside a Python string token
   in swiftcut/ui_gtk/**/*.py. String tokens are STRING plus the literal
   parts of f-strings and t-strings (FSTRING_MIDDLE, TSTRING_MIDDLE),
   so f"https://{host}" is caught. Comments are not strings.
3. No "http://" or "https://" (any case) in the text files under
   swiftcut/resources/ (a file is text if it decodes as UTF-8;
   binaries are skipped), except XML namespace declarations
   (xmlns="..." or xmlns:prefix="...") that every SVG carries. The
   one SVG <metadata> block, the C2PA manifest in the SwiftCut icon,
   is base64 with no plain-text URL, so it needs no exclusion.
4. No browser-opening API in swiftcut/ui_gtk/**/*.py: no text
   containing webbrowser, launch_uri, show_uri, launch_default_for_uri,
   UriLauncher or LinkButton, so longer names such as show_uri_full
   are caught too.

The About dialog's Rayforge attribution has no URL, so it needs no
exception here; the LICENSE file lives outside both trees.
"""

import re
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "swiftcut" / "ui_gtk"
RESOURCES_ROOT = REPO_ROOT / "swiftcut" / "resources"

# A moved or renamed package would leave the roots pointing at nothing
# and the gate would pass without scanning a single file.
for _root in (UI_ROOT, RESOURCES_ROOT):
    assert _root.is_dir(), f"scan root missing: {_root}"

URL_SCHEMES = ("http://", "https://")

STRING_TOKEN_TYPES = {
    tok_type
    for tok_type in (
        tokenize.STRING,
        getattr(tokenize, "FSTRING_MIDDLE", None),
        getattr(tokenize, "TSTRING_MIDDLE", None),
    )
    if tok_type is not None
}

XMLNS_DECLARATION = re.compile(r'xmlns(:[\w.-]+)?="https?://[^"]*"')

BROWSER_APIS = re.compile(
    r"webbrowser|launch_uri|show_uri|launch_default_for_uri"
    r"|UriLauncher|LinkButton"
)


def _ui_python_files() -> list[Path]:
    return sorted(UI_ROOT.rglob("*.py"))


def _resource_files() -> list[Path]:
    return sorted(p for p in RESOURCES_ROOT.rglob("*") if p.is_file())


def _resource_text(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return None


def test_no_patreon_in_ui_or_resources():
    hits = [
        str(path.relative_to(REPO_ROOT))
        for path in _ui_python_files()
        if "patreon" in path.read_text(encoding="utf-8").lower()
    ]
    hits += [
        str(path.relative_to(REPO_ROOT))
        for path in _resource_files()
        if b"patreon" in path.read_bytes().lower()
    ]
    assert not hits, f"Patreon mentioned in: {hits}"


def test_no_url_in_ui_string_literals():
    hits = []
    for path in _ui_python_files():
        with path.open("rb") as f:
            for tok in tokenize.tokenize(f.readline):
                if tok.type in STRING_TOKEN_TYPES and any(
                    scheme in tok.string.lower() for scheme in URL_SCHEMES
                ):
                    rel = path.relative_to(REPO_ROOT)
                    hits.append(f"{rel}:{tok.start[0]}: {tok.string!r}")
    assert not hits, "URL in a UI string:\n" + "\n".join(hits)


def test_no_url_in_resources_beyond_xml_namespaces():
    hits = []
    for path in _resource_files():
        text = _resource_text(path)
        if text is None:
            continue
        text = XMLNS_DECLARATION.sub("", text.lower())
        if any(scheme in text for scheme in URL_SCHEMES):
            hits.append(str(path.relative_to(REPO_ROOT)))
    assert not hits, f"URL outside an xmlns declaration in: {hits}"


def test_no_browser_opening_api_in_ui():
    hits = []
    for path in _ui_python_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            if BROWSER_APIS.search(line):
                rel = path.relative_to(REPO_ROOT)
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    assert not hits, "Browser-opening code in the UI:\n" + "\n".join(hits)

"""Grep gate: no user-visible UI string still says "Rayforge".

The app was rebranded to SwiftCut (see rayforge/const.py APP_NAME).
This scans every .py file under rayforge/ui_gtk/ and rayforge/resources/
for string literals that are actually shown to the user - the argument
to a gettext `_()` call, or a value passed to a common GTK/Adwaita
text-setter (label=, title=, tooltip_text=, .set_title(...), etc.) -
and asserts none of them contain "rayforge" or "Rayforge".

This intentionally does NOT scan docstrings, comments, import
statements, or internal identifiers (e.g. the `RayforgeContext` class
name or `__gtype_name__ = "RayforgeFooRow"` GObject type names): none
of those are rendered to the user, and renaming them is a much larger,
separate refactor outside the scope of this rebrand.

Allow-list: two categories of "rayforge" text are permitted to remain
anywhere in the app by design and would be exempted here via
`ALLOWLIST` if they ever appeared under the scanned directories:
  - the legacy config-dir migration path, which must always read the
    literal directory name "rayforge" (see swiftcut/config.py,
    `_migrate_legacy_config_dir` / `_get_config_dir`, covered by
    tests/test_config.py) - it is not under ui_gtk/ or resources/, so
    it never trips this gate;
  - the MIT copyright/attribution notice, which names the original
    author "Samuel Abels" (see swiftcut/ui_gtk/about.py) rather than
    the word "Rayforge" itself, so it also never trips this gate.
Neither currently needs an entry, but the mechanism must remain
available for future additions.
"""

import ast
from pathlib import Path
from typing import Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = [
    REPO_ROOT / "swiftcut" / "ui_gtk",
    REPO_ROOT / "swiftcut" / "resources",
]

# A moved or renamed package would leave the roots pointing at nothing
# and the gate would pass without scanning a single file.
for _root in SCAN_ROOTS:
    assert _root.is_dir(), f"scan root missing: {_root}"

# Keyword argument names that, on any call, carry text shown to the user.
UI_TEXT_KWARGS = {
    "title",
    "label",
    "subtitle",
    "heading",
    "body",
    "tooltip_text",
    "placeholder_text",
}

# Method/function names whose first positional argument is user-visible
# text.
UI_TEXT_CALLS = {
    "set_title",
    "set_label",
    "set_subtitle",
    "set_heading",
    "set_body",
    "set_tooltip_text",
    "set_placeholder_text",
    "set_markup",
    "new_with_label",
}

# Exact user-visible strings that are allowed to contain "rayforge" or
# "Rayforge". See the module docstring for why each entry is here.
ALLOWLIST: set[str] = set()


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _string_const(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _iter_ui_strings(path: Path) -> Iterator[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)

        if name == "_" and node.args:
            text = _string_const(node.args[0])
            if text is not None:
                yield text

        if name in UI_TEXT_CALLS and node.args:
            text = _string_const(node.args[0])
            if text is not None:
                yield text

        for kw in node.keywords:
            if kw.arg in UI_TEXT_KWARGS:
                text = _string_const(kw.value)
                if text is not None:
                    yield text


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        files.extend(sorted(root.rglob("*.py")))
    return files


@pytest.mark.parametrize(
    "path",
    _python_files(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_no_rayforge_in_ui_visible_strings(path: Path):
    for text in _iter_ui_strings(path):
        if text in ALLOWLIST:
            continue
        assert "rayforge" not in text and "Rayforge" not in text, (
            f"{path}: user-visible string still says Rayforge: {text!r}"
        )

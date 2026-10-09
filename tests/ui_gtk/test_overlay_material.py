"""Every floating surface is one material, and only the theme paints it.

The Workflow and Workpiece Properties cards, the canvas toolbars, the
drop HUD and the status messages float over the work, and they are one
surface: the theme's ``.sc-overlay``. Its colours are tokens in
``theme.py`` (a solid glass colour per theme, the alpha it floats at, a
hairline rim and a shadow) and its lengths are roles in ``layout.py``.
No other module paints a background or a shadow of its own on a
floating surface, and text on the material stays readable whatever
lies beneath it (docs/design/swift-cut-tokens.md, section 3.6).
"""

import re
import time
from pathlib import Path

import pytest

from swiftcut.ui_gtk import layout, theme

SWIFTCUT = Path(layout.__file__).parent.parent
UI_GTK = SWIFTCUT / "ui_gtk"
TOKEN_MODULES = (UI_GTK / "theme.py", UI_GTK / "layout.py")

# Every module that builds a floating surface. A new one - a panel over
# the canvas, a preview transport, a first-run card - is listed here.
FLOATING_MODULES = (
    "ui_gtk/mainwindow.py",
    "ui_gtk/shared/expander.py",
    "ui_gtk/shared/visibility_overlay.py",
    "ui_gtk/shared/time_estimate_overlay.py",
    "ui_gtk/shared/job_preview_bar.py",
    "ui_gtk/canvas2d/drag_drop_cmd.py",
    "ui_gtk/getting_started.py",
    "shared/gcodeedit/viewer.py",
)

OVERLAY_TOKENS = {
    "sc_overlay_solid",
    "sc_overlay_bg",
    "sc_overlay_border",
    "sc_overlay_shadow",
}

_DEFINE = re.compile(r"@define-color\s+(\w+)\s+([^;]+);")
_LITERAL_BACKGROUND = re.compile(
    r"background(-color|-image)?\s*:[^;]*(rgba?\(|#[0-9a-fA-F]{8}\b)"
)
_PAINT = re.compile(
    r"^\s*(background(-color|-image)?|box-shadow)\s*:\s*([^;]*);"
)
_OVERLAY_RULE = re.compile(r"\.sc-overlay\b[^{\n]*\{")


def _tokens(dark: bool) -> dict[str, str]:
    return dict(_DEFINE.findall(theme._css_for(dark)))


def _declarations(css: str, selector: str) -> dict[str, str]:
    """Every declaration of the rules whose selector is exactly this."""
    found: dict[str, str] = {}
    for match in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        selectors = re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.DOTALL)
        if selectors.strip() != selector:
            continue
        for line in match.group(2).split(";"):
            if ":" in line:
                name, value = line.split(":", 1)
                found[name.strip()] = value.strip()
    return found


def _sources():
    for path in sorted(UI_GTK.rglob("*.py")) + sorted(
        (SWIFTCUT / "shared").rglob("*.py")
    ):
        if path not in TOKEN_MODULES:
            yield path


def _lines(path: Path):
    return enumerate(path.read_text().splitlines(), 1)


def test_both_themes_define_the_same_overlay_tokens():
    light = {n for n in _tokens(False) if n.startswith("sc_overlay_")}
    dark = {n for n in _tokens(True) if n.startswith("sc_overlay_")}

    assert light == dark == OVERLAY_TOKENS


@pytest.mark.parametrize("dark", (False, True))
def test_the_overlay_rule_paints_only_with_overlay_tokens(dark):
    css = theme._css_for(dark)
    rule = _declarations(css, ".sc-overlay")

    assert set(rule) == {
        "background-color",
        "border",
        "box-shadow",
        "border-radius",
    }
    assert rule["background-color"] == "@sc_overlay_bg"
    assert rule["border"] == (
        f"{layout.CSS_LENGTHS['hairline']} solid @sc_overlay_border"
    )
    assert rule["box-shadow"] == (
        f"{layout.CSS_LENGTHS['shadow_overlay']} @sc_overlay_shadow"
    )
    assert rule["border-radius"] == layout.CSS_LENGTHS["radius_overlay"]
    # A list inside a card would paint libadwaita's opaque view colour.
    assert _declarations(css, ".sc-overlay list") == {
        "background-color": "transparent"
    }


def test_one_radius_for_every_floating_surface():
    # The deck's card radius; its 9px canvas-overlay radius is retired.
    assert layout.CSS_LENGTHS["radius_overlay"] == "10px"


def test_no_module_but_the_theme_writes_a_literal_background_colour():
    offenders = [
        f"{path.relative_to(SWIFTCUT)}:{number}: {line.strip()}"
        for path in _sources()
        for number, line in _lines(path)
        if _LITERAL_BACKGROUND.search(line)
    ]

    assert offenders == []


@pytest.mark.parametrize("module", FLOATING_MODULES)
def test_no_floating_surface_paints_itself(module):
    offenders = []
    for number, line in _lines(SWIFTCUT / module):
        match = _PAINT.match(line)
        if match is None:
            continue
        value = match.group(3).strip()
        if value in ("none", "transparent") or "@sc_overlay_" in value:
            continue
        offenders.append(f"{module}:{number}: {line.strip()}")

    assert offenders == []


def test_only_the_theme_styles_the_overlay_class():
    offenders = [
        f"{path.relative_to(SWIFTCUT)}:{number}: {line.strip()}"
        for path in _sources()
        for number, line in _lines(path)
        if _OVERLAY_RULE.search(line)
    ]

    assert offenders == []


# --- Contrast ---------------------------------------------------------


def _resolve(value: str, tokens: dict[str, str]) -> tuple[float, ...]:
    """A token's colour as (r, g, b, a), r g b in 0-255."""
    value = value.strip()
    if value.startswith("@"):
        return _resolve(tokens[value[1:]], tokens)
    if value.startswith("#") and len(value) == 7:
        return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5)) + (1.0,)
    inner = value[value.index("(") + 1 : value.rindex(")")]
    if value.startswith("alpha("):
        color, factor = inner.rsplit(",", 1)
        r, g, b, a = _resolve(color, tokens)
        return r, g, b, a * float(factor)
    if value.startswith("rgba("):
        r, g, b, a = (float(part) for part in inner.split(","))
        return r, g, b, a
    raise ValueError(value)


def _over(top: tuple[float, ...], below: tuple[float, ...]):
    """An rgba colour composited over an opaque one."""
    alpha = top[3]
    return tuple(
        alpha * t + (1 - alpha) * b for t, b in zip(top[:3], below[:3])
    )


def _luminance(rgb) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("dark", (False, True))
@pytest.mark.parametrize("beneath", ("black", "white", "sc_canvas_bg"))
def test_overlay_text_is_readable_over_any_work(dark, beneath):
    tokens = _tokens(dark)
    below = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "sc_canvas_bg": _resolve("@sc_canvas_bg", tokens)[:3],
    }[beneath]
    surface = _over(_resolve("@sc_overlay_bg", tokens), below)
    text = _over(_resolve("@sc_fg", tokens), surface)
    caption = _over(_resolve("@sc_fg_dim", tokens), surface)

    # Body text keeps WCAG AAA; a dim caption keeps the 3:1 its opaque
    # ceiling (3.3:1 on the solid glass colour) leaves room for.
    assert _contrast(text, surface) >= 7
    assert _contrast(caption, surface) >= 3


def test_the_overlay_is_glass_not_an_opaque_panel():
    for dark in (False, True):
        alpha = _resolve("@sc_overlay_bg", _tokens(dark))[3]
        assert 0.85 <= alpha < 1


# --- The widgets ------------------------------------------------------


@pytest.mark.ui
def test_the_theme_stylesheet_parses_in_both_themes():
    from gi.repository import Gtk

    errors = []

    def collect(_provider, section, error):
        errors.append(f"{section.to_string()}: {error.message}")

    for dark in (False, True):
        provider = Gtk.CssProvider()
        provider.connect("parsing-error", collect)
        provider.load_from_string(theme._css_for(dark))

    assert errors == []


@pytest.mark.ui
def test_every_floating_widget_wears_the_overlay_class(
    ui_context_initializer,
):
    from swiftcut.shared.gcodeedit.viewer import GcodeViewer
    from swiftcut.ui_gtk.shared.expander import (
        Expander,
        ExpanderWithButton,
    )
    from swiftcut.ui_gtk.shared.time_estimate_overlay import (
        TimeEstimateOverlay,
    )
    from swiftcut.ui_gtk.shared.visibility_overlay import (
        VisibilityOverlay,
    )

    for widget in (
        Expander(),
        ExpanderWithButton("Add"),
        VisibilityOverlay(),
        TimeEstimateOverlay(),
        GcodeViewer().status_label,
    ):
        assert widget.has_css_class("sc-overlay"), type(widget).__name__


def _pump(seconds: float) -> None:
    from gi.repository import GLib

    end = time.monotonic() + seconds
    context = GLib.main_context_default()
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


@pytest.fixture
def main_window(ui_context_initializer):
    from gi.repository import Adw

    from swiftcut.ui_gtk.mainwindow import MainWindow

    class App(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)
            self.win.set_default_size(1280, 800)

    app = App(application_id="org.swiftcut.swiftcut.test.overlay-material")
    app.register(None)
    app.activate()
    win = app.win
    win.present()
    _pump(0.5)
    yield win
    win.doc_editor.cleanup()
    win.destroy()
    app.quit()
    _pump(0.2)


def _overlay_children(overlay):
    """The children an overlay floats over its main child."""
    child = overlay.get_first_child()
    while child is not None:
        if child is not overlay.get_child():
            yield child
        child = child.get_next_sibling()


def _descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


@pytest.mark.ui
def test_everything_floating_over_the_main_window_is_glass(main_window):
    from swiftcut.ui_gtk.shared.expander import Expander

    win = main_window
    # The drop HUD floats only while a file is dragged over the canvas.
    win.drag_drop_cmd._show_drop_overlay()
    hud = win.drag_drop_cmd._drop_overlay_label
    assert hud is not None
    assert hud.get_opacity() == 1.0

    floating = [
        child
        for overlay in (
            win._canvas_overlay,
            win.surface_overlay,
            win._status_overlay,
        )
        for child in _overlay_children(overlay)
    ]
    assert hud in floating
    for child in floating:
        if child is win._right_pane:
            # A transparent column; each card in it is the material.
            assert not child.has_css_class("sc-overlay")
            cards = [w for w in _descendants(child) if isinstance(w, Expander)]
            assert len(cards) >= 2
            assert all(card.has_css_class("sc-overlay") for card in cards)
        else:
            assert child.has_css_class("sc-overlay"), child
    win.drag_drop_cmd._hide_drop_overlay()

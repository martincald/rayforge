"""Generate the Windows splash image from the SwiftCut app icon SVG.

The splash is the brand plate: the icon's own gradient taken
full-bleed, with the swift knocked out in white beside the wordmark,
and the version from VERSION in the bottom right corner.

Corners are rounded. PyInstaller's Tk splash keys transparency off
pure magenta on Windows (see PyInstaller's splash_templates.py), so
the area outside the rounded rectangle is filled with magenta AND
given zero alpha. That colour key cannot express partial
transparency - an antialiased edge would blend blue into magenta and
leave a fringe - so the corner mask is thresholded to hard pixels,
which is the "only sharp transparent image corners are possible"
limitation PyInstaller documents.

The macOS build bundles the same image for swiftcut/splash.py; there
the pixi environment has no Rsvg typelib and no Segoe UI, so the
glyph goes through librsvg's own rsvg-convert (as
scripts/mac/mac_create_icon.sh does) and the wordmark uses the
system font. macOS shows it on a Retina screen from a transparent
window, so there it is drawn at twice the pixels, saved as 144 dpi to
keep its size in points, and its corners keep their antialiasing: no
colour key is involved.
"""

import io
import subprocess
import sys
from pathlib import Path

import cairo
import gi
import numpy as np
from PIL import Image, ImageDraw, ImageFont

here = Path(__file__).parent.parent.parent
source_path = here / "swiftcut/resources/icons/org.ilab.SwiftCut.svg"
splash_path = here / "swiftcut_splash.png"
VERSION = (here / "VERSION").read_text(encoding="utf-8").strip()

# Pixels per point: 2 for the macOS Retina splash, 1 for Windows.
SCALE = 2 if sys.platform == "darwin" else 1
WIDTH, HEIGHT = 480 * SCALE, 320 * SCALE
RADIUS = 20 * SCALE
GLYPH_SIZE = 150 * SCALE
GAP = 22 * SCALE
FONT_SIZE = 40 * SCALE
CREDIT = "by Martín Calderón"
CREDIT_SIZE = 15 * SCALE
CREDIT_GAP = 8 * SCALE
CREDIT_COLOR = (0xE3, 0xEE, 0xFF)
VERSION_SIZE = 12 * SCALE
VERSION_MARGIN = 14 * SCALE
MAGENTA = (255, 0, 255)

# Brand tokens, from docs/design/swift-cut-tokens.md.
BLUE_LIGHT = (0x7C, 0xBE, 0xFF)
BLUE_BRAND = (0x2F, 0x7B, 0xFF)
BLUE_DEEP = (0x0B, 0x3B, 0xD1)
DEEP_SHADE = (0x00, 0x1B, 0x7A)
SUPERSAMPLE = 4


def render_glyph(size):
    """Render the swift alone, without the icon's background plate."""
    svg = source_path.read_text(encoding="utf-8")
    start = svg.index('<g id="background"')
    end = svg.index('<g id="swift"')
    bare = svg[:start] + svg[end:]

    try:
        gi.require_version("Rsvg", "2.0")
    except ValueError:
        png = subprocess.run(
            ["rsvg-convert", "-w", str(size), "-h", str(size)],
            input=bare.encode("utf-8"),
            capture_output=True,
            check=True,
        ).stdout
        return Image.open(io.BytesIO(png)).convert("RGBA")
    from gi.repository import Rsvg

    handle = Rsvg.Handle.new_from_data(bare.encode("utf-8"))
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    viewport = Rsvg.Rectangle()
    viewport.x = 0
    viewport.y = 0
    viewport.width = size
    viewport.height = size
    handle.render_document(ctx, viewport)

    buf = io.BytesIO()
    surface.write_to_png(buf)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGBA")


def brand_gradient():
    """The icon's diagonal blue gradient, at splash proportions."""
    ys, xs = np.mgrid[0:HEIGHT, 0:WIDTH]
    # Diagonal sweep, normalised to 0..1 across the plate.
    t = (xs / (WIDTH - 1) + ys / (HEIGHT - 1)) / 2.0

    stops = [(0.0, BLUE_LIGHT), (0.46, BLUE_BRAND), (1.0, BLUE_DEEP)]
    out = np.zeros((HEIGHT, WIDTH, 3), dtype=float)
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        band = (t >= t0) & (t <= t1)
        local = np.clip((t - t0) / (t1 - t0), 0.0, 1.0)
        for ch in range(3):
            out[..., ch] = np.where(
                band, c0[ch] + (c1[ch] - c0[ch]) * local, out[..., ch]
            )
    return out


def radial(cx, cy, radius, color, peak):
    """A soft radial wash, as the icon layers over its gradient."""
    ys, xs = np.mgrid[0:HEIGHT, 0:WIDTH]
    dx = (xs / WIDTH - cx) * WIDTH
    dy = (ys / HEIGHT - cy) * HEIGHT
    dist = np.sqrt(dx**2 + dy**2) / (radius * max(WIDTH, HEIGHT))
    alpha = np.clip(1.0 - dist, 0.0, 1.0) ** 2 * peak
    wash = np.zeros((HEIGHT, WIDTH, 3), dtype=float)
    for ch in range(3):
        wash[..., ch] = color[ch]
    return wash, alpha[..., None]


plate = brand_gradient()
for cx, cy, rad, color, peak in [
    (0.28, 0.12, 0.75, (255, 255, 255), 0.34),
    (0.75, 1.00, 0.80, DEEP_SHADE, 0.35),
]:
    wash, alpha = radial(cx, cy, rad, color, peak)
    plate = plate * (1 - alpha) + wash * alpha

canvas = Image.fromarray(plate.round().astype("uint8"), "RGB").convert(
    "RGBA"
)

# Compose the mark and the wordmark as one centred row.
glyph = render_glyph(GLYPH_SIZE)


def load_font(size, windows_names, mac_weight):
    """The system UI font: Segoe UI on Windows, SF on macOS."""
    for name in windows_names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    try:
        font = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", size)
        font.set_variation_by_name(mac_weight)
        return font
    except (OSError, ValueError):
        return ImageFont.load_default()


font = load_font(FONT_SIZE, ("segoeuisb.ttf", "segoeuib.ttf"), "Semibold")
credit_font = load_font(CREDIT_SIZE, ("segoeui.ttf",), "Regular")
version_font = load_font(VERSION_SIZE, ("segoeui.ttf",), "Regular")

draw = ImageDraw.Draw(canvas)
text = "SwiftCut"
box = draw.textbbox((0, 0), text, font=font)
text_w, text_h = box[2] - box[0], box[3] - box[1]
credit_box = draw.textbbox((0, 0), CREDIT, font=credit_font)
credit_w = credit_box[2] - credit_box[0]
credit_h = credit_box[3] - credit_box[1]

# The credit hangs under the wordmark, both centred in one column.
column_w = max(text_w, credit_w)
column_h = text_h + CREDIT_GAP + credit_h
row_w = GLYPH_SIZE + GAP + column_w
left = (WIDTH - row_w) // 2
column_left = left + GLYPH_SIZE + GAP
column_top = (HEIGHT - column_h) // 2
canvas.alpha_composite(glyph, (left, (HEIGHT - GLYPH_SIZE) // 2))
draw.text(
    (column_left + (column_w - text_w) // 2 - box[0], column_top - box[1]),
    text,
    font=font,
    fill=(255, 255, 255, 255),
)
draw.text(
    (
        column_left + (column_w - credit_w) // 2 - credit_box[0],
        column_top + text_h + CREDIT_GAP - credit_box[1],
    ),
    CREDIT,
    font=credit_font,
    fill=CREDIT_COLOR + (255,),
)
version_text = f"Version {VERSION}"
version_box = draw.textbbox((0, 0), version_text, font=version_font)
draw.text(
    (
        WIDTH - VERSION_MARGIN - version_box[2],
        HEIGHT - VERSION_MARGIN - version_box[3],
    ),
    version_text,
    font=version_font,
    fill=CREDIT_COLOR + (255,),
)

# Rounded-corner mask: supersample the curve for an accurate outline.
big = (WIDTH * SUPERSAMPLE, HEIGHT * SUPERSAMPLE)
mask = Image.new("L", big, 0)
ImageDraw.Draw(mask).rounded_rectangle(
    [(0, 0), (big[0] - 1, big[1] - 1)],
    radius=RADIUS * SUPERSAMPLE,
    fill=255,
)
mask = mask.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)

if SCALE == 1:
    # Windows: threshold so no pixel is partly keyed, and outside the
    # plate magenta (the colour key) and zero alpha, so the corners
    # fall away whether or not Tk honours the alpha channel.
    mask = mask.point(lambda v: 255 if v >= 128 else 0)
    out = Image.new("RGBA", (WIDTH, HEIGHT), MAGENTA + (0,))
    out.paste(canvas, (0, 0), mask)
else:
    # macOS: the window is transparent, so the edge keeps its alpha.
    out = canvas.copy()
out.putalpha(mask)
out.save(splash_path, format="PNG", dpi=(72 * SCALE, 72 * SCALE))
print("Splash generation complete.")

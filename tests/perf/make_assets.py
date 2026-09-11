"""Generate the fixed performance-test assets under tests/perf/.

The assets are committed, so this script exists to make them
reproducible, not to run on every measurement. Regenerate with::

    python tests/perf/make_assets.py

The *geometry* is deterministic: no randomness, no clock, no network,
so every run emits the same segment count at the same coordinates and
timings stay comparable. The bytes are not - ezdxf stamps its own
handles, so regenerating large.dxf changes the file hash without
changing the drawing. The assets are therefore committed and this
script is only for reproducing them, never a build step; do not
regenerate midway through a before/after comparison.
"""

import math
from pathlib import Path

import ezdxf

HERE = Path(__file__).parent

# Segment counts the perf audit quotes. Keep these stable: changing one
# invalidates every recorded before/after number for that asset.
SMALL_SVG_SEGMENTS = 200
LARGE_DXF_SEGMENTS = 20000
RASTER_SIZE = (3000, 2000)


def _star_points(cx, cy, r_outer, r_inner, points):
    """Vertices of a star, alternating outer and inner radius."""
    verts = []
    for i in range(points * 2):
        angle = math.pi * i / points - math.pi / 2
        r = r_outer if i % 2 == 0 else r_inner
        verts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return verts


def write_small_svg(path):
    """~200 line segments as a grid of stars, in mm user units."""
    per_star = 20  # 10 points -> 20 vertices -> 20 closed segments
    stars = SMALL_SVG_SEGMENTS // per_star
    cols = 5
    spacing = 20.0
    body = []
    for n in range(stars):
        cx = 15.0 + spacing * (n % cols)
        cy = 15.0 + spacing * (n // cols)
        verts = _star_points(cx, cy, 8.0, 3.5, per_star // 2)
        pts = " ".join(f"{x:.3f},{y:.3f}" for x, y in verts)
        body.append(
            f'  <polygon points="{pts}" fill="none" '
            f'stroke="#000000" stroke-width="0.2"/>'
        )
    width = spacing * cols + 10.0
    height = spacing * ((stars + cols - 1) // cols) + 10.0
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width:.1f}mm" height="{height:.1f}mm" '
        f'viewBox="0 0 {width:.1f} {height:.1f}">\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")
    return stars * per_star


def write_large_dxf(path):
    """~20000 segments as LWPOLYLINE entities on one layer."""
    doc = ezdxf.new("R2010")
    # $INSUNITS is load-bearing and ezdxf does NOT set it: its default
    # of 0 ("unitless") is read by the importer as METRES, which turns
    # this 610x130 mm drawing into a 610x130 METRE workpiece. That is
    # not a theoretical problem - the resulting part drove ops
    # generation to 17.7 GB RSS and took the machine down. 4 = mm.
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    doc.layers.add("CUT", color=7)

    per_poly = 40
    polys = LARGE_DXF_SEGMENTS // per_poly
    cols = 50
    spacing = 12.0
    for n in range(polys):
        cx = 10.0 + spacing * (n % cols)
        cy = 10.0 + spacing * (n // cols)
        verts = _star_points(cx, cy, 5.0, 2.2, per_poly // 2)
        msp.add_lwpolyline(
            verts, close=True, dxfattribs={"layer": "CUT"}
        )
    doc.saveas(path)
    return polys * per_poly


def write_raster_png(path):
    """A 3000x2000 greyscale-ish pattern with real high-frequency detail.

    A flat fill would let the tracer short-circuit and would not
    represent a real raster job, so this draws concentric rings plus a
    diagonal hatch.
    """
    from PIL import Image, ImageDraw

    w, h = RASTER_SIZE
    img = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(img)

    cx, cy = w / 2, h / 2
    for r in range(40, int(max(w, h) / 1.4), 40):
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r], outline=0, width=6
        )
    for x in range(-h, w, 60):
        draw.line([(x, 0), (x + h, h)], fill=90, width=3)

    img.save(path, format="PNG", optimize=False)
    return w * h


def main():
    HERE.mkdir(parents=True, exist_ok=True)
    n = write_small_svg(HERE / "small.svg")
    print(f"small.svg   {n} segments")
    n = write_large_dxf(HERE / "large.dxf")
    print(f"large.dxf   {n} segments")
    n = write_raster_png(HERE / "raster.png")
    print(f"raster.png  {RASTER_SIZE[0]}x{RASTER_SIZE[1]} ({n} px)")


if __name__ == "__main__":
    main()

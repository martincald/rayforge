"""
Writes the import-structure fixtures beside this script, synthesized
in the shape of real exports (no real Illustrator or Fusion file yet):

- illustrator_two_layers.svg: an Illustrator SVG in points (72 per
  inch, a viewBox and no width or height), layers Cut (the outline, a
  red stroke from a CSS class) and Engrave (a group of three shapes,
  two outlined letters, a placed PNG clipped through a CSS class on
  its group).
- illustrator_traced.dxf: the same idea as Illustrator writes a traced
  logo to DXF: 120 small closed polylines (ACI 7 and 250) inside a red
  (ACI 1) outline, one layer, no blocks, millimetres.
- cad_plate.dxf: two plates as Fusion or Onshape write them: outlines
  of separate LINE and ARC entities (rounded corners, entities out of
  order), CIRCLE holes, layer 0, millimetres.
- layer_names.svg: an SVG in millimetres whose layers are named for
  what they do, as Illustrator writes them (an id, the name with
  spaces in data-name): "cut" (a filled square), "scan 3mm mdf" (an
  outline), "engrave" (a filled circle) and "Layer 1" (an outline).

The source-units fixtures: each a 100 x 50 mm outline (283.46 x 141.73
pt, 377.95 x 188.98 px at 96 per inch) filling its page.

- illustrator_responsive.svg: Illustrator's Export As, Responsive: its
  generator comment, data-name attributes, a viewBox in points and no
  width or height.
- illustrator_fixed.svg: the same with a unitless width and height.
- illustrator_artboard.svg: the same outline on an A4 artboard (595.28
  x 841.89 pt), 20 mm from its left and 30 mm from its top.
- illustrator_save_as_px.svg: Illustrator's Save As SVG: its generator
  comment, x="0px" y="0px", width and height in px, xml:space.
- illustrator_hidden_layer.svg: a Save As SVG with Illustrator's
  namespace (xmlns:i) and a hidden layer (display:none), and no
  data-name: what visible_svg writes again tells nothing of
  Illustrator.
- inkscape_mm.svg: an Inkscape file in millimetres (sodipodi and
  inkscape namespaces, width and height in mm, a viewBox in mm).
- plain_px.svg: an SVG in px with no generator: 96 per inch.

Run from the repository root to write them again::

    python tests/fixtures/import/make_fixtures.py
"""

import base64
import struct
import zlib
from pathlib import Path

import ezdxf

HERE = Path(__file__).parent

# The placed PNG: 40 x 20 pixels, drawn 1.8 pt per pixel at (216, 108)
# pt; the clip keeps x 234..270 pt (pixels 10..30) and all its height.
PNG_SIZE = (40, 20)


def png_bytes(width: int, height: int) -> bytes:
    """A grey ramp PNG, 8-bit greyscale, written byte for byte."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + body + struct.pack(">I", crc)

    rows = b"".join(
        b"\x00" + bytes((x * 255 // (width - 1)) for x in range(width))
        for _y in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def illustrator_svg() -> str:
    png = base64.b64encode(png_bytes(*PNG_SIZE)).decode("ascii")
    width, height = PNG_SIZE
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Generator: Adobe Illustrator 28.0.0, SVG Export Plug-In . SVG \
Version: 6.00 Build 0)  -->
<svg xmlns="http://www.w3.org/2000/svg" \
xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 432 288">
  <defs>
    <style>
      .cls-1 {{
        fill: none;
        stroke: red;
        stroke-miterlimit: 10;
      }}

      .cls-2 {{
        fill: #231f20;
      }}

      .cls-3 {{
        clip-path: url(#clippath);
      }}
    </style>
    <clipPath id="clippath">
      <rect x="234" y="108" width="36" height="36"/>
    </clipPath>
  </defs>
  <g id="Cut">
    <rect class="cls-1" x="36" y="36" width="360" height="216"/>
  </g>
  <g id="Engrave">
    <g id="Logo">
      <circle class="cls-2" cx="90" cy="90" r="18"/>
      <polygon class="cls-2" points="72 144 108 144 90 117"/>
      <rect class="cls-2" x="126" y="72" width="36" height="36"/>
    </g>
    <g id="Text" data-name="Text">
      <path d="M72,180h9v27h18v9h-27Z"/>
      <path d="M108,180h36v36h-36Z M117,189v18h18v-18Z"/>
    </g>
    <g class="cls-3">
      <image width="{width}" height="{height}" \
transform="translate(216 108) scale(1.8)" \
xlink:href="data:image/png;base64,{png}"/>
    </g>
  </g>
</svg>
"""


AI_GENERATOR = (
    "<!-- Generator: Adobe Illustrator 28.0.0, SVG Export Plug-In . SVG "
    "Version: 6.00 Build 0)  -->"
)
AI_STYLE = """  <defs>
    <style>
      .cls-1 {
        fill: none;
        stroke: #000;
        stroke-miterlimit: 10;
      }
    </style>
  </defs>"""
AI_RECT = '<rect class="cls-1" width="283.46" height="141.73"/>'
SAVE_AS_HEAD = (
    '<svg version="1.1" id="Layer_1" xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" {extra}x="0px" y="0px"\n'
    '\t width="283.46px" height="141.73px" viewBox="0 0 283.46 141.73" '
    'style="enable-background:new 0 0 283.46 141.73;" '
    'xml:space="preserve">'
)
SAVE_AS_STYLE = """<style type="text/css">
\t.st0{fill:none;stroke:#000000;stroke-miterlimit:10;}
</style>"""


def illustrator_export_svg(size: str = "") -> str:
    """Illustrator's Export As: Responsive without size, else fixed."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
{AI_GENERATOR}
<svg id="Layer_1" data-name="Layer 1" \
xmlns="http://www.w3.org/2000/svg" {size}viewBox="0 0 283.46 141.73">
{AI_STYLE}
  {AI_RECT}
</svg>
"""


def illustrator_artboard_svg() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
{AI_GENERATOR}
<svg id="Layer_1" data-name="Layer 1" \
xmlns="http://www.w3.org/2000/svg" viewBox="0 0 595.28 841.89">
{AI_STYLE}
  <rect class="cls-1" x="56.69" y="85.04" width="283.46" height="141.73"/>
</svg>
"""


def illustrator_save_as_svg() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
{AI_GENERATOR}
{SAVE_AS_HEAD.format(extra="")}
{SAVE_AS_STYLE}
<rect class="st0" width="283.46" height="141.73"/>
</svg>
"""


def illustrator_hidden_layer_svg() -> str:
    head = SAVE_AS_HEAD.format(
        extra='xmlns:i="http://ns.adobe.com/AdobeIllustrator/10.0/" '
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
{AI_GENERATOR}
{head}
{SAVE_AS_STYLE}
<g id="Guides" style="display:none;">
\t<rect x="20" y="20" width="100" height="50"/>
</g>
<g id="Cut">
\t<rect class="st0" width="283.46" height="141.73"/>
</g>
</svg>
"""


def inkscape_mm_svg() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!-- Created with Inkscape (http://www.inkscape.org/) -->

<svg
   width="100mm"
   height="50mm"
   viewBox="0 0 100 50"
   version="1.1"
   id="svg1"
   inkscape:version="1.3.2 (091e20e, 2023-11-25)"
   sodipodi:docname="inkscape_mm.svg"
   xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
   xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
   xmlns="http://www.w3.org/2000/svg"
   xmlns:svg="http://www.w3.org/2000/svg">
  <sodipodi:namedview
     id="namedview1"
     inkscape:document-units="mm" />
  <defs
     id="defs1" />
  <g
     inkscape:label="Layer 1"
     inkscape:groupmode="layer"
     id="layer1">
    <rect
       style="fill:none;stroke:#000000;stroke-width:0.1"
       id="rect1"
       width="100"
       height="50"
       x="0"
       y="0" />
  </g>
</svg>
"""


def plain_px_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" width="377.95px" \
height="188.98px" viewBox="0 0 377.95 188.98">
  <rect width="377.95" height="188.98" fill="none" stroke="black"/>
</svg>
"""


def traced_dxf(path: Path) -> None:
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (120, 0), (120, 80), (0, 80)],
        close=True,
        dxfattribs={"color": 1},
    )
    for i in range(12):
        for j in range(10):
            x, y = 6 + 9.5 * i, 6 + 7.5 * j
            msp.add_lwpolyline(
                [(x, y), (x + 1.5, y), (x + 1.5, y + 1.5), (x, y + 1.5)],
                close=True,
                dxfattribs={"color": 7 if (i + j) % 2 else 250},
            )
    doc.saveas(path)


def _plate(x0, y0, w, h, r):
    """
    A rounded plate's outline as LINE and ARC entities, counter
    clockwise: (lines, arcs), each a list of DXF entity arguments.
    """
    x1, y1 = x0 + w, y0 + h
    lines = [
        ((x0 + r, y0), (x1 - r, y0)),
        ((x1, y0 + r), (x1, y1 - r)),
        ((x1 - r, y1), (x0 + r, y1)),
        ((x0, y1 - r), (x0, y0 + r)),
    ]
    arcs = [
        ((x1 - r, y0 + r), r, 270, 360),
        ((x1 - r, y1 - r), r, 0, 90),
        ((x0 + r, y1 - r), r, 90, 180),
        ((x0 + r, y0 + r), r, 180, 270),
    ]
    return lines, arcs


def cad_dxf(path: Path) -> None:
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    plates = [_plate(0, 0, 100, 60, 5), _plate(120, 0, 80, 50, 4)]
    for lines, _arcs in plates:
        for start, end in reversed(lines):
            msp.add_line(start, end)
    for _lines, arcs in plates:
        for center, radius, start, end in arcs:
            msp.add_arc(center, radius, start, end)
    holes = [
        ((10, 10), 3),
        ((90, 10), 3),
        ((90, 50), 3),
        ((10, 50), 3),
        ((135, 25), 2.5),
        ((185, 25), 2.5),
        ((160, 25), 8),
    ]
    for center, radius in holes:
        msp.add_circle(center, radius)
    doc.saveas(path)


def layer_names_svg() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="100mm" \
viewBox="0 0 200 100">
  <g id="cut">
    <rect x="10" y="10" width="40" height="40" fill="#000"/>
  </g>
  <g id="scan_3mm_mdf" data-name="scan 3mm mdf">
    <rect x="60" y="10" width="40" height="40" fill="none" stroke="#f00"/>
  </g>
  <g id="engrave">
    <circle cx="130" cy="30" r="20" fill="#000"/>
  </g>
  <g id="Layer_1" data-name="Layer 1">
    <rect x="160" y="10" width="30" height="80" fill="none" stroke="#00f"/>
  </g>
</svg>
"""


def main() -> None:
    (HERE / "illustrator_two_layers.svg").write_text(illustrator_svg())
    (HERE / "illustrator_responsive.svg").write_text(illustrator_export_svg())
    (HERE / "illustrator_fixed.svg").write_text(
        illustrator_export_svg('width="283.46" height="141.73" ')
    )
    (HERE / "illustrator_artboard.svg").write_text(illustrator_artboard_svg())
    (HERE / "illustrator_save_as_px.svg").write_text(illustrator_save_as_svg())
    (HERE / "illustrator_hidden_layer.svg").write_text(
        illustrator_hidden_layer_svg()
    )
    (HERE / "inkscape_mm.svg").write_text(inkscape_mm_svg())
    (HERE / "plain_px.svg").write_text(plain_px_svg())
    (HERE / "layer_names.svg").write_text(layer_names_svg())
    traced_dxf(HERE / "illustrator_traced.dxf")
    cad_dxf(HERE / "cad_plate.dxf")


if __name__ == "__main__":
    main()

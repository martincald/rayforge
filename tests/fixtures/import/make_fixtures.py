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


def main() -> None:
    (HERE / "illustrator_two_layers.svg").write_text(illustrator_svg())
    traced_dxf(HERE / "illustrator_traced.dxf")
    cad_dxf(HERE / "cad_plate.dxf")


if __name__ == "__main__":
    main()

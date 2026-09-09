"""Generate the Windows .ico from the SwiftCut app icon SVG.

Renders the vector source natively at every icon size, rather than
downscaling a single raster, so the mark stays crisp at 16 and 32 px.
"""

import io
from pathlib import Path

import cairo
import gi
from PIL import Image

gi.require_version("Rsvg", "2.0")

from gi.repository import Rsvg  # noqa: E402

here = Path(__file__).parent.parent.parent
source_path = here / "rayforge/resources/icons/org.ilab.SwiftCut.svg"
ico_path = here / "swiftcut.ico"

SIZES = [256, 128, 64, 48, 32, 16]


def render(svg_data: bytes, size: int) -> Image.Image:
    """Render the SVG into a square RGBA image of the given size."""
    handle = Rsvg.Handle.new_from_data(svg_data)
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


svg_data = source_path.read_bytes()
icons = [render(svg_data, size) for size in SIZES]
sizes = [(size, size) for size in SIZES]
icons[0].save(
    ico_path, format="ICO", sizes=sizes, append_images=icons[1:]
)
print("Icon generation complete.")

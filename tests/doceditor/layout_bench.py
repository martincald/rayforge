"""
Benchmark documents for Auto Layout, and the measures a layout is
judged by.

Each document is real workpieces: one SVG file per piece, drawn as an
unfilled outline like a typical cut file, imported one after another
through the editor (DocEditor.file.load_file_from_path) onto the
ilab-614 bed. A layout is measured on true outlines, polygonized to
TRUE_TOLERANCE_MM: every pair of pieces must keep CLEARANCE_MM, and
compactness is the bounding box area of the laid-out outlines over the
sum of their areas (1.0 would be no waste at all).
"""

import asyncio
import math
import time
from pathlib import Path
from typing import NamedTuple

import numpy as np
from raygeo.geo.shape.polygon import do_polygons_intersect

from swiftcut.core.bed_bounds import inside
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.layout.outline import item_world_polygons
from swiftcut.pipeline import intent_controller

#: The ilab-614 bed as (x, y, width, height) in world mm.
BED = (0.0, 0.0, 1400.0, 900.0)
#: The gap every pair of laid-out outlines must keep, in mm.
CLEARANCE_MM = 1.0
#: How finely outlines are polygonized for measuring, in mm.
TRUE_TOLERANCE_MM = 0.01

_UNIT_SQUARE = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


class Piece(NamedTuple):
    """One piece: its SVG shape, size and true area (mm, mm^2)."""

    name: str
    width: float
    height: float
    area: float
    body: str


def circle(diameter: float) -> Piece:
    r = diameter / 2
    return Piece(
        f"circle-{diameter:g}",
        diameter,
        diameter,
        math.pi * r * r,
        f'<circle cx="{r:g}" cy="{r:g}" r="{r:g}"/>',
    )


def ellipse(width: float, height: float) -> Piece:
    rx, ry = width / 2, height / 2
    return Piece(
        f"ellipse-{width:g}x{height:g}",
        width,
        height,
        math.pi * rx * ry,
        f'<ellipse cx="{rx:g}" cy="{ry:g}" rx="{rx:g}" ry="{ry:g}"/>',
    )


def rectangle(width: float, height: float) -> Piece:
    return Piece(
        f"rect-{width:g}x{height:g}",
        width,
        height,
        width * height,
        f'<rect width="{width:g}" height="{height:g}"/>',
    )


def _area(outline: np.ndarray) -> float:
    """The area inside a polygon (shoelace formula)."""
    x, y = outline[:, 0], outline[:, 1]
    twice = np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))
    return float(abs(twice) / 2)


def polygon(name: str, points: list[tuple[float, float]]) -> Piece:
    corners = np.array(points, dtype=float)
    width, height = corners.max(axis=0) - corners.min(axis=0)
    return Piece(
        name,
        float(width),
        float(height),
        _area(corners),
        '<polygon points="{}"/>'.format(
            " ".join(f"{x:g},{y:g}" for x, y in points)
        ),
    )


def l_shape(width: float, height: float, bar: float) -> Piece:
    return polygon(
        f"L-{width:g}x{height:g}",
        [(0, 0), (bar, 0), (bar, height - bar), (width, height - bar)]
        + [(width, height), (0, height)],
    )


def u_shape(width: float, height: float, bar: float) -> Piece:
    return polygon(
        f"U-{width:g}x{height:g}",
        [(0, 0), (bar, 0), (bar, height - bar), (width - bar, height - bar)]
        + [(width - bar, 0), (width, 0), (width, height), (0, height)],
    )


def cross(size: float, bar: float) -> Piece:
    a, b = (size - bar) / 2, (size + bar) / 2
    return polygon(
        f"cross-{size:g}",
        [(a, 0), (b, 0), (b, a), (size, a), (size, b), (b, b), (b, size)]
        + [(a, size), (a, b), (0, b), (0, a), (a, a)],
    )


def star(size: float, points: int = 5) -> Piece:
    r_outer, r_inner = size / 2, size / 5
    corners = []
    for i in range(points * 2):
        angle = math.pi * i / points - math.pi / 2
        r = r_outer if i % 2 == 0 else r_inner
        corners.append(
            (
                round(r_outer + r * math.cos(angle), 3),
                round(r_outer + r * math.sin(angle), 3),
            )
        )
    return polygon(f"star-{size:g}", corners)


#: 20 circles, 10 to 80 mm across.
CIRCLES_20 = [
    circle(d)
    for d in (80, 70, 60, 50, 45, 40, 35, 30, 30, 25)
    + (25, 20, 20, 18, 15, 15, 12, 12, 10, 10)
]

#: Circles, ellipses and rectangles, six of each.
MIXED = (
    [circle(d) for d in (70, 50, 40, 30, 20, 12)]
    + [
        ellipse(w, h)
        for w, h in ((90, 45), (70, 35), (60, 25), (40, 20), (30, 15))
        + ((20, 12),)
    ]
    + [
        rectangle(w, h)
        for w, h in ((100, 50), (80, 30), (50, 50), (40, 25), (30, 30))
        + ((20, 10),)
    ]
)

#: 40 pieces: circles, ellipses, rectangles and six concave shapes.
FORTY = (
    [circle(d) for d in (80, 60, 50, 40, 35, 30, 25, 20, 15, 10)]
    + [
        ellipse(w, h)
        for w, h in ((100, 50), (80, 40), (70, 30), (60, 35), (50, 25))
        + ((40, 30), (35, 20), (30, 15), (25, 12), (20, 10))
    ]
    + [
        rectangle(w, h)
        for w, h in ((120, 60), (100, 40), (90, 90), (80, 50), (70, 20))
        + ((60, 60), (50, 30), (45, 45), (40, 15), (35, 25), (30, 30))
        + ((25, 10), (20, 20), (15, 15))
    ]
    + [
        l_shape(80, 80, 25),
        l_shape(60, 40, 15),
        u_shape(90, 60, 20),
        u_shape(50, 40, 12),
        cross(60, 20),
        star(70),
    ]
)


class Benchmark(NamedTuple):
    """A document, and the stock (width, height) centred on the bed."""

    pieces: list[Piece]
    stock: tuple[float, float]


#: The benchmark set. Each stock is about twice the pieces' area.
BENCHMARKS = {
    "circles-20": Benchmark(CIRCLES_20, (250.0, 200.0)),
    "mixed-18": Benchmark(MIXED, (280.0, 200.0)),
    "forty-40": Benchmark(FORTY, (500.0, 320.0)),
}


def write_svg(path: Path, piece: Piece, fill: str = "none") -> Path:
    """An SVG of the piece's outline, on a page its size, in mm."""
    w, h = piece.width, piece.height
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{w:g}mm" height="{h:g}mm" viewBox="0 0 {w:g} {h:g}">'
        f'<g fill="{fill}" stroke="black" stroke-width="0.1">'
        f"{piece.body}</g></svg>"
    )
    return path


async def settle(editor, task_mgr, timeout: float = 60.0):
    """
    Waits until the editor has been idle (no task, no pipeline work)
    for longer than the pipeline's rebuild debounce, so a rebuild that
    a change scheduled has run too.
    """
    quiet = intent_controller.REBUILD_DEBOUNCE_MS / 1000 + 0.1
    deadline = time.monotonic() + timeout
    idle_since = None
    while True:
        now = time.monotonic()
        assert now < deadline, "the editor did not settle"
        if task_mgr.has_tasks() or editor.is_processing:
            idle_since = None
        elif idle_since is None:
            idle_since = now
        elif now - idle_since > quiet:
            return
        await asyncio.sleep(0.01)


async def build(
    editor,
    task_mgr,
    folder: Path,
    pieces: list[Piece],
    fill: str = "none",
    timeout: float = 60.0,
) -> list[WorkPiece]:
    """
    Imports the pieces into the editor's document, each once the one
    before is in (so the document order and their positions are the
    same on every run); returns their workpieces in that order. A
    fill other than "none" draws them filled: the outlines stay the
    same, only what renders changes.
    """
    deadline = time.monotonic() + timeout
    workpieces = []
    for n, piece in enumerate(pieces):
        path = write_svg(folder / f"{n:02d}-{piece.name}.svg", piece, fill)
        before = set(editor.doc.all_workpieces)
        editor.file.load_file_from_path(path, None, PassthroughSpec())
        while not (new := set(editor.doc.all_workpieces) - before):
            assert time.monotonic() < deadline, "import did not finish"
            await asyncio.sleep(0.005)
        (workpiece,) = new
        workpieces.append(workpiece)
    await settle(editor, task_mgr, deadline - time.monotonic())
    return workpieces


def add_stock(editor, size: tuple[float, float]):
    """Adds a visible stock of the given size, centred on the bed."""
    editor.stock.add_stock()
    stock = editor.doc.stock_items[-1]
    w, h = size
    stock.set_size(w, h)
    stock.pos = (BED[0] + (BED[2] - w) / 2, BED[1] + (BED[3] - h) / 2)
    return stock


def true_outlines(item) -> list[np.ndarray]:
    """An item's outer outlines in world mm, polygonized finely."""
    return [
        np.asarray(p, dtype=float)
        for p in item_world_polygons(item, TRUE_TOLERANCE_MM)
    ]


def gap(a: np.ndarray, b: np.ndarray, within=CLEARANCE_MM) -> float:
    """
    The exact distance between two polygon outlines that do not cross,
    where it is less than `within` (at least `within` where it is
    not): the nearest vertex-to-edge distance, both ways. (raygeo's
    get_polygon_boundary_distance overestimates it.)
    """

    def one_way(points, outline):
        lo, hi = outline.min(axis=0) - within, outline.max(axis=0) + within
        points = points[np.all((points > lo) & (points < hi), axis=1)]
        if not len(points):
            return math.inf
        ends = np.roll(outline, -1, axis=0)
        lo, hi = points.min(axis=0) - within, points.max(axis=0) + within
        near = (np.maximum(outline, ends) > lo) & (
            np.minimum(outline, ends) < hi
        )
        near = near.all(axis=1)
        if not near.any():
            return math.inf
        start, edge = outline[near], (ends - outline)[near]
        p = points[:, None, :]
        t = ((p - start) * edge).sum(-1) / (edge * edge).sum(-1)
        nearest = start + np.clip(t, 0, 1)[..., None] * edge
        return np.sqrt(((p - nearest) ** 2).sum(-1)).min()

    return float(min(one_way(a, b), one_way(b, a)))


def _box(outline: np.ndarray) -> np.ndarray:
    return np.concatenate((outline.min(axis=0), outline.max(axis=0)))


def clash(a: list[np.ndarray], b: list[np.ndarray]) -> str | None:
    """
    How two items' outlines clash: "overlap" when they cross or one
    lies inside the other, "close" when they keep less than
    CLEARANCE_MM, None when they keep it.
    """
    worst = None
    for pa in a:
        for pb in b:
            ba, bb = _box(pa), _box(pb)
            if np.any(ba[:2] >= bb[2:] + CLEARANCE_MM) or np.any(
                bb[:2] >= ba[2:] + CLEARANCE_MM
            ):
                continue
            if do_polygons_intersect(pa.tolist(), pb.tolist()):
                return "overlap"
            if gap(pa, pb) < CLEARANCE_MM - 1e-6:
                worst = "close"
    return worst


def clashes(laid_out, fixed=()) -> dict[str, int]:
    """
    The pairs of items that clash, by kind: every pair of laid-out
    items, and every laid-out item with every fixed one.
    """
    moved = [true_outlines(item) for item in laid_out]
    still = [true_outlines(item) for item in fixed]
    counts = {"overlap": 0, "close": 0}
    for i, a in enumerate(moved):
        for b in moved[i + 1 :] + still:
            kind = clash(a, b)
            if kind:
                counts[kind] += 1
    return counts


def outline_area(item) -> float:
    """The area inside an item's outlines, in mm^2."""
    return sum(_area(p) for p in true_outlines(item))


def compactness(items) -> float:
    """
    The bounding box area of the items' outlines over the sum of the
    areas inside them.
    """
    points = np.concatenate([p for item in items for p in true_outlines(item)])
    w, h = points.max(axis=0) - points.min(axis=0)
    return float(w * h / sum(outline_area(item) for item in items))


def frame_box(item) -> tuple[float, float, float, float]:
    """The world bounding box of an item's frame, (x, y, w, h)."""
    transform = item.get_world_transform()
    corners = np.array([transform.transform_point(p) for p in _UNIT_SQUARE])
    (x0, y0), (x1, y1) = corners.min(axis=0), corners.max(axis=0)
    return float(x0), float(y0), float(x1 - x0), float(y1 - y0)


def frames_outside(items, boundary) -> list:
    """The items whose frame is not inside the (x, y, w, h) boundary."""
    return [item for item in items if not inside(frame_box(item), boundary)]

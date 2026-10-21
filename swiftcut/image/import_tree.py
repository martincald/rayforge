"""
The structure of an imported vector file, as the file has it: source
layers, groups, paths and placed images. The SVG and DXF importers
build it; the import materializer turns it into workpieces and layers
for the chosen "Import as" mode.

Coordinates are the file's native ones (SVG user units, DXF drawing
units) with every nested transform applied: a node's world_transform
takes its own coordinates to the document's, and a path's geometry is
already in document coordinates. ImportTree.unit_to_mm scales them to
millimetres; ImportTree.is_y_down says which way native Y points.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from raygeo.geo import Geometry, Matrix
from raygeo.geo.types import Rect


@dataclass
class ImportNode:
    """
    What every node carries: its name, the id of the source layer it
    is on (None outside any layer), its color ("#rrggbb", None if it
    has none) and its flattened world transform.
    """

    name: str
    source_layer: str | None = None
    color: str | None = None
    world_transform: Matrix = field(default_factory=Matrix.identity)


@dataclass
class PathNode(ImportNode):
    """One path, its geometry in document coordinates."""

    geometry: Geometry = field(default_factory=Geometry)
    closed: bool = False


@dataclass
class ImageNode(ImportNode):
    """
    A placed raster: its bytes as the file holds them (PNG, JPEG),
    its box (x, y, width, height) in its own coordinates, which
    world_transform takes to the document, and its clip path in
    document coordinates, if it has one.
    """

    data: bytes = b""
    placement: Rect = (0.0, 0.0, 0.0, 0.0)
    clip: Geometry | None = None

    def world_bbox(self) -> Rect:
        """
        The box (x, y, width, height) the image covers in document
        coordinates: its placement through its world transform, cut
        to its clip's box.
        """
        x, y, w, h = self.placement
        corners = [
            self.world_transform.transform_point(p)
            for p in ((x, y), (x + w, y), (x, y + h), (x + w, y + h))
        ]
        min_x = min(p[0] for p in corners)
        min_y = min(p[1] for p in corners)
        max_x = max(p[0] for p in corners)
        max_y = max(p[1] for p in corners)
        if self.clip is not None and not self.clip.is_empty():
            cx0, cy0, cx1, cy1 = self.clip.rect()
            min_x, min_y = max(min_x, cx0), max(min_y, cy0)
            max_x, max_y = min(max_x, cx1), min(max_y, cy1)
        return min_x, min_y, max(0.0, max_x - min_x), max(0.0, max_y - min_y)


@dataclass
class GroupNode(ImportNode):
    """An SVG <g> or a DXF block insert, with its children in order."""

    children: list[ImportNode] = field(default_factory=list)

    def paths(self) -> Iterator[PathNode]:
        """Every path under this node, in drawing order."""
        for child in self.children:
            if isinstance(child, PathNode):
                yield child
            elif isinstance(child, GroupNode):
                yield from child.paths()

    def images(self) -> Iterator[ImageNode]:
        """Every image under this node, in drawing order."""
        for child in self.children:
            if isinstance(child, ImageNode):
                yield child
            elif isinstance(child, GroupNode):
                yield from child.images()


@dataclass
class LayerNode(GroupNode):
    """
    A source layer: an SVG layer group (Illustrator, Inkscape) or a
    DXF layer. Its name is the layer's name as the file shows it.
    """


@dataclass
class ImportTree:
    """
    A whole file. root holds its layers in file order, and whatever
    the file has outside any layer (groups, paths, images) beside
    them.
    """

    root: GroupNode
    unit_to_mm: float = 1.0
    is_y_down: bool = False
    warnings: list[str] = field(default_factory=list)

    def layers(self) -> list[LayerNode]:
        """The source layers, in file order."""
        return [c for c in self.root.children if isinstance(c, LayerNode)]

    def rect_mm(self, rect: Rect) -> Rect:
        """A native (x, y, width, height) box in millimetres."""
        s = self.unit_to_mm
        x, y, w, h = rect
        return x * s, y * s, w * s, h * s

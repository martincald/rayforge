"""
The structure of a DXF file as an ImportTree: its layers, block
inserts (as groups) and paths, in drawing units, Y up.

Paths are made much as the importer makes them: each container's
entities (a layer's own, each insert's) chained end to start, gaps
closed with the importer's tolerance, one path per resulting contour.
The chaining here also matches ends within that tolerance and either
way round (the importer's matches truncated millimetres, start after
end only), so a CAD outline drawn as separate LINE and ARC entities,
an arc's end a hair off its line's start, is one closed path.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import TYPE_CHECKING

from raygeo.geo import Geometry, Matrix

from ..import_tree import GroupNode, ImportTree, LayerNode, PathNode

if TYPE_CHECKING:
    from .importer import DxfImporter

logger = logging.getLogger(__name__)

BYBLOCK = 0
BYLAYER = 256
# ACI 7 draws white on a dark screen and black on paper.
ACI_BLACK_OR_WHITE = 7


def build_dxf_tree(importer: DxfImporter, doc) -> ImportTree:
    """The ImportTree of a read DXF document (an ezdxf Drawing)."""
    builder = _DxfTreeBuilder(importer, doc)
    return ImportTree(
        root=builder.root(),
        unit_to_mm=importer._get_scale_to_mm(doc),
        is_y_down=False,
    )


def _chain(paths: list, tolerance: float) -> list:
    """
    The paths in chains: each followed by an unused path that starts
    where it ends, or else one that ends there, reversed; ends match
    within tolerance.
    """
    starts: defaultdict[tuple[int, int], list[int]] = defaultdict(list)
    ends: defaultdict[tuple[int, int], list[int]] = defaultdict(list)

    def cell(point) -> tuple[int, int]:
        return math.floor(point.x / tolerance), math.floor(point.y / tolerance)

    def unused_near(index, point) -> int | None:
        cx, cy = cell(point)
        for nx in (cx - 1, cx, cx + 1):
            for ny in (cy - 1, cy, cy + 1):
                for i in index.get((nx, ny), ()):
                    if not used[i] and point.isclose(
                        paths[i].start if index is starts else paths[i].end,
                        abs_tol=tolerance,
                    ):
                        return i
        return None

    for i, path in enumerate(paths):
        starts[cell(path.start)].append(i)
        ends[cell(path.end)].append(i)
    used = [False] * len(paths)
    ordered = []
    for first in range(len(paths)):
        if used[first]:
            continue
        used[first] = True
        path = paths[first]
        ordered.append(path)
        while True:
            i = unused_near(starts, path.end)
            if i is not None:
                path = paths[i]
            else:
                i = unused_near(ends, path.end)
                if i is None:
                    break
                path = paths[i].reversed()
            used[i] = True
            ordered.append(path)
    return ordered


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _aci_hex(aci: int) -> str:
    """An AutoCAD color index as "#rrggbb", ACI 7 as black."""
    from ezdxf.colors import aci2rgb

    if aci == ACI_BLACK_OR_WHITE:
        return "#000000"
    return _hex(aci2rgb(aci))


def _matrix(m44) -> Matrix:
    """An ezdxf Matrix44 (row vectors) as a 2D raygeo Matrix."""
    ux, uy = m44[0, 0], m44[0, 1]
    vx, vy = m44[1, 0], m44[1, 1]
    tx, ty = m44[3, 0], m44[3, 1]
    return Matrix([[ux, vx, tx], [uy, vy, ty], [0.0, 0.0, 1.0]])


class _DxfTreeBuilder:
    def __init__(self, importer: DxfImporter, doc):
        self.importer = importer
        self.doc = doc
        self.layer_colors = {
            layer.dxf.name: (
                _hex(layer.rgb)
                if layer.rgb is not None
                else _aci_hex(abs(layer.dxf.color))
            )
            for layer in doc.layers
        }
        # Each container's paths by layer, made into nodes once the
        # whole drawing's box (and so the gap tolerance) is known:
        # (group, or None for the layers, paths, colors, transform).
        self.pending: list[tuple] = []

    def root(self) -> GroupNode:
        """
        The layers in table order (those with content), each holding
        its own paths and its inserts' groups.
        """
        import ezdxf.math
        import ezdxf.path

        layers = {
            layer.dxf.name: LayerNode(
                name=layer.dxf.name, source_layer=layer.dxf.name
            )
            for layer in self.doc.layers
            if layer.dxf.name.lower() != "defpoints"
        }
        root = GroupNode(name="DXF")
        identity = ezdxf.math.Matrix44()
        self._fill(
            self.doc.modelspace(), identity, "#000000", layers, root, None
        )
        # The importer's tolerance, from the box of the same paths.
        box = ezdxf.path.bbox(
            [path for entry in self.pending for path in entry[2]], fast=True
        )
        diagonal = math.hypot(*(box.size.vec2)) if box.has_data else 0.0
        tolerance = max(0.01, diagonal / 20000.0)
        loose: dict[str, list[PathNode]] = {}
        for group, layer, raw, colors, transform in self.pending:
            nodes = self._path_nodes(layer, raw, colors, transform, tolerance)
            if group is None:
                loose[layer] = nodes
            else:
                group.children.extend(nodes)
        for name, layer in layers.items():
            layer.children[:0] = loose.get(name, [])
            if layer.children:
                root.children.append(layer)
        return root

    def _fill(self, entities, transform, block_color, layers, outside, group):
        """
        Collects a container's entities: inserts become groups (in
        their own layer's node, outside any when it has none), the
        rest paths, for group (None: their layers' nodes), chained
        later per entity layer.
        """
        raw: defaultdict[str, list] = defaultdict(list)
        colors: dict[tuple[int, int], str | None] = {}
        for entity in entities:
            if entity.dxftype() == "INSERT":
                inserted = self._insert(entity, transform, block_color)
                if inserted is None:
                    continue
                target = layers.get(entity.dxf.layer)
                if target is None:
                    outside.children.append(inserted)
                else:
                    target.children.append(inserted)
                continue
            layer = entity.dxf.layer
            if layer.lower() == "defpoints":
                continue
            color = self._color(entity, block_color)
            for path in self._paths(entity, transform):
                raw[layer].append(path)
                s = path.start
                colors.setdefault((int(s.x * 1000), int(s.y * 1000)), color)
        for layer, paths in raw.items():
            self.pending.append((group, layer, paths, colors, transform))
        return raw

    def _insert(self, insert, parent, block_color) -> GroupNode | None:
        """
        An insert as a group, its transform composed as the importer
        composes it, its BYBLOCK entities in its color.
        """
        name = insert.dxf.name
        if name not in self.doc.blocks:
            return None
        transform = insert.matrix44() @ parent
        color = self._color(insert, block_color)
        group = GroupNode(
            name=name,
            source_layer=insert.dxf.layer,
            color=color,
            world_transform=_matrix(transform),
        )
        raw = self._fill(
            self.doc.blocks.get(name), transform, color, {}, group, group
        )
        return group if group.children or raw else None

    def _paths(self, entity, transform) -> list:
        """An entity's ezdxf paths in document coordinates."""
        import ezdxf.path
        from ezdxf.addons import text2path

        try:
            if entity.dxftype() in ("TEXT", "MTEXT"):
                paths = text2path.make_paths_from_entity(entity)
            else:
                paths = [ezdxf.path.make_path(entity)]  # type: ignore
            return [path.transform(transform) for path in paths]
        except Exception:
            logger.debug(
                "Failed to convert DXF entity %s",
                entity.dxftype(),
                exc_info=True,
            )
            return []

    def _color(self, entity, block_color: str) -> str | None:
        """An entity's color: its own, its layer's, or its block's."""
        if entity.rgb is not None:
            return _hex(entity.rgb)
        aci = entity.dxf.color
        if aci == BYLAYER:
            return self.layer_colors.get(entity.dxf.layer)
        if aci == BYBLOCK:
            return block_color
        return _aci_hex(aci)

    def _path_nodes(
        self, layer, paths, colors, transform, tolerance
    ) -> list[PathNode]:
        """
        One container's paths of one layer, chained, and gap-closed as
        the importer does, one node per contour, colored as the entity
        it starts with.
        """
        geometry = Geometry()
        for path in _chain(paths, tolerance):
            self.importer._consume_native_path(geometry, path)
        if geometry.is_empty():
            return []
        geometry.close_gaps(tolerance=tolerance)
        world = _matrix(transform)
        nodes = []
        for contour in geometry.split_into_contours():
            if contour.is_empty():
                continue
            x, y, _z = contour.get_command_at(0).end
            nodes.append(
                PathNode(
                    name=layer,
                    source_layer=layer,
                    color=colors.get((int(x * 1000), int(y * 1000))),
                    world_transform=world,
                    geometry=contour,
                    closed=contour.is_closed(),
                )
            )
        return nodes

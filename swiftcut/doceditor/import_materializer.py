"""
Turns an import into the document's workpieces and layers by the
chosen "Import as" mode, from the importer's workpieces and the
file's ImportTree:

- SINGLE: each workpiece as the importer made it.
- INDIVIDUAL: one workpiece per path.
- PIECES: one workpiece per piece the grouper finds (an outline with
  everything inside it).
- BY_SOURCE: one workpiece per group the file has, on a layer per
  source layer; loose paths as PIECES.

It works in two phases. In the import's worker thread, before the
content is placed, prepare_import() builds the tree, plans each
workpiece's pieces in that workpiece's normalized (0-1) space and adds
the file's placed images as workpieces of their own; placing moves
only matrices, so the plans hold. At commit, materialize() cuts each
workpiece into its planned pieces where it was going.
"""

from __future__ import annotations

import logging
import math
import warnings
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from gettext import gettext as _
from pathlib import Path
from typing import TYPE_CHECKING

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import pyvips

from raygeo.geo import Geometry
from raygeo.geo.types import Rect

from ..core.item import DocItem
from ..core.layer import Layer
from ..core.vectorization_spec import (
    LayerImportMode,
    LayerSource,
    PassthroughSpec,
    TraceSpec,
    VectorizationSpec,
)
from ..core.workpiece import WorkPiece
from ..image.engine import NormalizationEngine
from ..image.grouper import group_pieces
from ..image.import_tree import (
    GroupNode,
    ImageNode,
    ImportTree,
    LayerNode,
    PathNode,
)
from ..image.jpg.importer import JpgImporter
from ..image.png.importer import PngImporter
from ..image.svg.importer import SvgImporter
from .split_cmd import PathSplitStrategy

if TYPE_CHECKING:
    from ..core.source_asset import SourceAsset
    from ..image.base_importer import Importer
    from ..image.structures import ImportResult, ParsingResult

logger = logging.getLogger(__name__)

# First points this close (mm) are the same point.
_POINT_TOLERANCE_MM = 1e-3


class ImportGrouping(Enum):
    """How an import's content becomes workpieces."""

    BY_SOURCE = "by_source"
    PIECES = "pieces"
    INDIVIDUAL = "individual"
    SINGLE = "single"


@dataclass
class ImportOptions:
    """
    The "Import as" choices of one import: the grouping, whether a
    piece's interior detail goes to a layer of its own, whether placed
    images come in, and (BY_SOURCE) whether each source layer gets a
    layer of its own.
    """

    grouping: ImportGrouping = ImportGrouping.SINGLE
    interior_on_own_layer: bool = False
    keep_images: bool = True
    layer_per_source_layer: bool = True


@dataclass
class PlannedPiece:
    """
    One piece of a workpiece, in the workpiece's normalized space: its
    boundary (cut) and interior (artwork; empty unless it goes to a
    layer of its own), and where they came from: the piece's source
    layer, its color (its outline's, or its group's first path's) and
    its interior's (the first interior path's).
    """

    boundary: Geometry
    interior: Geometry
    source_layer: str | None
    color: str | None
    interior_color: str | None = None


@dataclass
class PreparedImport:
    """
    What the worker phase hands the commit: the options, the grouping
    in effect, the file's tree (if one was built), each workpiece's
    planned pieces by uid, and the name of the interior layer.
    """

    options: ImportOptions
    grouping: ImportGrouping
    tree: ImportTree | None = None
    plans: dict[str, list[PlannedPiece]] = field(default_factory=dict)
    interior_layer_name: str = ""


def options_for(
    options: ImportOptions | None, split_paths: bool = False
) -> ImportOptions:
    """
    The options of an import. Without any, an import is what it was
    before there were options: individual shapes with split_paths,
    else a single shape, and no placed images.
    """
    if options is not None:
        return options
    grouping = (
        ImportGrouping.INDIVIDUAL if split_paths else ImportGrouping.SINGLE
    )
    return ImportOptions(grouping=grouping, keep_images=False)


def import_spec(
    spec: VectorizationSpec | None,
    options: ImportOptions,
    importer_cls: type[Importer] | None = None,
) -> VectorizationSpec | None:
    """
    The spec the importer runs with. BY_SOURCE reads the file's own
    layers (not its colors), each onto a layer of its own or all onto
    the current one, as layer_per_source_layer says. An SVG whose
    placed images come in as workpieces renders its vector pieces
    without them.
    """
    by_source = options.grouping is ImportGrouping.BY_SOURCE
    images_apart = (
        options.keep_images
        and importer_cls is not None
        and issubclass(importer_cls, SvgImporter)
    )
    if not (by_source or images_apart):
        return spec
    spec = spec or PassthroughSpec()
    if not isinstance(spec, PassthroughSpec):
        return spec
    if images_apart:
        spec = replace(spec, images_apart=True)
    if not by_source:
        return spec
    by_layers = spec.layer_source is LayerSource.SVG_LAYERS
    return replace(
        spec,
        active_layer_ids=spec.active_layer_ids if by_layers else None,
        layer_source=LayerSource.SVG_LAYERS,
        layer_import_mode=(
            LayerImportMode.NEW_LAYERS
            if options.layer_per_source_layer
            else LayerImportMode.FLATTEN
        ),
    )


def effective_grouping(
    tree: ImportTree | None, grouping: ImportGrouping
) -> ImportGrouping:
    """
    The grouping an import gets: BY_SOURCE of a file with at most one
    layer and no groups (nothing to go by) is PIECES.
    """
    if grouping is ImportGrouping.BY_SOURCE and (
        tree is None
        or (len(tree.layers()) <= 1 and not _has_groups(tree.root))
    ):
        return ImportGrouping.PIECES
    return grouping


def _has_groups(node: GroupNode) -> bool:
    """Whether any group (a layer is not one) lies under node."""
    for child in node.children:
        if isinstance(child, LayerNode):
            if _has_groups(child):
                return True
        elif isinstance(child, GroupNode):
            return True
    return False


# --- Worker phase ---


def prepare_import(
    import_result: ImportResult,
    importer_cls: type[Importer],
    filename: Path,
    spec: VectorizationSpec | None,
    options: ImportOptions,
) -> PreparedImport:
    """
    Plans the pieces of the import's workpieces and adds its placed
    images to the payload. Runs in the worker thread, before the
    content is placed.
    """
    prepared = PreparedImport(
        options=options,
        grouping=options.grouping,
        interior_layer_name=_("{name} engrave").format(name=filename.stem),
    )
    payload = import_result.payload
    parse_result = import_result.parse_result
    if payload is None or parse_result is None or isinstance(spec, TraceSpec):
        return prepared
    grouped = options.grouping in (
        ImportGrouping.PIECES,
        ImportGrouping.BY_SOURCE,
    )
    # Individual shapes take their source layer and color from it.
    wants_tree = grouped or options.grouping is ImportGrouping.INDIVIDUAL
    data = None
    if wants_tree or options.keep_images:
        data = filename.read_bytes()
    if wants_tree or (options.keep_images and b"<image" in (data or b"")):
        importer = importer_cls(data, source_file=filename)
        ppi = spec.ppi if spec is not None else 96.0
        prepared.tree = importer.build_tree(ppi)
    tree = prepared.tree
    if tree is not None:
        tree.unit_to_mm = parse_result.native_unit_to_mm
        import_result.warnings.extend(tree.warnings)
    prepared.grouping = effective_grouping(tree, options.grouping)
    if grouped:
        unit_to_mm = parse_result.native_unit_to_mm
        for wp in _workpieces(payload.items):
            plan = _plan(prepared, wp, spec, unit_to_mm)
            if plan:
                prepared.plans[wp.uid] = plan
    if tree is not None and options.keep_images:
        _add_images(prepared, import_result, filename, spec)
    return prepared


def _workpieces(items: Sequence[DocItem]) -> list[WorkPiece]:
    """The workpieces of imported items, in layers or not."""
    found = []
    for item in items:
        if isinstance(item, Layer):
            found.extend(
                c for c in item.get_content_items() if isinstance(c, WorkPiece)
            )
        elif isinstance(item, WorkPiece):
            found.append(item)
    return found


def _host_paths(
    tree: ImportTree | None, wp: WorkPiece, spec: VectorizationSpec | None
) -> list[PathNode]:
    """
    The tree's paths the workpiece holds: those of its source layer,
    or (merged layers) of every layer read. Without a tree (or for
    color layers, which the tree does not know), the workpiece's own
    contours.
    """
    segment = wp.source_segment
    by_colors = (
        isinstance(spec, PassthroughSpec)
        and spec.layer_source is LayerSource.COLORS
    )
    if tree is None or segment is None or by_colors:
        return _contour_paths(wp)
    paths = list(tree.root.paths())
    if segment.layer_id is not None:
        return [p for p in paths if p.source_layer == segment.layer_id]
    active = (
        spec.active_layer_ids if isinstance(spec, PassthroughSpec) else None
    )
    # The importer reads only layers when the file has some.
    has_layers = bool(tree.layers())
    return [
        p
        for p in paths
        if (not active or p.source_layer in active)
        and (p.source_layer is not None or not has_layers)
    ]


def _contour_paths(wp: WorkPiece) -> list[PathNode]:
    """A workpiece's contours as paths, in native coordinates."""
    segment = wp.source_segment
    if segment is None or segment.pristine_geometry is None:
        return []
    return [
        PathNode(
            name=wp.name,
            source_layer=segment.layer_id,
            geometry=contour,
            closed=contour.is_closed(),
        )
        for contour in segment.pristine_geometry.split_into_contours()
    ]


def _plan(
    prepared: PreparedImport,
    wp: WorkPiece,
    spec: VectorizationSpec | None,
    unit_to_mm: float,
) -> list[PlannedPiece]:
    """A workpiece's pieces, as (boundary, interior) path lists."""
    segment = wp.source_segment
    paths = _host_paths(prepared.tree, wp, spec)
    if segment is None or segment.normalization_matrix is None or not paths:
        return []
    split = prepared.options.interior_on_own_layer
    if prepared.grouping is ImportGrouping.BY_SOURCE:
        assert prepared.tree is not None
        parts = _source_parts(prepared.tree, paths, unit_to_mm, split)
    else:
        parts = _grouped_parts(paths, unit_to_mm, split)
    norm = segment.normalization_matrix
    return [
        PlannedPiece(
            boundary=_fragment(boundary, norm),
            interior=_fragment(interior, norm),
            source_layer=(boundary or interior)[0].source_layer,
            color=color,
            interior_color=interior[0].color if interior else None,
        )
        for boundary, interior, color in parts
    ]


def _fragment(paths: list[PathNode], norm) -> Geometry:
    """Paths in native coordinates as one normalized geometry."""
    geo = Geometry()
    for path in paths:
        geo.extend(path.geometry)
    geo.transform(norm)
    return geo


def _grouped_parts(paths, unit_to_mm, split):
    """
    The grouper's pieces as (boundary, interior, color): interior
    detail kept apart only when it goes to a layer of its own. A
    piece's color is its outline's (its largest boundary path).
    """
    order = {id(p): i for i, p in enumerate(paths)}
    parts = []
    for piece in group_pieces(paths, unit_to_mm):
        boundary, interior = piece.boundary, piece.interior
        if not split:
            boundary = sorted(boundary + interior, key=lambda p: order[id(p)])
            interior = []
        outline = max(boundary or interior, key=_box_area)
        parts.append((boundary, interior, outline.color))
    return parts


def _box_area(path: PathNode) -> float:
    x0, y0, x1, y1 = path.geometry.rect()
    return (x1 - x0) * (y1 - y0)


def _source_parts(tree, paths, unit_to_mm, split):
    """
    BY_SOURCE pieces as (boundary, interior, color): each group at
    the top of a layer (or of the file, outside layers) one piece,
    its interior the grouper's interior of its paths; the loose paths
    as the grouper groups them. A group's color is its first path's.
    """
    owner = _top_groups(tree)
    groups: dict[int, list[PathNode]] = {}
    loose = []
    for path in paths:
        group = owner.get(id(path))
        if group is None:
            loose.append(path)
        else:
            groups.setdefault(group, []).append(path)
    parts = []
    for members in groups.values():
        interior = []
        if split:
            inside = {
                id(p)
                for piece in group_pieces(members, unit_to_mm)
                for p in piece.interior
            }
            interior = [p for p in members if id(p) in inside]
            members = [p for p in members if id(p) not in inside]
        parts.append((members, interior, (members or interior)[0].color))
    if loose:
        parts.extend(_grouped_parts(loose, unit_to_mm, split))
    return parts


def _top_groups(tree: ImportTree) -> dict[int, int]:
    """
    For each path in a group, the id of the group at the top of its
    layer (or of the file, outside layers).
    """
    owner = {}
    containers = [tree.root, *tree.layers()]
    for container in containers:
        for child in container.children:
            if isinstance(child, GroupNode) and not isinstance(
                child, LayerNode
            ):
                for path in child.paths():
                    owner[id(path)] = id(child)
    return owner


# --- Placed images ---


def _add_images(
    prepared: PreparedImport,
    import_result: ImportResult,
    filename: Path,
    spec: VectorizationSpec | None,
) -> None:
    """
    Adds each placed image of the tree, as a workpiece of its own, to
    the payload: on its source layer's layer when the import makes
    layers of source layers, else beside the other items.
    """
    assert prepared.tree is not None and import_result.payload is not None
    assert import_result.parse_result is not None
    payload = import_result.payload
    by_layers = not (
        isinstance(spec, PassthroughSpec)
        and spec.layer_source is LayerSource.COLORS
    )
    active = (
        spec.active_layer_ids
        if by_layers and isinstance(spec, PassthroughSpec)
        else None
    )
    new_layers = by_layers and not (
        isinstance(spec, PassthroughSpec)
        and spec.layer_import_mode is LayerImportMode.FLATTEN
    )
    names = {n.source_layer: n.name for n in prepared.tree.layers()}
    homes = {
        wp.source_segment.layer_id: item
        for item in payload.items
        if isinstance(item, Layer)
        for wp in _workpieces([item])
        if wp.source_segment is not None
    }
    for image in prepared.tree.root.images():
        if active and image.source_layer not in active:
            continue
        made = _image_workpiece(
            image, import_result.parse_result, filename, import_result
        )
        if made is None:
            continue
        wp, asset = made
        payload.assets.append(asset)
        home = homes.get(image.source_layer) if by_layers else None
        if home is None and new_layers and image.source_layer is not None:
            home = Layer(name=names.get(image.source_layer, image.name))
            homes[image.source_layer] = home
            payload.items.append(home)
        if home is not None:
            home.add_child(wp)
        else:
            payload.items.append(wp)


def _image_workpiece(
    image: ImageNode,
    parse_result: ParsingResult,
    filename: Path,
    import_result: ImportResult,
) -> tuple[WorkPiece, SourceAsset] | None:
    """
    A placed image as a workpiece of its own, cut to its clip's box,
    imported like a PNG or JPEG imported whole and laid where the
    file shows it. An image turned or flipped is skipped, with a
    warning.
    """
    (a, c, e), (b, d, f), _row = image.world_transform.to_list()
    if abs(b) > 1e-9 or abs(c) > 1e-9 or a <= 0 or d <= 0:
        import_result.warnings.append(
            _(
                'Image "{name}" is rotated, skewed or flipped and was not '
                "imported."
            ).format(name=image.name)
        )
        return None
    pixels = pyvips.Image.new_from_buffer(image.data, "")
    x, y, w, h = image.placement
    drawn = (a * x + e, d * y + f, a * w, d * h)
    crop = _pixel_crop(drawn, image.clip, pixels.width, pixels.height)
    if crop is None:
        return None
    (left, top, cols, rows), rect = crop
    data, importer_cls = image.data, PngImporter
    if (left, top, cols, rows) != (0, 0, pixels.width, pixels.height):
        data = pixels.crop(left, top, cols, rows).pngsave_buffer()
    elif image.data.startswith(b"\xff\xd8"):
        importer_cls = JpgImporter
    suffix = ".jpg" if importer_cls is JpgImporter else ".png"
    importer = importer_cls(
        data, source_file=filename.with_name(image.name + suffix)
    )
    result = importer.get_doc_items(
        TraceSpec(threshold=1.0, auto_threshold=False)
    )
    if result is None or result.payload is None or not result.payload.items:
        return None
    (wp,) = _workpieces(result.payload.items)
    layout = NormalizationEngine.calculate_layout_item(rect, parse_result)
    width_mm, height_mm = layout.world_matrix.get_abs_scale()
    wp.matrix = layout.world_matrix
    wp.natural_width_mm, wp.natural_height_mm = width_mm, height_mm
    if wp.source_segment is not None:
        wp.source_segment.cropped_width_mm = width_mm
        wp.source_segment.cropped_height_mm = height_mm
    wp.source_layer = image.source_layer
    return wp, result.payload.source


def _pixel_crop(
    drawn: Rect, clip: Geometry | None, width_px: int, height_px: int
) -> tuple[tuple[int, int, int, int], Rect] | None:
    """
    The pixels (left, top, columns, rows) an image keeps inside its
    clip's box, rounded out to whole pixels, and the native box they
    fill; None if none shows.
    """
    x, y, w, h = drawn
    x0, y0, x1, y1 = x, y, x + w, y + h
    if clip is not None and not clip.is_empty():
        cx0, cy0, cx1, cy1 = clip.rect()
        x0, y0 = max(x0, cx0), max(y0, cy0)
        x1, y1 = min(x1, cx1), min(y1, cy1)
    sx, sy = width_px / w, height_px / h
    eps = 1e-6
    left = max(0, math.floor((x0 - x) * sx + eps))
    top = max(0, math.floor((y0 - y) * sy + eps))
    right = min(width_px, math.ceil((x1 - x) * sx - eps))
    bottom = min(height_px, math.ceil((y1 - y) * sy - eps))
    if right <= left or bottom <= top:
        return None
    rect = (
        x + left / sx,
        y + top / sy,
        (right - left) / sx,
        (bottom - top) / sy,
    )
    return (left, top, right - left, bottom - top), rect


# --- Commit phase ---


def materialize(
    pairs: list[tuple[DocItem, DocItem]],
    source: SourceAsset | None,
    prepared: PreparedImport,
    doc: DocItem,
) -> list[tuple[DocItem, DocItem]]:
    """
    The (owner, item) pairs of an import, its workpieces cut as the
    grouping says, each piece going where its workpiece was going;
    interior pieces on a layer of their own when the options say so.
    The items are not in the document yet, so no undo is needed.
    """
    grouping = prepared.grouping
    if grouping is ImportGrouping.SINGLE:
        return pairs
    if grouping is ImportGrouping.INDIVIDUAL:
        index = _first_point_index(pairs, prepared.tree)
        pairs = split_into_paths(pairs, source)
        if index:
            _attribute(pairs, index)
        return pairs
    interior_layer = Layer(name=prepared.interior_layer_name)

    def pieces_of(wp: WorkPiece) -> list[DocItem]:
        plan = prepared.plans.get(wp.uid)
        if not plan:
            return [wp]
        kept, inner = _cut(wp, plan, source)
        interior_layer.add_children(inner)
        return list(kept)

    result: list[tuple[DocItem, DocItem]] = []
    for owner, item in pairs:
        if isinstance(item, Layer):
            for child in item.get_content_items():
                if isinstance(child, WorkPiece):
                    index = item.children.index(child)
                    item.remove_child(child)
                    item.add_children(pieces_of(child), index=index)
            result.append((owner, item))
        elif isinstance(item, WorkPiece):
            result.extend((owner, piece) for piece in pieces_of(item))
        else:
            result.append((owner, item))
    if interior_layer.get_content_items():
        result.append((doc, interior_layer))
    return result


def _cut(
    wp: WorkPiece, plan: list[PlannedPiece], source: SourceAsset | None
) -> tuple[list[WorkPiece], list[WorkPiece]]:
    """
    The workpiece cut into its planned pieces: (boundary pieces,
    interior pieces), each with its source layer and color.
    """
    roles = []
    fragments = []
    for piece in plan:
        for geometry, inner in (
            (piece.boundary, False),
            (piece.interior, True),
        ):
            if not geometry.is_empty():
                roles.append((piece, inner))
                fragments.append(geometry)
    # apply_split makes nothing of a lone fragment; twice, it makes
    # one piece of it twice.
    lone = len(fragments) == 1
    made = wp.apply_split(
        fragments * 2 if lone else fragments, source=source, drop_dust=False
    )
    kept: list[WorkPiece] = []
    inner_pieces: list[WorkPiece] = []
    for (piece, inner), new in zip(roles, made[:1] if lone else made):
        new.source_layer = piece.source_layer
        new.source_color = piece.interior_color if inner else piece.color
        (inner_pieces if inner else kept).append(new)
    return kept, inner_pieces


def split_into_paths(
    pairs: list[tuple[DocItem, DocItem]], source: SourceAsset | None
) -> list[tuple[DocItem, DocItem]]:
    """
    Replaces each imported workpiece of several paths, top level or
    in a layer, with one workpiece per path (see PathSplitStrategy),
    every path kept, each going where the workpiece was going. The
    items are not in the document yet, so no undo is needed.
    """
    strategy = PathSplitStrategy()

    def paths_of(wp: WorkPiece) -> list[DocItem]:
        fragments = strategy.calculate_fragments(wp)
        pieces = wp.apply_split(fragments, source=source, drop_dust=False)
        return list(pieces) if len(pieces) > 1 else [wp]

    result: list[tuple[DocItem, DocItem]] = []
    for owner, item in pairs:
        if isinstance(item, Layer):
            for child in item.get_content_items():
                if isinstance(child, WorkPiece):
                    index = item.children.index(child)
                    item.remove_child(child)
                    item.add_children(paths_of(child), index=index)
            result.append((owner, item))
        elif isinstance(item, WorkPiece):
            result.extend((owner, piece) for piece in paths_of(item))
        else:
            result.append((owner, item))
    return result


def _cell(point) -> tuple[int, int]:
    return (
        math.floor(point[0] / _POINT_TOLERANCE_MM),
        math.floor(point[1] / _POINT_TOLERANCE_MM),
    )


def _vector_workpieces(pairs) -> list[WorkPiece]:
    """The paired workpieces, placed images left out."""
    return [
        wp
        for wp in _workpieces([item for _owner, item in pairs])
        if wp.source_segment is not None
        and not isinstance(wp.source_segment.vectorization_spec, TraceSpec)
    ]


def _first_point_index(pairs, tree: ImportTree | None):
    """
    The tree's paths by the world position of each of their contours'
    first point, in the workpieces they lie in.
    """
    index: defaultdict[tuple[int, int], list] = defaultdict(list)
    if tree is None:
        return index
    for wp in _vector_workpieces(pairs):
        segment = wp.source_segment
        if segment is None or segment.normalization_matrix is None:
            continue
        to_world = wp.matrix @ segment.normalization_matrix
        for path in _host_paths(tree, wp, segment.vectorization_spec):
            for contour in path.geometry.split_into_contours():
                x, y, _z = contour.get_command_at(0).end
                point = to_world.transform_point((x, y))
                index[_cell(point)].append((point, path))
    return index


def _attribute(pairs, index) -> None:
    """
    Gives each workpiece the source layer and color of the tree path
    its first point starts.
    """
    for wp in _vector_workpieces(pairs):
        boundaries = wp.boundaries
        if boundaries is None or boundaries.is_empty():
            continue
        x, y, _z = boundaries.get_command_at(0).end
        path = _path_at(index, wp.matrix.transform_point((x, y)))
        if path is not None:
            wp.source_layer = path.source_layer
            wp.source_color = path.color


def _path_at(index, point) -> PathNode | None:
    """The indexed path with a first point at point, if any."""
    cx, cy = _cell(point)
    for nx in (cx - 1, cx, cx + 1):
        for ny in (cy - 1, cy, cy + 1):
            for other, path in index.get((nx, ny), ()):
                if math.dist(point, other) <= _POINT_TOLERANCE_MM:
                    return path
    return None

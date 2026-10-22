"""
The structure of an SVG file as an ImportTree: its layers (the same
top-level groups the importer makes layers of), groups, paths and
placed images, in the SVG's user units (the viewBox coordinates the
importer's geometry is in).

Each path's geometry is what raygeo makes of that one element under
its flattened transform, so it is the importer's geometry for it,
curves flattened alike.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from gettext import gettext as _
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import pyvips

from raygeo.geo import Geometry, Matrix
from raygeo.svg import svg_string_to_geometry
from raygeo.svg.length import parse_svg_length
from raygeo.svg.metadata import extract_svg_metadata
from raygeo.svg.transform import parse_svg_transform

from ...core.color import normalize_color
from ..import_tree import (
    GroupNode,
    ImageNode,
    ImportNode,
    ImportTree,
    LayerNode,
    PathNode,
)
from .svgutil import PPI, SVG_NS, get_natural_size, layer_groups

logger = logging.getLogger(__name__)

XLINK_HREF = "{http://www.w3.org/1999/xlink}href"

# Elements whose children are drawn where they stand. Everything not
# listed here, in SHAPES or handled by name (image, text, use) draws
# nothing: defs, clipPath, mask, symbol, style, metadata and the like.
CONTAINERS = {"g", "a", "switch", "svg"}
SHAPES = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}

# Properties that pass from a parent to its children.
INHERITED = ("fill", "stroke", "color", "visibility")

_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_CLASS_SELECTOR = re.compile(r"^\.([\w-]+)$")
_URL = re.compile(r"url\(\s*['\"]?#([^)'\"]+)['\"]?\s*\)")
_TEXT_PREVIEW = 40


def build_svg_tree(
    data: bytes, source_file: Path | None = None, ppi: float = PPI
) -> ImportTree:
    """
    The ImportTree of an SVG. A linked image is looked up next to
    source_file; ppi sizes a file without physical units. What cannot
    be imported (text not outlined, missing or unknown images) is
    skipped with a warning in the tree's warnings.
    """
    root = ET.fromstring(data)
    builder = _SvgTreeBuilder(root, source_file)
    tree = ImportTree(
        root=GroupNode(name=source_file.stem if source_file else "SVG"),
        unit_to_mm=_unit_to_mm(data, ppi),
        is_y_down=True,
        warnings=builder.warnings,
    )
    builder.fill(tree.root)
    return tree


def _unit_to_mm(data: bytes, ppi: float) -> float:
    """
    Millimetres per user unit, as the importer works it out: the
    physical width over the viewBox width (without a viewBox, a user
    unit is a pixel at ppi).
    """
    meta = extract_svg_metadata(data.decode("utf-8"))
    width_px = meta.width_px(ppi)
    size_mm = get_natural_size(data, ppi=ppi)
    if width_px is None or width_px <= 0:
        return 25.4 / ppi
    width_mm = size_mm[0] if size_mm else width_px * 25.4 / ppi
    if meta.viewbox and meta.viewbox[2] > 0:
        return width_mm / meta.viewbox[2]
    return width_mm / width_px


def _local(element: ET.Element) -> str:
    """An element's tag without its namespace."""
    tag = element.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _parse_declarations(text: str | None) -> dict[str, str]:
    """A CSS declaration list ("fill:none;stroke:#f00") as a dict."""
    props = {}
    for item in (text or "").split(";"):
        name, sep, value = item.partition(":")
        if sep and name.strip():
            props[name.strip().lower()] = value.strip()
    return props


def _matrix_text(matrix: Matrix) -> str:
    """A matrix as an SVG transform, at full precision."""
    (a, c, e), (b, d, f), _row = matrix.to_list()
    return f"matrix({a!r} {b!r} {c!r} {d!r} {e!r} {f!r})"


def _length(element: ET.Element, name: str) -> float | None:
    """A length attribute in user units, None if absent or bad."""
    text = element.get(name)
    if text is None:
        return None
    try:
        value, _unit = parse_svg_length(text)
        return float(value)
    except (ValueError, TypeError):
        return None


def _image_format(data: bytes) -> str | None:
    """PNG or JPEG by its signature, else None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    return None


@dataclass
class _Context:
    """What an element inherits from where it stands."""

    world: Matrix
    props: dict[str, str]
    layer: str | None
    clip: Geometry | None


class _SvgTreeBuilder:
    def __init__(self, root: ET.Element, source_file: Path | None):
        self.root = root
        self.folder = source_file.parent if source_file else None
        self.warnings: list[str] = []
        self.by_id = {
            e.get("id"): e for e in root.iter() if e.get("id") is not None
        }
        self.class_rules = self._class_rules(root)
        self._using: set[int] = set()

    # --- Walking ---

    def fill(self, tree_root: GroupNode) -> None:
        """Adds the layers, and what lies outside them, to tree_root."""
        world = Matrix(parse_svg_transform(self.root.get("transform", "")))
        top = _Context(
            world, self._props(self.root, {"fill": "black"}), None, None
        )
        layers = {
            id(g): (lid, name) for g, lid, name in layer_groups(self.root)
        }
        for child in self.root:
            if id(child) in layers:
                layer_id, name = layers[id(child)]
                layer = self._layer(child, layer_id, name, top)
                if layer is not None:
                    tree_root.children.append(layer)
            else:
                tree_root.children.extend(self._nodes(child, top))

    def _layer(
        self, group: ET.Element, layer_id: str, name: str, ctx: _Context
    ) -> LayerNode | None:
        if group.get("display") == "none":
            return None
        inner = self._enter(group, ctx, layer_id)
        node = LayerNode(
            name=name, source_layer=layer_id, world_transform=inner.world
        )
        for child in group:
            node.children.extend(self._nodes(child, inner))
        return node

    def _enter(
        self, element: ET.Element, ctx: _Context, layer: str | None
    ) -> _Context:
        """The context an element's own content is drawn in."""
        transform = element.get("transform")
        world = ctx.world
        if transform:
            world = ctx.world @ Matrix(parse_svg_transform(transform))
        props = self._props(element, ctx.props)
        clip = self._clip(element, props, world)
        return _Context(
            world, props, layer, clip if clip is not None else ctx.clip
        )

    def _nodes(self, element: ET.Element, ctx: _Context) -> list[ImportNode]:
        """The nodes one element makes: none, one, or (use) a group."""
        tag = _local(element)
        if element.get("display") == "none":
            return []
        if tag in CONTAINERS:
            return [self._group(element, ctx)]
        if tag in SHAPES:
            path = self._path(element, ctx)
            return [path] if path is not None else []
        if tag == "image":
            image = self._image(element, ctx)
            return [image] if image is not None else []
        if tag == "use":
            group = self._use(element, ctx)
            return [group] if group is not None else []
        if tag == "text":
            self._warn_text(element)
        return []

    def _group(self, element: ET.Element, ctx: _Context) -> GroupNode:
        inner = self._enter(element, ctx, ctx.layer)
        node = GroupNode(
            name=element.get("data-name") or element.get("id") or _("Group"),
            source_layer=ctx.layer,
            world_transform=inner.world,
        )
        for child in element:
            node.children.extend(self._nodes(child, inner))
        return node

    def _use(self, element: ET.Element, ctx: _Context) -> GroupNode | None:
        """
        A <use> as a group: what it references, moved by its x and y
        (a symbol's own viewBox is not applied, as the importer does
        not apply it).
        """
        target = self._referenced(element)
        if target is None or id(target) in self._using:
            return None
        inner = self._enter(element, ctx, ctx.layer)
        shift = Matrix.translation(
            _length(element, "x") or 0.0, _length(element, "y") or 0.0
        )
        inner.world = inner.world @ shift
        node = GroupNode(
            name=(
                element.get("data-name")
                or target.get("data-name")
                or target.get("id")
                or _("Group")
            ),
            source_layer=ctx.layer,
            world_transform=inner.world,
        )
        self._using.add(id(target))
        try:
            if _local(target) == "symbol":
                symbol = self._enter(target, inner, ctx.layer)
                for child in target:
                    node.children.extend(self._nodes(child, symbol))
            else:
                node.children.extend(self._nodes(target, inner))
        finally:
            self._using.discard(id(target))
        return node

    def _referenced(self, element: ET.Element) -> ET.Element | None:
        """The element an href="#id" points at."""
        href = element.get("href") or element.get(XLINK_HREF) or ""
        if not href.startswith("#"):
            return None
        return self.by_id.get(href[1:])

    # --- Paths ---

    def _path(self, element: ET.Element, ctx: _Context) -> PathNode | None:
        inner = self._enter(element, ctx, ctx.layer)
        if inner.props.get("visibility") in ("hidden", "collapse"):
            return None
        geometry = self._geometry(element, ctx.world)
        if geometry.is_empty():
            return None
        return PathNode(
            name=(
                element.get("data-name")
                or element.get("id")
                or _local(element)
            ),
            source_layer=ctx.layer,
            color=self._color(inner.props),
            world_transform=inner.world,
            geometry=geometry,
            closed=all(c.is_closed() for c in geometry.split_into_contours()),
        )

    @staticmethod
    def _geometry(element: ET.Element, world: Matrix) -> Geometry:
        """
        One shape element's geometry in document coordinates, as
        raygeo makes it: the element alone, under world and its own
        transform.
        """
        shape = ET.Element(element.tag, dict(element.attrib))
        svg = (
            f'<svg xmlns="{SVG_NS}"><g transform="{_matrix_text(world)}">'
            f"{ET.tostring(shape, encoding='unicode')}</g></svg>"
        )
        try:
            return svg_string_to_geometry(svg, 1.0, 1.0)
        except ValueError:
            return Geometry()

    # --- Style ---

    @staticmethod
    def _class_rules(root: ET.Element) -> list[tuple[str, dict[str, str]]]:
        """The class rules (".cls-1{...}") of every <style>, in order."""
        rules = []
        for style in root.iter():
            if _local(style) != "style":
                continue
            text = _CSS_COMMENT.sub("", style.text or "")
            for selectors, body in _CSS_RULE.findall(text):
                props = _parse_declarations(body)
                for selector in selectors.split(","):
                    match = _CLASS_SELECTOR.match(selector.strip())
                    if match:
                        rules.append((match.group(1), props))
        return rules

    def _props(
        self, element: ET.Element, inherited: dict[str, str]
    ) -> dict[str, str]:
        """
        An element's style: its presentation attributes, overridden by
        its classes' rules, overridden by its style attribute; what it
        leaves unset (or sets to inherit) comes from inherited.
        """
        own = {
            name: element.get(name)
            for name in (*INHERITED, "clip-path")
            if element.get(name) is not None
        }
        classes = set((element.get("class") or "").split())
        for name, props in self.class_rules:
            if name in classes:
                own.update(props)
        own.update(_parse_declarations(element.get("style")))
        props = {
            name: inherited[name] for name in INHERITED if name in inherited
        }
        for name, value in own.items():
            if value != "inherit":
                props[name] = value
        return props

    @staticmethod
    def _color(props: dict[str, str]) -> str | None:
        """The stroke if it has one, else the fill, as "#rrggbb"."""
        for name in ("stroke", "fill"):
            value = props.get(name, "none").strip()
            if value == "currentColor":
                value = props.get("color", "black")
            if value != "none":
                return normalize_color(value)
        return None

    # --- Clips ---

    def _clip(
        self, element: ET.Element, props: dict[str, str], world: Matrix
    ) -> Geometry | None:
        """
        The clip path an element sets, in document coordinates: its
        clipPath's shapes in the element's user space (world), under
        the clipPath's own transform.
        """
        match = _URL.search(props.get("clip-path", ""))
        if not match:
            return None
        clip_path = self.by_id.get(match.group(1))
        if clip_path is None or _local(clip_path) != "clipPath":
            return None
        if clip_path.get("clipPathUnits") == "objectBoundingBox":
            self.warnings.append(_("A clip in object units was ignored."))
            return None
        transform = clip_path.get("transform")
        if transform:
            world = world @ Matrix(parse_svg_transform(transform))
        clip = Geometry()
        for geometry in self._clip_shapes(clip_path, world):
            clip.extend(geometry)
        return None if clip.is_empty() else clip

    def _clip_shapes(
        self, element: ET.Element, world: Matrix
    ) -> Iterator[Geometry]:
        """The shapes under a clipPath, <use> resolved, in place."""
        for child in element:
            tag = _local(child)
            transform = child.get("transform")
            inner = world
            if transform:
                inner = world @ Matrix(parse_svg_transform(transform))
            if tag in SHAPES:
                yield self._geometry(child, world)
            elif tag == "use":
                target = self._referenced(child)
                if target is not None and _local(target) in SHAPES:
                    shift = Matrix.translation(
                        _length(child, "x") or 0.0, _length(child, "y") or 0.0
                    )
                    yield self._geometry(target, inner @ shift)
            elif tag in CONTAINERS:
                yield from self._clip_shapes(child, inner)

    # --- Images ---

    def _image(self, element: ET.Element, ctx: _Context) -> ImageNode | None:
        inner = self._enter(element, ctx, ctx.layer)
        name = element.get("data-name") or element.get("id") or _("Image")
        data = self._image_data(element, name)
        if data is None:
            return None
        try:
            pixels = pyvips.Image.new_from_buffer(data, "")
        except pyvips.Error:
            self._warn_image(name)
            return None
        placement, clip = self._placement(
            element, pixels.width, pixels.height, inner.world
        )
        return ImageNode(
            name=name,
            source_layer=ctx.layer,
            world_transform=inner.world,
            data=data,
            placement=placement,
            clip=inner.clip if inner.clip is not None else clip,
        )

    def _image_data(self, element: ET.Element, name: str) -> bytes | None:
        """The PNG or JPEG bytes an image embeds or links, else None."""
        href = (element.get("href") or element.get(XLINK_HREF) or "").strip()
        data = None
        if href.startswith("data:"):
            header, _sep, payload = href.partition(",")
            if header.endswith(";base64"):
                try:
                    data = base64.b64decode(payload)
                except (binascii.Error, ValueError):
                    data = None
        elif href:
            path = Path(unquote(urlparse(href).path))
            if not path.is_absolute() and self.folder is not None:
                path = self.folder / path
            try:
                data = path.read_bytes()
            except OSError:
                data = None
        if data is None or _image_format(data) is None:
            self._warn_image(name)
            return None
        return data

    @staticmethod
    def _placement(
        element: ET.Element, width_px: int, height_px: int, world: Matrix
    ) -> tuple[tuple[float, float, float, float], Geometry | None]:
        """
        The box the image's pixels fill, in its own coordinates, after
        preserveAspectRatio (none stretches; meet fits inside the box;
        slice covers it, cut to the box: the second value, a clip in
        document coordinates).
        """
        x = _length(element, "x") or 0.0
        y = _length(element, "y") or 0.0
        width = _length(element, "width")
        height = _length(element, "height")
        if width is None and height is None:
            width, height = float(width_px), float(height_px)
        elif width is None:
            width = height * width_px / height_px
        elif height is None:
            height = width * height_px / width_px
        words = (element.get("preserveAspectRatio") or "").split()
        align = words[0] if words else "xMidYMid"
        if align == "none" or width <= 0 or height <= 0:
            return (x, y, width, height), None
        slice_ = len(words) > 1 and words[1] == "slice"
        fit = max if slice_ else min
        scale = fit(width / width_px, height / height_px)
        drawn_w, drawn_h = width_px * scale, height_px * scale
        offsets = {"Min": 0.0, "Mid": 0.5, "Max": 1.0}
        dx = (width - drawn_w) * offsets.get(align[1:4], 0.5)
        dy = (height - drawn_h) * offsets.get(align[5:8], 0.5)
        clip = None
        if slice_:
            clip = Geometry()
            corners = ((x, y), (x + width, y), (x + width, y + height))
            clip.move_to(*world.transform_point((x, y + height)))
            for corner in corners:
                clip.line_to(*world.transform_point(corner))
            clip.close_path()
        return (x + dx, y + dy, drawn_w, drawn_h), clip

    # --- Warnings ---

    def _warn_image(self, name: str) -> None:
        self.warnings.append(
            _(
                'Image "{name}" is missing or not a PNG or JPEG and was '
                "not imported."
            ).format(name=name)
        )

    def _warn_text(self, element: ET.Element) -> None:
        text = " ".join("".join(element.itertext()).split())
        if len(text) > _TEXT_PREVIEW:
            text = text[: _TEXT_PREVIEW - 1] + "…"
        self.warnings.append(
            _(
                'Text "{text}" is not outlined and was not imported. In '
                "Illustrator: Type > Create Outlines."
            ).format(text=text)
        )

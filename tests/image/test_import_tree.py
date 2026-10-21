import pytest
from raygeo.geo import Geometry, Matrix

from swiftcut.image.import_tree import (
    GroupNode,
    ImageNode,
    ImportTree,
    LayerNode,
    PathNode,
)


def _rect(x, y, w, h) -> Geometry:
    geo = Geometry()
    geo.move_to(x, y)
    geo.line_to(x + w, y)
    geo.line_to(x + w, y + h)
    geo.line_to(x, y + h)
    geo.close_path()
    return geo


def _path(name, x=0.0, y=0.0) -> PathNode:
    return PathNode(name=name, geometry=_rect(x, y, 1, 1), closed=True)


class TestImageWorldBox:
    def test_placement_through_the_world_transform(self):
        image = ImageNode(
            name="photo",
            placement=(0, 0, 40, 20),
            world_transform=Matrix.translation(10, 5) @ Matrix.scale(2, 2),
        )

        assert image.world_bbox() == pytest.approx((10, 5, 80, 40))

    def test_cut_to_its_clip(self):
        image = ImageNode(
            name="photo",
            placement=(50, 0, 40, 40),
            clip=_rect(60, 10, 20, 20),
        )

        assert image.world_bbox() == pytest.approx((60, 10, 20, 20))

    def test_a_clip_outside_it_leaves_nothing(self):
        image = ImageNode(
            name="photo",
            placement=(0, 0, 10, 10),
            clip=_rect(20, 20, 5, 5),
        )

        _x, _y, w, h = image.world_bbox()

        assert (w, h) == (0.0, 0.0)


class TestWalkingTheTree:
    def test_paths_and_images_in_drawing_order_through_groups(self):
        photo = ImageNode(name="photo")
        inner = GroupNode(name="g2", children=[_path("b"), photo])
        layer = LayerNode(name="Cut", children=[_path("a"), inner, _path("c")])

        assert [p.name for p in layer.paths()] == ["a", "b", "c"]
        assert list(layer.images()) == [photo]

    def test_layers_leaves_out_what_is_outside_any_layer(self):
        cut = LayerNode(name="Cut")
        engrave = LayerNode(name="Engrave")
        tree = ImportTree(
            root=GroupNode(
                name="file", children=[cut, GroupNode(name="g"), engrave]
            )
        )

        assert tree.layers() == [cut, engrave]

    def test_rect_mm_scales_native_units(self):
        tree = ImportTree(root=GroupNode(name="file"), unit_to_mm=25.4 / 72)

        assert tree.rect_mm((72, 144, 72, 36)) == pytest.approx(
            (25.4, 50.8, 25.4, 12.7)
        )

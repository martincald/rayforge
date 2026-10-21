import time

import pytest
from raygeo.geo import Geometry

from swiftcut.image.grouper import Piece, group_pieces
from swiftcut.image.import_tree import PathNode

RED = "#ff0000"
BLACK = "#000000"


def _rect(x, y, w, h, color=RED, layer="cut") -> PathNode:
    geo = Geometry()
    geo.move_to(x, y)
    geo.line_to(x + w, y)
    geo.line_to(x + w, y + h)
    geo.line_to(x, y + h)
    geo.close_path()
    return PathNode(
        name="rect",
        source_layer=layer,
        color=color,
        geometry=geo,
        closed=True,
    )


def _circle(cx, cy, r, color=RED, layer="cut") -> PathNode:
    geo = Geometry()
    geo.move_to(cx + r, cy)
    geo.arc_to(cx - r, cy, i=-r, j=0, clockwise=False)
    geo.arc_to(cx + r, cy, i=r, j=0, clockwise=False)
    geo.close_path()
    return PathNode(
        name="circle",
        source_layer=layer,
        color=color,
        geometry=geo,
        closed=True,
    )


def _line(*points, color=BLACK, layer="cut") -> PathNode:
    geo = Geometry()
    geo.move_to(*points[0])
    for point in points[1:]:
        geo.line_to(*point)
    return PathNode(name="line", source_layer=layer, color=color, geometry=geo)


def _group(paths, **kwargs) -> list[Piece]:
    pieces = group_pieces(paths, **kwargs)
    placed = [p for piece in pieces for p in piece.boundary + piece.interior]
    assert sorted(map(id, placed)) == sorted(map(id, paths))
    return pieces


def _plate(x, y, holes=12) -> list[PathNode]:
    outline = _rect(x, y, 100, 60)
    return [outline] + [
        _circle(x + 12 + 15 * (k % 6), y + 15 + 30 * (k // 6), 4)
        for k in range(holes)
    ]


class TestOutlines:
    def test_empty_input_gives_no_pieces(self):
        assert group_pieces([]) == []

    def test_a_plate_keeps_its_holes_as_boundary(self):
        paths = _plate(0, 0)

        pieces = _group(paths)

        assert len(pieces) == 1
        assert pieces[0].boundary == paths
        assert pieces[0].interior == []

    def test_artwork_in_another_color_is_interior(self):
        outline = _rect(0, 0, 400, 400)
        blobs = []
        for k in range(120):
            cx, cy = 20 + 30 * (k % 12), 20 + 30 * (k // 12)
            blobs.append(_circle(cx, cy, 8, color=BLACK))
            if k % 40 == 0:
                blobs.append(_circle(cx, cy, 3, color=BLACK))
        paths = [outline] + blobs

        pieces = _group(paths)

        assert len(pieces) == 1
        assert pieces[0].boundary == [outline]
        assert pieces[0].interior == blobs

    @pytest.mark.parametrize("kind", [{"color": BLACK}, {"layer": "engrave"}])
    def test_a_direct_child_of_another_kind_is_interior(self, kind):
        outline = _rect(0, 0, 50, 50)
        other = _circle(25, 25, 5, **kind)

        pieces = _group([outline, other])

        assert pieces[0].boundary == [outline]
        assert pieces[0].interior == [other]

    def test_a_hole_at_the_centre_does_not_take_the_outline(self):
        outline = _rect(0, 0, 80, 40)
        hole = _circle(40, 20, 10)

        pieces = _group([outline, hole])

        assert len(pieces) == 1
        assert pieces[0].boundary == [outline, hole]

    def test_paths_keep_input_order_in_a_piece(self):
        hole = _circle(40, 20, 10)
        outline = _rect(0, 0, 80, 40)
        art = _circle(10, 10, 3, color=BLACK)

        pieces = _group([hole, art, outline])

        assert pieces[0].boundary == [hole, outline]
        assert pieces[0].interior == [art]

    def test_an_island_in_a_hole_is_interior(self):
        outline = _circle(0, 0, 50)
        hole = _circle(0, 0, 30)
        island = _circle(0, 0, 10)

        pieces = _group([outline, hole, island])

        assert len(pieces) == 1
        assert pieces[0].boundary == [outline, hole]
        assert pieces[0].interior == [island]

    def test_lone_outlines_are_a_piece_each(self):
        blobs = [_circle(20 * k, 0, 5, color=BLACK) for k in range(3)]

        pieces = _group(blobs)

        assert [p.boundary for p in pieces] == [[b] for b in blobs]

    def test_plates_side_by_side_keep_their_own_holes(self):
        left = _plate(0, 0, holes=6)
        right = _plate(150, 0, holes=4)

        pieces = _group(left + right)

        assert [p.boundary for p in pieces] == [left, right]

    def test_pieces_come_in_drawing_order_of_their_first_path(self):
        left = _plate(0, 0, holes=2)
        right = _plate(150, 0, holes=2)
        paths = [right[1], left[0], right[0], left[1], left[2], right[2]]

        pieces = _group(paths)

        assert pieces[0].boundary == [right[1], right[0], right[2]]
        assert pieces[1].boundary == [left[0], left[1], left[2]]


class TestOpenPaths:
    def test_an_open_path_inside_an_outline_is_interior(self):
        outline = _rect(0, 0, 100, 100)
        stroke = _line((20, 20), (50, 80), (80, 20))

        pieces = _group([outline, stroke])

        assert pieces[0].boundary == [outline]
        assert pieces[0].interior == [stroke]

    def test_an_open_path_joins_the_smallest_outline_holding_it(self):
        big = _rect(0, 0, 100, 100)
        crossing = _rect(50, 50, 60, 60)
        stroke = _line((60, 60), (70, 70))

        pieces = _group([big, crossing, stroke])

        assert [p.boundary for p in pieces] == [[big], [crossing]]
        assert pieces[1].interior == [stroke]

    def test_the_first_vertex_holds_when_the_midpoint_does_not(self):
        outline = _rect(0, 0, 100, 100)
        stroke = _line((50, 50), (150, 50), (150, 60))

        pieces = _group([outline, stroke])

        assert len(pieces) == 1
        assert pieces[0].interior == [stroke]

    def test_an_open_path_outside_every_outline_is_its_own_piece(self):
        outline = _rect(0, 0, 100, 100)
        stroke = _line((300, 0), (320, 0))

        pieces = _group([outline, stroke])

        assert len(pieces) == 2
        assert pieces[1].boundary == [stroke]
        assert pieces[1].interior == []


class TestLooseClusters:
    def test_far_apart_clusters_are_separate_pieces(self):
        a = [_line((0, 0), (10, 0)), _line((0, 1), (10, 1))]
        b = [_line((500, 0), (510, 0)), _line((500, 1), (510, 1))]

        pieces = _group(a + b)

        assert [p.boundary for p in pieces] == [a, b]
        assert all(p.interior == [] for p in pieces)

    def test_clusters_join_transitively(self):
        chain = [_line((11 * k, 0), (11 * k + 10, 0)) for k in range(5)]

        pieces = _group(chain)

        assert [p.boundary for p in pieces] == [chain]

    def test_the_minimum_gap_is_one_millimetre(self):
        a = _line((0, 0), (5, 0))
        b = _line((5.5, 0), (10, 0))
        c = _line((11.5, 0), (12, 0))

        pieces = _group([a, b, c])

        assert [p.boundary for p in pieces] == [[a, b], [c]]

    def test_the_minimum_gap_is_in_native_units(self):
        a = _line((0, 0), (0.2, 0))
        b = _line((0.26, 0), (0.4, 0))

        assert len(_group([a, b], unit_to_mm=1.0)) == 1
        assert len(_group([a, b], unit_to_mm=25.4)) == 2

    def test_the_drawing_box_sets_the_gap(self):
        a = _line((0, 0), (10, 0))
        b = _line((40, 0), (50, 0))

        assert len(_group([a, b])) == 2
        pieces = _group([a, b], drawing_bbox=(0, 0, 2000, 2000))
        assert [p.boundary for p in pieces] == [[a, b]]


def _many_plates() -> list[PathNode]:
    paths = []
    for n in range(40):
        x, y = 120 * (n % 8), 120 * (n // 8)
        paths.append(_rect(x, y, 100, 100))
        for k in range(30):
            paths.append(
                _circle(x + 10 + 15 * (k % 6), y + 10 + 10 * (k // 6), 3)
            )
        for k in range(15):
            paths.append(
                _circle(
                    x + 10 + 20 * (k % 5),
                    y + 65 + 10 * (k // 5),
                    3,
                    color=BLACK,
                )
            )
        for k in range(4):
            paths.append(
                _line((x + 10 + 20 * k, y + 93), (x + 25 + 20 * k, y + 95))
            )
    return paths


def test_two_thousand_paths_group_fast():
    paths = _many_plates()
    assert len(paths) == 2000

    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        pieces = group_pieces(paths)
        best = min(best, time.perf_counter() - start)

    print(f"group_pieces, 2000 paths: {best * 1000:.1f} ms")
    assert len(pieces) == 40
    assert all(len(p.boundary) == 31 for p in pieces)
    assert all(len(p.interior) == 19 for p in pieces)
    assert best < 0.5

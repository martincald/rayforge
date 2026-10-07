import pickle

import numpy as np
import pytest
from raygeo.geo import Matrix
from raygeo.geo.shape.polygon import do_polygons_intersect, get_circle_polygon

from swiftcut.shared.placement import Piece, arrange, layout

# (x, y, width, height) in world mm, and its centre.
BOUNDARY = (0.0, 0.0, 400.0, 300.0)
CENTRE = (200.0, 150.0)


class Proxy:
    """Records progress; says to stop when told to."""

    def __init__(self, cancelled=False):
        self.cancelled = cancelled
        self.total = None
        self.progress = []

    def set_total(self, total):
        self.total = total

    def set_progress(self, progress):
        self.progress.append(progress)

    def is_cancelled(self):
        return self.cancelled


def rect(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def rect_piece(id, x, y, w, h):
    """A piece whose outline is its frame."""
    return Piece(id, [rect(x, y, w, h)], (x, y, w, h))


def circle_piece(id, radius):
    outline = get_circle_polygon((0, 0), radius, 64)
    return Piece(id, [outline], (-radius, -radius, 2 * radius, 2 * radius))


def l_piece(id, x, y):
    """An L, 60 wide and 40 tall, filling its frame's left and bottom."""
    outline = [(0, 0), (60, 0), (60, 15), (15, 15), (15, 40), (0, 40)]
    return Piece(id, [[(x + a, y + b) for a, b in outline]], (x, y, 60, 40))


def placed(piece, result):
    """
    The piece's outlines and frame corners where the result puts them,
    by the matrix a caller builds from it.
    """
    angle, dx, dy, fits = result
    assert fits
    x, y, w, h = piece.frame
    matrix = Matrix.translation(dx, dy) @ Matrix.rotation(
        angle, center=(x + w / 2, y + h / 2)
    )
    outlines = [
        [matrix.transform_point(p) for p in outline]
        for outline in piece.outlines
    ]
    corners = [matrix.transform_point(p) for p in rect(x, y, w, h)]
    return outlines, corners


def frame_centre(corners):
    points = np.asarray(corners)
    return (points.min(axis=0) + points.max(axis=0)) / 2


def gap(a, b):
    """The exact distance between two outlines that do not cross."""

    def one_way(points, polygon):
        p = np.asarray(points, dtype=float)[:, None, :]
        start = np.asarray(polygon, dtype=float)
        edge = np.roll(start, -1, axis=0) - start
        t = ((p - start) * edge).sum(-1) / (edge * edge).sum(-1)
        nearest = start + np.clip(t, 0, 1)[..., None] * edge
        return np.sqrt(((p - nearest) ** 2).sum(-1)).min()

    return min(one_way(a, b), one_way(b, a))


def assert_clear(outlines, others):
    """No outline crosses or is closer than 1 mm to any of the others."""
    for outline in outlines:
        for other in others:
            assert not do_polygons_intersect(outline, other)
            assert gap(outline, other) >= 1.0 - 1e-6


def assert_inside(corners, boundary):
    bx, by, bw, bh = boundary
    (x0, y0), (x1, y1) = np.min(corners, axis=0), np.max(corners, axis=0)
    assert x0 >= bx - 1e-9 and y0 >= by - 1e-9
    assert x1 <= bx + bw + 1e-9 and y1 <= by + bh + 1e-9


def test_largest_piece_takes_the_target():
    small = rect_piece("small", 0, 0, 20, 20)
    large = rect_piece("large", 300, 200, 50, 50)

    result = arrange(Proxy(), [small, large], [], BOUNDARY, CENTRE)

    large_outlines, corners = placed(large, result["large"])
    assert frame_centre(corners) == pytest.approx(CENTRE)
    small_outlines, _corners = placed(small, result["small"])
    assert_clear(small_outlines, large_outlines)


def test_later_pieces_go_where_the_pile_grows_least():
    big = rect_piece("big", 0, 0, 100, 100)
    wide = rect_piece("wide", 0, 0, 40, 30)
    small = rect_piece("small", 0, 0, 20, 20)

    result = arrange(Proxy(), [big, wide, small], [], BOUNDARY, CENTRE)

    # The small one fits in the pile beside the wide one, under the big
    # one; nearest the centre would be against the big one's side.
    pile = [placed(p, result[p.id])[1] for p in (big, wide)]
    _outlines, corners = placed(small, result["small"])
    x0, y0 = np.min(pile, axis=(0, 1))
    x1, y1 = np.max(pile, axis=(0, 1))
    assert_inside(corners, (x0, y0, x1 - x0, y1 - y0))


def test_equal_pieces_go_in_the_given_order():
    first = rect_piece("first", 300, 200, 30, 30)
    second = rect_piece("second", 0, 0, 30, 30)

    result = arrange(Proxy(), [first, second], [], BOUNDARY, CENTRE)

    _outlines, corners = placed(first, result["first"])
    assert frame_centre(corners) == pytest.approx(CENTRE)


def test_pieces_keep_the_clearance_from_obstacles_and_each_other():
    obstacles = [get_circle_polygon(CENTRE, 40, 64), rect(80, 60, 50, 50)]
    pieces = [circle_piece(r, r) for r in (30, 25, 20, 15, 10)]
    pieces.append(l_piece("L", 0, 0))

    result = arrange(Proxy(), pieces, obstacles, BOUNDARY, CENTRE)

    laid_out = []
    for piece in pieces:
        outlines, corners = placed(piece, result[piece.id])
        assert_inside(corners, BOUNDARY)
        assert_clear(outlines, obstacles + laid_out)
        laid_out.extend(outlines)


@pytest.mark.parametrize(
    "piece, tries",
    [
        # A circle looks the same every way; a rectangle turned half
        # way too; an L never.
        (circle_piece("circle", 20), 1),
        (rect_piece("rectangle", 0, 0, 60, 20), 2),
        (l_piece("L", 0, 0), 4),
    ],
)
def test_turns_that_look_the_same_are_tried_once(monkeypatch, piece, tries):
    calls = []
    find_position = layout.find_position

    def counting(*args, **kwargs):
        calls.append(args)
        return find_position(*args, **kwargs)

    monkeypatch.setattr(layout, "find_position", counting)

    arrange(Proxy(), [piece], [], BOUNDARY, CENTRE)

    assert len(calls) == tries


def test_same_outline_in_a_turned_frame_is_tried():
    # The square looks the same turned, but its frame does not: only
    # upright does the frame fit the boundary.
    piece = Piece("piece", [rect(0, 0, 10, 10)], (0, 0, 30, 10))
    boundary = (0, 0, 12, 40)

    result = arrange(Proxy(), [piece], [], boundary, (6, 20))

    _outlines, corners = placed(piece, result["piece"])
    assert_inside(corners, boundary)


def test_a_turn_is_counter_clockwise_like_the_matrix():
    # The square sits in the left of a frame that fits the boundary
    # only upright. Turned counter-clockwise it is at the bottom of
    # the frame, clear of the obstacle along the top; clockwise it
    # would be in the obstacle.
    piece = Piece("piece", [rect(0, 0, 10, 10)], (0, 0, 30, 10))
    boundary = (0, 0, 12, 40)
    obstacles = [rect(0, 22, 12, 18)]

    result = arrange(Proxy(), [piece], obstacles, boundary, (6, 20))

    assert result["piece"][0] == 90
    outlines, corners = placed(piece, result["piece"])
    assert_inside(corners, boundary)
    assert_clear(outlines, obstacles)


def test_the_turn_landing_nearest_wins():
    # Turned half way, the L's notch takes the obstacle's corner and
    # its frame centres on the target; every other turn hits it there.
    piece = l_piece("L", 0, 0)
    obstacles = [rect(100, 60, 113, 93)]

    result = arrange(Proxy(), [piece], obstacles, BOUNDARY, CENTRE)

    assert result["L"][0] == 180
    outlines, corners = placed(piece, result["L"])
    assert frame_centre(corners) == pytest.approx(CENTRE)
    assert_clear(outlines, obstacles)


def test_ties_go_to_the_smaller_turn():
    # Every turn of the L reaches the target on an empty boundary.
    result = arrange(Proxy(), [l_piece("L", 0, 0)], [], BOUNDARY, CENTRE)

    assert result["L"][0] == 0


def test_frame_stays_inside_the_boundary():
    # The outline fills only the left third of its frame.
    piece = Piece("piece", [rect(0, 0, 10, 10)], (0, 0, 30, 10))
    boundary = (100, 100, 30, 10)

    result = arrange(Proxy(), [piece], [], boundary, (100, 100))

    _outlines, corners = placed(piece, result["piece"])
    assert np.min(corners, axis=0) == pytest.approx((100, 100))
    assert np.max(corners, axis=0) == pytest.approx((130, 110))


def test_piece_that_fits_nowhere_stays_and_is_kept_clear_of():
    # Too long for the boundary either way, and across its centre.
    long = rect_piece("long", 120, 140, 200, 20)
    small = rect_piece("small", 0, 0, 20, 20)
    boundary = (100, 100, 150, 100)

    result = arrange(Proxy(), [long, small], [], boundary, (175, 150))

    assert result["long"] == (0.0, 0.0, 0.0, False)
    outlines, corners = placed(small, result["small"])
    assert_inside(corners, boundary)
    assert_clear(outlines, long.outlines)


def test_smaller_piece_too_long_for_the_boundary_is_kept_clear_of():
    # The rod is placed after the square, being smaller, but is too
    # long for the boundary either way and lies across its centre.
    rod = rect_piece("rod", 75, 147.5, 200, 5)
    square = rect_piece("square", 0, 0, 40, 40)
    boundary = (100, 100, 150, 100)

    result = arrange(Proxy(), [rod, square], [], boundary, (175, 150))

    assert result["rod"] == (0.0, 0.0, 0.0, False)
    outlines, corners = placed(square, result["square"])
    assert_inside(corners, boundary)
    assert_clear(outlines, rod.outlines)


def test_smaller_piece_that_fits_nowhere_is_kept_clear_of():
    # Only a band 20 mm tall across the boundary is free. The L fits
    # the boundary but not the band, any way up; it is placed after
    # the square, being smaller, and its leg crosses the target.
    obstacles = [rect(0, 0, 100, 40), rect(0, 60, 100, 40)]
    outline = [(48, 35), (78, 35), (78, 38), (51, 38), (51, 65), (48, 65)]
    thin_l = Piece("L", [outline], (48, 35, 30, 30))
    square = rect_piece("square", 0, 0, 15, 15)
    boundary = (0, 0, 100, 100)

    result = arrange(Proxy(), [thin_l, square], obstacles, boundary, (50, 50))

    assert result["L"] == (0.0, 0.0, 0.0, False)
    outlines, corners = placed(square, result["square"])
    assert_inside(corners, boundary)
    assert_clear(outlines, obstacles + thin_l.outlines)


def test_progress_is_one_step_per_piece():
    proxy = Proxy()
    pieces = [rect_piece(n, 0, 0, 10, 10) for n in range(3)]

    arrange(proxy, pieces, [], BOUNDARY, CENTRE)

    assert proxy.total == 3
    assert proxy.progress == [1, 2, 3]


def test_cancelled_gives_nothing():
    pieces = [rect_piece(n, 0, 0, 10, 10) for n in range(3)]

    assert arrange(Proxy(cancelled=True), pieces, [], BOUNDARY, CENTRE) == {}


def test_input_and_result_are_picklable_and_repeatable():
    pieces = [l_piece("L", 0, 0), rect_piece(1, 0, 0, 10, 10)]
    args = (pieces, [rect(150, 100, 50, 50)], BOUNDARY, CENTRE)

    result = arrange(Proxy(), *pickle.loads(pickle.dumps(args)))

    assert pickle.loads(pickle.dumps(result)) == result
    assert result == arrange(Proxy(), *args)

import math
import pickle
import time
import tracemalloc

import numpy as np
import pytest
from raygeo.geo.shape.polygon import (
    do_polygons_intersect,
    get_circle_polygon,
    get_polygon_boundary_distance,
)

from swiftcut.shared.placement import Placement, engine, find_position

# The ilab-614 bed: (x, y, width, height) in world mm.
BED = (0.0, 0.0, 1400.0, 900.0)
CENTRE = (700.0, 450.0)


def square(x, y, size):
    """A square with its lower-left corner at (x, y)."""
    return [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]


def circle(x, y, radius):
    return get_circle_polygon((x, y), radius, 64)


def moved(polygon, result):
    return [(x + result.dx, y + result.dy) for x, y in polygon]


def centre_of(polygon):
    points = np.asarray(polygon)
    return (points.min(axis=0) + points.max(axis=0)) / 2


def distance_to_centre(polygon):
    return math.dist(centre_of(polygon), CENTRE)


def gap(a, b):
    """
    The exact distance between two polygon outlines that do not cross:
    the nearest vertex-to-edge distance, both ways. (raygeo's
    get_polygon_boundary_distance measures from edge midpoints only,
    which overestimates it.)
    """

    def one_way(points, polygon):
        p = np.asarray(points, dtype=float)[:, None, :]
        start = np.asarray(polygon, dtype=float)
        edge = np.roll(start, -1, axis=0) - start
        t = ((p - start) * edge).sum(-1) / (edge * edge).sum(-1)
        nearest = start + np.clip(t, 0, 1)[..., None] * edge
        return np.sqrt(((p - nearest) ** 2).sum(-1)).min()

    return min(one_way(a, b), one_way(b, a))


def place(polygon, obstacles, **kwargs):
    """Place a one-outline piece; check it is free and on the bed."""
    result = find_position([polygon], obstacles, BED, **kwargs)
    assert result.fits
    placed = moved(polygon, result)
    x0, y0 = np.min(placed, axis=0)
    x1, y1 = np.max(placed, axis=0)
    assert x0 >= -1e-9 and y0 >= -1e-9
    assert x1 <= 1400 + 1e-9 and y1 <= 900 + 1e-9
    for obstacle in obstacles:
        assert not do_polygons_intersect(placed, obstacle)
        assert gap(placed, obstacle) >= 1.0
    return placed


def test_empty_bed_centres_the_piece():
    placed = place(square(10, 20, 50), [])

    assert np.allclose(centre_of(placed), CENTRE)


def test_free_target_is_kept():
    obstacles = [square(650, 400, 100)]

    placed = place(square(0, 0, 50), obstacles, target=(300.0, 200.0))

    assert np.allclose(centre_of(placed), (300, 200))


def test_target_outside_the_bed_lands_flush_inside():
    placed = place(square(0, 0, 50), [], target=(-100.0, 450.0))

    assert np.allclose(centre_of(placed), (25, 450))


def test_occupied_centre_takes_the_nearest_free_spot():
    obstacles = [square(600, 350, 200)]

    placed = place(square(0, 0, 100), obstacles)

    # Nearest possible: side by side, the clearance apart.
    assert 151.0 <= distance_to_centre(placed) <= 151.1


def test_concave_obstacle_takes_the_piece_into_its_pocket():
    # A U open to the right whose bottom wall ends at the bed centre:
    # the nearest free spot is inside the pocket, on top of that wall
    # (21 mm away), not under it (41 mm).
    obstacles = [
        [
            (600, 430),
            (800, 430),
            (800, 450),
            (620, 450),
            (620, 610),
            (800, 610),
            (800, 630),
            (600, 630),
        ]
    ]

    placed = place(square(0, 0, 40), obstacles)

    assert 21.0 <= distance_to_centre(placed) <= 21.1


def test_piece_slides_along_a_wall_into_the_corner():
    # An L whose inner corner is just off the bed centre. From the
    # nearest free grid spot, (730, 480), the slide toward the centre
    # stops on the lower arm at (726, 476); the slide along x then
    # takes the piece into the corner, against both arms.
    obstacles = [
        [
            (600, 300),
            (900, 300),
            (900, 455),
            (700, 455),
            (700, 700),
            (600, 700),
        ]
    ]

    placed = place(square(0, 0, 40), obstacles)

    assert np.allclose(centre_of(placed), (721, 476), atol=0.05)


def test_asymmetric_piece_misses_the_obstacles():
    triangle = [(0, 0), (60, 0), (0, 60)]
    obstacles = [square(650, 400, 100), circle(560, 450, 30)]

    place(triangle, obstacles)


def test_full_bed_does_not_fit_and_targets_the_centre():
    piece = square(0, 0, 50)

    result = find_position([piece], [square(0, 0, 1400)], BED)

    assert not result.fits
    assert np.allclose(centre_of(moved(piece, result)), CENTRE)


def test_piece_larger_than_the_bed_does_not_fit():
    piece = [(0, 0), (1500, 0), (1500, 100), (0, 100)]

    result = find_position([piece], [], BED, target=(100.0, 100.0))

    assert not result.fits
    assert np.allclose(centre_of(moved(piece, result)), (700, 100))


def test_piece_as_large_as_the_bed_fits_despite_float_noise():
    # Scaling to fit leaves the size a last bit above the bed's.
    width = np.nextafter(1400.0, 2000.0)
    piece = [(0, 0), (width, 0), (width, 900), (0, 900)]

    result = find_position([piece], [], BED)

    assert result.fits
    assert np.allclose(centre_of(moved(piece, result)), CENTRE)


def test_small_piece_fills_a_gap_in_the_pile():
    pile = []
    for _ in range(6):
        pile.append(place(circle(0, 0, 100), pile))
    x0, y0 = np.min(np.concatenate(pile), axis=0)
    x1, y1 = np.max(np.concatenate(pile), axis=0)
    outside = min(700 - x0, x1 - 700, 450 - y0, y1 - 450)

    placed = place(square(0, 0, 20), pile)

    assert distance_to_centre(placed) < outside


def test_circles_keep_the_clearance():
    placed = []
    for radius in (60, 25, 40, 25, 10, 60, 25, 40, 10, 25):
        placed.append(place(circle(0, 0, radius), placed))

    for i, a in enumerate(placed):
        for b in placed[:i]:
            assert gap(a, b) >= 1.0
            assert get_polygon_boundary_distance(a, b) >= 1.0


def test_piece_inside_a_ring_outline_is_rejected():
    ring = circle(700, 450, 300)

    placed = place(square(0, 0, 20), [ring])

    assert distance_to_centre(placed) > 300


def test_squares_slide_together_to_the_clearance():
    first = place(square(0, 0, 200), [])

    second = place(square(0, 0, 200), [first])

    assert gap(first, second) <= 1.05


def test_multi_outline_piece_straddles_a_small_obstacle():
    # Two squares 70 mm apart, moved as one, around a 20 mm obstacle.
    piece = [square(0, 0, 30), square(100, 0, 30)]
    obstacles = [square(690, 440, 20)]

    result = find_position(piece, obstacles, BED)

    assert result.fits
    assert np.allclose(centre_of(moved(piece[0], result)), (650, 450))
    assert np.allclose(centre_of(moved(piece[1], result)), (750, 450))


def test_every_outline_of_a_piece_keeps_the_clearance():
    # At the centre, only the second square would hit the obstacle.
    piece = [square(0, 0, 30), square(100, 0, 30)]
    obstacles = [square(745, 445, 10)]

    result = find_position(piece, obstacles, BED)

    assert result.fits
    for outline in piece:
        placed = moved(outline, result)
        assert not do_polygons_intersect(placed, obstacles[0])
        assert gap(placed, obstacles[0]) >= 1.0


def test_same_input_same_result():
    obstacles = [circle(700, 450, 80), square(560, 300, 90)]
    piece = [[(0, 0), (60, 0), (60, 20), (20, 20), (20, 60), (0, 60)]]

    first = find_position(piece, obstacles, BED)
    second = find_position(piece, obstacles, BED)

    assert first == second
    assert pickle.loads(pickle.dumps(first)) == first
    assert isinstance(first, Placement)


def comb(x, y, width, height):
    """
    A comb over the box: a 20 mm spine along its bottom, and teeth 3 mm
    wide and 3 mm apart up to its top. Nothing of the L below fits
    between them, and its concave outline leaves most positions over
    the comb to an exact test.
    """
    points = [(x, y), (x + width, y), (x + width, y + height)]
    right = x + width
    while right - 6 > x:
        points += [
            (right - 3, y + height),
            (right - 3, y + 20),
            (right - 6, y + 20),
            (right - 6, y + height),
        ]
        right -= 6
    return points + [(x, y + height)]


L_PIECE = [(0, 0), (30, 0), (30, 8), (8, 8), (8, 20), (0, 20)]


def count_exact_tests(monkeypatch):
    """The positions the engine tests exactly, from now on."""
    calls = []
    is_free = engine._Search.is_free

    def counted(search, x, y):
        calls.append((x, y))
        return is_free(search, x, y)

    monkeypatch.setattr(engine._Search, "is_free", counted)
    return calls


def test_exact_tests_stop_at_the_cap(monkeypatch):
    # Uncapped, this takes about 8000 exact tests and 4 s.
    calls = count_exact_tests(monkeypatch)

    result = find_position([L_PIECE], [comb(0, 0, 1400, 900)], BED)

    assert not result.fits
    assert len(calls) == engine.MAX_TESTS


def test_past_the_cap_the_nearest_position_known_free_is_taken():
    # The bed centre is over a comb, with free bed all around it.
    obstacles = [comb(500, 300, 400, 300)]

    placed = place(L_PIECE, obstacles, max_tests=0)

    assert distance_to_centre(placed) > 150


def edges(polygon):
    """A polygon's sides as (start, end) edges."""
    return list(zip(polygon, polygon[1:] + polygon[:1]))


def bed_sides():
    return edges([(0, 0), (1400, 0), (1400, 900), (0, 900)])


def test_shared_length_counts_flush_overlaps_longer_than_the_tolerance():
    piece = edges(square(0, 0, 10))
    # Along the right side for 6 mm, 0.005 mm off.
    beside = [((10.005, 4), (10.005, 30))]
    # Along the top side, but 0.02 mm off.
    above = [((0, 10.02), (10, 10.02))]
    # Along the bottom side for 0.005 mm only.
    corner = [((9.995, 0), (20, 0))]

    assert engine.shared_length(piece, beside, 0.01) == 6.0
    assert engine.shared_length(piece, above, 0.01) == 0.0
    assert engine.shared_length(piece, corner, 0.01) == 0.0
    assert engine.shared_length(piece, beside + above, 0.03) == 16.0


def flush_place(polygon, obstacles, others, target):
    """Place a one-outline piece flush along others, at clearance 0."""
    flush = engine.Flush(edges(polygon), others, 0.01)
    result = find_position(
        [polygon], obstacles, BED, target, clearance=0.0, flush=flush
    )
    assert result.fits
    placed = moved(polygon, result)
    for obstacle in obstacles:
        assert not do_polygons_intersect(placed, obstacle)
    return placed


def test_a_snap_lays_the_piece_exactly_along_a_nearby_obstacle_edge():
    # The free target leaves the piece 0.5 mm right of the obstacle.
    obstacle = square(0, 100, 10)
    piece = square(0, 0, 10)
    target = (15.5, 105.0)

    alone = flush_place(piece, [obstacle], [], target)
    placed = flush_place(piece, [obstacle], edges(obstacle), target)

    assert np.min(alone, axis=0)[0] == 10.5
    assert abs(np.min(placed, axis=0)[0] - 10) <= 1e-9
    assert np.allclose(np.min(placed, axis=0)[1], 100)


def test_a_snap_lays_the_piece_exactly_along_the_bed_edge():
    piece = square(0, 0, 10)

    placed = flush_place(piece, [], bed_sides(), (5.5, 450.0))

    assert abs(np.min(placed, axis=0)[0]) <= 1e-9
    assert np.allclose(np.min(placed, axis=0)[1], 445)


def test_a_snap_that_would_overlap_is_rejected():
    # Flush with the big obstacle's side, the piece would overlap the
    # small one, which reaches 0.2 mm up into its bottom left corner;
    # it lies along the small one's side instead.
    big = square(0, 100, 10)
    small = [(10.1, 95), (10.4, 95), (10.4, 100.2), (10.1, 100.2)]
    piece = square(0, 0, 10)
    others = edges(big) + edges(small)

    placed = flush_place(piece, [big, small], others, (15.5, 105.0))

    assert abs(np.min(placed, axis=0)[0] - 10.4) <= 1e-9


def slivers():
    """
    Slivers left of a 10 mm square centred on (15.5, 100), 0.01 mm
    wide and apart, longer the farther away: a snap onto any but the
    nearest overlaps those nearer, and the longest snaps go first.
    """
    return [
        [(x, 100 - h), (x + 0.01, 100 - h), (x + 0.01, 100 + h), (x, 100 + h)]
        for k in range(100)
        for x, h in [(10.48 - 0.02 * k, 0.5 + 0.04 * k)]
    ]


def test_snap_tests_stop_at_the_cap(monkeypatch):
    # Every line kept, there are 200 snaps, all but one blocked.
    monkeypatch.setattr(engine, "_SNAP_LINES", 1000)
    obstacles = slivers()
    piece = square(0, 0, 10)
    others = [e for sliver in obstacles for e in edges(sliver)]
    flush = engine.Flush(edges(piece), others, 0.01)
    target = (15.5, 100.0)
    calls = count_exact_tests(monkeypatch)
    find_position([piece], obstacles, BED, target, clearance=0.0)
    search_tests = len(calls)

    result = find_position(
        [piece], obstacles, BED, target, clearance=0.0, flush=flush
    )

    assert len(calls) - 2 * search_tests == engine._SNAP_TESTS
    assert result == (10.5, 95.0, True)


def test_the_nearest_lines_make_the_snaps():
    obstacles = slivers()
    piece = square(0, 0, 10)
    others = [e for sliver in obstacles for e in edges(sliver)]
    flush = engine.Flush(edges(piece), others, 0.01)

    result = find_position(
        [piece], obstacles, BED, (15.5, 100.0), clearance=0.0, flush=flush
    )

    # Flush with the nearest sliver, the only free snap.
    assert result.dx == pytest.approx(10.49, abs=1e-9)


def ngon(x, y, radius, sides):
    return [
        (x + radius * math.cos(a), y + radius * math.sin(a))
        for a in np.arange(sides) * 2 * math.pi / sides
    ]


def long_comb(count, size, length):
    """
    A comb from the origin: `count` teeth `size` wide and apart and
    `length` long on a spine `size` thick. No edge is shorter than
    size.
    """
    right, top = (2 * count - 1) * size, size + length
    points = [(0, 0), (right, 0)]
    for k in reversed(range(count)):
        left = 2 * k * size
        points += [(left + size, top), (left, top)]
        if k:
            points += [(left, size), (left - size, size)]
    return points


def flush_phase(monkeypatch, piece, obstacles, bed, target):
    """
    find_position at clearance 0 with every side flush within 0.01 mm;
    its result, seconds, and the flush phase's peak memory in bytes.
    """
    peaks = []
    snap = engine._snap

    def traced(*args):
        tracemalloc.start()
        try:
            return snap(*args)
        finally:
            peaks.append(tracemalloc.get_traced_memory()[1])
            tracemalloc.stop()

    monkeypatch.setattr(engine, "_snap", traced)
    others = [e for obstacle in obstacles for e in edges(obstacle)]
    flush = engine.Flush(edges(piece), others, 0.01)
    start = time.perf_counter()
    result = find_position(
        [piece], obstacles, bed, target, clearance=0.0, flush=flush
    )
    seconds = time.perf_counter() - start
    assert result.fits
    (peak,) = peaks
    return result, seconds, peak


@pytest.mark.parametrize("sides", [1440, 2000])
def test_a_flattened_curve_lays_flush_quickly_in_little_memory(
    monkeypatch, sides
):
    # Curves flattened into thousands of edges, each parallel within
    # the tolerance to tens of its neighbours'. Uncapped, 1440 sides
    # took 163 MB and 2000 sides 6.7 GB and 89 s.
    piece = ngon(100, 100, 50, sides)
    obstacles = [
        ngon(200 + dx, 200 + dy, 50, sides)
        for dx, dy in ((0, 0), (100, 0), (0, 100), (100, 100))
    ]

    _result, seconds, peak = flush_phase(
        monkeypatch, piece, obstacles, (0, 0, 400, 400), (250.0, 250.0)
    )

    assert seconds < 0.5
    assert peak < 50 * 2**20


def test_many_long_edges_lay_flush_quickly_in_little_memory(monkeypatch):
    # Two combs of 80 teeth, no edge under 6 mm, one turned half way
    # with its teeth down in the other's gaps, 0.5 mm short of touching
    # it: hundreds of exactly parallel edges, tens of them within a
    # grid step of each. Uncapped, this took 163 MB.
    piece = long_comb(80, 6.0, 400.0)
    right, top = 2 * 80 * 6.0, 2 * 6.0 + 400.0 + 0.5
    obstacle = [(right - x, top - y) for x, y in piece]

    result, seconds, peak = flush_phase(
        monkeypatch, piece, [obstacle], BED, tuple(centre_of(piece))
    )

    assert seconds < 0.5
    assert peak < 50 * 2**20
    # Up into contact.
    assert (result.dx, result.dy) == pytest.approx((0.0, 0.5), abs=1e-9)
    assert not do_polygons_intersect(moved(piece, result), obstacle)

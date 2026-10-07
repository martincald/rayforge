import math
import pickle

import numpy as np
from raygeo.geo.shape.polygon import (
    do_polygons_intersect,
    get_circle_polygon,
    get_polygon_boundary_distance,
)

from swiftcut.shared.placement import Placement, find_position

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

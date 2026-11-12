"""
Path fills: how the source paths of a workpiece's geometry are
filled, worked out against the paths, kept with the segment and
carried into the pieces a workpiece is split into.
"""

from raygeo.geo import Geometry, Matrix

from swiftcut.core.path_fills import ContourIndex, paths_of
from swiftcut.core.source_asset_segment import SourceAssetSegment
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece


def _square(x: float, y: float, size: float) -> Geometry:
    geo = Geometry()
    geo.move_to(x, y)
    geo.line_to(x + size, y)
    geo.line_to(x + size, y + size)
    geo.line_to(x, y + size)
    geo.close_path()
    return geo


def _joined(*parts: Geometry) -> Geometry:
    geo = Geometry()
    for part in parts:
        geo.extend(part)
    return geo


# A ring (two contours) filled even-odd, an unfilled square and a
# filled one, in a 0..1 box.
RING = [_square(0.0, 0.0, 0.4), _square(0.1, 0.1, 0.2)]
OPEN_SQUARE = _square(0.5, 0.0, 0.2)
SOLID_SQUARE = _square(0.5, 0.6, 0.4)
PATHS = [(RING, "evenodd"), ([OPEN_SQUARE], None), ([SOLID_SQUARE], "nonzero")]


class TestContourIndex:
    def test_each_contour_is_found_on_its_path(self):
        geometry = _joined(*RING, OPEN_SQUARE, SOLID_SQUARE)

        fills = ContourIndex(PATHS).path_fills(geometry)

        assert fills == [(2, "evenodd"), (1, None), (1, "nonzero")]

    def test_order_and_subsets_follow_the_geometry(self):
        geometry = _joined(SOLID_SQUARE, RING[1])

        fills = ContourIndex(PATHS).path_fills(geometry)

        assert fills == [(1, "nonzero"), (1, "evenodd")]

    def test_a_contour_off_by_float_noise_is_found(self):
        moved = _square(0.5 + 1e-12, 0.6, 0.4)

        assert ContourIndex(PATHS).path_fills(moved) == [(1, "nonzero")]

    def test_a_contour_of_no_path_gives_none(self):
        stray = _joined(SOLID_SQUARE, _square(0.8, 0.0, 0.1))

        assert ContourIndex(PATHS).path_fills(stray) is None

    def test_same_corner_different_size_are_told_apart(self):
        """Two squares sharing their first point: told by their box."""
        small, large = _square(0, 0, 0.1), _square(0, 0, 0.5)
        index = ContourIndex([([large], None), ([small], "nonzero")])

        fills = index.path_fills(_joined(small, large))

        assert fills == [(1, "nonzero"), (1, None)]

    def test_identical_paths_are_told_apart_by_order(self):
        """
        The same square drawn twice, filled then unfilled: each is
        used up once, so neither takes the other's fill, and the two
        are two paths, not one of two contours.
        """
        square = _square(0, 0, 0.5)
        index = ContourIndex([([square], "evenodd"), ([square], None)])

        assert index.path_fills(_joined(square, square)) == [
            (1, "evenodd"),
            (1, None),
        ]

    def test_a_contour_read_twice_starts_a_path_of_its_own(self):
        """A file path the importer reads twice is two paths."""
        geometry = _joined(*RING, *RING)

        fills = ContourIndex([(RING, "evenodd")]).path_fills(geometry)

        assert fills == [(2, "evenodd"), (2, "evenodd")]


class TestPathsOf:
    def test_groups_the_contours_by_path(self):
        geometry = _joined(*RING, OPEN_SQUARE)

        paths = paths_of(geometry, [(2, "evenodd"), (1, None)])

        assert paths is not None
        assert [(len(c), rule) for c, rule in paths] == [
            (2, "evenodd"),
            (1, None),
        ]

    def test_none_without_path_fills_or_when_they_miscount(self):
        geometry = _joined(*RING, OPEN_SQUARE)

        assert paths_of(geometry, None) is None
        assert paths_of(geometry, [(2, "evenodd")]) is None
        assert paths_of(geometry, [(4, None)]) is None


def _segment(path_fills) -> SourceAssetSegment:
    return SourceAssetSegment(
        source_asset_uid="asset",
        vectorization_spec=PassthroughSpec(),
        pristine_geometry=_joined(*RING, OPEN_SQUARE, SOLID_SQUARE),
        normalization_matrix=Matrix.identity(),
        path_fills=path_fills,
    )


FILLS = [(2, "evenodd"), (1, None), (1, "nonzero")]


class TestSegment:
    def test_path_fills_survive_to_dict_and_back(self):
        segment = _segment(FILLS)

        data = segment.to_dict()
        restored = SourceAssetSegment.from_dict(data)

        assert data["path_fills"] == [
            [2, "evenodd"],
            [1, None],
            [1, "nonzero"],
        ]
        assert restored.path_fills == FILLS

    def test_a_segment_saved_before_has_none(self):
        data = _segment(FILLS).to_dict()
        del data["path_fills"]

        assert SourceAssetSegment.from_dict(data).path_fills is None

    def test_a_clone_with_new_geometry_has_none(self):
        clone = _segment(FILLS).clone_with_geometry(_square(0, 0, 1))

        assert clone.path_fills is None


def _workpiece(path_fills) -> WorkPiece:
    wp = WorkPiece(name="drawing", source_segment=_segment(path_fills))
    wp.set_size(100.0, 100.0)
    return wp


class TestWorkpiece:
    def test_a_save_and_load_keeps_them(self):
        wp = _workpiece(FILLS)

        restored = WorkPiece.from_dict(wp.to_dict())

        assert restored.source_segment.path_fills == FILLS

    def test_a_duplicate_and_the_world_copy_keep_them(self):
        wp = _workpiece(FILLS)

        assert wp.duplicate().source_segment.path_fills == FILLS
        assert wp.in_world().source_segment.path_fills == FILLS

    def test_split_pieces_keep_their_paths_fills(self):
        wp = _workpiece(FILLS)

        pieces = wp.apply_split(
            [_joined(*RING), _joined(SOLID_SQUARE, OPEN_SQUARE)],
            drop_dust=False,
        )

        assert [p.source_segment.path_fills for p in pieces] == [
            [(2, "evenodd")],
            [(1, "nonzero"), (1, None)],
        ]
        for piece in pieces:
            fills = piece.source_segment.path_fills
            assert paths_of(piece.boundaries, fills) is not None

    def test_a_piece_with_a_contour_of_no_path_has_none(self):
        wp = _workpiece(FILLS)

        pieces = wp.apply_split(
            [_joined(*RING), _square(0.8, 0.0, 0.1)], drop_dust=False
        )

        assert [p.source_segment.path_fills for p in pieces] == [
            [(2, "evenodd")],
            None,
        ]

    def test_pieces_of_a_workpiece_without_them_have_none(self):
        wp = _workpiece(None)

        pieces = wp.apply_split([_joined(*RING), _joined(SOLID_SQUARE)])

        assert [p.source_segment.path_fills for p in pieces] == [None, None]

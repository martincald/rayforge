"""
The job preview's finished image: scrubbing back starts from the last
kept copy before the new time, and shows the same pixels as drawing
the finished segments from the start.
"""

from types import SimpleNamespace
from typing import Any, cast

import cairo
import numpy as np
import pytest
from raygeo.geo import Matrix

from swiftcut.pipeline.job_preview import (
    CUT,
    SCAN,
    TRAVEL,
    JobPreviewModel,
    PreviewSegment,
)
from swiftcut.ui_gtk.canvas2d.elements import job_preview
from swiftcut.ui_gtk.canvas2d.elements.job_preview import JobPreviewElement

pytestmark = pytest.mark.ui

COLORS = {TRAVEL: (0, 0, 1, 1), CUT: (1, 0, 0, 1), SCAN: (0, 0.5, 0, 1)}
VIEW = Matrix.translation(10, 190) @ Matrix.scale(2.0, -2.0)
COUNT = 1000


def _model() -> JobPreviewModel:
    """Raster rows with a travel back between them, one segment a second."""
    segments = []
    for n in range(COUNT):
        row, kind = divmod(n, 2)
        y = row * 0.3
        points = ((5.0, y), (95.0, y)) if kind == 0 else ((95.0, y), (5.0, y))
        segments.append(
            PreviewSegment(n, SCAN if kind == 0 else TRAVEL, points, n, n + 1)
        )
    return JobPreviewModel(segments, float(COUNT))


def _element() -> JobPreviewElement:
    element = JobPreviewElement()
    element.model = _model()
    # Just what the finished image reads of its canvas.
    element.canvas = cast(
        Any,
        SimpleNamespace(
            view_transform=VIEW,
            get_width=lambda: 220,
            get_height=lambda: 200,
            get_scale_factor=lambda: 2,
        ),
    )
    return element


def _pixels(element, done) -> np.ndarray:
    view = cairo.Matrix(*VIEW.for_cairo())
    image = element._finished_image(view, COLORS, done)
    image.flush()
    return np.frombuffer(bytes(image.get_data()), np.uint8).copy()


@pytest.fixture
def drawn(monkeypatch):
    """Counts the segments draw_segments is asked to draw."""
    counts = []
    real = job_preview.draw_segments

    def counting(ctx, view, colors, segments):
        counts.append(len(segments))
        real(ctx, view, colors, segments)

    monkeypatch.setattr(job_preview, "draw_segments", counting)
    return counts


def test_scrubbing_back_matches_drawing_from_the_start(drawn):
    from_start = _pixels(_element(), 530)

    element = _element()
    _pixels(element, COUNT)
    drawn.clear()
    scrubbed = _pixels(element, 530)

    assert np.array_equal(scrubbed, from_start)
    # From the copy at 400 (every 200 of 1000), not from 0.
    assert sum(drawn) == 130


def test_a_jump_forward_past_a_copy_starts_from_it(drawn):
    element = _element()
    _pixels(element, COUNT)
    _pixels(element, 100)
    drawn.clear()

    jumped = _pixels(element, 870)
    # From the copy at 800, not on from 100.
    assert sum(drawn) == 70

    assert np.array_equal(jumped, _pixels(_element(), 870))


def test_a_new_view_starts_over_without_copies(drawn):
    element = _element()
    _pixels(element, COUNT)
    cast(Any, element.canvas).view_transform = Matrix.translation(1, 0) @ VIEW
    drawn.clear()

    _pixels(element, 530)

    assert sum(drawn) == 530
    assert [count for count, _ in element._checkpoints] == [200, 400]

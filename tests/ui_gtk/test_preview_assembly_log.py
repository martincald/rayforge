"""An empty document has no preview, and the log says so quietly.

Every preview of a document with no visible steps ends in
NoVisibleStepsError. That is the document's state, not a failure: one
DEBUG line, no ERROR, no traceback. Any other error still logs one.
"""

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from swiftcut.pipeline.pipeline import NoVisibleStepsError
from swiftcut.ui_gtk.mainwindow import MainWindow

_LOGGER = "swiftcut.ui_gtk.mainwindow"


def _window() -> Any:
    # Stands in for the window, which is all this callback reads.
    pipeline = SimpleNamespace(artifact_store=MagicMock())
    return SimpleNamespace(
        doc_editor=SimpleNamespace(pipeline=pipeline),
        _on_previews_ready=MagicMock(),
    )


def _finish(win, error, caplog) -> list[logging.LogRecord]:
    with (
        patch("swiftcut.ui_gtk.mainwindow.GLib.idle_add") as idle_add,
        caplog.at_level(logging.DEBUG, logger=_LOGGER),
    ):
        MainWindow._on_assembly_for_preview_finished(win, None, error)
    idle_add.assert_called_once_with(win._on_previews_ready, None)
    return [r for r in caplog.records if r.name == _LOGGER]


def test_an_empty_document_logs_one_debug_line(caplog):
    error = NoVisibleStepsError(
        "The document has no visible steps with workpieces to assemble."
    )

    records = _finish(_window(), error, caplog)

    assert [(r.levelno, r.getMessage(), r.exc_info) for r in records] == [
        (logging.DEBUG, str(error), None)
    ]


def test_any_other_error_still_logs_an_error_with_its_traceback(caplog):
    error = RuntimeError("Job encoding failed: boom")

    records = _finish(_window(), error, caplog)

    assert [(r.levelno, r.getMessage()) for r in records] == [
        (logging.ERROR, "Failed to aggregate ops for preview")
    ]
    assert records[0].exc_info is not None

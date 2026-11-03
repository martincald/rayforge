"""Session log rotation and the crash reporter's traceback."""

import logging
import os

import pytest

from swiftcut import app, logging_setup


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """A scratch LOG_DIR; the root logger's handlers come back after."""
    monkeypatch.setattr(logging_setup, "LOG_DIR", tmp_path)
    monkeypatch.setattr(app, "LOG_DIR", tmp_path)
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield tmp_path
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def _old_logs(log_dir, count):
    """count session logs, the oldest first, an hour apart."""
    paths = []
    for n in range(count):
        path = log_dir / f"session-2026-01-0{n + 1}_00-00-00.log"
        path.write_text("old\n")
        stamp = 1_700_000_000 + n * 3600
        os.utime(path, (stamp, stamp))
        paths.append(path)
    return paths


def test_only_the_newest_session_logs_are_kept(log_dir):
    paths = _old_logs(log_dir, 7)
    other = log_dir / "notes.txt"
    other.write_text("not a log\n")

    logging_setup._cleanup_old_logs(log_dir, 5)

    assert sorted(log_dir.glob("session-*.log")) == paths[2:]
    assert other.exists()


def test_a_new_session_counts_its_own_log_among_those_kept(log_dir):
    old = _old_logs(log_dir, 6)

    logging_setup.setup_logging("INFO")

    kept = set(log_dir.glob("session-*.log"))
    assert len(kept) == logging_setup.LOG_FILES_TO_KEEP
    assert logging_setup.get_current_log_file() in kept
    assert kept - {logging_setup.get_current_log_file()} == set(old[2:])


def test_an_unhandled_exception_leaves_its_traceback_in_the_log(
    log_dir, monkeypatch
):
    monkeypatch.setattr(logging, "shutdown", lambda: None)
    logging_setup.setup_logging("INFO")

    try:
        raise ValueError("the crash under test")
    except ValueError as e:
        app.handle_exception(ValueError, e, e.__traceback__)

    for handler in logging.getLogger().handlers:
        handler.flush()
    text = logging_setup.get_current_log_file().read_text(encoding="utf-8")
    assert "Unhandled exception" in text
    assert "Traceback (most recent call last)" in text
    assert "ValueError: the crash under test" in text

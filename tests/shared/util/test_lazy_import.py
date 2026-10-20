"""defer(): `import name` binds a placeholder that imports on first use."""

import sys
import textwrap
import threading

import pytest

from swiftcut.shared.util.lazy_import import defer, is_deferred


def _runs() -> int:
    """How many times the heavy module has run."""
    return vars(sys)["heavy_runs"]


@pytest.fixture
def heavy(tmp_path, monkeypatch):
    """A module that counts each time it runs, importable as `heavy`."""
    (tmp_path / "heavy.py").write_text(
        textwrap.dedent(
            """
            import sys
            import time

            time.sleep(0.05)  # long enough for two threads to race
            sys.heavy_runs = getattr(sys, "heavy_runs", 0) + 1

            class Thing:
                pass

            VALUE = 42
            """
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "heavy", raising=False)
    monkeypatch.setattr(sys, "heavy_runs", 0, raising=False)
    yield
    sys.modules.pop("heavy", None)


def test_import_binds_the_placeholder_without_running_it(heavy):
    defer("heavy")

    import heavy  # noqa: F401  # pyright: ignore[reportMissingImports]

    assert _runs() == 0
    assert is_deferred("heavy")


def test_the_first_attribute_runs_it_once(heavy):
    defer("heavy")
    import heavy  # pyright: ignore[reportMissingImports]

    assert heavy.VALUE == 42
    assert heavy.VALUE == 42
    assert _runs() == 1
    assert not is_deferred("heavy")


def test_a_binding_made_before_and_one_made_after_agree(heavy):
    defer("heavy")
    import heavy as before  # pyright: ignore[reportMissingImports]

    assert before.VALUE == 42
    import heavy as after  # pyright: ignore[reportMissingImports]

    assert before.Thing is after.Thing
    assert sys.modules["heavy"] is after


def test_from_import_runs_it(heavy):
    defer("heavy")

    from heavy import VALUE  # pyright: ignore[reportMissingImports]

    assert VALUE == 42
    assert _runs() == 1


def test_two_threads_reading_at_once_run_it_once(heavy):
    defer("heavy")
    import heavy  # pyright: ignore[reportMissingImports]

    values = []
    threads = [
        threading.Thread(target=lambda: values.append(heavy.VALUE))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert values == [42, 42]
    assert _runs() == 1


def test_an_imported_module_is_left_alone(heavy):
    import heavy  # pyright: ignore[reportMissingImports]

    defer("heavy")

    assert sys.modules["heavy"] is heavy
    assert _runs() == 1


def test_a_missing_module_is_ignored():
    defer("no_such_module_anywhere")

    assert "no_such_module_anywhere" not in sys.modules

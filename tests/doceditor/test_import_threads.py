"""An import computes off the main thread and changes the document on
it: scale to fit and the search for a free spot (the outlines of every
piece on the bed) run in the import's worker, the items go in on the
main thread, and a "no free space" notice reaches the UI there too.
"""

import asyncio
import threading
import time

import pytest

from swiftcut.core.vectorization_spec import PassthroughSpec


def _svg(path, width, height):
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}mm" height="{height}mm" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="none" '
        'stroke="black" stroke-width="0.1"/></svg>'
    )
    return path


@pytest.fixture
def bed(test_machine_and_config):
    machine, _config = test_machine_and_config
    machine.set_axis_extents(100, 100)
    return machine


async def _import(editor, task_mgr, path):
    editor.file.load_file_from_path(path, None, PassthroughSpec())
    deadline = time.monotonic() + 30.0
    while task_mgr.has_tasks():
        assert time.monotonic() < deadline, "import did not finish"
        await asyncio.sleep(0.01)
    await editor.wait_until_settled()


@pytest.mark.asyncio
async def test_placement_runs_off_the_main_thread(
    doc_editor, task_mgr, bed, tmp_path, monkeypatch
):
    file = doc_editor.file
    threads = {}

    def spy(name):
        method = getattr(file, name)

        def record(*args, **kwargs):
            threads[name] = threading.current_thread()
            return method(*args, **kwargs)

        monkeypatch.setattr(file, name, record)

    spy("_place_at_nearest_free_spot")
    spy("_commit_import")
    notices = []
    doc_editor.notification_requested.connect(
        lambda sender, **kwargs: notices.append(threading.current_thread()),
        weak=False,
    )
    main = threading.current_thread()

    await _import(doc_editor, task_mgr, _svg(tmp_path / "a.svg", 90, 90))
    # A second one finds no room beside the first: its notice comes
    # from the worker's search, delivered on the main thread.
    await _import(doc_editor, task_mgr, _svg(tmp_path / "b.svg", 90, 90))

    assert threads["_place_at_nearest_free_spot"] is not main
    assert threads["_commit_import"] is main
    assert notices == [main]
    assert len(doc_editor.doc.all_workpieces) == 2

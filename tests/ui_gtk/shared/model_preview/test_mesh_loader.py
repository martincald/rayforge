from pathlib import Path
from unittest.mock import patch

import trimesh

from swiftcut.ui_gtk.shared.model_preview.mesh_loader import (
    _load_mesh_data,
    _model_cache,
)


def _make_simple_mesh():
    return trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        faces=[[0, 1, 2]],
        process=False,
    )


class TestLoadMeshData:
    def setup_method(self):
        _model_cache.clear()

    def test_returns_none_on_missing_file(self):
        result = _load_mesh_data(Path("/nonexistent/file.glb"))
        assert result is None

    def test_caches_result(self, tmp_path):
        glb_file = tmp_path / "test.glb"
        glb_file.write_bytes(b"fake")

        mesh = _make_simple_mesh()

        with patch("trimesh.load", return_value=mesh):
            result = _load_mesh_data(glb_file)

        assert result is not None
        assert result.triangle_count == 1
        assert glb_file in _model_cache

        with patch("trimesh.load") as mock_load:
            result2 = _load_mesh_data(glb_file)
            mock_load.assert_not_called()

        assert result2 is result

    def test_handles_scene_with_geometry(self, tmp_path):
        glb_file = tmp_path / "multi.glb"
        glb_file.write_bytes(b"fake")

        mesh = _make_simple_mesh()
        scene = trimesh.Scene(geometry={"mesh1": mesh})

        with patch("trimesh.load", return_value=scene):
            result = _load_mesh_data(glb_file)

        assert result is not None
        assert result.triangle_count == 1

    def test_returns_none_on_trimesh_error(self, tmp_path):
        glb_file = tmp_path / "bad.glb"
        glb_file.write_bytes(b"fake")

        with patch("trimesh.load", side_effect=Exception("parse error")):
            result = _load_mesh_data(glb_file)

        assert result is None

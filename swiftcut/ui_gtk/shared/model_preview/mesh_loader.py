"""
Loads and caches .glb mesh data for machine-settings model previews.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh
from trimesh.visual.color import ColorVisuals
from trimesh.visual.material import PBRMaterial

logger = logging.getLogger(__name__)


@dataclass
class _CachedModelData:
    positions: np.ndarray
    normals: np.ndarray
    colors: np.ndarray | None
    faces: np.ndarray
    bounds: tuple[np.ndarray, np.ndarray]
    triangle_count: int


_model_cache: dict[Path, _CachedModelData] = {}


def _extract_color(mesh: trimesh.Trimesh) -> np.ndarray | None:
    if mesh.visual is None:
        return None
    if isinstance(mesh.visual, ColorVisuals):
        vc = mesh.visual.vertex_colors
        if vc is not None and len(vc) == len(mesh.vertices):
            return np.array(vc, dtype=np.float32) / 255.0
        return None
    mat = mesh.visual.material
    if isinstance(mat, PBRMaterial):
        base = mat.baseColorFactor
    else:
        base = mat.diffuse
    if base is not None:
        c = np.array(base, dtype=np.float32)
        if c.max() > 1.0:
            c = c / 255.0
        if c.shape[0] == 3:
            c = np.append(c, 1.0)
        return np.tile(c, (len(mesh.vertices), 1))
    return None


def _load_mesh_data(path: Path) -> _CachedModelData | None:
    cached = _model_cache.get(path)
    if cached is not None:
        return cached

    try:
        loaded = trimesh.load(str(path), file_type="glb")
        if isinstance(loaded, trimesh.Scene):
            meshes = []
            colors = []
            for node in loaded.graph.nodes_geometry:
                transform, geom_name = loaded.graph.get(node)
                geom = loaded.geometry[geom_name]
                color = _extract_color(geom)
                geom = geom.apply_transform(transform)
                meshes.append(geom)
                if color is not None:
                    colors.append(color)
            mesh = trimesh.util.concatenate(meshes)
            assert isinstance(mesh, trimesh.Trimesh)
            has_colors = len(colors) == len(meshes) and sum(
                c.shape[0] for c in colors
            ) == len(mesh.vertices)
            vertex_colors = (
                np.vstack(colors).astype(np.float32) if has_colors else None
            )
        elif isinstance(loaded, trimesh.Trimesh):
            mesh = loaded
            vertex_colors = _extract_color(mesh)
        else:
            logger.error(
                "Unexpected type from trimesh.load: %s",
                type(loaded).__name__,
            )
            return None

        assert isinstance(mesh, trimesh.Trimesh)

        positions = np.array(mesh.vertices, dtype=np.float32)
        normals = np.array(mesh.vertex_normals, dtype=np.float32)

        y_up_to_z_up = np.array(
            [[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float32
        )
        positions = (y_up_to_z_up @ positions.T).T
        normals = (y_up_to_z_up @ normals.T).T

        bounds = (
            positions.min(axis=0),
            positions.max(axis=0),
        )

        faces = np.array(mesh.faces, dtype=np.uint32)
        triangle_count = len(faces)

        data = _CachedModelData(
            positions=positions,
            normals=normals,
            colors=vertex_colors,
            faces=faces,
            bounds=bounds,
            triangle_count=triangle_count,
        )
        _model_cache[path] = data
        return data
    except Exception as e:  # noqa: BLE001 - trimesh library boundary
        logger.error("Failed to load model %s: %s", path, e)
        return None


def get_model_extent(path: Path) -> float | None:
    data = _load_mesh_data(path)
    if data is None:
        return None
    bmin, bmax = data.bounds
    return float(np.max(bmax - bmin))

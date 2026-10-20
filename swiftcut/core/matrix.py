from typing import Any

import numpy as np


def euler_rotation_matrix(rx: float, ry: float, rz: float) -> np.ndarray:
    """
    Build a 3x3 rotation matrix from Euler angles in degrees.

    The rotation order is X -> Y -> Z (extrinsic Tait-Bryan angles).
    """
    ax, ay, az = np.radians(rx), np.radians(ry), np.radians(rz)
    cx, sx = np.cos(ax), np.sin(ax)
    cy, sy = np.cos(ay), np.sin(ay)
    cz, sz = np.cos(az), np.sin(az)
    return np.array(
        [
            [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
            [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
            [-sy, sx * cy, cx * cy],
        ],
        dtype=np.float64,
    )


class TransformMixin:
    """
    Rotation and uniform scale of a part placed in the machine's 3D
    scene by a 4x4 ``transform``, as Euler angles in degrees (see
    euler_rotation_matrix). The class supplies ``transform`` and a
    blinker ``changed`` signal, sent when either changes.
    """

    transform: np.ndarray
    changed: Any

    def get_rotation(self):
        t = self.transform
        sx = float(np.linalg.norm(t[0, :3]))
        sy = float(np.linalg.norm(t[1, :3]))
        sz = float(np.linalg.norm(t[2, :3]))
        rx = np.degrees(np.arctan2(t[2, 1] / sy, t[2, 2] / sz))
        ry = np.degrees(
            np.arctan2(-t[2, 0] / sx, np.sqrt(t[2, 1] ** 2 + t[2, 2] ** 2))
        )
        rz = np.degrees(np.arctan2(t[1, 0] / sx, t[0, 0] / sx))
        return rx, ry, rz

    def set_rotation(self, rx: float, ry: float, rz: float):
        cur = self.get_rotation()
        if cur[0] == rx and cur[1] == ry and cur[2] == rz:
            return
        pos = self.transform[:3, 3].copy()
        scale = self.get_scale()
        self.transform[:3, :3] = euler_rotation_matrix(rx, ry, rz) * scale
        self.transform[:3, 3] = pos
        self.changed.send(self)

    def get_scale(self) -> float:
        return float(np.linalg.norm(self.transform[0, :3]))

    def set_scale(self, scale: float):
        if self.get_scale() == scale:
            return
        pos = self.transform[:3, 3].copy()
        rx, ry, rz = self.get_rotation()
        self.transform[:3, :3] = euler_rotation_matrix(rx, ry, rz) * scale
        self.transform[:3, 3] = pos
        self.changed.send(self)

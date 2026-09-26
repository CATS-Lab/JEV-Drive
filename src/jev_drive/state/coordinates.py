"""Physical transformations, with XY planar yaw and full 3D positions."""

import numpy as np
from scipy.spatial.transform import Rotation


def rotation(ego):
    return Rotation.from_quat(ego["quaternion_xyzw"])


def points_to_ego(points, ego):
    xyz = np.asarray(points, dtype=float).reshape(-1, 3)
    return rotation(ego).inv().apply(xyz - np.asarray(ego["position_world_m"]))


def vectors_to_ego(vectors, ego):
    return rotation(ego).inv().apply(np.asarray(vectors, dtype=float))


def heading_to_ego(quaternion, ego):
    forward = (rotation(ego).inv() * Rotation.from_quat(quaternion)).apply(
        [1.0, 0.0, 0.0]
    )
    return float(np.arctan2(forward[1], forward[0]))


def in_roi(point, roi):
    x, y = point[:2]
    return roi[0] <= x <= roi[1] and roi[2] <= y <= roi[3]

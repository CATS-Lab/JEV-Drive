"""Lane polygon association; ambiguous or missing matches are left unknown."""

import numpy as np
from shapely.geometry import Point, Polygon
from .coordinates import points_to_ego


def lane_id(position_ego, snapshot):
    candidates = []
    point = Point(position_ego[:2])
    for lane in snapshot.lanes:
        left, right = lane.get("left_edge_world", []), lane.get("right_edge_world", [])
        if len(left) < 2 or len(right) < 2:
            continue
        polygon = Polygon(
            np.concatenate(
                [
                    points_to_ego(left, snapshot.ego)[:, :2],
                    points_to_ego(right, snapshot.ego)[::-1, :2],
                ]
            )
        )
        if polygon.is_valid and polygon.covers(point):
            candidates.append(str(lane["id"]))
    return candidates[0] if len(candidates) == 1 else None

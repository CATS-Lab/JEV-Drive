"""Expose regulatory sign facts with source categories preserved."""

from .snapshot import SceneSnapshot
from ..config import Config


from .coordinates import points_to_ego, in_roi


def build(snapshot: SceneSnapshot, config: Config) -> list:
    result = []
    for sign in snapshot.traffic_controls.get("signs", []):
        position = points_to_ego([sign["position_world_m"]], snapshot.ego)[0]
        if in_roi(position, config.road_roi):
            result.append(
                {
                    "id": sign["id"],
                    "position_m": position.tolist(),
                    "source_category": sign["source_category"],
                    "lane_ids": sign.get("lane_ids", []),
                    "regulatory_value": sign.get("regulatory_value"),
                }
            )
    return result

"""Stop/wait-line categories are map facts, not stop/yield commands."""

from .snapshot import SceneSnapshot
from ..config import Config


from .road_graph import clip_resample


def build(snapshot: SceneSnapshot, config: Config) -> list:
    result = []
    for line in snapshot.traffic_controls.get("stop_lines", []):
        segments = clip_resample(
            line["points_world"],
            snapshot.ego,
            config.road_roi,
            config.centerline_spacing_m,
        )
        if segments:
            result.append(
                {
                    "id": line["id"],
                    "segments": segments,
                    "lane_ids": line.get("lane_ids", []),
                    "source_category": line["source_category"],
                    "is_implicit": line["is_implicit"],
                }
            )
    return result

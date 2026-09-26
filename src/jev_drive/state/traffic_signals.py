"""Timestamped signal observations; static geometry never implies a phase."""

from .snapshot import SceneSnapshot
from ..config import Config


from .coordinates import points_to_ego, in_roi, heading_to_ego


def build(snapshot: SceneSnapshot, config: Config) -> list:
    result = []
    for signal in snapshot.traffic_controls.get("signals", []):
        position = points_to_ego([signal["position_world_m"]], snapshot.ego)[0]
        if not in_roi(position, config.road_roi):
            continue
        valid = [
            p
            for p in signal.get("phase_history", [])
            if p["timestamp_us"] <= snapshot.timestamp_us
        ]
        phase = max(valid, key=lambda p: p["timestamp_us"]) if valid else None
        fresh = (
            phase is not None
            and snapshot.timestamp_us - phase["timestamp_us"]
            <= config.signal_max_age_s * 1e6
        )
        result.append(
            {
                "id": signal["id"],
                "position_m": position.tolist(),
                "heading_rad": heading_to_ego(signal["quaternion_xyzw"], snapshot.ego),
                "applies_to_lane_ids": signal.get("lane_ids", []),
                "category": signal.get("category", "unknown"),
                "phase": phase["phase"] if fresh else "unknown",
                "phase_timestamp_us": phase["timestamp_us"] if phase else None,
                "phase_source": phase["source"] if phase else "unavailable",
                "phase_stale": phase is not None and not fresh,
            }
        )
    return result

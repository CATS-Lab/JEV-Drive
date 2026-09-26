"""Current geometric ROI and nearest-K selection; no driving role labels."""

from .snapshot import SceneSnapshot
from ..config import Config


import numpy as np
from .coordinates import points_to_ego, vectors_to_ego, heading_to_ego, in_roi, rotation
from .lane_matching import lane_id


def build(snapshot: SceneSnapshot, config: Config) -> list:
    candidates = []
    for actor in snapshot.actors:
        xyz = points_to_ego([actor["position_world_m"]], snapshot.ego)[0]
        if in_roi(xyz, config.actor_roi):
            candidates.append(
                (float(np.linalg.norm(xyz[:2])), str(actor["id"]), actor, xyz)
            )
    ego_velocity_world = rotation(snapshot.ego).apply(snapshot.ego["velocity_rig_mps"])
    result = []
    for _, actor_id, a, xyz in sorted(candidates, key=lambda x: (x[0], x[1]))[
        : config.max_actors
    ]:
        velocity = a.get("velocity_world_mps")
        relative = (
            None
            if velocity is None
            else vectors_to_ego(np.asarray(velocity) - ego_velocity_world, snapshot.ego)
        )
        result.append(
            {
                "id": actor_id,
                "type": config.actor_types.get(a["source_type"], "unknown"),
                "source_type": a["source_type"],
                "lane_id": lane_id(xyz, snapshot),
                "x_m": float(xyz[0]),
                "y_m": float(xyz[1]),
                "relative_vx_mps": None if relative is None else float(relative[0]),
                "relative_vy_mps": None if relative is None else float(relative[1]),
                "velocity_source": a.get("velocity_source", "unavailable"),
                "heading_rad": heading_to_ego(a["quaternion_xyzw"], snapshot.ego),
                "length_m": float(a["dimensions_m"][0]),
                "width_m": float(a["dimensions_m"][1]),
            }
        )
    return result

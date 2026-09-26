"""Physical self-motion only. Command state is supplied by JevModel."""

from .snapshot import SceneSnapshot


def build(snapshot: SceneSnapshot) -> dict:
    ego = snapshot.ego
    return {
        "speed_mps": float(ego["velocity_rig_mps"][0]),
        "acceleration_mps2": float(ego["acceleration_rig_mps2"][0]),
        "yaw_rate_radps": float(ego["angular_velocity_rig_radps"][2]),
        "length_m": float(ego["dimensions_m"][0]),
        "width_m": float(ego["dimensions_m"][1]),
        "box_center_rig_m": ego["box_center_rig_m"],
        "box_heading_rig_rad": ego.get("box_heading_rig_rad", 0.0),
    }

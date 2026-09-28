"""Source lane facts, without inventing regulatory units or crossing permission."""

from .coordinates import points_to_ego, in_roi


def build(lane, snapshot, config):
    source = lane.get("source_attributes", {})
    return {
        "availability": "available" if source else "unavailable",
        **source,
        "speed_limit_unit": "unverified",
        "speed_limit_mps": None,
    }


def markings(lane, side, snapshot, config):
    result = []
    samples = lane.get(side + "_marking_samples_world", [])
    if not samples:
        return result
    positions = points_to_ego([s["position_world"] for s in samples], snapshot.ego)
    for sample, position in zip(samples, positions):
        if in_roi(position, config.road_roi):
            result.append(
                {
                    "position_m": [round(float(x), 3) for x in position[:2]],
                    "style": sample["style"],
                    "color": sample["color"],
                }
            )
    # Geometry is carried by boundary.segments. Keep only the endpoints of
    # constant style/color runs in the annotation samples, including both
    # sides of every change; do not serialize the same label at every vertex.
    return [
        value
        for i, value in enumerate(result)
        if i == 0
        or i == len(result) - 1
        or (value["style"], value["color"])
        != (result[i - 1]["style"], result[i - 1]["color"])
        or (value["style"], value["color"])
        != (result[i + 1]["style"], result[i + 1]["color"])
    ]

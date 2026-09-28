"""Auditable, current-frame suppression of likely duplicate actor boxes.

This is a geometry heuristic, not an assertion of physical object identity.
Raw scene data are never changed. Partial overlaps remain available for review.
"""

import math
from itertools import combinations, product
import numpy as np
from scipy.spatial.transform import Rotation
from shapely.geometry import Polygon

VERSION = "overlap-v1"
MIN_OVERLAP_AREA_M2 = 0.1
CONTAINMENT = 0.8
MAX_HEADING_DIFFERENCE_RAD = math.radians(15)
MAX_VELOCITY_DIFFERENCE_MPS = 3.0
VEHICLES = {"automobile", "vehicle", "bus", "heavy_truck", "trailer"}


def _geometry(actor):
    length, width, height = actor["dimensions_m"]
    rotation = Rotation.from_quat(actor["quaternion_xyzw"])
    position = np.asarray(actor["position_world_m"], dtype=float)
    corners = np.array(
        [
            [length / 2, width / 2, 0],
            [length / 2, -width / 2, 0],
            [-length / 2, -width / 2, 0],
            [-length / 2, width / 2, 0],
        ]
    )
    footprint = Polygon((rotation.apply(corners) + position)[:, :2])
    vertices = np.array(
        list(
            product(
                [-length / 2, length / 2],
                [-width / 2, width / 2],
                [-height / 2, height / 2],
            )
        )
    )
    z = (rotation.apply(vertices) + position)[:, 2]
    forward = rotation.apply([1, 0, 0])
    return (
        footprint,
        (float(z.min()), float(z.max())),
        math.atan2(forward[1], forward[0]),
    )


def filter_actors(actors, enabled=True):
    """Return original retained records and a separate audit; do not mutate input."""
    records = {str(a["id"]): a for a in actors}
    if len(records) != len(actors):
        raise ValueError("duplicate actor IDs")
    audit = {
        "version": VERSION,
        "enabled": enabled,
        "input_count": len(actors),
        "removed": [],
        "retained_overlap_pairs": [],
    }
    if not enabled:
        audit["output_count"] = len(actors)
        return list(actors), audit
    geometry = {key: _geometry(a) for key, a in records.items()}
    ordered = sorted(records, key=lambda key: (geometry[key][0].bounds[0], key))
    pairs = {}
    for i, key in enumerate(ordered):
        poly, z, heading = geometry[key]
        for other in ordered[i + 1 :]:
            op, oz, oh = geometry[other]
            if op.bounds[0] > poly.bounds[2]:
                break
            if op.bounds[1] > poly.bounds[3] or poly.bounds[1] > op.bounds[3]:
                continue
            area = poly.intersection(op).area
            if area <= MIN_OVERLAP_AREA_M2:
                continue
            a, b = records[key], records[other]
            z_overlap = max(0.0, min(z[1], oz[1]) - max(z[0], oz[0]))
            height_fraction = z_overlap / max(1e-9, min(z[1] - z[0], oz[1] - oz[0]))
            angle = abs(math.atan2(math.sin(heading - oh), math.cos(heading - oh)))
            va, vb = a.get("velocity_world_mps"), b.get("velocity_world_mps")
            velocity_difference = (
                None
                if va is None or vb is None
                else float(np.linalg.norm(np.asarray(va) - np.asarray(vb)))
            )
            family = a["source_type"] in VEHICLES and b["source_type"] in VEHICLES
            geometry_compatible = (
                family
                and height_fraction >= 0.5
                and angle <= MAX_HEADING_DIFFERENCE_RAD
            )
            compatible = (
                geometry_compatible
                and velocity_difference is not None
                and velocity_difference <= MAX_VELOCITY_DIFFERENCE_MPS
            )
            pair = tuple(sorted([key, other]))
            pairs[pair] = {
                "ids": list(pair),
                "area_m2": area,
                "intersection_over_smaller": area / min(poly.area, op.area),
                "vertical_overlap_fraction": height_fraction,
                "heading_difference_rad": angle,
                "velocity_difference_mps": velocity_difference,
                "compatible": bool(compatible),
                "geometry_compatible": bool(geometry_compatible),
                "iou": area / (poly.area + op.area - area),
                "area_ratio": max(poly.area, op.area) / min(poly.area, op.area),
            }

    # Prefer two separate, well-supported component boxes over one encompassing box.
    # Require components to be disjoint and cover most of the large box jointly.
    removed = set()
    protected = set()
    for key in sorted(records, key=lambda k: (-geometry[k][0].area, k)):
        if key in protected:
            continue
        poly = geometry[key][0]
        children = []
        for other in records:
            pair = pairs.get(tuple(sorted([key, other])))
            if (
                other != key
                and other not in removed
                and pair
                and pair["geometry_compatible"]
            ):
                op = geometry[other][0]
                if (
                    poly.area >= 1.5 * op.area
                    and pair["area_m2"] / op.area >= CONTAINMENT
                ):
                    children.append(other)
        for left, right in combinations(sorted(children), 2):
            lp, rp = geometry[left][0], geometry[right][0]
            if lp.intersection(rp).area / min(lp.area, rp.area) > 0.1:
                continue
            coverage = lp.union(rp).intersection(poly).area / poly.area
            if coverage < 0.55:
                continue
            removed.add(key)
            protected.update([left, right])
            audit["removed"].append(
                {
                    "id": key,
                    "reason": "enclosing_multiple_components",
                    "represented_by": [left, right],
                    "coverage": coverage,
                    "component_overlaps": [
                        pairs[tuple(sorted([key, child]))] for child in [left, right]
                    ],
                }
            )
            break

    # Greedy suppression compares only with survivors, not transitive overlap chains.
    survivors = []
    for key in sorted(records, key=lambda k: (-geometry[k][0].area, k)):
        if key in removed:
            continue
        representative = None
        if key not in protected:
            for other in survivors:
                pair = pairs.get(tuple(sorted([key, other])))
                if (
                    pair
                    and pair["geometry_compatible"]
                    and pair["area_ratio"] <= 1.5
                    and (
                        (
                            pair["compatible"]
                            and pair["intersection_over_smaller"] >= CONTAINMENT
                        )
                        or pair["iou"] >= 0.85
                    )
                ):
                    representative = other
                    break
        if representative is None:
            survivors.append(key)
        else:
            removed.add(key)
            audit["removed"].append(
                {
                    "id": key,
                    "reason": "near_duplicate_box",
                    "represented_by": [representative],
                    "overlap": pairs[tuple(sorted([key, representative]))],
                }
            )
    audit["retained_overlap_pairs"] = [
        p for ids, p in sorted(pairs.items()) if not (set(ids) & removed)
    ]
    result = [a for a in actors if str(a["id"]) not in removed]
    audit["output_count"] = len(result)
    return result, audit

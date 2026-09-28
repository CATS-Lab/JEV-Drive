"""Evaluation-only surface alignment for simulations without ground contact."""
import numpy as np
from shapely.geometry import Point


class GeometryAssessmentError(RuntimeError):
    """The source map cannot establish a single local road level."""


def local_surface(lanes, center, nearest_segment):
    point = Point(center[:2])
    candidates = []
    for lane, polygon in lanes:
        distance = polygon.distance(point)
        # Permit a small map seam or a center just outside the road boundary.
        if distance > 2.0:
            continue
        segment = nearest_segment(lane["center_world"], center)
        if segment is not None:
            candidates.append((distance, str(lane["id"]), float(segment[0][2])))
    if not candidates:
        raise GeometryAssessmentError("No source lane surface within 2 m of ego center")
    closest = min(c[0] for c in candidates)
    candidates = [c for c in candidates if c[0] <= closest + 0.05]
    heights = [c[2] for c in candidates]
    if max(heights) - min(heights) > 1.5:
        raise GeometryAssessmentError("Ambiguous stacked road surfaces beneath ego")
    return {
        "mode": "local_road_surface_v1",
        "surface_z_m": float(np.median(heights)),
        "source_lane_ids": sorted(c[1] for c in candidates),
        "nearest_polygon_distance_m": closest,
    }

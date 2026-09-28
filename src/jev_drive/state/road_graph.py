"""Crop lane geometry, preserve disconnected pieces, and report topology facts."""

from .snapshot import SceneSnapshot
from ..config import Config


import numpy as np
from shapely.geometry import LineString, Point, box
from .coordinates import points_to_ego


def clip_resample(points_world, ego, roi, spacing):
    if len(points_world) < 2:
        return []
    xy = points_to_ego(points_world, ego)[:, :2]
    line = LineString(xy)
    clipped = line.intersection(box(roi[0], roi[2], roi[1], roi[3]))
    geometries = (
        [clipped]
        if clipped.geom_type == "LineString"
        else list(getattr(clipped, "geoms", []))
    )
    result = []
    for segment in geometries:
        if segment.geom_type != "LineString" or segment.length < 1e-6:
            continue
        # Retain original lane travel direction even if clipping changes ordering.
        coords = list(segment.coords)
        if line.project(Point(coords[0])) > line.project(Point(coords[-1])):
            segment = LineString(coords[::-1])
        ds = list(np.arange(0, segment.length, spacing)) + [segment.length]
        # Millimetre precision avoids spending model context on float noise.
        # The source snapshot retains full precision.
        result.append(
            [
                [round(float(p.x), 3), round(float(p.y), 3)]
                for p in (segment.interpolate(d) for d in ds)
            ]
        )
    return result


def build(snapshot: SceneSnapshot, config: Config) -> dict:
    lanes = []
    all_ids = {str(lane["id"]) for lane in snapshot.lanes}
    for lane in snapshot.lanes:
        center = clip_resample(
            lane["center_world"],
            snapshot.ego,
            config.road_roi,
            config.centerline_spacing_m,
        )
        if not center:
            continue
        item = {"id": str(lane["id"]), "centerline_segments": center}
        for key in ("left_neighbors", "right_neighbors", "successors"):
            item[key] = sorted(str(x) for x in lane[key])
        for side in ("left", "right"):
            item[side + "_boundary"] = {
                "type": lane.get(side + "_marking", "unknown"),
                "segments": clip_resample(
                    lane.get(side + "_edge_world", []),
                    snapshot.ego,
                    config.road_roi,
                    config.centerline_spacing_m,
                ),
            }
        lanes.append(item)
    ids = {lane["id"] for lane in lanes}
    for lane in lanes:
        refs = set(
            lane["left_neighbors"] + lane["right_neighbors"] + lane["successors"]
        )
        lane["references_outside_roi"] = sorted((refs & all_ids) - ids)
        lane["unresolved_references"] = sorted(refs - all_ids)
    return {
        "lanes": sorted(lanes, key=lambda lane: lane["id"]),
        "roi_m": list(config.road_roi),
        "availability": snapshot.provenance.get("map", "available"),
    }

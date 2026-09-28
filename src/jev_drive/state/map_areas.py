"""Crop source area polygons; preserve holes and invalid-geometry evidence."""

from shapely.geometry import Polygon, box
from .coordinates import points_to_ego


def build(snapshot, config):
    roi = config.road_roi
    window = box(roi[0], roi[2], roi[1], roi[3])
    result, invalid = [], []
    for area in snapshot.map_areas:
        points = points_to_ego(area["points_world"], snapshot.ego)[:, :2]
        polygon = Polygon(points)
        if not polygon.is_valid or polygon.area <= 1e-6:
            invalid.append(area["id"])
            continue
        clipped = polygon.intersection(window)
        parts = (
            [clipped]
            if clipped.geom_type == "Polygon"
            else getattr(clipped, "geoms", [])
        )
        polygons = [
            {
                "exterior": [
                    [round(float(x), 3), round(float(y), 3)]
                    for x, y in p.exterior.coords
                ],
                "holes": [
                    [[round(float(x), 3), round(float(y), 3)] for x, y in ring.coords]
                    for ring in p.interiors
                ],
            }
            for p in parts
            if p.geom_type == "Polygon" and p.area > 1e-6
        ]
        if polygons:
            result.append(
                {
                    "id": area["id"],
                    "kind": area["kind"],
                    "category": area["category"],
                    "lane_ids": area.get("lane_ids", []),
                    "source_is_complete": area.get("is_complete"),
                    "clipped_to_roi": not window.covers(polygon),
                    "polygons": polygons,
                }
            )
    return {
        "source": "raw_map",
        "available_layers": snapshot.available_area_layers,
        "areas": sorted(result, key=lambda a: (a["kind"], a["id"])),
        "invalid_geometry_ids": invalid,
        "roi_m": list(roi),
    }

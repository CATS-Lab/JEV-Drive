"""Source-map road edges, distinct from lane dividers and ROI boundaries."""

from shapely.geometry import LineString, box
from .coordinates import points_to_ego


def build(snapshot, config):
    roi = config.road_roi
    window = box(roi[0], roi[2], roi[1], roi[3])
    edges = []
    for edge in snapshot.road_edges:
        if len(edge["points_world"]) < 2:
            continue
        xy = points_to_ego(edge["points_world"], snapshot.ego)[:, :2]
        clipped = LineString(xy).intersection(window)
        parts = (
            [clipped]
            if clipped.geom_type == "LineString"
            else getattr(clipped, "geoms", [])
        )
        segments = [
            [[round(float(x), 3), round(float(y), 3)] for x, y in part.coords]
            for part in parts
            if part.geom_type == "LineString" and part.length > 1e-6
        ]
        if segments:
            edges.append({"id": str(edge["id"]), "segments": segments})
    available = snapshot.provenance.get(
        "road_edges"
    ) == "source_map_road_edges" or bool(snapshot.road_edges)
    return {
        "source": "source_map_road_edges" if available else "unavailable",
        "availability": "available" if available else "unavailable",
        "edges": sorted(edges, key=lambda e: e["id"]),
        "roi_m": list(roi),
        "geometry": "open_polylines; no closed drivable-area polygon or interior-side labels",
    }

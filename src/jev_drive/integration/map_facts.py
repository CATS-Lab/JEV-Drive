"""Read source map facts omitted by VectorMap, without behavior inference."""

from io import BytesIO
from zipfile import ZipFile
import pyarrow.parquet as pq

AREA_LAYERS = (
    "crosswalk",
    "road_island",
    "gore_area",
    "buffer_zone",
    "intersection_area",
    "road_marking",
)


def read_map_facts(path):
    with ZipFile(path) as archive:
        directory = next(
            (
                d
                for d in ("map_data", "clipgt", "fastmap")
                if d + "/lane.parquet" in archive.namelist()
            ),
            None,
        )
        if directory is None:
            return {
                "lanes": {},
                "areas": [],
                "associations": [],
                "signs": {},
                "available_layers": [],
            }

        def read(name):
            filename = directory + "/" + name + ".parquet"
            return (
                pq.read_table(BytesIO(archive.read(filename))).to_pylist()
                if filename in archive.namelist()
                else []
            )

        lanes = {
            str(row["key"]["map_id"]): row["lane"]
            for row in read("lane")
            if row.get("lane") and row["key"].get("map_id")
        }
        areas, available = [], []
        for name in AREA_LAYERS:
            if directory + "/" + name + ".parquet" in archive.namelist():
                available.append(name)
            for row in read(name):
                value = row.get(name)
                if (
                    not value
                    or not row["key"].get("map_id")
                    or len(value.get("location") or []) < 3
                ):
                    continue
                areas.append(
                    {
                        "id": str(row["key"]["map_id"]),
                        "kind": name,
                        "category": value.get("category", "unknown"),
                        "points_world": [
                            [p[k] for k in "xyz"] for p in value["location"]
                        ],
                        "is_complete": value.get("is_complete"),
                    }
                )
        signs = {
            str(row["key"]["map_id"]): row["traffic_sign"]
            for row in read("traffic_sign")
            if row.get("traffic_sign") and row["key"].get("map_id")
        }
        return {
            "lanes": lanes,
            "areas": areas,
            "associations": read("association"),
            "signs": signs,
            "available_layers": available,
        }


def entity_lane_links(associations, kind, entity_ids, lane_ids):
    """Resolve explicit links by ID membership, not misleading relation names."""
    result = {key: set() for key in entity_ids}
    for row in associations:
        if row["key"].get("kind") != kind or not row.get("association"):
            continue
        left = set(map(str, row["association"].get("subjects") or []))
        right = set(map(str, row["association"].get("objects") or []))
        for entities, lanes in ((left, right), (right, left)):
            for key in entities & entity_ids:
                result[key].update(lanes & lane_ids)
    return {key: sorted(value) for key, value in result.items()}


def enrich(lanes, controls, facts):
    lane_ids = {lane["id"] for lane in lanes}
    for lane in lanes:
        raw = facts["lanes"].get(lane["id"])
        if raw is None:
            continue
        lane["source_attributes"] = {
            key: raw.get(key)
            for key in (
                "lane_direction",
                "map_end",
                "speed_limit",
                "vehicle_types",
                "use_types",
                "suicide_lane_special_tag",
            )
        }
        for side in ("left", "right"):
            rail = raw.get(side + "_rail") or []
            styles, colors = (
                raw.get(side + "_edge_styles") or [],
                raw.get(side + "_edge_colors") or [],
            )
            lane[side + "_marking_samples_world"] = [
                {
                    "position_world": [point[k] for k in "xyz"],
                    "style": styles[i] if i < len(styles) else "unknown",
                    "color": colors[i] if i < len(colors) else "unknown",
                }
                for i, point in enumerate(rail)
            ]
            unique = set(styles)
            lane[side + "_marking"] = (
                next(iter(unique))
                if len(unique) == 1
                else ("mixed" if unique else "unknown")
            )
    for key, kind in (
        ("signals", "LIGHT_TO_LANE"),
        ("signs", "SIGN_TO_LANE"),
        ("stop_lines", "WAIT_LINE_TO_LANE"),
    ):
        links = entity_lane_links(
            facts["associations"],
            kind,
            {str(item["id"]) for item in controls[key]},
            lane_ids,
        )
        for item in controls[key]:
            item["lane_ids"] = sorted(
                set(item.get("lane_ids", [])) | set(links[str(item["id"])])
            )
            if key == "signs":
                raw = facts["signs"].get(str(item["id"]))
                if raw and raw.get("orientation"):
                    item["quaternion_xyzw"] = [raw["orientation"][k] for k in "xyzw"]
    for area in facts["areas"]:
        kind = {
            "crosswalk": "CROSSWALK_TO_LANE",
            "intersection_area": "INTERSECTION_AREA_TO_LANE",
            "road_marking": "ROAD_MARKING_TO_LANE",
        }.get(area["kind"])
        area["lane_ids"] = (
            entity_lane_links(facts["associations"], kind, {area["id"]}, lane_ids)[
                area["id"]
            ]
            if kind
            else []
        )

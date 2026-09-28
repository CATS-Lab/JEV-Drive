from dataclasses import replace
from copy import deepcopy

from jev_drive.integration.map_facts import enrich, entity_lane_links
from jev_drive.state.state_builder import JevStateBuilder
from jev_drive.state.navigation import build as navigation
from jev_drive.state.map_areas import build as areas
from jev_drive.config import Config
from test_core import snapshot
from test_navigation import scene


def test_light_association_uses_id_membership_in_either_direction():
    def row(left, right):
        return {
            "key": {"kind": "LIGHT_TO_LANE"},
            "association": {"subjects": left, "objects": right},
        }

    links = entity_lane_links(
        [row(["lane"], ["light"]), row(["light"], ["lane2", "missing"])],
        "LIGHT_TO_LANE",
        {"light"},
        {"lane", "lane2"},
    )
    assert links == {"light": ["lane", "lane2"]}


def test_raw_lane_attributes_markings_and_sign_orientation_survive_enrichment():
    s = snapshot()
    controls = {
        "signals": [],
        "signs": [{"id": "sign", "lane_ids": []}],
        "stop_lines": [],
    }
    facts = {
        "lanes": {
            "lane-a": {
                "left_rail": [{"x": 0, "y": 2, "z": 0}, {"x": 5, "y": 2, "z": 0}],
                "left_edge_styles": ["SOLID_SINGLE", "LONG_DASHED_SINGLE"],
                "left_edge_colors": ["YELLOW", "WHITE"],
                "speed_limit": "25",
                "use_types": ["SHOULDER_LANE"],
                "lane_direction": "STRAIGHT",
            }
        },
        "areas": [],
        "associations": [
            {
                "key": {"kind": "SIGN_TO_LANE"},
                "association": {"subjects": ["lane-a"], "objects": ["sign"]},
            }
        ],
        "signs": {"sign": {"orientation": dict(x=0, y=0, z=0, w=1)}},
    }
    enrich(s.lanes, controls, facts)
    state = JevStateBuilder(Config()).build(s)["state"]
    lane = state["road"]["lanes"][0]
    assert (
        lane["attributes"]["speed_limit"] == "25"
        and lane["attributes"]["speed_limit_mps"] is None
    )
    assert lane["left_boundary"]["type"] == "mixed"
    assert [p["style"] for p in lane["left_boundary"]["source_samples"]] == [
        "SOLID_SINGLE",
        "LONG_DASHED_SINGLE",
    ]
    assert controls["signs"][0]["lane_ids"] == ["lane-a"]
    assert controls["signs"][0]["quaternion_xyzw"] == [0, 0, 0, 1]


def test_navigation_does_not_include_shoulder_or_hov():
    s = scene()
    lanes = deepcopy(s.lanes)
    lanes[1]["source_attributes"] = {"use_types": ["SHOULDER_LANE"]}
    lanes[3]["source_attributes"] = {"use_types": ["HOV_LANE"]}
    nav = navigation(replace(s, lanes=lanes), Config())
    assert nav["availability"] == "available"
    assert [c["lane_ids"] for c in nav["corridors"]] == [["a"], ["c"]]


def test_clipped_area_and_invalid_geometry_are_explicit():
    s = replace(
        snapshot(),
        map_areas=[
            {
                "id": "cross",
                "kind": "crosswalk",
                "category": "PEDESTRIAN",
                "points_world": [[-25, -2, 0], [5, -2, 0], [5, 2, 0], [-25, 2, 0]],
                "lane_ids": ["lane-a"],
            },
            {
                "id": "bad",
                "kind": "road_island",
                "category": "unknown",
                "points_world": [[0, 0, 0], [2, 2, 0], [0, 2, 0], [2, 0, 0]],
            },
        ],
        available_area_layers=["crosswalk", "road_island"],
    )
    result = areas(s, Config())
    assert result["invalid_geometry_ids"] == ["bad"]
    assert result["areas"][0]["clipped_to_roi"] is True
    assert result["areas"][0]["lane_ids"] == ["lane-a"]
    assert min(p[0] for p in result["areas"][0]["polygons"][0]["exterior"]) == -20


def test_observation_scope_and_lateral_motion():
    s = snapshot()
    s.ego["velocity_rig_mps"][1] = 1.5
    for i in range(3):
        s.actors.append(
            {
                "id": str(i),
                "source_type": "automobile",
                "position_world_m": [10 + 10 * i, 0, 0],
                "quaternion_xyzw": [0, 0, 0, 1],
                "dimensions_m": [4, 2, 1.5],
                "velocity_world_mps": [10, 0, 0],
            }
        )
    state = JevStateBuilder(Config(max_actors=1)).build(s)["state"]
    assert state["ego"]["lateral_speed_mps"] == 1.5
    assert state["actors"][0]["relative_vy_mps"] == -1.5
    assert state["observation_scope"]["omitted_by_nearest_k"] == 2
    assert state["observation_scope"]["selected_count"] == 1


def test_marking_compaction_preserves_both_sides_of_changes():
    from jev_drive.state.lane_attributes import markings

    lane = {
        "left_marking_samples_world": [
            {
                "position_world": [i, 2, 0],
                "style": "solid" if i < 4 else "dashed",
                "color": "white",
            }
            for i in range(8)
        ]
    }
    result = markings(lane, "left", snapshot(), Config())
    assert [p["position_m"][0] for p in result] == [0, 3, 4, 7]
    assert [p["style"] for p in result] == ["solid", "solid", "dashed", "dashed"]


def test_null_signal_placeholder_is_not_an_actor(tmp_path):
    from zipfile import ZipFile
    import pyarrow as pa
    import pyarrow.parquet as pq
    from jev_drive.integration.alpasim_adapter import artifact_signals

    sink = pa.BufferOutputStream()
    pq.write_table(
        pa.Table.from_pylist(
            [{"key": {"map_id": None}, "traffic_light": {"category": None}}]
        ),
        sink,
    )
    artifact = tmp_path / "empty.usdz"
    with ZipFile(artifact, "w") as archive:
        archive.writestr("clipgt/traffic_light.parquet", sink.getvalue().to_pybytes())
    assert artifact_signals(artifact) == ([], "available")

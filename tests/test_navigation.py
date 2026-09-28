from dataclasses import replace
from copy import deepcopy

from jev_drive.config import Config
from jev_drive.state.navigation import build
from test_core import snapshot


def lane(key, points, neighbors=(), successors=()):
    return dict(
        id=key,
        center_world=points,
        left_neighbors=list(neighbors),
        right_neighbors=[],
        successors=list(successors),
    )


def scene():
    return replace(
        snapshot(),
        lanes=[
            lane("a", [[0, 0, 0], [40, 0, 0]], ["b"], ["c"]),
            lane("b", [[0, 4, 0], [40, 4, 0]], ["a"], ["d"]),
            lane("c", [[40, 0, 0], [80, 0, 0]], ["d"]),
            lane("d", [[40, 4, 0], [80, 4, 0]], ["c"]),
            lane("opposing", [[40, 8, 0], [0, 8, 0]], ["b"]),
        ],
        navigation_goal_world_m=[75, 0, 0],
    )


def test_corridor_allows_lane_choice_and_excludes_oncoming():
    result = build(scene(), Config())
    assert result["availability"] == "available"
    assert [c["lane_ids"] for c in result["corridors"]] == [["a", "b"], ["c", "d"]]
    assert "route_segments" not in result


def test_intermediate_gt_and_target_lane_do_not_affect_route():
    s = scene()
    original = build(s, Config())
    assert (
        build(replace(s, route_world=[[999, -99, 0], [-999, 22, 0]]), Config())
        == original
    )
    assert build(replace(s, navigation_goal_world_m=[75, 4, 0]), Config()) == original


def test_legacy_snapshot_uses_endpoint_only():
    s = replace(
        scene(), navigation_goal_world_m=None, route_world=[[0, 0, 0], [75, 0, 0]]
    )
    assert build(s, Config()) == build(
        replace(s, route_world=[[1000, 1000, 0], [75, 0, 0]]), Config()
    )


def test_missing_and_disconnected_destinations_do_not_fall_back_to_gt():
    s = scene()
    assert (
        build(replace(s, navigation_goal_world_m=[999, 999, 0]), Config())[
            "availability"
        ]
        == "unavailable"
    )
    assert (
        build(replace(s, navigation_goal_world_m=None, route_world=[]), Config())[
            "reason"
        ]
        == "missing_destination"
    )
    lanes = deepcopy(s.lanes)
    for item in lanes:
        item["successors"] = []
    assert build(replace(s, lanes=lanes), Config())["reason"] == "no_directed_map_route"


def test_explicit_destination_overrides_recording():
    assert (
        len(
            build(scene(), Config(navigation_destination_world_m=(20, 0, 0)))[
                "corridors"
            ]
        )
        == 1
    )


def test_fork_selected_by_map_connectivity_to_destination():
    s = scene()
    lanes = deepcopy(s.lanes)
    lanes[0]["successors"].append("turn")
    lanes.append(lane("turn", [[40, 0, 0], [40, -40, 0]]))
    result = build(
        replace(s, lanes=lanes, navigation_goal_world_m=[40, -35, 0]), Config()
    )
    assert [c["lane_ids"] for c in result["corridors"]] == [["a", "b"], ["turn"]]

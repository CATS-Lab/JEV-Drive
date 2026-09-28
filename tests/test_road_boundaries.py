from dataclasses import replace
from jev_drive.config import Config
from jev_drive.state.road_boundaries import build
from test_core import snapshot


def test_source_edges_are_clipped_without_inventing_roi_edges():
    s = replace(
        snapshot(),
        road_edges=[
            {"id": "edge", "points_world": [[-30, 6, 0], [0, 5, 0], [100, 5, 0]]}
        ],
    )
    r = build(s, Config())
    assert r["availability"] == "available"
    segments = r["edges"][0]["segments"]
    assert len(segments) == 1
    assert segments[0][0][0] == -20 and segments[0][-1][0] == 80
    assert [0.0, 5.0] in segments[0]  # Retain the original corner.
    assert all(point[1] >= 5 for point in segments[0])


def test_missing_map_edges_are_not_inferred_from_lane_dividers():
    r = build(snapshot(), Config())
    assert r["availability"] == "unavailable"
    assert r["edges"] == []


def test_outside_roi_is_distinct_from_unavailable_source():
    s = replace(
        snapshot(),
        road_edges=[{"id": "far", "points_world": [[0, 100, 0], [10, 100, 0]]}],
    )
    r = build(s, Config())
    assert r["availability"] == "available" and r["edges"] == []


def test_disconnected_pieces_are_not_joined_across_crop():
    s = replace(
        snapshot(),
        road_edges=[
            {
                "id": "u",
                "points_world": [[0, 0, 0], [0, 30, 0], [10, 30, 0], [10, 0, 0]],
            }
        ],
    )
    assert len(build(s, Config())["edges"][0]["segments"]) == 2

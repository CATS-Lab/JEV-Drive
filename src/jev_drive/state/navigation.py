"""Map-topology road corridors; recorded intermediate waypoints are never used."""

from heapq import heappop, heappush

import numpy as np
from shapely.geometry import LineString, Point
from scipy.spatial.transform import Rotation


def _tangent(line, distance):
    a = line.interpolate(max(0, distance - 0.5))
    b = line.interpolate(min(line.length, distance + 0.5))
    delta = np.array([b.x - a.x, b.y - a.y])
    return delta / max(float(np.linalg.norm(delta)), 1e-9)


def build(snapshot, config):
    """Group adjacent same-direction lanes and route over directed successors.

    A corridor is a local map-derived road section, not an official road ID.
    Group membership describes route intent, not permission to cross markings.
    """
    goal = config.navigation_destination_world_m
    source = "configured_destination"
    if goal is None:
        goal = snapshot.navigation_goal_world_m
        source = snapshot.provenance.get("navigation_goal", "snapshot_destination")
    if goal is None and snapshot.route_world:
        # Backward compatibility for archived snapshots: endpoint ONLY.
        goal = snapshot.route_world[-1]
        source = "legacy_route_endpoint_only"
    result = {
        "mode": "road_corridor",
        "source": "map_topology",
        "destination_source": source,
        "availability": "unavailable",
        "corridors": [],
    }
    if goal is None:
        return {**result, "reason": "missing_destination"}
    # Ordinary-car route planning excludes known shoulders and HOV lanes:
    # HOV eligibility is not supplied in the current experiment.
    excluded = {
        str(lane["id"])
        for lane in snapshot.lanes
        if set(lane.get("source_attributes", {}).get("use_types") or [])
        & {"SHOULDER_LANE", "HOV_LANE"}
    }
    result["excluded_lane_uses"] = ["SHOULDER_LANE", "HOV_LANE"]
    lanes = {
        str(lane["id"]): lane
        for lane in snapshot.lanes
        if str(lane["id"]) not in excluded
    }
    lines = {
        key: LineString(np.asarray(lane["center_world"])[:, :2])
        for key, lane in lanes.items()
        if len(lane["center_world"]) >= 2
    }
    lines = {key: line for key, line in lines.items() if line.length > 1e-6}
    if not lines:
        return {**result, "reason": "missing_map_geometry"}
    parent = {key: key for key in lines}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for key in sorted(lines):
        lane, line = lanes[key], lines[key]
        midpoint = line.interpolate(line.length / 2)
        for other in lane.get("left_neighbors", []) + lane.get("right_neighbors", []):
            other = str(other)
            if other not in lines:
                continue
            # Adjacency alone need not imply the same travel direction.
            direction = _tangent(lines[other], lines[other].project(midpoint))
            if np.dot(_tangent(line, line.length / 2), direction) > 0.5:
                a, b = sorted([find(key), find(other)])
                parent[b] = a
    groups = {}
    for key in sorted(lines):
        groups.setdefault(find(key), []).append(key)
    membership = {key: group for group, keys in groups.items() for key in keys}
    graph = {group: set() for group in groups}
    for key, group in membership.items():
        for successor in lanes[key].get("successors", []):
            next_group = membership.get(str(successor))
            if next_group is not None and next_group != group:
                graph[group].add(next_group)

    def match(position, forward=None):
        point = Point(position[:2])
        candidates = []
        for key, line in lines.items():
            if (
                forward is not None
                and np.dot(_tangent(line, line.project(point)), forward) <= 0.5
            ):
                continue
            candidates.append((line.distance(point), key))
        if not candidates:
            return None
        distance, key = min(candidates)
        # Do not silently attach an off-map vehicle/destination to a distant road.
        return membership[key] if distance <= 6.0 else None

    forward = Rotation.from_quat(snapshot.ego["quaternion_xyzw"]).apply([1, 0, 0])[:2]
    start = match(snapshot.ego["position_world_m"], forward)
    target = match(goal)
    if start is None or target is None:
        return {**result, "reason": "ego_or_destination_not_matched"}
    distances, previous = {start: 0.0}, {}
    queue = [(0.0, start)]
    while queue:
        cost, group = heappop(queue)
        if cost != distances[group]:
            continue
        if group == target:
            break
        for successor in sorted(graph[group]):
            weight = min(lines[key].length for key in groups[successor])
            new_cost = cost + weight
            if new_cost < distances.get(successor, float("inf")):
                distances[successor] = new_cost
                previous[successor] = group
                heappush(queue, (new_cost, successor))
    if target not in distances:
        return {**result, "reason": "no_directed_map_route"}
    path = [target]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    result.update(
        availability="available",
        destination_corridor_id="corridor:" + target,
        corridors=[
            {"id": "corridor:" + group, "lane_ids": groups[group]} for group in path
        ],
    )
    return result

"""Checks supported by raw geometry; unknown traffic rules stay unassessed.

These are sampled box/geometry checks, not a continuous collision guarantee.
Source road edges are distinct from lane dividers and ROI crop boundaries.
"""

from itertools import product
import numpy as np
from scipy.spatial.transform import Rotation
from shapely.geometry import LineString, Point, Polygon
from ..state.actor_filter import filter_actors


class SafetyViolation(RuntimeError):
    pass


def box_geometry(position, quaternion, dimensions, offset=(0, 0, 0)):
    rotation = Rotation.from_quat(quaternion)
    half = np.asarray(dimensions, dtype=float) / 2
    position = np.asarray(position) + rotation.apply(offset)
    corners = np.array(
        [
            [half[0], half[1], 0],
            [half[0], -half[1], 0],
            [-half[0], -half[1], 0],
            [-half[0], half[1], 0],
        ]
    )
    z = (rotation.apply(list(product(*[[-x, x] for x in half]))) + position)[:, 2]
    return (
        Polygon((rotation.apply(corners) + position)[:, :2]),
        (z.min(), z.max()),
        position,
    )


def nearest_segment(points, point):
    p = np.asarray(points, dtype=float)
    if len(p) < 2:
        return None
    delta = p[1:, :2] - p[:-1, :2]
    length2 = (delta * delta).sum(axis=1)
    u = np.clip(
        ((point[:2] - p[:-1, :2]) * delta).sum(axis=1) / np.maximum(length2, 1e-12),
        0,
        1,
    )
    projected = p[:-1] + u[:, None] * (p[1:] - p[:-1])
    distances = np.linalg.norm(projected[:, :2] - point[:2], axis=1)
    distances[length2 < 1e-12] = np.inf
    i = int(np.argmin(distances))
    if not np.isfinite(distances[i]):
        return None
    return projected[i], delta[i] / np.sqrt(length2[i])


class GeometryChecker:
    def __init__(self, lanes, road_edges, actor_filter=True):
        self.actor_filter = actor_filter
        self.lanes = []
        for lane in lanes:
            left, right = lane["left_edge_world"], lane["right_edge_world"]
            if len(left) < 2 or len(right) < 2:
                continue
            poly = Polygon(
                np.concatenate([np.asarray(left)[:, :2], np.asarray(right)[::-1, :2]])
            )
            if poly.is_valid and poly.area > 0:
                self.lanes.append((lane, poly))
        self.edges = []
        for edge in road_edges:
            points = np.asarray(edge["points_world"], dtype=float)
            # Segment-wise height checking avoids false contacts with overpasses.
            for a, b in zip(points, points[1:]):
                if np.linalg.norm(b[:2] - a[:2]) > 1e-6:
                    self.edges.append(
                        (str(edge["id"]), np.array([a, b]), LineString([a[:2], b[:2]]))
                    )

    def check(self, ego, actors):
        body, z, center = box_geometry(
            ego["position_world_m"],
            ego["quaternion_xyzw"],
            ego["dimensions_m"],
            ego["box_center_rig_m"],
        )
        issues = []
        retained, audit = filter_actors(actors, self.actor_filter)
        for actor in retained:
            other, oz, _ = box_geometry(
                actor["position_world_m"],
                actor["quaternion_xyzw"],
                actor["dimensions_m"],
            )
            overlap = min(z[1], oz[1]) - max(z[0], oz[0])
            if overlap > 0.2 and body.intersection(other).area > 0.02:
                issues.append(
                    {
                        "type": "collision",
                        "actor_id": str(actor["id"]),
                        "overlap_area_m2": body.intersection(other).area,
                    }
                )
        edge_ids = set()
        # Road geometry is at the road surface, compare to the bottom of the body.
        surface_z = float(z[0])
        for key, points, line in self.edges:
            if body.intersection(line).length > 0.1:
                projected, _ = nearest_segment(points, center)
                if abs(projected[2] - surface_z) < 1.5:
                    edge_ids.add(key)
        if edge_ids:
            issues.append({"type": "road_edge_overlap", "edge_ids": sorted(edge_ids)})
        containing = []
        for lane, poly in self.lanes:
            segment = nearest_segment(lane["center_world"], center)
            if (
                segment is not None
                and abs(segment[0][2] - surface_z) < 1.5
                and poly.covers(Point(center[:2]))
            ):
                containing.append((lane, segment[1]))
        velocity = Rotation.from_quat(ego["quaternion_xyzw"]).apply(
            ego["velocity_rig_mps"]
        )[:2]
        speed = float(np.linalg.norm(velocity))
        if (
            containing
            and speed > 1
            and all(
                float(np.dot(direction, velocity / speed)) < -0.5
                for _, direction in containing
            )
        ):
            issues.append(
                {"type": "wrong_way", "lane_ids": [str(l["id"]) for l, _ in containing]}
            )
        if containing and all(
            "SHOULDER_LANE" in (l.get("source_attributes", {}).get("use_types") or [])
            for l, _ in containing
        ):
            issues.append(
                {
                    "type": "shoulder_lane",
                    "lane_ids": [str(l["id"]) for l, _ in containing],
                }
            )
        return {
            "issues": issues,
            "lane_ids": sorted(str(l["id"]) for l, _ in containing),
            "actor_count_raw": len(actors),
            "actor_count_checked": len(retained),
            "suppressed_actor_ids": [r["id"] for r in audit["removed"]],
            "lane_membership_known": bool(containing),
            "speed_mps": speed,
            "position_world_m": list(map(float, ego["position_world_m"])),
        }


class SafetyMonitor:
    sample_interval_us = 50_000

    def __init__(self, adapter, steps, dt_s):
        self.adapter, self.steps = adapter, steps
        self.dt_us = round(dt_s * 1e6)
        self.first_policy_us = (
            int(adapter.artifact.rig.trajectory.timestamps_us[0]) + self.dt_us
        )
        self.checker = GeometryChecker(
            adapter.lanes, adapter.road_edges, adapter.config.actor_overlap_filter
        )
        self.failure = None
        self.last_safe_us = self.first_policy_us
        self.samples = 0
        self.lane_unknown_samples = 0
        self.distance_m = 0.0
        self.stopped_samples = 0
        self.previous_position = None
        self.visited_lane_ids = set()
        self.logger = None

    def inspect(self, snapshot, *, initial=False):
        result = self.checker.check(snapshot.ego, snapshot.actors)
        result.update(
            event="safety_sample", timestamp_us=snapshot.timestamp_us, initial=initial
        )
        if self.logger:
            self.logger.write(result)
        if result["issues"]:
            index = max(
                0, (snapshot.timestamp_us - self.first_policy_us - 1) // self.dt_us
            )
            self.failure = {
                **result,
                "event": "safety_failure",
                "decision_index": index,
            }
            if self.logger:
                self.logger.write(self.failure)
            raise SafetyViolation(", ".join(i["type"] for i in result["issues"]))
        self.samples += 1
        self.lane_unknown_samples += not result["lane_membership_known"]
        self.stopped_samples += result["speed_mps"] < 0.1
        position = np.asarray(snapshot.ego["position_world_m"])
        if self.previous_position is not None:
            self.distance_m += float(np.linalg.norm(position - self.previous_position))
        self.previous_position = position
        self.visited_lane_ids.update(result["lane_ids"])
        self.last_safe_us = max(self.last_safe_us, snapshot.timestamp_us)

    async def on_message(self, message):
        if message.WhichOneof("log_entry") != "controller_return":
            return
        from alpasim_utils.geometry import pose_from_grpc

        for state in sorted(
            message.controller_return.states, key=lambda s: s.timestamp_us
        ):
            ts = int(state.timestamp_us)
            if ts <= self.first_policy_us or ts <= self.last_safe_us:
                continue
            d = state.dynamic_state
            dynamics = [
                v
                for vector in [
                    d.linear_velocity,
                    d.angular_velocity,
                    d.linear_acceleration,
                    d.angular_acceleration,
                ]
                for v in [vector.x, vector.y, vector.z]
            ]
            snapshot = self.adapter.snapshot(
                "safety-evaluation",
                ts,
                0,
                ego_pose=pose_from_grpc(state.pose_local_to_rig),
                dynamics=dynamics,
            )
            self.inspect(snapshot)

    def report(self):
        safe_steps = min(
            self.steps, max(0, (self.last_safe_us - self.first_policy_us) // self.dt_us)
        )
        return {
            "safe_steps": safe_steps,
            "safe_time_coverage": safe_steps / self.steps,
            "failure": self.failure,
            "sample_count": self.samples,
            "requested_sample_interval_us": self.sample_interval_us,
            "safe_distance_m": self.distance_m,
            "stationary_sample_fraction": self.stopped_samples / max(1, self.samples),
            "visited_lane_ids": sorted(self.visited_lane_ids),
            "unknown_lane_samples": self.lane_unknown_samples,
            "checks": [
                "collision_filtered_full_scene_actors",
                "source_road_edge_overlap",
                "wrong_way",
                "shoulder_lane",
            ],
            "unassessed": [
                "traffic_light_rules",
                "stop_sign_rules",
                "posted_speed_limits",
                "solid_marking_crossing",
                "off_road_without_observed_road_edge_contact",
                "continuous_between_sample_contacts",
            ],
            "collision_area_threshold_m2": 0.02,
            "vertical_overlap_threshold_m": 0.2,
            "road_edge_overlap_threshold_m": 0.1,
            "map_height_tolerance_m": 1.5,
            "source_road_edges_available": bool(self.checker.edges),
        }

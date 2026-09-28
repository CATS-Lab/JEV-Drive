"""AlpaSim data access only; state builders are simulator-independent."""

from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile
import numpy as np
from scipy.spatial.transform import Rotation
from ..state.snapshot import SceneSnapshot


def pose_dict(pose):
    return {
        "position_world_m": np.asarray(pose.vec3).tolist(),
        "quaternion_xyzw": np.asarray(pose.quat).tolist(),
    }


def map_records(vector_map):
    from trajdata.maps.vec_map_elements import MapElementType

    if vector_map is None:
        raise ValueError("JEV requires a vector map")
    lanes, signs, lines = [], [], []
    sign_lanes, line_lanes = {}, {}
    for lane in vector_map.lanes:
        lane_id = str(lane.id)
        lanes.append(
            {
                "id": lane_id,
                "center_world": lane.center.xyz.tolist(),
                "left_edge_world": (
                    lane.left_edge.xyz.tolist() if lane.left_edge is not None else []
                ),
                "right_edge_world": (
                    lane.right_edge.xyz.tolist() if lane.right_edge is not None else []
                ),
                "left_neighbors": sorted(lane.adj_lanes_left),
                "right_neighbors": sorted(lane.adj_lanes_right),
                "successors": sorted(lane.next_lanes),
            }
        )
        for sign in lane.traffic_sign_ids or []:
            sign_lanes.setdefault(str(sign), []).append(lane_id)
        for line in lane.wait_line_ids or []:
            line_lanes.setdefault(str(line), []).append(lane_id)
    for sign in vector_map.elements.get(MapElementType.TRAFFIC_SIGN, {}).values():
        category = (
            sign.sign_type.decode()
            if isinstance(sign.sign_type, bytes)
            else str(sign.sign_type)
        )
        signs.append(
            {
                "id": str(sign.id),
                "position_world_m": np.asarray(sign.position).tolist(),
                "source_category": category,
                "lane_ids": sign_lanes.get(str(sign.id), []),
            }
        )
    for line in vector_map.elements.get(MapElementType.WAIT_LINE, {}).values():
        category = (
            line.wait_line_type.decode()
            if isinstance(line.wait_line_type, bytes)
            else str(line.wait_line_type)
        )
        lines.append(
            {
                "id": str(line.id),
                "points_world": line.polyline.xyz.tolist(),
                "source_category": category,
                "is_implicit": bool(line.is_implicit),
                "lane_ids": line_lanes.get(str(line.id), []),
            }
        )
    return lanes, {
        "signals": [],
        "stop_lines": lines,
        "signs": signs,
        "availability": {
            "signal_geometry": "unavailable",
            "signal_phases": "unavailable",
            "stop_lines": "available",
            "signs": "available",
        },
    }


def artifact_signals(path):
    """Read geometry in the same clipgt/map_data coordinates used by VectorMap.

    This does not infer phase or lane applicability from geometry. Lane links
    are read only from explicit LIGHT_TO_LANE source associations. Raw signal
    category and quaternion are preserved; dynamic phases need a separate source.
    """
    import pyarrow.parquet as pq

    with ZipFile(path) as z:
        for directory in ("map_data", "clipgt", "fastmap"):
            filename = directory + "/traffic_light.parquet"
            if filename not in z.namelist():
                continue
            rows = pq.read_table(BytesIO(z.read(filename))).to_pylist()
            records = {}
            for row in rows:
                light = row["traffic_light"]
                center = light["center"]
                quat = light["orientation"]
                key = str(row["key"]["map_id"])
                records[key] = {
                    "id": key,
                    "position_world_m": [center[c] for c in "xyz"],
                    "quaternion_xyzw": [quat[c] for c in "xyzw"],
                    "category": light["category"],
                    "lane_ids": [],
                    "phase_history": [],
                }
            association_file = directory + "/association.parquet"
            if association_file in z.namelist():
                associations = pq.read_table(
                    BytesIO(z.read(association_file))
                ).to_pylist()
                for association in associations:
                    if association["key"]["kind"] != "LIGHT_TO_LANE":
                        continue
                    links = association["association"]
                    for signal_id in links["subjects"]:
                        if str(signal_id) in records:
                            records[str(signal_id)]["lane_ids"] = sorted(
                                set(
                                    records[str(signal_id)]["lane_ids"]
                                    + [str(x) for x in links["objects"]]
                                )
                            )
            return list(records.values()), "available"
    return [], "unavailable"


def actor_records(traffic_objects, timestamp_us):
    records = []
    for actor_id, obj in traffic_objects.items():
        trajectory = obj.trajectory
        tr = trajectory.time_range_us
        if timestamp_us not in tr:
            continue
        pose = trajectory.interpolate_pose(timestamp_us)
        past_ts = max(tr.start, timestamp_us - 100000)
        velocity = None
        if past_ts < timestamp_us:
            past = trajectory.interpolate_pose(past_ts)
            velocity = (
                (np.asarray(pose.vec3) - np.asarray(past.vec3))
                / ((timestamp_us - past_ts) * 1e-6)
            ).tolist()
        records.append(
            {
                "id": str(actor_id),
                "source_type": obj.label_class,
                **pose_dict(pose),
                "dimensions_m": [obj.aabb.x, obj.aabb.y, obj.aabb.z],
                "velocity_world_mps": velocity,
                "velocity_source": (
                    "past_position_difference"
                    if velocity is not None
                    else "unavailable"
                ),
            }
        )
    return records


class AlpasimAdapter:
    def __init__(self, artifact_path, config, signal_annotations=None):
        from alpasim_utils.artifact import Artifact

        self.config = config
        self.artifact = Artifact(str(artifact_path), _smooth_trajectories=False)
        self.lanes, self.controls = map_records(self.artifact.map)
        self.road_edges = [
            {"id": str(edge.id), "points_world": edge.polyline.xyz.tolist()}
            for edge in self.artifact.map.road_edges
        ]
        signals, available = artifact_signals(artifact_path)
        self.controls["signals"] = signals
        self.controls["availability"]["signal_geometry"] = available
        if signal_annotations:
            doc = json.loads(Path(signal_annotations).read_text())
            if doc["scene_id"] != self.artifact.scene_id:
                raise ValueError("signal annotation scene mismatch")
            known = {s["id"]: s for s in signals}
            for sid, history in doc["signals"].items():
                if sid not in known:
                    raise ValueError("unknown annotated signal ID")
                for item in history:
                    if item["phase"] not in {
                        "red",
                        "yellow",
                        "green",
                        "unknown",
                    } or not isinstance(item["timestamp_us"], int):
                        raise ValueError("invalid signal annotation")
                    item["source"] = doc["source"]
                known[sid]["phase_history"] = history
            self.controls["availability"]["signal_phases"] = "annotated"

    def snapshot(
        self,
        session_id,
        timestamp_us,
        step_index,
        ego_pose=None,
        dynamics=None,
        traffic_objects=None,
        route_world=None,
        vehicle_config=None,
    ):
        from alpasim_utils.scenario import VehicleConfig

        rig = self.artifact.rig
        if ego_pose is None:
            ego_pose = rig.trajectory.interpolate_pose(timestamp_us)
        if dynamics is None:
            t0 = max(rig.trajectory.time_range_us.start, timestamp_us - 100000)
            if t0 == timestamp_us:
                raise ValueError("need past ego sample to estimate dynamics")
            past = rig.trajectory.interpolate_pose(t0)
            dt = (timestamp_us - t0) * 1e-6
            vel_world = (np.asarray(ego_pose.vec3) - np.asarray(past.vec3)) / dt
            vel_rig = Rotation.from_quat(ego_pose.quat).inv().apply(vel_world)
            yaw_delta = np.arctan2(
                np.sin(ego_pose.yaw() - past.yaw()), np.cos(ego_pose.yaw() - past.yaw())
            )
            dynamics = np.r_[
                vel_rig, [0.0, 0.0, yaw_delta / dt], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            ]
            dynamics_source = "backward_difference; initial_acceleration_assumed_zero"
        else:
            dynamics_source = "alpasim_controller_state"
        v = vehicle_config or rig.vehicle_config or VehicleConfig()
        ego = {
            **pose_dict(ego_pose),
            "velocity_rig_mps": np.asarray(dynamics[:3]).tolist(),
            "angular_velocity_rig_radps": np.asarray(dynamics[3:6]).tolist(),
            "acceleration_rig_mps2": np.asarray(dynamics[6:9]).tolist(),
            "dimensions_m": [v.aabb_x_m, v.aabb_y_m, v.aabb_z_m],
            "box_center_rig_m": [
                v.aabb_x_offset_m + v.aabb_x_m / 2,
                v.aabb_y_offset_m,
                v.aabb_z_offset_m + v.aabb_z_m / 2,
            ],
        }
        # Only a destination is needed; never read intermediate recorded route points.
        goal = self.config.navigation_destination_world_m
        goal_source = "configured_destination"
        if goal is None:
            goal = rig.trajectory.positions[-1].tolist()
            goal_source = "recorded_trip_endpoint_only"
        return SceneSnapshot(
            session_id,
            self.artifact.scene_id,
            int(timestamp_us),
            step_index,
            self.config.decision_dt_s,
            ego,
            self.lanes,
            actor_records(
                (
                    self.artifact.traffic_objects
                    if traffic_objects is None
                    else traffic_objects
                ),
                timestamp_us,
            ),
            [],
            self.controls,
            {
                "map": "available",
                "road_edges": "source_map_road_edges",
                "actors": "simulation_ground_truth",
                "ego": dynamics_source,
                "route": "map_topology",
                "navigation_goal": goal_source,
                "signal_source": "artifact_geometry_and_optional_annotations",
                "source_artifact": str(self.artifact.source),
            },
            navigation_goal_world_m=list(goal),
            road_edges=self.road_edges,
        )

    def from_runtime(self, state, event):
        ts = int(event.timestamp_us)
        if int(state.ego_trajectory.timestamps_us[-1]) != ts:
            raise ValueError("ego timestamp mismatch")
        true = state.ego_trajectory.last_pose
        estimated = state.ego_trajectory_estimate.last_pose
        if not np.allclose(true.as_se3(), estimated.as_se3(), atol=1e-4):
            raise ValueError("v1 requires ego noise disabled")
        dt = event.interval_us * 1e-6
        if abs(dt - self.config.decision_dt_s) > 1e-9:
            raise ValueError("decision interval mismatch")
        dynamics = state.ego_trajectory.interpolate_dynamics(
            np.array([ts], dtype=np.uint64)
        )[0]
        # AlpaSim force-GT propagation uses empty DynamicState messages. At the
        # first policy step after warmup, recover motion from actual past poses.
        estimated_after_warmup = ts <= state.unbound.closed_loop_start_us
        if estimated_after_warmup:
            history = state.ego_trajectory.trajectory()
            past_ts = max(int(history.timestamps_us[0]), ts - event.interval_us)
            if past_ts >= ts:
                raise ValueError("missing ego motion history after warmup")
            past = history.interpolate_pose(past_ts)
            elapsed = (ts - past_ts) * 1e-6
            velocity = (
                Rotation.from_quat(true.quat)
                .inv()
                .apply((np.asarray(true.vec3) - np.asarray(past.vec3)) / elapsed)
            )
            yaw = (
                np.arctan2(
                    np.sin(true.yaw() - past.yaw()), np.cos(true.yaw() - past.yaw())
                )
                / elapsed
            )
            dynamics = np.r_[
                velocity, [0.0, 0.0, yaw], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            ]
        snapshot = self.snapshot(
            state.unbound.rollout_uuid,
            ts,
            (ts - state.unbound.first_policy_timestamp_us) // event.interval_us,
            ego_pose=true,
            dynamics=dynamics,
            traffic_objects=state.traffic_objs,
            vehicle_config=state.unbound.vehicle_config,
        )
        if estimated_after_warmup:
            snapshot.provenance["ego"] = (
                "runtime_pose_history_after_force_gt; acceleration_assumed_zero"
            )
        return snapshot

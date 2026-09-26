"""CPU harness: real AlpaSim MPC/dynamics, recorded actors, no renderer.

This complements (does not impersonate) the full AlpaSim RuntimeService path.
"""

import json
import uuid
from pathlib import Path
import numpy as np
from alpasim_grpc.v0 import common_pb2 as common, controller_pb2 as ctrl
from alpasim_utils.geometry import (
    pose_to_grpc,
    pose_from_grpc,
    dynamic_state_to_array,
    array_to_dynamic_states,
)
from alpasim_controller.system import create_system
from alpasim_controller.mpc_controller import ControllerConfig
from ..logging.decision_log import DecisionLog
from ..policy.jev_model import JevModel
from ..state.state_builder import JevStateBuilder
from .alpasim_adapter import AlpasimAdapter
from .driver_service import trajectory_proto


async def run(
    artifact, config, client, output, steps=10, start_offset_s=1.0, annotations=None
):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "decisions.jsonl").exists():
        raise ValueError("use a new output directory")
    adapter = AlpasimAdapter(artifact, config, annotations)
    sid = str(uuid.uuid4())
    t = adapter.artifact.rig.trajectory.time_range_us.start + round(
        start_offset_s * 1e6
    )
    if (
        t + steps * round(config.decision_dt_s * 1e6)
        >= adapter.artifact.rig.trajectory.time_range_us.stop
    ):
        raise ValueError("run extends past scene")
    initial = adapter.snapshot(sid, t, 0)
    dyn = np.r_[
        initial.ego["velocity_rig_mps"],
        initial.ego["angular_velocity_rig_radps"],
        initial.ego["acceleration_rig_mps2"],
        [0.0, 0.0, 0.0],
    ]
    pose = adapter.artifact.rig.trajectory.interpolate_pose(t)
    current = common.StateAtTime(
        timestamp_us=t,
        pose=pose_to_grpc(pose),
        state=array_to_dynamic_states(dyn[None, :])[0],
    )
    system = create_system(str(output / "controller.csv"), current, ControllerConfig())
    logger = DecisionLog(output)
    model = JevModel(config, client, logger)
    model.start(sid)
    report = {
        "harness": "local_alpasim_mpc",
        "actor_mode": "recorded_replay",
        "renderer": False,
        "session_id": sid,
        "scene_id": adapter.artifact.scene_id,
        "requested_steps": steps,
        "completed_steps": 0,
        "success": False,
    }
    (output / "initial_snapshot.json").write_text(
        json.dumps(initial.as_dict(), allow_nan=False)
    )
    try:
        for step in range(steps):
            snapshot = adapter.snapshot(
                sid,
                int(current.timestamp_us),
                step,
                ego_pose=pose_from_grpc(current.pose),
                dynamics=dynamic_state_to_array(current.state),
            )
            envelope = JevStateBuilder(config).build(snapshot)
            prediction = await model.predict(envelope)
            request = ctrl.RunControllerAndVehicleModelRequest(
                session_uuid=sid,
                state=current,
                planned_trajectory_in_rig=trajectory_proto(
                    prediction["trajectory"], current.timestamp_us
                ),
                future_time_us=current.timestamp_us + round(config.decision_dt_s * 1e6),
                coerce_dynamic_state=False,
            )
            response = system.run_controller_and_vehicle_model(request)
            last = response.states[-1]
            current = common.StateAtTime(
                timestamp_us=last.timestamp_us,
                pose=last.pose_local_to_rig,
                state=last.dynamic_state,
            )
            logger.write(
                {
                    "event": "outcome",
                    "session_id": sid,
                    "step_index": step,
                    "decision_timestamp_us": snapshot.timestamp_us,
                    "timestamp_us": int(current.timestamp_us),
                    "position_world_m": [
                        current.pose.vec.x,
                        current.pose.vec.y,
                        current.pose.vec.z,
                    ],
                    "speed_mps": current.state.linear_velocity.x,
                    "acceleration_mps2": current.state.linear_acceleration.x,
                    "yaw_rate_radps": current.state.angular_velocity.z,
                }
            )
            report["completed_steps"] += 1
        report["success"] = True
    except Exception as e:
        report["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        (output / "summary.json").write_text(json.dumps(report, indent=2))
        system._log_file_handle.close()
        model.close(sid)
    return report

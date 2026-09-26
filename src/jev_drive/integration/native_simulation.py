"""Native AlpaSim event loop with local driver/controller RPCs and recorded traffic.

Rendering and ground-contact correction are explicitly disabled for structured
state experiments. This runs PolicyEvent -> driver -> MPC -> StepEvent.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import uuid
import grpc
from alpasim_controller.server import VDCSimService
from alpasim_controller.mpc_controller import ControllerConfig
from alpasim_grpc.v0 import controller_pb2_grpc, egodriver_pb2_grpc, logging_pb2
from alpasim_runtime.camera_catalog import CameraCatalog
from alpasim_runtime.config import SimulationConfig, RouteGeneratorType
from alpasim_runtime.event_loop import EventBasedRollout
from alpasim_runtime.services.driver_service import DriverService
from alpasim_runtime.services.controller_service import ControllerService
from alpasim_runtime.services.physics_service import PhysicsService
from alpasim_runtime.services.sensorsim_service import SensorsimService
from alpasim_runtime.services.traffic_service import TrafficService
from alpasim_runtime.unbound_rollout import UnboundRollout
from alpasim_utils.artifact import Artifact
from eval.schema import EvalConfig
from ..logging.decision_log import DecisionLog
from ..policy.jev_model import JevModel
from .driver_service import JevDriverServicer


class OutcomeLogger:
    def __init__(self, logger, sid):
        self.logger = logger
        self.sid = sid

    async def on_message(self, message):
        if message.WhichOneof("log_entry") == "controller_return":
            for state in message.controller_return.states:
                self.logger.write(
                    {
                        "event": "outcome",
                        "session_id": self.sid,
                        "timestamp_us": int(state.timestamp_us),
                        "position_world_m": [
                            state.pose_local_to_rig.vec.x,
                            state.pose_local_to_rig.vec.y,
                            state.pose_local_to_rig.vec.z,
                        ],
                        "speed_mps": state.dynamic_state.linear_velocity.x,
                        "acceleration_mps2": state.dynamic_state.linear_acceleration.x,
                        "yaw_rate_radps": state.dynamic_state.angular_velocity.z,
                    }
                )


async def run(artifact, config, client, output, steps=5, annotations=None):
    # The explicit hook is required; fail before making decisions if the wrong
    # checkout is imported. This launcher never patches installed modules.
    from alpasim_runtime.events import policy

    if "JEV_DRIVE_ENABLED" not in Path(policy.__file__).read_text():
        raise RuntimeError(
            "Use scripts/jev-drive with the patched isolated AlpaSim worktree"
        )
    if steps < 1:
        raise ValueError("steps must be positive")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "decisions.jsonl").exists():
        raise ValueError("use a new output directory")
    config_path = output / "jev-config.json"
    config_path.write_text(json.dumps(config.as_dict(), indent=2))
    artifact = Path(artifact).resolve()
    data = Artifact(str(artifact), _smooth_trajectories=False)
    manifest_path = output / "scene-manifest.json"
    manifest_path.write_text(json.dumps({data.scene_id: str(artifact)}))
    env_values = {
        "JEV_DRIVE_ENABLED": "1",
        "JEV_CONFIG": str(config_path),
        "JEV_SCENE_MANIFEST": str(manifest_path),
        "JEV_SIGNAL_ANNOTATIONS": (
            str(Path(annotations).resolve()) if annotations else ""
        ),
    }
    old_env = {k: os.environ.get(k) for k in env_values}
    os.environ.update(env_values)
    logger = DecisionLog(output, total_steps=steps)
    model = JevModel(config, client, logger)
    driver_server = grpc.aio.server()
    egodriver_pb2_grpc.add_EgodriverServiceServicer_to_server(
        JevDriverServicer(model), driver_server
    )
    driver_port = driver_server.add_insecure_port("127.0.0.1:0")
    pool = ThreadPoolExecutor(max_workers=1)
    controller_server = grpc.server(pool)
    controller_dir = output / "controller"
    controller_dir.mkdir(exist_ok=True)
    controller_pb2_grpc.add_VDCServiceServicer_to_server(
        VDCSimService(str(controller_dir), ControllerConfig()), controller_server
    )
    controller_port = controller_server.add_insecure_port("127.0.0.1:0")
    controller_server.start()
    await driver_server.start()
    sid = str(uuid.uuid4())
    summary = {
        "harness": "native_alpasim_event_loop",
        "session_id": sid,
        "scene_id": data.scene_id,
        "requested_steps": steps,
        "success": False,
        "renderer": False,
        "ground_contact": False,
        "actor_mode": "recorded_replay",
        "policy_source": getattr(client, "source_label", "jev_api"),
    }
    try:
        catalog = CameraCatalog(None)
        renderer = SensorsimService("", True, catalog)
        sim_config = SimulationConfig(
            n_sim_steps=steps + 1,
            n_rollouts=1,
            min_traffic_duration_us=0,
            cameras=[],
            control_timestep_us=round(config.decision_dt_s * 1e6),
            force_gt_duration_us=round(config.decision_dt_s * 1e6),
            skip_driver_during_force_gt=True,
            route_generator_type=RouteGeneratorType.RECORDED,
        )
        unbound = UnboundRollout.create(
            sim_config,
            data.scene_id,
            logging_pb2.RolloutMetadata.VersionIds(),
            data,
            str(output / "rollouts"),
            renderer,
            session_uuid=sid,
        )
        rollout = EventBasedRollout(
            unbound,
            data,
            DriverService(f"127.0.0.1:{driver_port}"),
            renderer,
            PhysicsService("", True),
            TrafficService("", True),
            ControllerService(f"127.0.0.1:{controller_port}"),
            catalog,
            EvalConfig(enabled=False),
            None,
        )
        rollout.broadcaster.handlers.append(OutcomeLogger(logger, sid))
        print(
            f"Running {steps} JEV decisions ({steps * config.decision_dt_s:.1f}s closed loop).",
            flush=True,
        )
        await rollout.run()
        completed = sum(
            json.loads(line).get("event") == "decision"
            for line in logger.path.read_text().splitlines()
        )
        if completed != steps:
            raise RuntimeError(
                f"rollout ended after {completed} decisions; expected {steps}"
            )
        summary["success"] = True
    except Exception as e:
        summary["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        records = logger.path.read_text().splitlines() if logger.path.exists() else []
        summary["completed_decisions"] = sum(
            json.loads(line).get("event") == "decision" for line in records
        )
        (output / "summary.json").write_text(json.dumps(summary, indent=2))
        await driver_server.stop(0)
        controller_server.stop(0).wait()
        pool.shutdown(wait=True)
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return summary

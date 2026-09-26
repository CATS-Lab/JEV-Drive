from pathlib import Path
import os
import pytest
import grpc
pytest.importorskip("alpasim_grpc")
pytest.importorskip("alpasim_utils")
pytest.importorskip("alpasim_controller")
pytest.importorskip("alpasim_runtime")

from alpasim_grpc.v0 import (
    common_pb2 as common,
    egodriver_pb2 as driver,
    egodriver_pb2_grpc as service,
)
from alpasim_utils.geometry import Pose, pose_to_grpc
from jev_drive.integration.driver_service import JevDriverServicer
from jev_drive.integration.local_simulation import run
from jev_drive.policy.jev_model import JevModel
from jev_drive.logging.decision_log import DecisionLog
from jev_drive.state.state_builder import JevStateBuilder
from jev_drive.state.schema import encode
from jev_drive.config import Config
from test_core import snapshot, FixedClient


def scene_artifact():
    artifact = os.environ.get("JEV_TEST_ARTIFACT")
    if not artifact or not Path(artifact).is_file():
        pytest.skip("Set JEV_TEST_ARTIFACT to a compatible local 20-second USDZ scene")
    return artifact


@pytest.mark.asyncio
async def test_real_grpc_roundtrip_and_failure_status(tmp_path):
    model = JevModel(Config(), FixedClient(), DecisionLog(tmp_path))
    server = grpc.aio.server()
    service.add_EgodriverServiceServicer_to_server(JevDriverServicer(model), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = service.EgodriverServiceStub(channel)
            await stub.start_session(driver.DriveSessionRequest(session_uuid="session"))
            trajectory = common.Trajectory(
                poses=[
                    common.PoseAtTime(
                        timestamp_us=1000000, pose=pose_to_grpc(Pose.identity())
                    )
                ]
            )
            await stub.submit_egomotion_observation(
                driver.RolloutEgoTrajectory(
                    session_uuid="session", trajectory=trajectory
                )
            )
            e = JevStateBuilder(Config()).build(snapshot())
            req = driver.DriveRequest(
                session_uuid="session",
                time_now_us=1000000,
                time_query_us=1200000,
                renderer_data=encode(e),
            )
            response = await stub.drive(req)
            assert len(response.trajectory.poses) == 41
            assert response.trajectory.poses[0].timestamp_us == 1000000
            assert response.trajectory.poses[-1].pose.vec.x == pytest.approx(40.0)
            req.renderer_data = b"bad-json"
            with pytest.raises(grpc.aio.AioRpcError) as error:
                await stub.drive(req)
            assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    finally:
        await server.stop(0)


@pytest.mark.asyncio
async def test_local_real_mpc_closed_loop(tmp_path):
    scene = scene_artifact()
    result = await run(scene, Config(), FixedClient(), tmp_path, steps=3)
    assert result["success"] and result["completed_steps"] == 3
    assert (tmp_path / "controller.csv").stat().st_size > 0


@pytest.mark.asyncio
async def test_native_runtime_loop_and_api_failure(tmp_path):
    import json
    from alpasim_runtime.events import policy

    if "JEV_DRIVE_ENABLED" not in Path(policy.__file__).read_text():
        pytest.skip("run tests with isolated runtime on PYTHONPATH")
    from jev_drive.integration.native_simulation import run as native_run

    artifact = scene_artifact()
    client = FixedClient()
    client.source_label = "explicit_fixed_test_double"
    result = await native_run(artifact, Config(), client, tmp_path / "success", steps=2)
    assert result["success"] and result["completed_decisions"] == 2
    decisions = [
        json.loads(line)
        for line in (tmp_path / "success/decisions.jsonl").read_text().splitlines()
        if json.loads(line)["event"] == "decision"
    ]
    assert decisions[0]["state"]["ego"]["speed_mps"] > 1
    assert decisions[0]["control"]["target_speed"] > 1
    assert len(decisions[0]["state"]["actors"]) > 0

    class Broken:
        source_label = "injected_API_failure"

        async def decide(self, *args):
            raise RuntimeError("injected API failure")

    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await native_run(artifact, Config(), Broken(), tmp_path / "failure", steps=2)
    assert exc.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    failed = json.loads((tmp_path / "failure/summary.json").read_text())
    assert not failed["success"] and failed["completed_decisions"] == 0
    assert not list((tmp_path / "failure").rglob("_complete"))


@pytest.mark.asyncio
async def test_full_scene_reaches_recording_end_without_paid_calls(tmp_path):
    import json
    from alpasim_runtime.events import policy
    from alpasim_utils.artifact import Artifact
    from jev_drive.integration.native_simulation import run as native_run

    if "JEV_DRIVE_ENABLED" not in Path(policy.__file__).read_text():
        pytest.skip("run with the isolated runtime")
    artifact = scene_artifact()
    client = FixedClient()
    client.source_label = "explicit_fixed_test_double"
    result = await native_run(artifact, Config(), client, tmp_path, steps=99)
    rows = [
        json.loads(line)
        for line in (tmp_path / "decisions.jsonl").read_text().splitlines()
    ]
    decisions = [r for r in rows if r["event"] == "decision"]
    outcomes = [r for r in rows if r["event"] == "outcome"]
    end = (
        Artifact(artifact, _smooth_trajectories=False).rig.trajectory.time_range_us.stop
        - 1
    )
    assert result["success"] and result["completed_decisions"] == 99
    assert client.calls == 99
    assert len({r["timestamp_us"] for r in decisions}) == 99
    assert all(
        b["timestamp_us"] - a["timestamp_us"] == 200000
        for a, b in zip(decisions, decisions[1:])
    )
    assert outcomes[-1]["timestamp_us"] == end

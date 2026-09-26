"""Dedicated headless EgodriverService. RPC failures remain failed rollouts."""

import asyncio
import grpc
import numpy as np
from scipy.spatial.transform import Rotation
from alpasim_grpc import API_VERSION_MESSAGE
from alpasim_grpc.v0 import (
    common_pb2 as common,
    egodriver_pb2 as driver,
    egodriver_pb2_grpc as service,
)
from alpasim_utils.geometry import Pose, pose_from_grpc, pose_to_grpc
from ..state.schema import decode


def trajectory_proto(prediction, timestamp_us, world_pose=None):
    output = common.Trajectory()
    output.poses.add(
        timestamp_us=timestamp_us,
        pose=pose_to_grpc(world_pose if world_pose is not None else Pose.identity()),
    )
    for t, xy, heading in zip(
        prediction["times_s"],
        prediction["xy_m"],
        prediction["headings_rad"],
        strict=True,
    ):
        local = Pose(
            position=np.array([xy[0], xy[1], 0.0], dtype=np.float32),
            quaternion=Rotation.from_euler("z", heading).as_quat().astype(np.float32),
        )
        pose = world_pose @ local if world_pose is not None else local
        output.poses.add(
            timestamp_us=timestamp_us + round(t * 1e6), pose=pose_to_grpc(pose)
        )
    return output


class JevDriverServicer(service.EgodriverServiceServicer):
    def __init__(self, model):
        self.model = model
        self.poses = {}
        self.locks = {}

    async def get_version(self, request, context):
        return common.VersionId(
            version_id="jev-drive-0.1.0",
            git_hash="local",
            grpc_api_version=API_VERSION_MESSAGE,
        )

    async def start_session(self, request, context):
        try:
            self.model.start(request.session_uuid)
        except ValueError:
            await context.abort(
                grpc.StatusCode.ALREADY_EXISTS, "session already exists"
            )
        self.locks[request.session_uuid] = asyncio.Lock()
        return common.SessionRequestStatus()

    async def close_session(self, request, context):
        self.model.close(request.session_uuid)
        self.poses.pop(request.session_uuid, None)
        self.locks.pop(request.session_uuid, None)
        return common.Empty()

    async def submit_image_observation(self, request, context):
        return common.Empty()

    async def submit_route(self, request, context):
        return common.Empty()

    async def submit_recording_ground_truth(self, request, context):
        return common.Empty()

    async def submit_egomotion_observation(self, request, context):
        if request.trajectory.poses:
            self.poses[request.session_uuid] = request.trajectory.poses[-1]
        return common.Empty()

    async def drive(self, request, context):
        sid = request.session_uuid
        if sid not in self.locks:
            await context.abort(grpc.StatusCode.NOT_FOUND, "unknown session")
        async with self.locks[sid]:
            try:
                envelope = decode(request.renderer_data, sid, request.time_now_us)
                pose = self.poses[sid]
                if pose.timestamp_us != request.time_now_us:
                    raise ValueError("egomotion timestamp mismatch")
                if request.time_query_us - request.time_now_us != round(
                    envelope["decision_dt_s"] * 1e6
                ):
                    raise ValueError("query interval mismatch")
                prediction = await self.model.predict(envelope)
                return driver.DriveResponse(
                    trajectory=trajectory_proto(
                        prediction["trajectory"],
                        request.time_now_us,
                        pose_from_grpc(pose.pose),
                    )
                )
            except Exception as exc:
                # FAILED_PRECONDITION is not a transient retry status in AlpaSim.
                await context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    f"JEV rollout failed: {type(exc).__name__}: {exc}",
                )


async def serve(model, host, port):
    server = grpc.aio.server(
        options=[("grpc.max_receive_message_length", 64 * 1024 * 1024)]
    )
    service.add_EgodriverServiceServicer_to_server(JevDriverServicer(model), server)
    if not server.add_insecure_port(f"{host}:{port}"):
        raise RuntimeError("unable to bind driver")
    await server.start()
    print(f"JEV driver listening on {host}:{port}", flush=True)
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(0)

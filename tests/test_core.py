from dataclasses import replace
import json
import math
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from jev_drive.config import Config
from jev_drive.state.snapshot import SceneSnapshot
from jev_drive.state.state_builder import JevStateBuilder
from jev_drive.state.schema import encode, decode
from jev_drive.state import actors, traffic_signals
from jev_drive.control.control_state import ControlState
from jev_drive.control.limits import apply
from jev_drive.control.trajectory import generate
from jev_drive.control.choice_control import commands
from jev_drive.logging.decision_log import DecisionLog
from jev_drive.policy.jev_model import JevModel


def snapshot():
    lane = {
        "id": "lane-a",
        "center_world": [[-30.0, 0.0, 0.0], [100.0, 0.0, 0.0]],
        "left_edge_world": [[-30.0, 2.0, 0.0], [100.0, 2.0, 0.0]],
        "right_edge_world": [[-30.0, -2.0, 0.0], [100.0, -2.0, 0.0]],
        "left_neighbors": [],
        "right_neighbors": [],
        "successors": [],
    }
    return SceneSnapshot(
        "session",
        "scene",
        1000000,
        0,
        0.2,
        {
            "position_world_m": [0.0, 0.0, 0.0],
            "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0],
            "velocity_rig_mps": [10.0, 0.0, 0.0],
            "angular_velocity_rig_radps": [0.0, 0.0, 0.0],
            "acceleration_rig_mps2": [0.0, 0.0, 0.0],
            "dimensions_m": [4.7, 2.0, 1.5],
            "box_center_rig_m": [1.3, 0.0, 0.75],
        },
        [lane],
        [],
        [[-30.0, 0.0, 0.0], [100.0, 0.0, 0.0]],
        {
            "signals": [],
            "stop_lines": [],
            "signs": [],
            "availability": {
                "signal_geometry": "unavailable",
                "signal_phases": "unavailable",
                "stop_lines": "available",
                "signs": "available",
            },
        },
        {"map": "available", "route": "test_fixture"},
    )


def score_response(speed=4, steering=4):
    def answer(value):
        return {
            "type": "score",
            "score": float(value),
            "probabilities": {str(i): float(i == value) for i in range(9)},
            "confidence": 1.0,
            "legend": {str(i): str(i) for i in range(9)},
        }

    return {
        "model": "explicit-test-double",
        "answers": {"speed": answer(speed), "steering": answer(steering)},
    }


class FixedClient:
    def __init__(self, response=None):
        self.response = response or score_response()
        self.calls = 0

    async def decide(self, state, questions):
        self.calls += 1
        return self.response


@pytest.mark.parametrize("dt", [0.1, 0.2, 0.5])
def test_rate_bounds_and_actual_delta(dt):
    c = Config()
    state = ControlState(14.9, 0.39)
    result, log = apply(state, 1.0, 1.0, dt, c)
    assert result.target_speed <= 15 and result.steering_angle <= 0.4
    assert log["applied_delta_speed"] <= 3 * dt + 1e-9
    assert log["applied_delta_speed"] == pytest.approx(0.1)
    result, log = apply(ControlState(10.0, 0.0), -1.0, -0.5, dt, c)
    assert result.target_speed == pytest.approx(10.0 - min(1.0, 3 * dt))
    assert abs(log["applied_delta_steering"]) <= 0.8 * dt + 1e-9


def test_constant_curvature_sign_and_heading():
    left = generate(ControlState(5.0, 0.1), Config())
    right = generate(ControlState(5.0, -0.1), Config())
    np.testing.assert_allclose(
        np.array(left["xy_m"])[:, 0], np.array(right["xy_m"])[:, 0]
    )
    np.testing.assert_allclose(
        np.array(left["xy_m"])[:, 1], -np.array(right["xy_m"])[:, 1]
    )
    assert left["headings_rad"][-1] > 0 and right["headings_rad"][-1] < 0
    assert left["times_s"][0] == 0.1 and left["times_s"][-1] == 4.0


def test_choice_executes_selected_action_and_absolute_steering():
    a = {
        "speed": {
            "type": "choice",
            "choice": "accelerate",
            "probabilities": {"accelerate": 0.7, "hold": 0.2, "decelerate": 0.1},
            "confidence": 0.5,
        },
        "steering": {
            "type": "choice",
            "choice": "straight",
            "probabilities": {"left": 0.1, "straight": 0.8, "right": 0.1},
            "confidence": 0.5,
        },
    }
    dv, target = commands(a, Config(mode="choice"))
    assert dv == pytest.approx(1.0) and target == 0
    state, _ = apply(ControlState(5.0, 0.15), dv, target - 0.15, 0.2, Config())
    assert state.steering_angle == 0.0


def test_actor_rotation_relative_velocity_and_lane_association():
    s = snapshot()
    s = replace(
        s,
        ego={
            **s.ego,
            "quaternion_xyzw": Rotation.from_euler("z", math.pi / 2).as_quat().tolist(),
        },
        actors=[
            {
                "id": "actor-stable",
                "source_type": "automobile",
                "position_world_m": [0.0, 10.0, 0.0],
                "quaternion_xyzw": Rotation.from_euler("z", math.pi / 2)
                .as_quat()
                .tolist(),
                "dimensions_m": [4.0, 2.0, 1.0],
                "velocity_world_mps": [0.0, 8.0, 0.0],
            }
        ],
    )
    a = actors.build(s, Config())[0]
    assert a["x_m"] == pytest.approx(10.0) and a["y_m"] == pytest.approx(0.0, abs=1e-6)
    assert a["relative_vx_mps"] == pytest.approx(-2.0) and a[
        "heading_rad"
    ] == pytest.approx(0.0)
    assert a["lane_id"] is None and a["id"] == "actor-stable"


def test_no_future_signal_phase_or_fabricated_green():
    s = snapshot()
    signal = {
        "id": "light",
        "position_world_m": [10.0, 0.0, 3.0],
        "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0],
        "phase_history": [
            {"timestamp_us": 900000, "phase": "red", "source": "fixture"},
            {"timestamp_us": 1100000, "phase": "green", "source": "fixture"},
        ],
    }
    s = replace(s, traffic_controls={**s.traffic_controls, "signals": [signal]})
    assert traffic_signals.build(s, Config())[0]["phase"] == "red"
    assert (
        traffic_signals.build(replace(s, timestamp_us=3000000), Config())[0]["phase"]
        == "unknown"
    )


def test_crop_preserves_topology_reference_provenance():
    s = snapshot()
    s.lanes[0]["successors"] = ["lane-outside", "missing"]
    outside = {
        **s.lanes[0],
        "id": "lane-outside",
        "center_world": [[200.0, 0.0, 0.0], [300.0, 0.0, 0.0]],
        "successors": [],
    }
    s = replace(s, lanes=s.lanes + [outside])
    e = JevStateBuilder(Config()).build(s, b"opaque")
    lane = e["state"]["road"]["lanes"][0]
    assert (
        lane["centerline_segments"][0][0][0] == -20
        and lane["centerline_segments"][0][-1][0] == 80
    )
    assert lane["references_outside_roi"] == ["lane-outside"] and lane[
        "unresolved_references"
    ] == ["missing"]
    assert decode(encode(e), "session", 1000000)["renderer_payload_b64"] == "b3BhcXVl"
    with pytest.raises(ValueError):
        decode(encode(e), "wrong", 1000000)


@pytest.mark.asyncio
async def test_increment_applied_once_and_sessions_isolated(tmp_path):
    c = FixedClient(score_response(8, 8))
    m = JevModel(Config(), c, DecisionLog(tmp_path))
    m.start("session")
    e = JevStateBuilder(Config()).build(snapshot())
    r = await m.predict(e)
    r2 = await m.predict(e)
    assert (
        c.calls == 1 and r == r2 and r["control"]["target_speed"] == pytest.approx(10.6)
    )
    assert r["increments"]["applied_delta_speed"] == pytest.approx(0.6)
    m.start("session-b")
    s = replace(snapshot(), session_id="session-b")
    r3 = await m.predict(JevStateBuilder(Config()).build(s))
    assert r3["control"] == r["control"]


@pytest.mark.asyncio
async def test_api_error_terminates_without_command_fallback(tmp_path):
    class Broken:
        async def decide(self, *_):
            raise RuntimeError("injected failure")

    m = JevModel(Config(), Broken(), DecisionLog(tmp_path))
    m.start("session")
    e = JevStateBuilder(Config()).build(snapshot())
    with pytest.raises(RuntimeError, match="injected"):
        await m.predict(e)
    with pytest.raises(RuntimeError, match="already failed"):
        await m.predict(e)
    assert m.sessions["session"]["control"] is None
    assert json.loads((tmp_path / "decisions.jsonl").read_text())["event"] == "failure"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_score", [float("nan"), float("inf"), -1.0, 9.0, True, "4"]
)
async def test_malformed_score_is_not_neutral_control(tmp_path, invalid_score):
    response = score_response()
    response["answers"]["speed"]["score"] = invalid_score
    m = JevModel(Config(), FixedClient(response), DecisionLog(tmp_path))
    m.start("session")
    with pytest.raises(ValueError):
        await m.predict(JevStateBuilder(Config()).build(snapshot()))
    assert m.sessions["session"]["control"] is None
    failure = json.loads((tmp_path / "decisions.jsonl").read_text())
    assert failure["event"] == "failure" and failure["error_type"] == "ValueError"
    preserved = json.loads(failure["raw_response_json"])["answers"]["speed"]["score"]
    if isinstance(invalid_score, float) and math.isnan(invalid_score):
        assert math.isnan(preserved)
    else:
        assert preserved == invalid_score

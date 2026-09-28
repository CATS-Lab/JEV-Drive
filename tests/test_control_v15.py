from dataclasses import replace
import json
import numpy as np
import pytest
from jev_drive.config import Config
from jev_drive.control.control_state import ControlState
from jev_drive.control.limits import apply
from jev_drive.control.trajectory import generate
from jev_drive.control.score_control import commands, selected_level
from jev_drive.policy.jev_model import JevModel
from jev_drive.logging.decision_log import DecisionLog
from jev_drive.state.state_builder import JevStateBuilder
from test_core import FixedClient, score_response, snapshot


def test_initial_overspeed_preserved_and_steering_uses_actual_speed():
    c = Config()
    state = ControlState.initialize({"speed_mps": 31.23, "yaw_rate_radps": -0.0274}, c)
    assert state.target_speed == 31.23
    assert state.steering_angle == pytest.approx(
        np.arctan(c.wheelbase_m * -0.0274 / 31.23)
    )
    for _ in range(40):
        updated, changes = apply(state, 1, 0, 0.2, c)
        assert -0.6 - 1e-9 <= updated.target_speed - state.target_speed <= 0.6 + 1e-9
        if state.target_speed > 15:
            assert updated.target_speed < state.target_speed
        state = updated
    assert state.target_speed <= 15


@pytest.mark.parametrize(
    "start,target", [(31.23, 30.63), (31.23, 15), (10, 10.6), (10, 0), (0, 0)]
)
def test_reference_speed_ramp_and_integrated_distance(start, target):
    c = Config()
    tr = generate(ControlState(target, 0), c, initial_speed=start)
    v = np.r_[start, tr["speeds_mps"]]
    acc = np.diff(v) * 10
    assert np.min(acc) >= -3 - 1e-9 and np.max(acc) <= 3 + 1e-9
    assert np.all(np.diff(np.r_[0, np.array(tr["xy_m"])[:, 0]]) >= 0)
    if start == 31.23:
        assert tr["xy_m"][0][0] == pytest.approx(31.23 * 0.1 - 0.5 * 3 * 0.1**2)


@pytest.mark.asyncio
async def test_near_neutral_score_unwinds_and_does_not_integrate_bias(tmp_path):
    response = score_response()
    response["answers"]["steering"].update(
        score=3.99,
        probabilities=dict(
            zip(
                map(str, range(9)),
                [0.04, 0.04, 0.07, 0.14, 0.45, 0.11, 0.06, 0.05, 0.04],
            )
        ),
    )
    model = JevModel(Config(), FixedClient(response), DecisionLog(tmp_path))
    model.start("session")
    model.sessions["session"]["control"] = ControlState(10, -0.2)
    for i in range(30):
        snap = replace(snapshot(), timestamp_us=1000000 + i * 200000, step_index=i)
        result = await model.predict(JevStateBuilder(Config()).build(snap))
        assert result["score_diagnostics"]["steering"]["selected_level"] == 4
        assert result["increments"]["requested_steering_target_rad"] == 0
        assert result["control"]["steering_angle"] == pytest.approx(
            -0.04 if i == 0 else 0
        )


@pytest.mark.asyncio
async def test_repeated_direction_targets_do_not_accumulate(tmp_path):
    model = JevModel(Config(), FixedClient(score_response(4, 5)), DecisionLog(tmp_path))
    model.start("session")
    for i in range(20):
        result = await model.predict(
            JevStateBuilder(Config()).build(
                replace(snapshot(), timestamp_us=1000000 + i * 200000, step_index=i)
            )
        )
        assert result["control"]["steering_angle"] == pytest.approx(0.015)


def test_ambiguous_score_is_not_averaged_into_fake_straight():
    answer = score_response()["answers"]["steering"]
    answer["probabilities"] = {str(i): (0.5 if i in [0, 8] else 0) for i in range(9)}
    with pytest.raises(ValueError, match="ambiguous"):
        selected_level(answer)


@pytest.mark.asyncio
async def test_native_high_speed_start_has_no_speed_jump(tmp_path):
    from pathlib import Path
    from alpasim_runtime.events import policy
    from jev_drive.integration.native_simulation import run

    if "JEV_DRIVE_ENABLED" not in Path(policy.__file__).read_text():
        pytest.skip("isolated runtime required")
    artifact = Path(
        "/home/bcao44/bofeng/JEV-Drive/data/scenes/a8757d53-f10e-4117-8da9-3fd36c734a20.usdz"
    )
    if not artifact.exists():
        pytest.skip("local high-speed artifact unavailable")
    result = await run(
        artifact, Config(), FixedClient(score_response(0, 4)), tmp_path, steps=10
    )
    rows = [
        json.loads(l) for l in (tmp_path / "decisions.jsonl").read_text().splitlines()
    ]
    decisions = [r for r in rows if r["event"] == "decision"]
    outcomes = [
        r
        for r in rows
        if r["event"] == "outcome" and r["timestamp_us"] > decisions[0]["timestamp_us"]
    ]
    assert result["success"]
    assert decisions[0]["control_before"]["target_speed"] > 30
    assert decisions[0]["control"]["target_speed"] == pytest.approx(
        decisions[0]["state"]["ego"]["speed_mps"] - 0.6
    )
    assert min(r["acceleration_mps2"] for r in outcomes) > -3.1
    assert outcomes[-1]["speed_mps"] > 24


def test_absolute_steering_levels_keep_fine_resolution_and_full_range():
    from jev_drive.control.score_control import steering_targets

    targets = steering_targets(Config())
    assert targets == pytest.approx(
        [-0.4, -0.15, -0.06, -0.015, 0, 0.015, 0.06, 0.15, 0.4]
    )
    state = ControlState(5, 0)
    for expected in [0.16, 0.32, 0.4, 0.4]:
        dv, target = commands(score_response(4, 8)["answers"], Config())
        state, _ = apply(state, dv, target - state.steering_angle, 0.2, Config())
        assert state.steering_angle == pytest.approx(expected)


def test_overspeed_recovery_does_not_weaken_requested_braking_near_cap():
    result, log = apply(ControlState(15.2, 0), -1, 0, 0.2, Config())
    assert result.target_speed == pytest.approx(14.6)
    assert log["speed_cap_recovery"]

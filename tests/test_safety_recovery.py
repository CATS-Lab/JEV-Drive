import copy
import pytest
from jev_drive.evaluation.safety import GeometryChecker
from jev_drive.evaluation.replay import ReplayClient, ReplayDivergence
from jev_drive.evaluation.retries import RetrySites, metrics


def ego(y=0, vx=5):
    return dict(
        position_world_m=[0, y, 1],
        quaternion_xyzw=[0, 0, 0, 1],
        dimensions_m=[4, 2, 2],
        box_center_rig_m=[0, 0, 0],
        velocity_rig_mps=[vx, 0, 0],
    )


def lane(reverse=False, shoulder=False):
    return dict(
        id="a",
        center_world=[[x, 0, 0] for x in ([10, -10] if reverse else [-10, 10])],
        left_edge_world=[[-10, 2, 0], [10, 2, 0]],
        right_edge_world=[[-10, -2, 0], [10, -2, 0]],
        source_attributes={"use_types": ["SHOULDER_LANE"] if shoulder else []},
    )


def test_road_edge_is_not_lane_divider_and_wrong_way_is_motion():
    checker = GeometryChecker([lane()], [])
    assert not checker.check(ego(y=1.5), [])["issues"]
    checker = GeometryChecker(
        [lane()], [dict(id="road", points_world=[[-10, 2, 0], [10, 2, 0]])]
    )
    assert checker.check(ego(y=1.5), [])["issues"][0]["type"] == "road_edge_overlap"
    assert (
        GeometryChecker([lane(reverse=True)], []).check(ego(), [])["issues"][0]["type"]
        == "wrong_way"
    )
    assert not GeometryChecker([lane(), lane(reverse=True)], []).check(ego(), [])[
        "issues"
    ]
    assert (
        GeometryChecker([lane()], []).check(ego(vx=-5), [])["issues"][0]["type"]
        == "wrong_way"
    )
    assert (
        GeometryChecker([lane(shoulder=True)], []).check(ego(), [])["issues"][0]["type"]
        == "shoulder_lane"
    )


def test_collision_and_overpass_separation():
    actor = dict(
        id="car",
        position_world_m=[1, 0, 1],
        quaternion_xyzw=[0, 0, 0, 1],
        dimensions_m=[4, 2, 2],
        source_type="automobile",
        velocity_world_mps=[5, 0, 0],
    )
    checker = GeometryChecker([], [])
    assert checker.check(ego(), [actor])["issues"][0]["type"] == "collision"
    actor["position_world_m"][2] = 6
    assert not checker.check(ego(), [actor])["issues"]
    checker = GeometryChecker(
        [], [dict(id="bridge", points_world=[[-10, 0, 6], [10, 0, 6]])]
    )
    assert not checker.check(ego(), [])["issues"]


@pytest.mark.asyncio
async def test_replay_checks_before_paid_calls_and_preserves_feedback():
    class Base:
        calls = 0

        async def decide(self, state, questions):
            self.calls += 1
            return {"new": True}

    base = Base()
    row = {
        "state": {"timestamp_us": 1, "ego": {"v": 2}, "retry_context": {"old": True}},
        "raw_response": {"cached": True},
    }
    client = ReplayClient(
        base,
        [row],
        checkpoint={**row, "state": {"timestamp_us": 2, "ego": {"v": 3}}},
        context={"new": True},
    )
    state = {"timestamp_us": 1, "ego": {"v": 2}}
    assert await client.decide(state, []) == {"cached": True}
    assert state["retry_context"] == {"old": True} and base.calls == 0
    with pytest.raises(ReplayDivergence):
        await client.decide({"timestamp_us": 2, "ego": {"v": 30}}, [])
    assert base.calls == 0
    state = {"timestamp_us": 2, "ego": {"v": 3}}
    assert await client.decide(state, []) == {"new": True}
    assert state["retry_context"] == {"new": True}


def test_retry_sites_and_coverage_do_not_sum_branches():
    sites = RetrySites(3)
    failure = {"decision_index": 20, "position_world_m": [0, 0, 0]}
    assert [sites.consume(failure) for _ in range(4)] == [True, True, True, False]
    assert not sites.consume({"decision_index": 21, "position_world_m": [20, 0, 0]})
    assert sites.consume({"decision_index": 40, "position_world_m": [20, 0, 0]})
    attempts = [
        {
            "safety": {"safe_steps": n, "visited_lane_ids": ["a"]},
            "success": False,
            "new_decision_calls": n,
            "cached_answers_replayed": 0,
        }
        for n in [10, 20, 15]
    ]
    m = metrics(attempts, 100, [{"lane_ids": ["a"]}, {"lane_ids": ["b"]}])
    assert m["first_attempt_safe_time_coverage"] == 0.1
    assert m["best_branch_safe_time_coverage"] == 0.2
    assert m["best_branch_corridor_visit_fraction"] == 0.5


@pytest.mark.asyncio
async def test_native_cached_replay_and_monitor(tmp_path):
    import json
    from pathlib import Path
    from alpasim_runtime.events import policy
    from jev_drive.config import Config
    from jev_drive.integration.alpasim_adapter import AlpasimAdapter
    from jev_drive.integration.native_simulation import run
    from jev_drive.evaluation.safety import SafetyMonitor, SafetyViolation
    from jev_drive.evaluation.retries import decisions
    from test_core import FixedClient

    if "JEV_DRIVE_ENABLED" not in Path(policy.__file__).read_text():
        pytest.skip("isolated runtime required")
    artifact = "/home/data/alpamayo/alpamayo-scenes/all-usdzs/6f8343eb-9ac7-479c-9682-fcb88b6b48d3.usdz"
    a = AlpasimAdapter(artifact, Config())
    monitor = SafetyMonitor(a, 3, 0.2)
    result = await run(
        artifact,
        Config(),
        FixedClient(),
        tmp_path / "original",
        3,
        safety_monitor=monitor,
    )
    assert result["success"] and monitor.report()["safe_steps"] == 3
    assert monitor.samples >= 12
    rows = decisions(tmp_path / "original/decisions.jsonl")

    class NoAPI:
        async def decide(self, *args):
            raise AssertionError("unexpected API call")

    client = ReplayClient(NoAPI(), rows)
    monitor2 = SafetyMonitor(a, 3, 0.2)
    result = await run(
        artifact, Config(), client, tmp_path / "replay", 3, safety_monitor=monitor2
    )
    assert result["success"] and client.replayed == 3 and client.new_calls == 0

    class StopAfterOne(SafetyMonitor):
        async def on_message(self, message):
            await super().on_message(message)
            if self.report()["safe_steps"] >= 1:
                raise SafetyViolation("injected monitor abort")

    client = FixedClient()
    with pytest.raises(SafetyViolation):
        await run(
            artifact,
            Config(),
            client,
            tmp_path / "abort",
            3,
            safety_monitor=StopAfterOne(a, 3, 0.2),
        )
    assert client.calls == 1


@pytest.mark.asyncio
async def test_coordinator_runs_and_bounds_repeated_failures(tmp_path):
    from pathlib import Path
    from jev_drive.config import Config
    from jev_drive.evaluation.retries import run_scene
    from test_core import FixedClient

    artifact = "/home/data/alpamayo/alpamayo-scenes/all-usdzs/6f8343eb-9ac7-479c-9682-fcb88b6b48d3.usdz"
    if not Path(artifact).exists():
        pytest.skip("local scene unavailable")

    class Client(FixedClient):
        def __init__(self, *args, **kwargs):
            super().__init__()

        async def close(self):
            pass

    result = await run_scene(
        artifact, Config(), tmp_path / "success", 2, client_factory=Client
    )
    assert (
        result["status"] == "completed" and result["metrics"]["new_decision_calls"] == 2
    )
    from jev_drive.logging.decision_log import DecisionLog

    async def failing(artifact, config, client, out, steps, *, safety_monitor):
        log = DecisionLog(out)
        for i in range(8):
            state = {
                "timestamp_us": safety_monitor.first_policy_us + i * 200000,
                "value": i,
            }
            raw = await client.decide(state, [])
            log.write({"event": "decision", "state": state, "raw_response": raw})
        safety_monitor.last_safe_us = safety_monitor.first_policy_us + 7 * 200000
        safety_monitor.failure = {
            "issues": [{"type": "collision"}],
            "decision_index": 7,
            "timestamp_us": safety_monitor.first_policy_us + 8 * 200000,
            "position_world_m": [100, 0, 0],
        }
        raise RuntimeError("injected collision")

    result = await run_scene(
        artifact,
        Config(),
        tmp_path / "bounded",
        20,
        client_factory=Client,
        runner=failing,
    )
    assert result["status"] == "retry_limit_reached"
    assert len(result["attempts"]) == 4
    assert result["metrics"]["cached_answers_replayed"] == 6
    assert result["metrics"]["new_decision_calls"] == 26
    assert result["metrics"]["best_branch_safe_time_coverage"] == 0.35


def test_replay_tolerance_keeps_timestamps_exact_and_bounds_numeric_drift():
    from jev_drive.evaluation.replay import assert_same

    assert_same(
        {"road": {"x": -4.098}, "ego": {"speed": 10.0001}, "timestamp_us": 1000000},
        {"road": {"x": -4.099}, "ego": {"speed": 10.0}, "timestamp_us": 1000000},
    )
    with pytest.raises(ReplayDivergence):
        assert_same({"road": {"x": -4.096}}, {"road": {"x": -4.099}})
    with pytest.raises(ReplayDivergence):
        assert_same({"ego": {"speed": 10.1}}, {"ego": {"speed": 10.0}})
    with pytest.raises(ReplayDivergence):
        assert_same({"timestamp_us": 1000001}, {"timestamp_us": 1000000})

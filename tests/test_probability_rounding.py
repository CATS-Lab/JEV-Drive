"""Regression for the rounded Score distribution returned at live step 94."""

from copy import deepcopy
import json
import pytest
from jev_drive.config import Config
from jev_drive.control import score_control
from jev_drive.policy.jev_model import JevModel
from jev_drive.logging.decision_log import DecisionLog
from jev_drive.state.state_builder import JevStateBuilder
from test_core import FixedClient, snapshot, score_response

LIVE_PROBS = dict(
    zip(map(str, range(9)), [0.02, 0.05, 0.08, 0.10, 0.40, 0.17, 0.07, 0.07, 0.03])
)


@pytest.mark.asyncio
async def test_live_rounded_score_selects_modal_action_and_preserves_raw_response(
    tmp_path,
):
    response = score_response()
    response["answers"]["speed"].update(score=4.16, probabilities=LIVE_PROBS)
    original = deepcopy(response)
    model = JevModel(Config(), FixedClient(response), DecisionLog(tmp_path))
    model.start("session")
    result = await model.predict(JevStateBuilder(Config()).build(snapshot()))
    assert result["increments"]["raw_delta_speed"] == pytest.approx(0.0)
    assert result["raw_response"] == original
    assert result["score_diagnostics"]["speed"]["raw_probability_sum"] == pytest.approx(
        0.99
    )
    assert result["score_diagnostics"]["speed"][
        "probability_weighted_mean"
    ] == pytest.approx(sum(int(k) * v for k, v in LIVE_PROBS.items()) / 0.99)
    record = json.loads((tmp_path / "decisions.jsonl").read_text())
    assert record["raw_response"] == original
    assert not model.sessions["session"]["failed"]


@pytest.mark.parametrize("total", [0.99, 1.0, 1.01])
def test_small_score_sum_error_accepted(total):
    answer = score_response()["answers"]["speed"]
    answer["probabilities"] = {str(i): total / 9 for i in range(9)}
    assert score_control.score(answer) == 4


@pytest.mark.parametrize("total", [0, 0.98, 1.02, 2])
def test_large_score_sum_error_rejected(total):
    answer = score_response()["answers"]["speed"]
    answer["probabilities"] = {str(i): total / 9 for i in range(9)}
    with pytest.raises(ValueError, match="invalid probability distribution"):
        score_control.score(answer)


@pytest.mark.parametrize("value", [-0.001, 1.001, float("nan"), float("inf"), True])
def test_sum_tolerance_does_not_relax_individual_probabilities(value):
    answer = score_response()["answers"]["speed"]
    answer["probabilities"]["0"] = value
    with pytest.raises(ValueError):
        score_control.score(answer)


def test_choice_probabilities_remain_strict():
    with pytest.raises(ValueError):
        score_control.probabilities(
            {"probabilities": {"a": 0.49, "b": 0.50}}, ["a", "b"]
        )


def test_map_coordinate_rounding_is_bounded_and_keeps_snapshot():
    from jev_drive.state.road_graph import clip_resample

    snap = snapshot()
    points = [[0.1234567, 0.2345678, 0.0], [10.1234567, 0.2345678, 0.0]]
    original = deepcopy(points)
    segments = clip_resample(points, snap.ego, [-20, 80, -15, 15], 5.0)
    assert points == original
    assert segments[0][0] == [0.123, 0.235]
    assert segments[0][-1] == [10.123, 0.235]
    assert abs(segments[0][0][0] - points[0][0]) <= 0.0005
    assert abs(segments[0][0][1] - points[0][1]) <= 0.0005

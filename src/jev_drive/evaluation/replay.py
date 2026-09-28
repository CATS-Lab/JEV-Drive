"""Replay answers only after checking the reconstructed policy input."""

from copy import deepcopy
import math


class ReplayDivergence(RuntimeError):
    pass


def assert_same(actual, expected, path="state"):
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) - {"retry_context"} != set(
            expected
        ) - {"retry_context"}:
            raise ReplayDivergence(f"{path}: keys changed")
        for key in expected:
            if key != "retry_context":
                assert_same(actual[key], expected[key], path + "." + key)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ReplayDivergence(f"{path}: list length changed")
        for i, (a, b) in enumerate(zip(actual, expected)):
            assert_same(a, b, f"{path}[{i}]")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        # Map coordinates are rounded to millimetres by state builders. Tiny
        # MPC float differences can cross a rounding boundary by one quantum.
        tolerance = (
            0.0010001
            if path.startswith(("state.road.", "state.traffic_controls."))
            else 1e-3
        )
        if isinstance(expected, int):
            tolerance = 0
        if not isinstance(actual, (int, float)) or not math.isclose(
            actual, expected, rel_tol=0, abs_tol=tolerance
        ):
            raise ReplayDivergence(f"{path}: numeric value changed")
    elif actual != expected:
        raise ReplayDivergence(f"{path}: value changed")


class ReplayClient:
    def __init__(
        self, base, prefix=(), checkpoint=None, context=None, on_event=None, budget=None
    ):
        self.base, self.prefix, self.checkpoint = base, prefix, checkpoint
        self.context, self.on_event, self.budget = context, on_event, budget
        self.index = self.replayed = self.new_calls = 0
        self.source_label = getattr(base, "source_label", "jev_api")

    async def decide(self, state, questions):
        index = self.index
        if index < len(self.prefix):
            row = self.prefix[index]
            assert_same(state, row["state"])
            if "retry_context" in row["state"]:
                state["retry_context"] = deepcopy(row["state"]["retry_context"])
            self.replayed += 1
            response = deepcopy(row["raw_response"])
            source = "cached_answer"
        else:
            if index == len(self.prefix) and self.checkpoint is not None:
                assert_same(state, self.checkpoint["state"])
            if self.context:
                state["retry_context"] = deepcopy(self.context)
            if self.budget is not None:
                if self.budget["remaining"] <= 0:
                    raise RuntimeError("scene_new_decision_budget_exhausted")
                self.budget["remaining"] -= 1
            self.new_calls += 1
            response = await self.base.decide(state, questions)
            source = "new_api_answer"
        if self.on_event:
            self.on_event(
                {
                    "event": "decision_source",
                    "decision_index": index,
                    "timestamp_us": state["timestamp_us"],
                    "source": source,
                }
            )
        self.index += 1
        return response

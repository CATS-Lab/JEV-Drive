"""Validate distributions and map the returned continuous scores to commands."""

import math
from .action_mapping import continuous_commands, steering_targets


def number(value, name):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"invalid numeric {name}")
    return float(value)


def probabilities(answer, keys, *, sum_tolerance=1e-4):
    probs = answer["probabilities"]
    if set(probs) != set(keys):
        raise ValueError("probability keys mismatch")
    p = {k: number(probs[k], k) for k in keys}
    total = math.fsum(p.values())
    if (
        any(v < 0 or v > 1 for v in p.values())
        or abs(total - 1) > sum_tolerance + 1e-12
    ):
        raise ValueError(f"invalid probability distribution (sum={total:.8g})")
    # Confidence is optional metadata and is not a control input.
    if (
        "confidence" in answer
        and not 0 <= number(answer["confidence"], "confidence") <= 1
    ):
        raise ValueError("invalid confidence")
    return p


def score(answer):
    if answer["type"] != "score":
        raise ValueError("expected score answer")
    # Some Score responses round probabilities to two decimal places.
    # Accept at most one percentage point of sum error without changing raw data.
    probabilities(answer, [str(i) for i in range(9)], sum_tolerance=0.01)
    value = number(answer["score"], "score")
    if not 0 <= value <= 8:
        raise ValueError("score outside [0,8]")
    # Preserve the reported score; comparison with a recomputed mean is only
    # diagnostic, not an additional precision contract imposed on the backend.
    return value


def commands(answers, config):
    """Return continuous speed increment and absolute steering target."""
    return continuous_commands(score(answers["speed"]), score(answers["steering"]), config)


def diagnostics(answers):
    """Compare already-validated answers without changing their control values."""
    result = {}
    for axis in ("speed", "steering"):
        answer = answers[axis]
        total = math.fsum(answer["probabilities"].values())
        mean = math.fsum(int(k) * v for k, v in answer["probabilities"].items()) / total
        result[axis] = {
            "reported_score": answer["score"],
            "control_score": score(answer),
            "raw_probability_sum": total,
            "probability_weighted_mean": mean,
            "reported_minus_mean": answer["score"] - mean,
        }
    return result

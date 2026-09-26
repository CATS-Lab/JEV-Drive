"""Validate JEV score answers and map continuous scores to increments."""

import math


def number(value, name):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"invalid numeric {name}")
    return float(value)


def probabilities(answer, keys):
    probs = answer["probabilities"]
    if set(probs) != set(keys):
        raise ValueError("probability keys mismatch")
    p = {k: number(probs[k], k) for k in keys}
    if any(v < 0 or v > 1 for v in p.values()) or abs(sum(p.values()) - 1) > 1e-4:
        raise ValueError("invalid probability distribution")
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
    probabilities(answer, [str(i) for i in range(9)])
    value = number(answer["score"], "score")
    if not 0 <= value <= 8:
        raise ValueError("score outside [0,8]")
    # Use the reported score. Comparing it with a recomputed mean is diagnostic,
    # not an additional precision contract imposed on the backend.
    return value


def increments(answers, config):
    return (
        (score(answers["speed"]) - 4) * config.speed_score_gain,
        (score(answers["steering"]) - 4) * config.steering_score_gain,
    )


def diagnostics(answers):
    """Compare already-validated answers without changing their control values."""
    result = {}
    for axis in ("speed", "steering"):
        answer = answers[axis]
        mean = math.fsum(int(k) * v for k, v in answer["probabilities"].items())
        result[axis] = {
            "reported_score": answer["score"],
            "probability_weighted_mean": mean,
            "reported_minus_mean": answer["score"] - mean,
        }
    return result

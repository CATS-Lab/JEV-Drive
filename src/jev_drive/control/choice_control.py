"""Probability-weighted updates with the specified choice labels."""

from .score_control import probabilities


def increments(answers, config):
    if any(answers[k]["type"] != "choice" for k in ("speed", "steering")):
        raise ValueError("expected choice answer")
    v = probabilities(answers["speed"], ["accelerate", "hold", "decelerate"])
    s = probabilities(answers["steering"], ["left", "straight", "right"])
    for k, p in (("speed", v), ("steering", s)):
        selected = answers[k]["choice"]
        if selected not in p or p[selected] < max(p.values()) - 1e-6:
            raise ValueError("invalid selected choice")
    return (
        (v["accelerate"] - v["decelerate"]) * config.choice_speed_gain,
        (s["left"] - s["right"]) * config.choice_steering_gain,
    )

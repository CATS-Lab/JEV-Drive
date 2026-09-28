"""Execute the selected Choice action; steering targets are absolute."""

from .score_control import probabilities


def commands(answers, config):
    if any(answers[k]["type"] != "choice" for k in ("speed", "steering")):
        raise ValueError("expected choice answer")
    v = probabilities(answers["speed"], ["accelerate", "hold", "decelerate"])
    s = probabilities(answers["steering"], ["left", "straight", "right"])
    for k, p in (("speed", v), ("steering", s)):
        selected = answers[k]["choice"]
        if selected not in p or p[selected] < max(p.values()) - 1e-6:
            raise ValueError("invalid selected choice")
    return (
        {
            "accelerate": config.choice_speed_gain,
            "hold": 0.0,
            "decelerate": -config.choice_speed_gain,
        }[answers["speed"]["choice"]],
        {
            "left": config.choice_steering_gain,
            "straight": 0.0,
            "right": -config.choice_steering_gain,
        }[answers["steering"]["choice"]],
    )

"""Shared numeric action definitions for execution and model-facing descriptions."""


def speed_increments(config):
    return [(level - 4) * config.speed_score_gain for level in range(9)]


def choice_targets(config):
    return {
        "speed": {"accelerate": config.choice_speed_gain, "hold": 0.0, "decelerate": -config.choice_speed_gain},
        "steering": {"left": config.choice_steering_gain, "straight": 0.0, "right": -config.choice_steering_gain},
    }


def steering_targets(config):
    """Fine corrections near zero, with strong turns reaching the configured bound."""
    magnitudes = [
        min(config.max_abs_steering_rad, factor * config.steering_score_gain)
        for factor in (1, 4, 10)
    ] + [config.max_abs_steering_rad]
    return [-v for v in reversed(magnitudes)] + [0.0] + magnitudes


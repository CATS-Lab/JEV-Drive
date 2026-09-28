"""Shared numeric action definitions for execution and model-facing descriptions."""


def speed_increments(config):
    return [(level - 4) * config.speed_score_gain for level in range(9)]


def choice_targets(config):
    return {
        "speed": {"accelerate": config.choice_speed_gain, "hold": 0.0, "decelerate": -config.choice_speed_gain},
        "steering": {"left": config.choice_steering_gain, "straight": 0.0, "right": -config.choice_steering_gain},
    }


def continuous_commands(speed_score, steering_score, config):
    """Map the reported continuous scores to pre-limit commands."""
    return ((speed_score - 4) * config.speed_score_gain,
            (steering_score - 4) * config.steering_score_gain)


def steering_targets(config):
    """Integer anchors of the continuous steering mapping, before limits."""
    return [continuous_commands(4, level, config)[1] for level in range(9)]

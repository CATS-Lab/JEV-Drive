"""Shared numeric action definitions for execution and model-facing descriptions."""


def speed_increments(config):
    return [continuous_commands(level, 4, config)[0] for level in range(9)]


def choice_targets(config):
    return {
        "speed": {"accelerate": config.choice_speed_gain, "hold": 0.0, "decelerate": -config.choice_speed_gain},
        "steering": {"left": config.choice_steering_gain, "straight": 0.0, "right": -config.choice_steering_gain},
    }


def centered_score(value, width):
    """Continuous symmetric deadzone with unchanged endpoint magnitude."""
    if 4 - width <= value <= 4 + width:
        return 0.0
    delta = value - 4
    magnitude = max(0.0, abs(delta) - width) * 4 / (4 - width)
    return -magnitude if delta < 0 else magnitude


def continuous_commands(speed_score, steering_score, config):
    """Map the reported continuous scores to pre-limit commands."""
    return (centered_score(speed_score, config.score_deadzone) * config.speed_score_gain,
            centered_score(steering_score, config.score_deadzone) * config.steering_score_gain)


def steering_targets(config):
    """Integer anchors of the continuous steering mapping, before limits."""
    return [continuous_commands(4, level, config)[1] for level in range(9)]

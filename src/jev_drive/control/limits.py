"""Rate-limit commands in simulation time, then enforce absolute bounds."""

import math
from .control_state import ControlState


def clip(value, low, high):
    return max(low, min(high, value))


def apply(control, raw_speed, raw_steering, dt, config):
    if not all(math.isfinite(v) for v in (raw_speed, raw_steering, dt)) or dt <= 0:
        raise ValueError("invalid control update")
    dv = clip(
        raw_speed, -config.max_deceleration_mps2 * dt, config.max_acceleration_mps2 * dt
    )
    ds = clip(
        raw_steering,
        -config.max_steering_rate_radps * dt,
        config.max_steering_rate_radps * dt,
    )
    updated = ControlState(
        clip(
            control.target_speed + dv,
            config.min_target_speed_mps,
            config.max_target_speed_mps,
        ),
        clip(
            control.steering_angle + ds,
            -config.max_abs_steering_rad,
            config.max_abs_steering_rad,
        ),
    )
    return updated, {
        "raw_delta_speed": raw_speed,
        "raw_delta_steering": raw_steering,
        "rate_limited_delta_speed": dv,
        "rate_limited_delta_steering": ds,
        "applied_delta_speed": updated.target_speed - control.target_speed,
        "applied_delta_steering": updated.steering_angle - control.steering_angle,
    }

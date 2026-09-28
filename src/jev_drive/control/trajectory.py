"""Bicycle reference with constant curvature and bounded longitudinal ramp.

Arc geometry follows AlpaSim ManualModel. Arc length integrates a speed ramp
from measured speed instead of assuming the new target is reached instantly.
"""

import math
import numpy as np


def generate(control, config, *, initial_speed=None):
    n = round(config.trajectory_horizon_s * config.trajectory_frequency_hz)
    times = np.arange(1, n + 1, dtype=float) / config.trajectory_frequency_hz
    target, steer = control.target_speed, control.steering_angle
    start = target if initial_speed is None else float(initial_speed)
    if not math.isfinite(start) or start < 0:
        raise ValueError("reference initial speed must be finite and forward")
    change = target - start
    acceleration = (
        (config.max_acceleration_mps2 if change > 0 else -config.max_deceleration_mps2)
        if change
        else 0.0
    )
    duration = abs(change / acceleration) if acceleration else 0.0
    ramp_times = np.minimum(times, duration)
    speeds = start + acceleration * ramp_times
    distance = start * ramp_times + 0.5 * acceleration * ramp_times**2
    distance += target * (times - ramp_times)
    if abs(steer) < 1e-9:
        xy = np.column_stack((distance, np.zeros(n)))
        headings = np.zeros(n)
    else:
        radius = config.wheelbase_m / np.tan(steer)
        headings = distance / radius
        xy = np.column_stack(
            (radius * np.sin(headings), radius * (1 - np.cos(headings)))
        )
    return {
        "times_s": times.tolist(),
        "xy_m": xy.tolist(),
        "headings_rad": headings.tolist(),
        "speeds_mps": speeds.tolist(),
        "initial_speed_mps": start,
        "target_speed_mps": target,
        "ramp_acceleration_mps2": acceleration,
        "ramp_duration_s": duration,
    }

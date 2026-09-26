"""Headless constant-curvature bicycle trajectory matching AlpaSim ManualModel.

The geometry follows NVlabs/alpasim manual_model.py (Apache-2.0):
R = wheelbase / tan(steering), x = R sin(vt/R), y = R (1-cos(vt/R)).
"""

import numpy as np


def generate(control, config):
    n = round(config.trajectory_horizon_s * config.trajectory_frequency_hz)
    times = np.arange(1, n + 1, dtype=float) / config.trajectory_frequency_hz
    v, steer = control.target_speed, control.steering_angle
    if abs(v) <= 0.1:
        v = 0.0
    if abs(steer) < 0.001:
        xy = np.column_stack((v * times, np.zeros(n)))
        headings = np.zeros(n)
    else:
        radius = config.wheelbase_m / np.tan(steer)
        headings = v * times / radius
        xy = np.column_stack(
            (radius * np.sin(headings), radius * (1 - np.cos(headings)))
        )
    return {
        "times_s": times.tolist(),
        "xy_m": xy.tolist(),
        "headings_rad": headings.tolist(),
    }

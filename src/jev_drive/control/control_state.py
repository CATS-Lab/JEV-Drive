"""Per-rollout reference commands, distinct from measured actuator feedback."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ControlState:
    target_speed: float
    steering_angle: float

    @classmethod
    def initialize(cls, ego, config):
        speed = float(ego["speed_mps"])
        if not math.isfinite(speed) or speed < 0:
            raise ValueError("initial speed must be finite and forward")
        # Preserve actual motion, including overspeed. Limits bring the command
        # back into range gradually; yaw-to-steering uses actual speed too.
        steer = (
            math.atan(config.wheelbase_m * ego["yaw_rate_radps"] / speed)
            if speed > 0.25
            else 0.0
        )
        return cls(
            speed,
            max(-config.max_abs_steering_rad, min(config.max_abs_steering_rad, steer)),
        )

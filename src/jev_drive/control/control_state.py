"""Per-rollout reference commands, distinct from measured actuator feedback."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ControlState:
    target_speed: float
    steering_angle: float

    @classmethod
    def initialize(cls, ego, config):
        speed = max(
            config.min_target_speed_mps,
            min(config.max_target_speed_mps, ego["speed_mps"]),
        )
        steer = (
            math.atan(config.wheelbase_m * ego["yaw_rate_radps"] / speed)
            if speed > 0.25
            else 0.0
        )
        return cls(
            speed,
            max(-config.max_abs_steering_rad, min(config.max_abs_steering_rad, steer)),
        )

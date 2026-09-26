"""Validated experiment configuration, shared by snapshot builders and driver."""

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class Config:
    mode: str = "score"
    model: str = "typesafe-ai/jev"
    endpoint: str = "https://ai-gateway.vercel.sh/v1/evaluate"
    api_timeout_s: float = 120.0
    retry_429: bool = False
    retry_initial_s: float = 5.0
    retry_max_s: float = 60.0
    api_min_interval_s: float = 0.0
    decision_dt_s: float = 0.2
    road_roi: tuple = (-20.0, 80.0, -15.0, 15.0)
    actor_roi: tuple = (-30.0, 80.0, -20.0, 20.0)
    max_actors: int = 16
    centerline_spacing_m: float = 5.0
    min_target_speed_mps: float = 0.0
    max_target_speed_mps: float = 15.0
    max_acceleration_mps2: float = 3.0
    max_deceleration_mps2: float = 3.0
    max_abs_steering_rad: float = 0.4
    max_steering_rate_radps: float = 0.8
    wheelbase_m: float = 2.85
    speed_score_gain: float = 0.25
    steering_score_gain: float = 0.015
    choice_speed_gain: float = 1.0
    choice_steering_gain: float = 0.06
    trajectory_horizon_s: float = 4.0
    trajectory_frequency_hz: float = 10.0
    signal_max_age_s: float = 1.0
    actor_types: dict = field(
        default_factory=lambda: {
            "automobile": "vehicle",
            "bus": "vehicle",
            "heavy_truck": "vehicle",
            "trailer": "vehicle",
            "vehicle": "vehicle",
            "pedestrian": "pedestrian",
            "cyclist": "cyclist",
            "bicycle": "cyclist",
            "rider": "unknown",
        }
    )

    def __post_init__(self):
        if self.mode not in {"score", "choice"}:
            raise ValueError("mode must be score or choice")
        for name in (
            "api_timeout_s",
            "retry_initial_s",
            "retry_max_s",
            "decision_dt_s",
            "centerline_spacing_m",
            "max_acceleration_mps2",
            "max_deceleration_mps2",
            "max_abs_steering_rad",
            "max_steering_rate_radps",
            "wheelbase_m",
            "trajectory_horizon_s",
            "trajectory_frequency_hz",
            "signal_max_age_s",
        ):
            v = getattr(self, name)
            if not math.isfinite(v) or v <= 0:
                raise ValueError(f"invalid {name}")
        if not isinstance(self.retry_429, bool):
            raise ValueError("retry_429 must be boolean")
        if self.retry_initial_s > self.retry_max_s:
            raise ValueError("retry_initial_s exceeds retry_max_s")
        if not math.isfinite(self.api_min_interval_s) or self.api_min_interval_s < 0:
            raise ValueError("invalid api_min_interval_s")
        if self.min_target_speed_mps != 0 or self.max_target_speed_mps <= 0:
            raise ValueError("v1 requires forward-only bounds")
        if self.max_actors < 1:
            raise ValueError("max_actors must be positive")
        for roi in (self.road_roi, self.actor_roi):
            if (
                len(roi) != 4
                or not all(math.isfinite(v) for v in roi)
                or roi[0] >= roi[1]
                or roi[2] >= roi[3]
            ):
                raise ValueError("invalid ROI")
        for name in (
            "speed_score_gain",
            "steering_score_gain",
            "choice_speed_gain",
            "choice_steering_gain",
        ):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f"invalid {name}")

    @classmethod
    def load(cls, path=None):
        return cls(**json.loads(Path(path).read_text())) if path else cls()

    def as_dict(self):
        return asdict(self)

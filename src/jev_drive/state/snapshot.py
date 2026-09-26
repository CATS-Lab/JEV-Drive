"""Serializable snapshot. Native simulator objects never escape the adapter."""

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SceneSnapshot:
    session_id: str
    scene_id: str
    timestamp_us: int
    step_index: int
    decision_dt_s: float
    ego: dict
    lanes: list
    actors: list
    route_world: list
    traffic_controls: dict
    provenance: dict

    def as_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**value)

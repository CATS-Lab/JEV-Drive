"""Assemble independent signal, line, and sign builders."""

from .snapshot import SceneSnapshot
from ..config import Config


from . import traffic_signals, stop_lines, traffic_signs


def build(snapshot: SceneSnapshot, config: Config) -> dict:
    return {
        "signals": traffic_signals.build(snapshot, config),
        "stop_lines": stop_lines.build(snapshot, config),
        "signs": traffic_signs.build(snapshot, config),
        "availability": snapshot.traffic_controls["availability"],
    }

"""Compose separately testable state components without driving reasoning."""

import base64
from . import ego, road_graph, actors, navigation, traffic_controls
from .schema import FRAME, finite


class JevStateBuilder:
    def __init__(self, config):
        self.config = config

    def build(self, snapshot, renderer_payload=None):
        actor_state, actor_audit = actors.build_with_audit(snapshot, self.config)
        envelope = {
            "kind": "jev.scene_snapshot",
            "schema_version": 1,
            "session_id": snapshot.session_id,
            "scene_id": snapshot.scene_id,
            "step_index": snapshot.step_index,
            "timestamp_us": snapshot.timestamp_us,
            "decision_dt_s": snapshot.decision_dt_s,
            "coordinate_frame": FRAME,
            "state": {
                "ego": ego.build(snapshot),
                "road": road_graph.build(snapshot, self.config),
                "actors": actor_state,
                "navigation": navigation.build(snapshot, self.config),
                "traffic_controls": traffic_controls.build(snapshot, self.config),
            },
            "provenance": {**snapshot.provenance, "actor_filter": actor_audit},
            "renderer_payload_b64": (
                base64.b64encode(renderer_payload).decode()
                if renderer_payload
                else None
            ),
        }
        finite(envelope)
        return envelope

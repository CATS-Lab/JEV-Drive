"""Versioned transport validation. Reject non-finite or mismatched snapshots."""

import base64
import json
import math

FRAME = "ego_rig_x_forward_y_left_z_up"


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite value")
    if isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            finite(item)


def encode(envelope):
    finite(envelope)
    return json.dumps(envelope, allow_nan=False, separators=(",", ":")).encode()


def decode(payload, session_id=None, timestamp_us=None):
    if not payload:
        raise ValueError("missing scene snapshot")
    obj = json.loads(payload)
    finite(obj)
    if obj.get("kind") != "jev.scene_snapshot" or obj.get("schema_version") != 1:
        raise ValueError("unsupported snapshot schema")
    if obj.get("coordinate_frame") != FRAME:
        raise ValueError("invalid frame")
    if session_id is not None and obj["session_id"] != session_id:
        raise ValueError("session mismatch")
    if timestamp_us is not None and obj["timestamp_us"] != timestamp_us:
        raise ValueError("timestamp mismatch")
    if obj["decision_dt_s"] <= 0:
        raise ValueError("invalid decision interval")
    for key in ("ego", "road", "actors", "navigation", "traffic_controls"):
        if key not in obj["state"]:
            raise ValueError(f"missing {key}")
    if obj.get("renderer_payload_b64") is not None:
        base64.b64decode(obj["renderer_payload_b64"], validate=True)
    return obj

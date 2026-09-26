"""Independent per-session JEV model. No camera, GUI, or Alpamayo dependency."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import time
from ..control.control_state import ControlState
from ..control import score_control, choice_control, limits, trajectory
from ..state.vehicle_constraints import build as constraints
from ..state.schema import encode, decode
from .questions import build as questions, VERSION


class JevModel:
    def __init__(self, config, client, logger):
        self.config, self.client, self.logger = config, client, logger
        self.sessions = {}

    def start(self, session_id):
        if session_id in self.sessions:
            raise ValueError("duplicate session")
        self.sessions[session_id] = {
            "control": None,
            "last_timestamp": -1,
            "last_fingerprint": None,
            "result": None,
            "failed": False,
        }

    def close(self, session_id):
        self.sessions.pop(session_id, None)

    async def predict(self, envelope):
        envelope = decode(encode(envelope))
        sid, ts = envelope["session_id"], envelope["timestamp_us"]
        session = self.sessions[sid]
        if session["failed"]:
            raise RuntimeError("rollout already failed")
        fingerprint = hashlib.sha256(encode(envelope)).hexdigest()
        if (
            ts == session["last_timestamp"]
            and fingerprint == session["last_fingerprint"]
        ):
            return deepcopy(session["result"])
        if ts <= session["last_timestamp"]:
            raise ValueError("out-of-order or conflicting request")
        metadata = {
            "session_id": sid,
            "scene_id": envelope["scene_id"],
            "timestamp_us": ts,
            "step_index": envelope["step_index"],
        }
        started = time.perf_counter()
        state = raw = None
        try:
            dt = envelope["decision_dt_s"]
            if abs(dt - self.config.decision_dt_s) > 1e-9:
                raise ValueError("runtime/driver decision interval mismatch")
            state = deepcopy(envelope["state"])
            control = session["control"] or ControlState.initialize(
                state["ego"], self.config
            )
            state["ego"].update(
                commanded_steering_rad=control.steering_angle,
                current_target_speed_mps=control.target_speed,
            )
            state.update(
                vehicle_constraints=constraints(self.config),
                decision_dt_s=dt,
                timestamp_us=ts,
                coordinate_frame=envelope["coordinate_frame"],
            )
            raw = await self.client.decide(state, questions(self.config))
            latency = time.perf_counter() - started
            mapping = score_control if self.config.mode == "score" else choice_control
            dv, ds = mapping.increments(raw["answers"], self.config)
            updated, changes = limits.apply(control, dv, ds, dt, self.config)
            result = {
                **metadata,
                "event": "decision",
                "mode": self.config.mode,
                "prompt_version": VERSION,
                "state": state,
                "provenance": envelope["provenance"],
                "raw_response": raw,
                "score_diagnostics": (
                    score_control.diagnostics(raw["answers"])
                    if self.config.mode == "score"
                    else None
                ),
                "control_before": asdict(control),
                "control": asdict(updated),
                "increments": changes,
                "initialization_source": (
                    "kinematic_yaw_rate_or_standstill"
                    if session["control"] is None
                    else None
                ),
                "api_latency_s": latency,
                "decision_dt_s": dt,
                "trajectory": trajectory.generate(updated, self.config),
                "config": self.config.as_dict(),
            }
            self.logger.write(result)
            session.update(
                control=updated,
                last_timestamp=ts,
                last_fingerprint=fingerprint,
                result=deepcopy(result),
            )
            return result
        except Exception as e:
            session["failed"] = True
            self.logger.write(
                {
                    **metadata,
                    "event": "failure",
                    "snapshot": envelope,
                    "request_state": state,
                    # A JSON string preserves even rejected NaN/Infinity values
                    # without making the enclosing JSONL event nonstandard JSON.
                    "raw_response_json": json.dumps(raw) if raw is not None else None,
                    "error_details": getattr(e, "diagnostics", None),
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "elapsed_s": time.perf_counter() - started,
                }
            )
            raise

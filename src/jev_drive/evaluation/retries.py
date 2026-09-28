"""Bounded scene retries, retaining first-pass and recovered coverage separately."""

import asyncio
import json
from pathlib import Path
from ..policy.questions import VERSION
import numpy as np
from .replay import ReplayClient
from .safety import SafetyMonitor, SafetyViolation


def save(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def decisions(path):
    if not Path(path).exists():
        return []
    return [
        r
        for line in Path(path).read_text().splitlines()
        if (r := json.loads(line)).get("event") == "decision"
    ]


class RetrySites:
    def __init__(self, limit=3):
        self.limit = limit
        self.sites = []

    def consume(self, failure):
        index = failure["decision_index"]
        pos = np.asarray(failure["position_world_m"])
        # Same physical site OR nearby decision time: changing violation type
        # does not reset the retry budget, nor does a one-frame shift.
        site = next(
            (
                s
                for s in self.sites
                if abs(s["decision_index"] - index) <= 5
                or np.linalg.norm(np.asarray(s["position_world_m"]) - pos) <= 5
            ),
            None,
        )
        if site is None:
            site = {
                "decision_index": index,
                "position_world_m": pos.tolist(),
                "retries": 0,
            }
            self.sites.append(site)
        if site["retries"] >= self.limit:
            return False
        site["retries"] += 1
        return True


def metrics(attempts, steps, corridors):
    safe = [a["safety"]["safe_steps"] for a in attempts]
    best = max(range(len(attempts)), key=lambda i: safe[i]) if attempts else None
    initial = safe[0] if safe else 0
    best_safe = safe[best] if best is not None else 0

    def route_coverage(attempt):
        visited = set(attempt["safety"]["visited_lane_ids"])
        return (
            sum(bool(visited.intersection(c["lane_ids"])) for c in corridors)
            / len(corridors)
            if corridors
            else None
        )

    return {
        "requested_steps": steps,
        "attempts": len(attempts),
        "retries": max(0, len(attempts) - 1),
        "first_attempt_safe_steps": initial,
        "first_attempt_safe_time_coverage": initial / steps,
        "best_branch_safe_steps": best_safe,
        "best_branch_safe_time_coverage": best_safe / steps,
        "first_attempt_completed_without_detected_violation": bool(
            attempts and attempts[0]["success"]
        ),
        "completed_after_retries": any(a["success"] for a in attempts),
        "best_attempt": best,
        "first_attempt_corridor_visit_fraction": (
            route_coverage(attempts[0]) if attempts else None
        ),
        "best_branch_corridor_visit_fraction": (
            route_coverage(attempts[best]) if best is not None else None
        ),
        "initial_corridor_count": len(corridors),
        "new_decision_calls": sum(a["new_decision_calls"] for a in attempts),
        "cached_answers_replayed": sum(a["cached_answers_replayed"] for a in attempts),
        "interpretation": "Sampled checks only; time coverage is not destination completion. Corridor visitation is discrete, not distance coverage.",
    }


async def run_scene(
    artifact,
    config,
    output,
    steps,
    *,
    rewind_steps=5,
    max_retries=3,
    client_factory=None,
    runner=None,
    seed_log=None,
):
    from ..integration.alpasim_adapter import AlpasimAdapter
    from ..integration.native_simulation import run
    from ..policy.client_factory import create_client
    from ..logging.decision_log import DecisionLog
    from ..state.navigation import build

    if steps < 1 or rewind_steps < 1 or max_retries < 0:
        raise ValueError("invalid steps/rewind/retry limits")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "experiment.json").exists():
        raise ValueError("use a new experiment directory")
    adapter = AlpasimAdapter(artifact, config)
    dt_us = round(config.decision_dt_s * 1e6)
    first_us = int(adapter.artifact.rig.trajectory.timestamps_us[0]) + dt_us
    if first_us + steps * dt_us > int(
        adapter.artifact.rig.trajectory.timestamps_us[-1]
    ):
        raise ValueError("requested rollout extends beyond recording")
    snapshot = adapter.snapshot("preflight", first_us, 0)
    nav = build(snapshot, config)
    report = {
        "status": "preflight",
        "artifact": str(artifact),
        "scene_id": adapter.artifact.scene_id,
        "rewind_steps": rewind_steps,
        "max_retries_per_site": max_retries,
        "new_decision_call_limit": steps * (max_retries + 1),
        "attempts": [],
        "navigation": nav,
    }
    path = output / "experiment.json"
    save(path, report)
    if nav["availability"] != "available":
        report["status"] = "excluded_initial_navigation"
        save(path, report)
        return report
    preflight = SafetyMonitor(adapter, steps, config.decision_dt_s)
    try:
        preflight.inspect(snapshot, initial=True)
    except SafetyViolation:
        report.update(
            status="excluded_initial_geometry", initial_safety=preflight.report()
        )
        save(path, report)
        return report
    prefix = decisions(seed_log) if seed_log else []
    if any(r.get("prompt_version") != VERSION for r in prefix):
        raise ValueError("seed prompt version differs from current experiment baseline")
    checkpoint = context = None
    budget = {"remaining": report["new_decision_call_limit"]}
    sites = RetrySites(max_retries)
    while True:
        number = len(report["attempts"])
        out = output / f"attempt-{number:02d}"
        log = DecisionLog(out)
        monitor = SafetyMonitor(adapter, steps, config.decision_dt_s)
        monitor.inspect(snapshot, initial=True)
        base = (client_factory or create_client)(config, on_event=log.write)
        client = ReplayClient(base, prefix, checkpoint, context, log.write, budget)
        report.update(status="running", active_attempt=number)
        save(path, report)
        result = {"success": False}
        try:
            result = await (runner or run)(
                artifact, config, client, out, steps, safety_monitor=monitor
            )
        except asyncio.CancelledError:
            report["status"] = "interrupted"
            save(path, report)
            raise
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)[:1000]
        finally:
            await base.close()
        safety = monitor.report()
        attempt = {
            "output": str(out),
            "success": bool(
                result.get("success")
                and safety["safe_steps"] == steps
                and not monitor.failure
            ),
            "safety": safety,
            "new_decision_calls": client.new_calls,
            "cached_answers_replayed": client.replayed,
            "rewind_start_index": len(prefix),
            "error": result.get("error"),
        }
        report["attempts"].append(attempt)
        report["metrics"] = metrics(report["attempts"], steps, nav["corridors"])
        report["retry_sites"] = sites.sites
        save(path, report)
        if attempt["success"]:
            report["status"] = "completed"
            break
        if monitor.failure is None:
            report["status"] = "infrastructure_failed"
            break
        if not sites.consume(monitor.failure):
            report["status"] = "retry_limit_reached"
            break
        if budget["remaining"] <= 0:
            report["status"] = "decision_budget_reached"
            break
        rows = decisions(out / "decisions.jsonl")
        rewind = max(0, int(monitor.failure["decision_index"]) - rewind_steps)
        if rewind >= len(rows):
            report["status"] = "missing_replay_checkpoint"
            break
        prefix, checkpoint = rows[:rewind], rows[rewind]
        context = {
            "mode": "simulation_recovery",
            "previous_failure": monitor.failure["issues"],
            "failure_timestamp_us": monitor.failure["timestamp_us"],
            "failure_position_world_m": monitor.failure["position_world_m"],
            "instruction": "A previous simulated attempt from this state led to the reported violation. Reconsider the controls using the current scene and avoid the violation. This is retry feedback, not a live future observation.",
        }
    report["retry_sites"] = sites.sites
    report.pop("active_attempt", None)
    save(path, report)
    return report

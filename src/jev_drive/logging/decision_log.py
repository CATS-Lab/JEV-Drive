"""Durable JSONL events with session/step correlation."""

import json
from pathlib import Path


class DecisionLog:
    def __init__(self, output, total_steps=None):
        path = Path(output)
        path.mkdir(parents=True, exist_ok=True)
        self.path = path / "decisions.jsonl"
        self.total_steps = total_steps
        self.completed = 0

    def write(self, event):
        with self.path.open("a") as f:
            f.write(json.dumps(event, allow_nan=False, separators=(",", ":")) + "\n")
        if self.total_steps is not None and event.get("event") == "decision":
            self.completed += 1
            print(
                f"JEV step {self.completed}/{self.total_steps} completed; "
                f"target speed {event['control']['target_speed']:.3f} m/s; "
                f"request including waits {event['api_latency_s']:.2f}s",
                flush=True,
            )

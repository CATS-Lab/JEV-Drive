"""Run a fixed artifact manifest sequentially and update bilingual result indexes."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from ..policy.questions import VERSION
import subprocess
import sys
from .retries import run_scene, save
from ..config import Config


def update(suite, manifest):
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    reports = []
    for item in manifest["scenes"]:
        path = Path(item.get("output", "")) / "experiment.json"
        if path.is_file():
            reports.append(json.loads(path.read_text()))
    eligible = [r for r in reports if not r["status"].startswith("excluded")]
    measured = [r["metrics"] for r in eligible if "metrics" in r]
    manifest["aggregate"] = {
        "local_scenes": len(manifest["scenes"]),
        "preflight_processed": len(reports),
        "excluded": len(reports) - len(eligible),
        "eligible_started": len(eligible),
        "scenes_with_attempt_metrics": len(measured),
        "first_pass_completions": sum(
            m["first_attempt_completed_without_detected_violation"] for m in measured
        ),
        "completions_after_retries": sum(
            m["completed_after_retries"] for m in measured
        ),
        "mean_first_pass_safe_time_coverage": (
            sum(m["first_attempt_safe_time_coverage"] for m in measured) / len(measured)
            if measured
            else None
        ),
        "mean_best_branch_safe_time_coverage": (
            sum(m["best_branch_safe_time_coverage"] for m in measured) / len(measured)
            if measured
            else None
        ),
        "new_decision_calls_in_finished_attempts": sum(
            m["new_decision_calls"] for m in measured
        ),
        "infrastructure_failed_scenes": sum(
            r["status"] == "infrastructure_failed" for r in eligible
        ),
        "denominator_note": "Means include scenes with finished attempts; pending scenes are not silently counted as passes. API/infrastructure failures remain in the measured denominator.",
    }
    save(suite / "suite.json", manifest)
    for lang in ["en", "zh"]:
        chinese = lang == "zh"
        lines = [
            "# " + ("回退重试实验" if chinese else "Rollout recovery experiment"),
            "",
            (
                "回退 5 步；同一区域最多重试 3 次。首次尝试与重试后覆盖率分别统计。"
                if chinese
                else "Rewind 5 steps; at most 3 retries per failure site. First-pass and recovered coverage are separate."
            ),
            "",
            (
                "覆盖率为通过已实现采样检查的连续时间比例，不代表到达目的地或通过全部交通规则。"
                if chinese
                else "Coverage is continuous simulated time passing implemented sampled checks, not destination completion or all-rule compliance."
            ),
            "",
            "| Scene | Status | First pass | Best branch | Retries | Results |",
            "|---|---|---:|---:|---:|---|",
        ]
        for item in manifest["scenes"]:
            out = Path(item.get("output", suite / ("scene-" + item["tag"])))
            path = out / "experiment.json"
            report = json.loads(path.read_text()) if path.is_file() else {}
            m = report.get("metrics", {})
            percent = lambda k: f"{100*m[k]:.1f}%" if k in m else "—"
            link = f"[JSON]({out.name}/experiment.json)" if path.is_file() else "—"
            lines.append(
                f"| {item['tag']} | {report.get('status',item['status'])} | {percent('first_attempt_safe_time_coverage')} | {percent('best_branch_safe_time_coverage')} | {m.get('retries','—')} | {link} |"
            )
            for number, attempt_record in enumerate(report.get("attempts", [])):
                attempt = Path(attempt_record["output"])
                for media in sorted(attempt.glob("previews/*/*-" + lang + ".gif")) + sorted(attempt.glob("previews/status-" + lang + ".png")):
                    lines.append(f"[{item['tag']} / attempt-{number:02d} / {media.parent.name}]({media.relative_to(suite)})")
        # Keep table rows contiguous; preview links belong after the table.
        table = [line for line in lines if line.startswith("|")]
        front = lines[: lines.index(table[0])]
        links = [line for line in lines if line.startswith("[")]
        (suite / ("README.md" if chinese else "README.en.md")).write_text(
            "\n".join(front + table + [""] + links) + "\n"
        )


async def run_suite(args):
    suite = Path(args.output).resolve()
    suite.mkdir(parents=True, exist_ok=True)
    if (suite / "suite.json").exists():
        raise ValueError("use a new suite output directory")
    config = Config.load(args.config)
    scenes = json.loads(Path(args.manifest).read_text())["scenes"]
    manifest = {
        "status": "running",
        "scenes": [],
        "rewind_steps": 5,
        "max_retries_per_site": 3,
        "sample_interval_us": 50000,
        "prompt_version": VERSION,
    }
    for scene in scenes:
        manifest["scenes"].append(
            {
                "seed_log": scene.get("seed_log"),
                "tag": scene["tag"],
                "artifact": scene["artifact"],
                "status": "queued",
                "output": str(suite / ("scene-" + scene["tag"])),
            }
        )
    save(suite / "config.json", config.as_dict())
    update(suite, manifest)
    for item in manifest["scenes"]:
        item["status"] = "preflight"
        update(suite, manifest)
        out = Path(item["output"])
        try:
            from alpasim_utils.artifact import Artifact

            data = Artifact(item["artifact"], _smooth_trajectories=False)
            stamps = data.rig.trajectory.timestamps_us
            steps = (int(stamps[-1]) - int(stamps[0])) // round(
                config.decision_dt_s * 1e6
            ) - 1
            item["steps"] = steps
            del data
            item["status"] = "running"
            update(suite, manifest)
            seed = item.get("seed_log") or (args.seed_log if item["tag"] == args.seed_tag else None)
            result = await run_scene(
                item["artifact"], config, out, steps, seed_log=seed
            )
            item["status"] = result["status"]
            if args.render_script:
                from .previews import render_attempts
                item["attempt_previews"] = await render_attempts(result, item["artifact"], args.render_script)
                item["preview_status"] = "completed" if all(p["status"] == "completed" for p in item["attempt_previews"]) else "failed"
            if any(
                any(
                    "JEV HTTP " + str(code) in str(a.get("error"))
                    for code in [401, 402, 403]
                )
                for a in result["attempts"]
            ):
                manifest["status"] = "stopped_api_access_or_credit_error"
                update(suite, manifest)
                return
        except asyncio.CancelledError:
            item["status"] = "interrupted"
            manifest["status"] = "interrupted"
            update(suite, manifest)
            raise
        except Exception as exc:
            item.update(
                status="infrastructure_failed",
                error=type(exc).__name__ + ": " + str(exc)[:500],
            )
        update(suite, manifest)
    manifest["status"] = "finished"
    update(suite, manifest)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--render-script")
    p.add_argument("--seed-log")
    p.add_argument("--seed-tag", default="07054c19")
    asyncio.run(run_suite(p.parse_args()))


if __name__ == "__main__":
    main()

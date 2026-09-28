#!/usr/bin/env python3
"""Offline actor-filter audit and before/after previews; no model calls."""

import argparse
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.font_manager import FontProperties
import imageio.v2 as imageio
from jev_drive.config import Config
from jev_drive.integration.alpasim_adapter import AlpasimAdapter, actor_records
from jev_drive.state.actor_filter import filter_actors, VERSION

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run", type=Path, required=True)
parser.add_argument("--render", action="store_true")
args = parser.parse_args()
manifest = json.loads((args.run / "scene-manifest.json").read_text())
scene, artifact = next(iter(manifest.items()))
adapter = AlpasimAdapter(artifact, Config())
rows = []
for line in (args.run / "decisions.jsonl").read_text().splitlines():
    try:
        r = json.loads(line)
    except ValueError:
        continue
    if r.get("event") == "decision":
        rows.append(r)
out = args.run / "actor-cleanup"
out.mkdir(exist_ok=True)
entries = []
for row in rows:
    raw = actor_records(adapter.artifact.traffic_objects, row["timestamp_us"])
    clean, audit = filter_actors(raw)
    submitted = {a["id"] for a in row["state"]["actors"]}
    audit["removed_ids_in_original_JEV_input"] = sorted(
        {a["id"] for a in audit["removed"]} & submitted
    )
    pose = adapter.artifact.rig.trajectory.interpolate_pose(row["timestamp_us"])
    inverse = Rotation.from_quat(pose.quat).inv()
    removed_ids = {a["id"] for a in audit["removed"]}
    visible = []
    for actor in raw:
        xyz = inverse.apply(np.asarray(actor["position_world_m"]) - pose.vec3)
        if actor["id"] in removed_ids and -25 < xyz[0] < 80 and abs(xyz[1]) < 24:
            visible.append(actor["id"])
    audit["removed_ids_in_GT_preview"] = visible
    entries.append(
        {
            "step": row["step_index"],
            "timestamp_us": row["timestamp_us"],
            "raw_actors": raw,
            "filtered_actors": clean,
            "audit": audit,
        }
    )
with (out / "filtered-actors.jsonl").open("w") as f:
    for entry in entries:
        f.write(json.dumps(entry, allow_nan=False) + "\n")
summary = {
    "scene_id": scene,
    "filter_version": VERSION,
    "source": "Offline source-track audit; original rollout unchanged",
    "frames": len(entries),
    "affected_frames": sum(bool(e["audit"]["removed"]) for e in entries),
    "removed_actor_observations": sum(len(e["audit"]["removed"]) for e in entries),
    "unique_removed_ids": sorted(
        {a["id"] for e in entries for a in e["audit"]["removed"]}
    ),
    "affected_original_JEV_inputs": sum(
        bool(e["audit"]["removed_ids_in_original_JEV_input"]) for e in entries
    ),
    "remaining_overlap_observations": sum(
        len(e["audit"]["retained_overlap_pairs"]) for e in entries
    ),
    "remaining_overlap_pairs": sorted(
        {tuple(p["ids"]) for e in entries for p in e["audit"]["retained_overlap_pairs"]}
    ),
}
(out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary), flush=True)
if not args.render:
    raise SystemExit(0)
font = FontProperties(fname="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
for lang in ["zh", "en"]:
    images = []
    for i, entry in enumerate(entries):
        pose = adapter.artifact.rig.trajectory.interpolate_pose(entry["timestamp_us"])
        rot = Rotation.from_quat(pose.quat).inv()

        def points(xyz):
            p = rot.apply(np.asarray(xyz) - pose.vec3)
            return np.c_[-p[:, 1], p[:, 0]]

        removed = {a["id"] for a in entry["audit"]["removed"]}
        fig, axes = plt.subplots(1, 2, figsize=(10, 7))
        fig.subplots_adjust(left=0.04, right=0.96, bottom=0.12, top=0.83, wspace=0.08)
        elapsed = (entry["timestamp_us"] - entries[0]["timestamp_us"]) / 1e6
        visible_removed = len(entry["audit"]["removed_ids_in_GT_preview"])
        title = (
            f"重叠目标清理 · {elapsed:.1f} s · 画面内移除 {visible_removed} 个目标"
            if lang == "zh"
            else f"Actor overlap filtering | {elapsed:.1f} s | {visible_removed} suppressed in view"
        )
        fig.text(0.5, 0.95, title, ha="center", fontproperties=font, fontsize=14)
        fig.text(
            0.5,
            0.895,
            (
                "GT 视角 · 离线数据对比，非重新驾驶结果"
                if lang == "zh"
                else "GT camera | Offline data comparison, not a new driving rollout"
            ),
            ha="center",
            fontproperties=font,
            fontsize=10,
        )
        for ax, actors, label in zip(
            axes,
            [entry["raw_actors"], entry["filtered_actors"]],
            [
                "清理前" if lang == "zh" else "Before",
                "清理后" if lang == "zh" else "After",
            ],
        ):
            for lane in adapter.lanes:
                for key in ["left_edge_world", "right_edge_world"]:
                    if lane[key]:
                        p = points(lane[key])
                        ax.plot(p[:, 0], p[:, 1], color="#d5dae0", lw=0.6, zorder=0)
            for a in actors:
                pos = np.array(a["position_world_m"])
                p = points([pos])[0]
                if not (-24 < p[0] < 24 and -25 < p[1] < 80):
                    continue
                length, width = a["dimensions_m"][:2]
                corners = np.array(
                    [
                        [length / 2, width / 2, 0],
                        [length / 2, -width / 2, 0],
                        [-length / 2, -width / 2, 0],
                        [-length / 2, width / 2, 0],
                    ]
                )
                xy = points(
                    Rotation.from_quat(a["quaternion_xyzw"]).apply(corners) + pos
                )
                color = "#d94841" if a["id"] in removed else "#238a68"
                ax.add_patch(
                    Polygon(
                        xy,
                        fc=color,
                        ec=color,
                        alpha=0.35 if a["id"] in removed else 0.75,
                        lw=1.4,
                        zorder=2,
                    )
                )
                if a["id"] in removed:
                    ax.text(
                        *p,
                        a["id"],
                        fontsize=8,
                        color="#9d1c16",
                        weight="bold",
                        zorder=4,
                    )
            ax.scatter(0, 0, c="#1d4ed8", marker="^", s=35, zorder=5)
            ax.set(xlim=(-24, 24), ylim=(-25, 80))
            ax.set_aspect("equal")
            ax.axis("off")
            ax.set_title(label, fontproperties=font, fontsize=12)
        fig.text(
            0.5,
            0.035,
            (
                "红色：画面内移除的疑似重复框　绿色：保留目标　蓝色：GT 自车位置\n其余交叠保留供复查；几乎同位置框可按几何证据去重，详见审计日志。"
                if lang == "zh"
                else "Red: suspected duplicate suppressed in this frame | Green: retained | Blue: GT ego\nOther overlaps remain for review; see audit evidence for the coincident-box exception."
            ),
            ha="center",
            fontproperties=font,
            fontsize=9,
            linespacing=1.5,
        )
        fig.canvas.draw()
        images.append(np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy())
        if i == max(
            range(len(entries)),
            key=lambda n: len(entries[n]["audit"]["removed_ids_in_GT_preview"]),
        ):
            fig.savefig(out / f"example-{lang}.png", dpi=120)
        plt.close(fig)
    imageio.mimsave(out / f"before-after-{lang}.gif", images, duration=200, loop=0)

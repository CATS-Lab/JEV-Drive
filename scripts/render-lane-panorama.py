#!/usr/bin/env python3
"""Render a horizontal GT/JEV panorama with stable lane colors from saved logs."""

import argparse
import csv
import json
import struct
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import imageio.v2 as imageio

from alpasim_grpc.v0.logging_pb2 import LogEntry
from alpasim_utils.geometry import pose_from_grpc
from matplotlib.font_manager import FontProperties
from jev_drive.config import Config
from jev_drive.integration.alpasim_adapter import AlpasimAdapter, actor_records

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--steps", type=int, default=65)
parser.add_argument("--artifact", type=Path, required=True)
args = parser.parse_args()
rows = []
for line in (args.run / "decisions.jsonl").read_text().splitlines():
    try:
        row = json.loads(line)
    except ValueError:
        continue
    if row.get("event") == "decision":
        rows.append(row)
if args.steps < 1:
    raise SystemExit("--steps must be positive")
rows = rows[: args.steps]
if not rows:
    raise SystemExit("No completed decisions")
poses = {}
for p in (args.run / "controller").glob("*.csv"):
    for row in csv.DictReader(p.open()):
        try:
            t = int(row["timestamp_us"])
            pos = np.array([float(row[k]) for k in ["x", "y", "z"]])
            rot = Rotation.from_quat([float(row[k]) for k in ["qx", "qy", "qz", "qw"]])
        except (ValueError, KeyError, TypeError):
            continue
        poses[t] = (pos, rot)
# Read complete records only: the active writer may have a partial last record.

for log in (args.run / "rollouts").glob("*/*/rollout.asl"):
    data = log.read_bytes()
    offset = 0
    while offset + 4 <= len(data):
        size = struct.unpack_from(">L", data, offset)[0]
        offset += 4
        if offset + size > len(data):
            break
        entry = LogEntry.FromString(data[offset : offset + size])
        offset += size
        if entry.WhichOneof("log_entry") == "controller_return":
            for state in entry.controller_return.states:
                pose = pose_from_grpc(state.pose_local_to_rig)
                t = state.timestamp_us
                pos = np.asarray(pose.vec3, dtype=float)
                rot = Rotation.from_quat(np.asarray(pose.quat, dtype=float))
                if t in poses:
                    assert np.allclose(
                        poses[t][0], pos, atol=1e-4
                    ), "Pose sources disagree"
                poses[t] = (pos, rot)
missing = [r["timestamp_us"] for r in rows if r["timestamp_us"] not in poses]
if missing:
    raise SystemExit(f"Missing controller pose for {len(missing)} decision timestamps")


adapter = AlpasimAdapter(args.artifact, Config())
assert adapter.artifact.scene_id == rows[0]["scene_id"]
origin, orientation = poses[rows[0]["timestamp_us"]]
fixed_rotation = orientation.inv()


def fixed(xyz):
    return fixed_rotation.apply(np.asarray(xyz) - origin)[:, :2]


parent = {lane["id"]: lane["id"] for lane in adapter.lanes}


def root(key):
    while parent[key] != key:
        key = parent[key]
    return key


for lane in adapter.lanes:
    for nxt in lane["successors"]:
        if nxt in parent:
            parent[root(nxt)] = root(lane["id"])
# Seed lane numbers at the initial ego cross-section, in the ego travel direction.
seeds = []
for lane in adapter.lanes:
    p = fixed(lane["center_world"])
    if p[0, 0] < 1.4675 < p[-1, 0]:
        y = np.interp(1.4675, p[:, 0], p[:, 1])
        if abs(y) < 12:
            seeds.append((float(y), lane["id"]))
seeds.sort(reverse=True)
assert (
    len(seeds) == 4
), "This four-lane example requires four initial same-direction lanes"
assert (
    len({root(sid) for _, sid in seeds}) == 4
), "Lane branches merge; cannot assign stable labels"
labels = {
    lane["id"]: next(
        (
            f"L{i+1}"
            for i, (_, sid) in enumerate(seeds)
            if root(lane["id"]) == root(sid)
        ),
        None,
    )
    for lane in adapter.lanes
}
colors = {"L1": "#e6c6ef", "L2": "#b9d9f5", "L3": "#ffe0a3", "L4": "#bce8d5"}
times = [r["timestamp_us"] for r in rows]
gt_poses = [adapter.artifact.rig.trajectory.interpolate_pose(t) for t in times]
gt_track = fixed([p.vec3 for p in gt_poses])
jev_track = fixed([poses[t][0] for t in times])
xmin = -10
xmax = float(max(gt_track[:, 0].max(), jev_track[:, 0].max())) + 27
ymin, ymax = -6.5, 11.5
out = args.output
out.mkdir(parents=True, exist_ok=True)
font_path = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
font = FontProperties(fname=str(font_path))
traffic = [actor_records(adapter.artifact.traffic_objects, t) for t in times]


def body(ax, pos, rot, center, dimensions, color, edge="white", alpha=1):
    length, width = dimensions[:2]
    xy = np.array(
        [
            [length / 2, width / 2],
            [length / 2, -width / 2],
            [-length / 2, -width / 2],
            [-length / 2, width / 2],
        ]
    )
    xyz = np.c_[xy, np.zeros(4)] + center
    points = fixed(rot.apply(xyz) + pos)
    ax.add_patch(Polygon(points, fc=color, ec=edge, lw=0.6, alpha=alpha, zorder=6))


for language in ["en", "zh"]:
    frames = []
    for i, row in enumerate(rows):
        fig, axes = plt.subplots(2, 1, figsize=(12, 3.3))
        fig.subplots_adjust(left=0.045, right=0.99, bottom=0.23, top=0.73, hspace=0.5)
        elapsed = (times[i] - times[0]) / 1e6
        title = (
            f"同向 4 车道 · GT：L3 → L2 → L3 · {elapsed:.1f} s"
            if language == "zh"
            else f"4 same-direction lanes | GT: L3 > L2 > L3 | {elapsed:.1f} s"
        )
        fig.text(0.5, 0.92, title, ha="center", fontproperties=font, fontsize=15)
        subtitle = (
            "固定视角 · 向右行驶 → · L1–L4 从行驶方向左侧至右侧编号"
            if language == "zh"
            else "Fixed camera | Travel right > | L1–L4: left to right in travel direction"
        )
        fig.text(0.5, 0.83, subtitle, ha="center", fontproperties=font, fontsize=10)
        for ax, name, track in zip(axes, ["GT", "JEV"], [gt_track, jev_track]):
            for lane in adapter.lanes:
                label = labels[lane["id"]]
                if not label:
                    continue
                center = fixed(lane["center_world"])
                if center[:, 0].max() < xmin or center[:, 0].min() > xmax:
                    continue
                left, right = lane["left_edge_world"], lane["right_edge_world"]
                if left and right:
                    p = fixed(left + right[::-1])
                    ax.add_patch(
                        Polygon(p, fc=colors[label], ec="none", alpha=0.65, zorder=0)
                    )
                ax.plot(center[:, 0], center[:, 1], color="#668097", ls="--", lw=0.6)
                for edge in [left, right]:
                    if edge:
                        p = fixed(edge)
                        ax.plot(p[:, 0], p[:, 1], color="#555555", lw=0.6)
            for j, (y, _) in enumerate(seeds):
                ax.text(
                    -5,
                    y,
                    f"L{j+1}",
                    ha="center",
                    va="center",
                    fontsize=9,
                    weight="bold",
                    bbox=dict(
                        fc=colors[f"L{j+1}"], ec="white", boxstyle="round,pad=.15"
                    ),
                    zorder=9,
                )
            ax.plot(track[: i + 1, 0], track[: i + 1, 1], c="#087f8c", lw=1.6, zorder=4)
            for obj in traffic[i]:
                p = fixed([obj["position_world_m"]])[0]
                if xmin < p[0] < xmax and ymin < p[1] < ymax:
                    body(
                        ax,
                        np.array(obj["position_world_m"]),
                        Rotation.from_quat(obj["quaternion_xyzw"]),
                        [0, 0, 0],
                        obj["dimensions_m"],
                        "#c65e5e",
                        alpha=0.8,
                    )
            ego = row["state"]["ego"]
            pos, rot = (
                (gt_poses[i].vec3, Rotation.from_quat(gt_poses[i].quat))
                if name == "GT"
                else poses[times[i]]
            )
            body(
                ax,
                pos,
                rot,
                ego["box_center_rig_m"],
                [ego["length_m"], ego["width_m"]],
                "#13865b",
                "#064d35",
            )
            ax.set(xlim=(xmin, xmax), ylim=(ymin, ymax))
            ax.set_aspect("equal")
            ax.axis("off")
            ax.text(
                -0.01,
                0.5,
                name,
                transform=ax.transAxes,
                ha="right",
                va="center",
                fontsize=12,
                weight="bold",
            )
        footer = (
            "绿色：自车　红色：其他车辆　青色：已行驶轨迹；两行同一时间、同一比例\n高速公路属性未确认；地图边界不代表实际标线类型。"
            if language == "zh"
            else "Green: ego | Red: traffic | Teal: driven path | Matching timestamps and scale\nHighway classification unverified; map boundaries do not identify painted marking types."
        )
        fig.text(
            0.5,
            0.04,
            footer,
            ha="center",
            fontproperties=font,
            fontsize=10,
            linespacing=1.6,
        )
        fig.canvas.draw()
        frames.append(np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy())
        if i == len(rows) - 1:
            fig.savefig(out / f"panorama-{language}.png", dpi=120)
        plt.close(fig)
    imageio.mimsave(
        out / f"gt-vs-jev-panorama-{language}.gif", frames, duration=200, loop=0
    )
(out / "panorama-metadata.json").write_text(
    json.dumps(
        {
            "scene_id": rows[0]["scene_id"],
            "frames": len(rows),
            "time_span_s": (times[-1] - times[0]) / 1e6,
            "frame_duration_ms": 200,
            "frame": "Fixed initial ego pose; forward is right",
            "gt_source": "Original recorded rig trajectory, interpolated at JEV decision timestamps",
            "ego_geometry": "Same simulated vehicle footprint for both trajectories",
            "lane_ids": {key: value for key, value in labels.items() if value},
            "road_type": "unverified",
            "same_direction_lanes": len(seeds),
        },
        indent=2,
    )
    + "\n"
)
print(out)

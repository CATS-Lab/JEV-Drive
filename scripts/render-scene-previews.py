#!/usr/bin/env python3
"""Render paired panorama and lane close-up previews for a saved AlpaSim run."""

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

import colorsys
from shapely.geometry import LineString, Point, Polygon as ShapePolygon

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run", type=Path, required=True)
parser.add_argument("--steps", type=int, default=100000)
parser.add_argument("--artifact", type=Path, required=True)
parser.add_argument("--views", choices=["both", "panorama", "lanes"], default="both")
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
times = [r["timestamp_us"] for r in rows]
gt_poses = [adapter.artifact.rig.trajectory.interpolate_pose(t) for t in times]
origin, orientation = poses[times[0]]
fixed_rotation = orientation.inv()


def fixed(xyz):
    return fixed_rotation.apply(np.asarray(xyz) - origin)[:, :2]


tracks = {
    "GT": fixed([p.vec3 for p in gt_poses]),
    "JEV": fixed([poses[t][0] for t in times]),
}
# Join only one-to-one connections. Never merge distinct branches into one lane.
by_id = {lane["id"]: lane for lane in adapter.lanes}
parents = {k: k for k in by_id}
successors = {
    k: [s for s in lane["successors"] if s in by_id] for k, lane in by_id.items()
}
predecessors = {k: [] for k in by_id}
for k, nxt in successors.items():
    for n in nxt:
        predecessors[n].append(k)


def root(k):
    while parents[k] != k:
        k = parents[k]
    return k


for k, nxt in successors.items():
    if len(nxt) == 1 and len(predecessors[nxt[0]]) == 1:
        parents[root(nxt[0])] = root(k)
chain_roots = sorted({root(k) for k in by_id})
label_for_root = {k: f"L{i+1}" for i, k in enumerate(chain_roots)}
label_map = {k: label_for_root[root(k)] for k in by_id}
colors = {
    label: colorsys.hls_to_rgb((i * 0.61803398875) % 1, 0.84, 0.65)
    for i, label in enumerate(label_for_root.values())
}
geometry = []
for lane in adapter.lanes:
    center = np.asarray(lane["center_world"])
    left = np.asarray(lane["left_edge_world"])
    right = np.asarray(lane["right_edge_world"])
    poly = None
    if len(left) > 1 and len(right) > 1:
        poly = ShapePolygon(np.concatenate([left[:, :2], right[::-1, :2]]))
        if not poly.is_valid:
            poly = None
    geometry.append(
        dict(
            id=lane["id"],
            label=label_map[lane["id"]],
            center=center,
            left=left,
            right=right,
            poly=poly,
        )
    )
font = FontProperties(fname="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
preview = args.run / "previews"
pan_dir = preview / f"labeled-panorama-{len(rows):03d}"
close_dir = preview / f"labeled-lanes-{len(rows):03d}"
for folder in [pan_dir, close_dir]:
    folder.mkdir(parents=True, exist_ok=True)
cloud = np.concatenate(list(tracks.values()))
xmin, ymin = cloud.min(axis=0) - [15, 18]
xmax, ymax = cloud.max(axis=0) + [25, 18]
# Keep a landscape overview even on scenes with lateral turns.
height = ymax - ymin
if xmax - xmin < height * 1.8:
    mid = (xmin + xmax) / 2
    xmin = mid - height * 0.9
    xmax = mid + height * 0.9
traffic = [actor_records(adapter.artifact.traffic_objects, t) for t in times]
metrics = []


def pose_for(name, i):
    return (
        (np.asarray(gt_poses[i].vec3), Rotation.from_quat(gt_poses[i].quat))
        if name == "GT"
        else poses[times[i]]
    )


def footprint(pos, rot, center, length, width):
    xy = np.array(
        [
            [length / 2, width / 2],
            [length / 2, -width / 2],
            [-length / 2, -width / 2],
            [-length / 2, width / 2],
        ]
    )
    return rot.apply(np.c_[xy, np.zeros(4)] + center) + pos


for i, r in enumerate(rows):
    for name in ["GT", "JEV"]:
        pos, rot = pose_for(name, i)
        e = r["state"]["ego"]
        corners = footprint(
            pos, rot, e["box_center_rig_m"], e["length_m"], e["width_m"]
        )
        body = ShapePolygon(corners[:, :2])
        center = Point((rot.apply(e["box_center_rig_m"]) + pos)[:2])
        inside = set()
        cross = False
        for g in geometry:
            if g["poly"] is not None and g["poly"].covers(center):
                inside.add(g["label"])
            for edge in [g["left"], g["right"]]:
                if len(edge) > 1 and body.intersects(LineString(edge[:, :2])):
                    cross = True
        metrics.append(
            {
                "step": r["step_index"],
                "source": name,
                "timestamp_us": times[i],
                "center_lanes": sorted(inside),
                "boundary_overlap": cross,
            }
        )

for mode, folder in [("panorama", pan_dir), ("lanes", close_dir)]:
    if args.views not in ("both", mode):
        continue
    for lang in ["zh", "en"]:
        frames = []
        for i, r in enumerate(rows):
            panorama = mode == "panorama"
            if panorama:
                panorama_height = max(
                    7.5, 2 * 13.0 * (ymax - ymin) / (xmax - xmin) / 0.70
                )
                fig, axes = plt.subplots(2, 1, figsize=(14, panorama_height))
                fig.subplots_adjust(
                    left=0.035, right=0.985, bottom=0.14, top=0.85, hspace=0.24
                )
            else:
                fig, axes = plt.subplots(1, 2, figsize=(11, 7.8))
                fig.subplots_adjust(
                    left=0.03, right=0.97, bottom=0.16, top=0.81, wspace=0.07
                )
            elapsed = (times[i] - times[0]) / 1e6
            title = (
                f"GT / JEV · 多车道场景 · {elapsed:.1f} s"
                if lang == "zh"
                else f"GT / JEV | Multi-lane scene | {elapsed:.1f} s"
            )
            fig.text(0.5, 0.95, title, ha="center", fontproperties=font, fontsize=15)
            subtitle = (
                ("固定视角，初始前方朝右 →" if panorama else "各自跟随自车，前方朝上 ↑")
                if lang == "zh"
                else (
                    "Fixed camera; initial forward is right >"
                    if panorama
                    else "Each view follows its ego; forward is up"
                )
            )
            fig.text(
                0.5, 0.895, subtitle, ha="center", fontproperties=font, fontsize=10
            )
            for ax, name in zip(axes, ["GT", "JEV"]):
                pos, rot = pose_for(name, i)

                def transform(xyz):
                    if panorama:
                        return fixed(xyz)
                    local = rot.inv().apply(np.asarray(xyz) - pos)
                    return np.c_[-local[:, 1], local[:, 0]]

                bounds = (xmin, xmax, ymin, ymax) if panorama else (-14, 14, -7, 23)
                annotations = {}
                for g in geometry:
                    cp = transform(g["center"])
                    if (
                        cp[:, 0].max() < bounds[0]
                        or cp[:, 0].min() > bounds[1]
                        or cp[:, 1].max() < bounds[2]
                        or cp[:, 1].min() > bounds[3]
                    ):
                        continue
                    label = g["label"]
                    if g["poly"] is not None:
                        poly = transform(np.concatenate([g["left"], g["right"][::-1]]))
                        ax.add_patch(
                            Polygon(
                                poly, fc=colors[label], ec="none", alpha=0.8, zorder=0
                            )
                        )
                    ax.plot(cp[:, 0], cp[:, 1], color="#758596", ls="--", lw=0.6)
                    for edge in [g["left"], g["right"]]:
                        if len(edge) > 1:
                            p = transform(edge)
                            ax.plot(p[:, 0], p[:, 1], color="#555555", lw=0.8)
                    # One label per continuous chain in each viewport.
                    visible = cp[
                        (cp[:, 0] > bounds[0] + 1)
                        & (cp[:, 0] < bounds[1] - 1)
                        & (cp[:, 1] > bounds[2] + 1)
                        & (cp[:, 1] < bounds[3] - 1)
                    ]
                    if len(visible):
                        target = (
                            np.array([(xmin + xmax) / 2, (ymin + ymax) / 2])
                            if panorama
                            else np.array([0, 13])
                        )
                        idx = np.argmin(np.linalg.norm(visible - target, axis=1))
                        point = visible[idx]
                        dist = np.linalg.norm(point - target)
                        if label not in annotations or dist < annotations[label][0]:
                            annotations[label] = (dist, point)
                # Omit remote-map labels in the panorama; retain all nearby labels in the close-up.
                for label, (_, p) in annotations.items():
                    if (
                        panorama
                        and min(
                            np.linalg.norm(t - p, axis=1).min() for t in tracks.values()
                        )
                        > 12
                    ):
                        continue
                    ax.text(
                        *p,
                        label,
                        ha="center",
                        va="center",
                        fontsize=7 if panorama else 10,
                        weight="bold",
                        bbox=dict(
                            fc=colors[label], ec="white", boxstyle="round,pad=.15"
                        ),
                        zorder=8,
                    )
                if panorama:
                    ax.plot(
                        tracks[name][: i + 1, 0],
                        tracks[name][: i + 1, 1],
                        color="#087f8c",
                        lw=1.5,
                        zorder=4,
                    )
                for obj in traffic[i]:
                    p = transform([obj["position_world_m"]])[0]
                    if bounds[0] < p[0] < bounds[1] and bounds[2] < p[1] < bounds[3]:
                        corners = footprint(
                            np.asarray(obj["position_world_m"]),
                            Rotation.from_quat(obj["quaternion_xyzw"]),
                            [0, 0, 0],
                            *obj["dimensions_m"][:2],
                        )
                        ax.add_patch(
                            Polygon(
                                transform(corners),
                                fc="#c65e5e",
                                ec="white",
                                lw=0.4,
                                alpha=0.8,
                                zorder=5,
                            )
                        )
                e = r["state"]["ego"]
                corners = footprint(
                    pos, rot, e["box_center_rig_m"], e["length_m"], e["width_m"]
                )
                m = metrics[2 * i + (name == "JEV")]
                ax.add_patch(
                    Polygon(
                        transform(corners),
                        fc="#13865b",
                        ec="#c22c2c" if m["boundary_overlap"] else "#064d35",
                        lw=1.5,
                        zorder=7,
                    )
                )
                lanes = "/".join(m["center_lanes"]) or (
                    "未知/地图外" if lang == "zh" else "unknown/outside map"
                )
                status = (
                    ("跨边界" if m["boundary_overlap"] else "未跨边界")
                    if lang == "zh"
                    else (
                        "boundary overlap"
                        if m["boundary_overlap"]
                        else "clear of boundaries"
                    )
                )
                ax.set_title(
                    f"{name} | {lanes} | {status}", fontproperties=font, fontsize=10
                )
                ax.set(xlim=bounds[:2], ylim=bounds[2:])
                ax.set_aspect("equal")
                ax.axis("off")
            footer = (
                "编号和颜色对应无分支连接的车道段；路口分叉处重新编号，编号改变不一定代表换道\n绿色：自车　红色：交通车辆　红色轮廓：自车跨地图边界　青色：已行驶轨迹\n道路类型未确认；地图边界不代表实际标线类型。"
                if lang == "zh"
                else "Stable IDs/colors join one-to-one lane segments; IDs change at branches, not necessarily lane changes\nGreen: ego | Red: traffic | Red ego outline: mapped boundary overlap | Teal: driven path\nRoad classification unverified; map edges do not identify painted marking types."
            )
            fig.text(
                0.5,
                0.025,
                footer,
                ha="center",
                fontproperties=font,
                fontsize=9,
                linespacing=1.5,
            )
            fig.canvas.draw()
            frames.append(np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy())
            if i in [0, len(rows) // 2, len(rows) - 1]:
                fig.savefig(folder / f"frame-{i:03d}-{lang}.png", dpi=100)
            plt.close(fig)
        imageio.mimsave(
            folder / f"gt-vs-jev-{mode}-{lang}.gif", frames, duration=200, loop=0
        )
        print(mode, lang, "done", flush=True)
metadata = {
    "scene_id": rows[0]["scene_id"],
    "frames": len(rows),
    "span_s": (times[-1] - times[0]) / 1e6,
    "frame_duration_ms": 200,
    "labels": "One-to-one map-lane chains; new IDs at branches, not necessarily lane changes",
    "source_artifact": str(args.artifact),
    "label_map": label_map,
}
for mode, folder in [("panorama", pan_dir), ("lanes", close_dir)]:
    if args.views not in ("both", mode):
        continue
    metadata["layout"] = "GT above JEV" if mode == "panorama" else "GT left, JEV right"
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
(close_dir / "lane-associations.json").write_text(json.dumps(metrics, indent=2) + "\n")

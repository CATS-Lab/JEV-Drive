#!/usr/bin/env python3
"""Fixed scene view from saved decisions and timestamp-matched controller poses."""

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

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--steps", type=int, default=18)
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
from alpasim_grpc.v0.logging_pb2 import LogEntry
from alpasim_utils.geometry import pose_from_grpc

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
origin, orientation = poses[rows[0]["timestamp_us"]]
fixed_rotation = orientation.inv()
t0 = rows[0]["timestamp_us"]
out = args.output
out.mkdir(parents=True, exist_ok=True)


def points(event, xy):
    data = np.asarray(xy, dtype=float)
    if data.shape[1] == 2:
        data = np.column_stack([data, np.zeros(len(data))])
    pos, rot = poses[event["timestamp_us"]]
    fixed = fixed_rotation.apply(rot.apply(data) + pos - origin)
    return np.column_stack([-fixed[:, 1], fixed[:, 0]])


def line(ax, event, seg, **kw):
    if seg:
        p = points(event, seg)
        ax.plot(p[:, 0], p[:, 1], **kw)


def vehicle(ax, event, x, y, h, length, width, color):
    corners = np.array(
        [
            [length / 2, width / 2],
            [length / 2, -width / 2],
            [-length / 2, -width / 2],
            [-length / 2, width / 2],
        ]
    )
    c, s = np.cos(h), np.sin(h)
    xy = corners @ np.array([[c, s], [-s, c]]) + [x, y]
    ax.add_patch(
        Polygon(points(event, xy), facecolor=color, edgecolor="white", lw=0.5, zorder=6)
    )


track = np.array(
    [fixed_rotation.apply(poses[r["timestamp_us"]][0] - origin) for r in rows]
)
plot_track = np.column_stack([-track[:, 1], track[:, 0]])
# Fixed viewport across every frame, covering the actor context and reference horizons.
cloud = np.concatenate(
    [
        points(
            r,
            [[a["x_m"], a["y_m"]] for a in r["state"]["actors"]]
            + r["trajectory"]["xy_m"]
            + [[0, 0]],
        )
        for r in rows
    ]
)
xmin, xmax = min(-23, float(cloud[:, 0].min()) - 3), max(
    23, float(cloud[:, 0].max()) + 3
)
ymin, ymax = min(-22, float(cloud[:, 1].min()) - 3), max(
    85, float(cloud[:, 1].max()) + 5
)
# Sample overlapping map crops along the drive to keep longer previews continuous.
background = rows[::10]
if background[-1] is not rows[-1]:
    background.append(rows[-1])
all_pose_times = sorted(t for t in poses if t >= t0 and t <= rows[-1]["timestamp_us"])
all_pose_positions = np.array([poses[t][0] for t in all_pose_times])
distance = np.r_[
    0, np.cumsum(np.linalg.norm(np.diff(all_pose_positions, axis=0), axis=1))
]
distance_at = dict(zip(all_pose_times, distance))


def draw(ax, i, detail=True):
    r = rows[i]
    s = r["state"]
    for bg in background:
        for lane in bg["state"]["road"]["lanes"]:
            for seg in lane["centerline_segments"]:
                line(ax, bg, seg, color="#c1c7d0", lw=0.6, zorder=1)
            for side in ["left_boundary", "right_boundary"]:
                for seg in lane[side]["segments"]:
                    line(ax, bg, seg, color="#e2e5e9", lw=0.45, zorder=1)
    for bg in background:
        for seg in bg["state"]["navigation"].get("route_segments", []):
            line(ax, bg, seg, color="#228be6", lw=1.4, label=None, zorder=2)
    for a in s["actors"]:
        vehicle(
            ax,
            r,
            a["x_m"],
            a["y_m"],
            a["heading_rad"],
            a["length_m"],
            a["width_m"],
            "#c65e5e",
        )
        p = points(r, [[a["x_m"], a["y_m"]]])[0]
        if detail:
            ax.annotate(
                a["id"], p, xytext=(4, 2), textcoords="offset points", fontsize=7
            )
    for item in s["traffic_controls"]["stop_lines"]:
        for seg in item["segments"]:
            line(ax, r, seg, color="#d9480f", lw=2)
    for item in s["traffic_controls"]["signs"]:
        p = points(r, [item["position_m"]])[0]
        ax.scatter(*p, marker="^", c="purple", s=25)
    for item in s["traffic_controls"]["signals"]:
        p = points(r, [item["position_m"]])[0]
        ax.scatter(
            *p,
            c={"red": "red", "green": "green", "yellow": "gold"}.get(
                item["phase"], "gray"
            ),
            s=25,
        )
    hist = all_pose_positions[: all_pose_times.index(r["timestamp_us"]) + 1]
    h = fixed_rotation.apply(hist - origin)
    ax.plot(-h[:, 1], h[:, 0], color="#0b7285", lw=3, zorder=4, label="Actual ego path")
    line(ax, r, r["trajectory"]["xy_m"], color="#2f9e44", ls="--", lw=1.4, zorder=3)
    e = s["ego"]
    x, y = e["box_center_rig_m"][:2]
    vehicle(
        ax, r, x, y, e["box_heading_rig_rad"], e["length_m"], e["width_m"], "#198754"
    )
    ax.scatter(0, 0, marker="x", s=45, c="#111827", zorder=7)
    p = plot_track[i]
    ax.annotate(
        "EGO",
        p,
        xytext=(12, -7),
        textcoords="offset points",
        fontsize=9,
        color="#087f5b",
        weight="bold",
        arrowprops={"arrowstyle": "-", "color": "#087f5b"},
    )
    elapsed = (r["timestamp_us"] - t0) / 1e6
    ax.set_title(
        f"Step {r['step_index']} / {len(rows)}  |  t + {elapsed:.1f} s\nActual speed {e['speed_mps']:.2f} m/s  |  traveled {distance_at[r['timestamp_us']]:.1f} m",
        fontsize=10,
    )
    ax.set(
        xlim=(xmin, xmax),
        ylim=(ymin, ymax),
        xlabel="Fixed lateral coordinate (m)",
        ylabel="Fixed forward coordinate (m)",
    )
    ax.set_aspect("equal")
    ax.grid(alpha=0.14)


frames = []
for i in range(len(rows)):
    fig, ax = plt.subplots(figsize=(4.2, 8), layout="constrained")
    draw(ax, i, False)
    ax.set_title("")
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.tick_params(
        axis="both",
        which="both",
        bottom=False,
        left=False,
        labelbottom=False,
        labelleft=False,
    )
    for spine in ax.spines.values():
        spine.set_visible(False)
    # Keep only simulation time; the README provides the color legend.
    elapsed = (rows[i]["timestamp_us"] - t0) / 1e6
    fig.text(
        0.04,
        0.97,
        f"{elapsed:.1f} s",
        va="top",
        fontsize=12,
        color="#475569",
    )
    # Remove moving EGO labels while keeping geometry untouched.
    for label in list(ax.texts):
        if label.get_text() == "EGO":
            label.remove()
    p = out / f"frame-{i:05d}.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    frames.append(imageio.imread(p))
imageio.mimsave(out / "rollout.gif", frames, duration=200, loop=0)
(out / "manifest.json").write_text(
    json.dumps(
        {
            "description": "Partial live JEV Score rollout in a fixed camera; not a complete-scene result.",
            "frame": "First-decision origin and orientation fixed across all frames",
            "pose_source": "Controller CSV and native controller_return records, exact timestamp matches",
            "scene_id": rows[0]["scene_id"],
            "policy_source": rows[0]
            .get("raw_response", {})
            .get("providerMetadata", {})
            .get("gateway")
            is not None
            and "vercel_ai_gateway"
            or rows[0].get("config", {}).get("backend", "unspecified"),
            "mode": rows[0]["mode"],
            "decision_frames": len(rows),
            "time_span_s": (rows[-1]["timestamp_us"] - t0) / 1e6,
            "traveled_m": float(distance[-1]),
            "frame_duration_ms": 200,
        },
        indent=2,
    )
    + "\n"
)
print(
    json.dumps(
        {"output": str(out), "frames": len(rows), "traveled_m": float(distance[-1])}
    )
)

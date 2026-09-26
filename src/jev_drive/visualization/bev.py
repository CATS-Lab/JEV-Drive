"""Noninteractive BEV frames, using the exact state delivered to JEV."""

from pathlib import Path
import json
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Circle


def box_points(x, y, heading, length, width):
    pts = np.array(
        [
            [length / 2, width / 2],
            [length / 2, -width / 2],
            [-length / 2, -width / 2],
            [-length / 2, width / 2],
        ]
    )
    c, s = np.cos(heading), np.sin(heading)
    return pts @ np.array([[c, s], [-s, c]]) + [x, y]


def render(event, path):
    state = event["state"]
    fig, ax = plt.subplots(figsize=(8, 8), dpi=100)

    def line(segment, **kw):
        xy = np.asarray(segment)
        if len(xy):
            ax.plot(-xy[:, 1], xy[:, 0], **kw)

    def vehicle(x, y, h, length, width, color):
        xy = box_points(x, y, h, length, width)
        ax.add_patch(Polygon(np.c_[-xy[:, 1], xy[:, 0]], color=color, alpha=0.8))

    for lane in state["road"]["lanes"]:
        for segment in lane["centerline_segments"]:
            line(segment, color="gray", linewidth=0.7)
        for side in ("left_boundary", "right_boundary"):
            for segment in lane[side]["segments"]:
                line(
                    segment,
                    color="silver",
                    linewidth=0.5,
                    linestyle="--" if lane[side]["type"] == "dashed" else "-",
                )
    for segment in state["navigation"]["route_segments"]:
        line(segment, color="#3286ce", linewidth=1.5, alpha=0.7)
    for item in state["traffic_controls"]["stop_lines"]:
        for segment in item["segments"]:
            line(segment, color="#bf5b17", linewidth=2)
    for signal in state["traffic_controls"]["signals"]:
        x, y = signal["position_m"][:2]
        phase = signal["phase"]
        ax.scatter(
            [-y],
            [x],
            c={"red": "red", "yellow": "gold", "green": "green"}.get(phase, "gray"),
            marker="o",
            s=45,
        )
        ax.annotate(phase, (-y, x), fontsize=6)
    for sign in state["traffic_controls"]["signs"]:
        x, y = sign["position_m"][:2]
        ax.scatter([-y], [x], c="purple", marker="^", s=30)
        ax.annotate(sign["source_category"], (-y, x), fontsize=5)
    ego = state["ego"]
    offset = ego["box_center_rig_m"]
    vehicle(
        offset[0],
        offset[1],
        ego["box_heading_rig_rad"],
        ego["length_m"],
        ego["width_m"],
        "#268a4a",
    )
    ax.plot([0], [0], "k+", markersize=5)
    for actor in state["actors"]:
        x, y = actor["x_m"], actor["y_m"]
        if actor["type"] == "pedestrian":
            ax.add_patch(Circle((-y, x), 0.4, color="orange"))
        else:
            vehicle(
                x,
                y,
                actor["heading_rad"],
                actor["length_m"],
                actor["width_m"],
                "orange" if actor["type"] == "cyclist" else "#bf5652",
            )
        ax.annotate(actor["id"], (-y, x), fontsize=6)
    if "trajectory" in event:
        line(event["trajectory"]["xy_m"], color="green", linestyle=":", linewidth=2)
    control = event.get("control", {})
    inc = event.get("increments", {})
    text = f"step {event['step_index']} | t={event['timestamp_us']/1e6:.2f}s | {event.get('mode','snapshot')}\n"
    text += f"speed={ego['speed_mps']:.2f} m/s | target={control.get('target_speed',0):.2f} | steering={control.get('steering_angle',0):.3f} rad\n"
    text += f"dv={inc.get('applied_delta_speed',0):+.3f} | dsteer={inc.get('applied_delta_steering',0):+.4f} | API={event.get('api_latency_s',0):.3f}s"
    if "raw_response" in event:
        for key, answer in event["raw_response"]["answers"].items():
            text += f"\n{key}: " + (
                f"score={answer['score']:.3f}"
                if answer["type"] == "score"
                else str(answer["probabilities"])
            )
    ax.set_title(text, fontsize=8, loc="left")
    ax.set_xlim(-20, 20)
    ax.set_ylim(-20, 80)
    ax.set_aspect("equal")
    ax.set_xlabel("right (-ego y), m")
    ax.set_ylabel("forward (+ego x), m")
    ax.grid(alpha=0.15)
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def export(log_path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    frames = []
    manifest = []
    for raw in Path(log_path).read_text().splitlines():
        event = json.loads(raw)
        if event["event"] != "decision":
            continue
        path = output / f"frame-{len(frames):05d}.png"
        render(event, path)
        frames.append(path)
        manifest.append(
            {
                "file": path.name,
                "session_id": event["session_id"],
                "timestamp_us": event["timestamp_us"],
                "step_index": event["step_index"],
            }
        )
    (output / "frames.json").write_text(json.dumps(manifest, indent=2))
    if frames:
        import imageio.v2 as imageio

        imageio.mimsave(
            output / "rollout.gif",
            [imageio.imread(p) for p in frames],
            duration=200,
            loop=0,
        )
    return len(frames)

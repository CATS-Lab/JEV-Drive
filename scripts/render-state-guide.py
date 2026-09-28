#!/usr/bin/env python3
"""Render historical documentation BEVs from saved pre-corridor states.

The navigation panel describes the archived GT-route input, not the current
road-corridor interface; see docs/navigation.md for the current contract.
"""

import argparse
import json
import os
from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.text import Text
from matplotlib.patches import Polygon, Rectangle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/images"
OUT.mkdir(parents=True, exist_ok=True)
MAIN = json.loads((ROOT / "docs/examples/driving-state.json").read_text())["state"]
GREEN, BLUE, ORANGE, PURPLE = "#087f5b", "#1864ab", "#d9480f", "#862e9c"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})


def rounded(obj):
    if isinstance(obj, float):
        return round(obj, 3)
    if isinstance(obj, dict):
        return {k: rounded(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rounded(v) for v in obj]
    return obj


def line(ax, seg, **kw):
    xy = np.asarray(seg)
    if len(xy):
        ax.plot(-xy[:, 1], xy[:, 0], **kw)


def body(ax, x, y, h, l, w, color, alpha=1):
    p = np.array([[l / 2, w / 2], [l / 2, -w / 2], [-l / 2, -w / 2], [-l / 2, w / 2]])
    c, s = np.cos(h), np.sin(h)
    p = p @ np.array([[c, s], [-s, c]]) + [x, y]
    ax.add_patch(
        Polygon(
            np.c_[-p[:, 1], p[:, 0]],
            facecolor=color,
            edgecolor=color,
            alpha=alpha,
            zorder=4,
        )
    )


def base(state, title, subtitle, xlim=(-22, 22), ylim=(-30, 82)):
    fig = plt.figure(figsize=(13, 8), layout="constrained")
    gs = fig.add_gridspec(1, 2, width_ratios=[1, 1.3])
    ax = fig.add_subplot(gs[0])
    tx = fig.add_subplot(gs[1])
    tx.axis("off")
    for lane in state["road"]["lanes"]:
        for seg in lane["centerline_segments"]:
            line(ax, seg, color="#cbd5e1", lw=0.8, zorder=1)
        for side in ("left_boundary", "right_boundary"):
            for seg in lane[side]["segments"]:
                line(ax, seg, color="#e2e8f0", lw=0.6, zorder=1)
    e = state["ego"]
    b = e["box_center_rig_m"]
    body(
        ax,
        b[0],
        b[1],
        e["box_heading_rig_rad"],
        e["length_m"],
        e["width_m"],
        GREEN,
        0.7,
    )
    ax.plot(0, 0, "k+", ms=8, zorder=8)
    ax.set(
        xlim=xlim,
        ylim=ylim,
        xlabel="Right on page = -ego y (m)",
        ylabel="Forward = +ego x (m)",
    )
    ax.set_aspect("equal")
    ax.grid(alpha=0.15)
    fig.suptitle(
        title + "\n" + subtitle, fontsize=15, fontweight="bold", ha="left", x=0.04
    )
    return fig, ax, tx


def tag(ax, x, y, label, color, offset=(12, 10)):
    ax.annotate(
        label,
        (-y, x),
        xytext=offset,
        textcoords="offset points",
        fontsize=11,
        fontweight="bold",
        color=color,
        zorder=10,
        bbox={"boxstyle": "round,pad=.25", "fc": "white", "ec": color, "alpha": 0.95},
        arrowprops={"arrowstyle": "-", "color": color},
    )


def panel(tx, heading, obj, notes):
    tx.text(0, 0.98, heading, va="top", color=BLUE, weight="bold", fontsize=13)
    text = json.dumps(rounded(obj), indent=2)
    tx.text(
        0,
        0.92,
        text,
        va="top",
        fontfamily="DejaVu Sans Mono",
        fontsize=10,
        linespacing=1.22,
    )
    tx.text(0, 0.02, notes, va="bottom", fontsize=10, color="#334155", linespacing=1.5)


def save(fig, name):
    if TRANSLATIONS:
        for text in fig.findobj(Text):
            old = text.get_text()
            new = old
            for source, target in sorted(
                TRANSLATIONS.items(), key=lambda pair: -len(pair[0])
            ):
                new = new.replace(source, target)
            if new != old:
                text.set_text(new)
                text.set_fontproperties(
                    FontProperties(
                        fname=str(CJK_FONT),
                        size=text.get_fontsize(),
                        weight=text.get_fontweight(),
                        style=text.get_fontstyle(),
                    )
                )
    fig.savefig(OUT / name, dpi=160, facecolor="white")
    plt.close(fig)


def ego():
    s = MAIN
    e = s["ego"]
    b = e["box_center_rig_m"]
    fig, ax, tx = base(
        s,
        "01 / Ego: physical state and body geometry",
        "Selected snapshot | green rectangle = ego box | black cross = rig origin",
        (-5, 5),
        (-4, 8),
    )
    tag(ax, b[0], b[1], "E1", GREEN, (35, 30))
    ax.scatter(-b[1], b[0], c="white", edgecolors="black", zorder=9)
    ax.annotate(
        "rig (0, 0)",
        (0, 0),
        xytext=(-100, -25),
        textcoords="offset points",
        arrowprops={"arrowstyle": "->"},
    )
    ax.annotate(
        "box center",
        (0, b[0]),
        xytext=(-110, 30),
        textcoords="offset points",
        arrowprops={"arrowstyle": "->"},
    )
    ax.annotate(
        "+x forward",
        xy=(0, 7),
        xytext=(0, 5),
        arrowprops={"arrowstyle": "->", "lw": 2},
        ha="center",
    )
    ax.annotate(
        "+y left",
        xy=(-4, 0),
        xytext=(-1.5, 0),
        arrowprops={"arrowstyle": "->", "lw": 2},
        va="center",
    )
    panel(
        tx,
        "E1 → state.ego",
        {
            k: e[k]
            for k in (
                "speed_mps",
                "acceleration_mps2",
                "yaw_rate_radps",
                "length_m",
                "width_m",
                "box_center_rig_m",
                "box_heading_rig_rad",
            )
        },
        "Numbers rounded to 3 decimals for display.\nBox center is offset from the rig origin.\nSpeed is measured longitudinal motion, not target speed.\nCommand fields are shown separately in Figure 06.",
    )
    save(fig, "state-01-ego.png")


def road():
    s = MAIN
    lane = min(
        s["road"]["lanes"],
        key=lambda l: min(
            x * x + y * y for seg in l["centerline_segments"] for x, y in seg
        ),
    )
    seg = lane["centerline_segments"][0]
    fig, ax, tx = base(
        s,
        "02 / Road: sampled geometry and source lane IDs",
        "Blue = selected lane | purple/orange = its left/right boundaries",
    )
    for piece in lane["centerline_segments"]:
        line(ax, piece, color=BLUE, lw=2.5)
    for side, color in [("left_boundary", PURPLE), ("right_boundary", ORANGE)]:
        for piece in lane[side]["segments"]:
            line(ax, piece, color=color, lw=1.8)
    for i, (x, y) in enumerate(seg[:3]):
        ax.scatter(-y, x, c=BLUE, s=25, zorder=5)
        tag(ax, x, y, f"P{i}", BLUE, (25 + i * 15, 0))
    x, y = seg[len(seg) // 2]
    tag(ax, x, y, "L1", BLUE)
    xmin, xmax, ymin, ymax = s["road"]["roi_m"]
    ax.add_patch(
        Rectangle(
            (-ymax, xmin),
            ymax - ymin,
            xmax - xmin,
            fill=False,
            ec=BLUE,
            ls="--",
            lw=1.2,
        )
    )
    item = {
        k: lane[k]
        for k in (
            "id",
            "left_neighbors",
            "right_neighbors",
            "successors",
            "references_outside_roi",
            "unresolved_references",
        )
    }
    # Compact coordinate rows retain exact field names but show only first 3 vertices.
    tx.text(
        0,
        0.98,
        "L1 → state.road.lanes[]",
        va="top",
        color=BLUE,
        weight="bold",
        fontsize=13,
    )
    block = (
        json.dumps(rounded(item), indent=2)
        + "\n\ncenterline_segments[0]:\n"
        + "\n".join(f"  P{i}: [{x:.3f}, {y:.3f}]" for i, (x, y) in enumerate(seg[:3]))
    )
    block += (
        "\n  ... remaining sampled vertices\n\nleft_boundary.type: "
        + lane["left_boundary"]["type"]
        + "\nright_boundary.type: "
        + lane["right_boundary"]["type"]
    )
    tx.text(0, 0.92, block, va="top", fontfamily="DejaVu Sans Mono", fontsize=10)
    tx.text(
        0,
        0.03,
        "Dashed box: road.roi_m = [-20, 80, -15, 15].\nP0–P2 match the first 3 vertices listed above.\nEach vertex is [x forward, y left], in meters.\nIDs keep source identity; disconnected pieces stay separate.\nGray background: other retained lanes.",
        va="bottom",
        fontsize=10,
        linespacing=1.5,
    )
    save(fig, "state-02-road.png")


def actors():
    s = MAIN
    chosen = s["actors"][0]
    fig, ax, tx = base(
        s,
        "03 / Actors: boxes, IDs and relative velocity",
        "Orange = selected actor | muted red = other retained actors",
    )
    for a in s["actors"]:
        body(
            ax,
            a["x_m"],
            a["y_m"],
            a["heading_rad"],
            a["length_m"],
            a["width_m"],
            ORANGE if a is chosen else "#c98484",
            0.8,
        )
        if a is not chosen:
            ax.annotate(
                "id " + a["id"],
                (-a["y_m"], a["x_m"]),
                xytext=(8, 0),
                textcoords="offset points",
                fontsize=8,
            )
    a = chosen
    tag(ax, a["x_m"], a["y_m"], "A1", ORANGE, (-90, -20))
    vx, vy = a["relative_vx_mps"], a["relative_vy_mps"]
    if vx is not None and vy is not None:
        ax.annotate(
            "",
            (-a["y_m"] - vy, a["x_m"] + vx),
            (-a["y_m"], a["x_m"]),
            arrowprops={"arrowstyle": "->", "color": ORANGE, "lw": 2.5},
        )
    panel(
        tx,
        "A1 → state.actors[0]",
        a,
        "Positions use the ego rig frame; heading is relative to ego.\nArrow = relative velocity x 1 second, not a forecast.\nThe label leader only identifies its box.\nUnknown velocity is null, not zero.\nActor selection: ROI first, then nearest K (default 16).",
    )
    save(fig, "state-03-actors.png")


def navigation():
    s = MAIN
    seg = s["navigation"]["route_segments"][0]
    fig, ax, tx = base(
        s,
        "04 / Navigation: the intended route",
        "Blue = route geometry | gray = road geometry | green = ego",
    )
    for piece in s["navigation"]["route_segments"]:
        line(ax, piece, color=BLUE, lw=2.5)
    indices = [0, 4, 8, 12, 16]
    for i in indices:
        if i < len(seg):
            x, y = seg[i]
            ax.scatter(-y, x, c=BLUE, s=25, zorder=5)
            tag(ax, x, y, f"R{i}", BLUE, (25, 0))
    tx.text(
        0,
        0.98,
        "state.navigation.route_segments[0]",
        va="top",
        color=BLUE,
        weight="bold",
        fontsize=13,
    )
    text = (
        "source: "
        + s["navigation"]["source"]
        + "\n\nSelected actual array entries:\n\n"
        + "\n\n".join(
            f"R{i} → index {i}\n  [{seg[i][0]:.3f}, {seg[i][1]:.3f}]"
            for i in indices
            if i < len(seg)
        )
    )
    tx.text(0, 0.90, text, va="top", fontfamily="DejaVu Sans Mono", fontsize=11)
    tx.text(
        0,
        0.03,
        "Each point is [x forward, y left], in meters.\nAll route vertices are connected on the plot; only labeled\nentries are listed here. The route expresses navigation\nintent. It is not a JEV-generated trajectory or steering action.",
        va="bottom",
        fontsize=10,
        linespacing=1.5,
    )
    save(fig, "state-04-navigation.png")


def traffic():
    s = MAIN
    t = s["traffic_controls"]
    w = t["stop_lines"][1]
    sign = t["signs"][0]
    fig, ax, tx = base(
        s,
        "05 / Traffic controls: observed map facts",
        "Same selected snapshot | orange = stop lines | purple = signs",
        (-5, 20),
        (-12, 14),
    )
    for item in t["stop_lines"]:
        for piece in item["segments"]:
            line(ax, piece, color=ORANGE, lw=3)
    for item in t["signs"]:
        x, y = item["position_m"][:2]
        ax.scatter(-y, x, c=PURPLE, marker="^", s=65, zorder=6)
    x, y = w["segments"][0][0]
    tag(ax, x, y, "W1", ORANGE, (-90, -25))
    x, y = sign["position_m"][:2]
    tag(ax, x, y, "S1", PURPLE, (-90, 30))
    tx.text(
        0,
        0.98,
        "W1 → stop_lines[1] / S1 → signs[0]",
        va="top",
        color=BLUE,
        weight="bold",
        fontsize=12,
    )
    text = "W1\n" + json.dumps(
        rounded(
            {k: w[k] for k in ("id", "lane_ids", "source_category", "is_implicit")}
        ),
        indent=2,
    )
    text += "\nsegments[0] endpoints:\n" + "\n".join(
        f"  [{x:.3f}, {y:.3f}]" for x, y in w["segments"][0]
    )
    text += "\n\nS1\n" + json.dumps(
        rounded(
            {
                k: sign[k]
                for k in (
                    "id",
                    "position_m",
                    "source_category",
                    "lane_ids",
                    "regulatory_value",
                )
            }
        ),
        indent=2,
    )
    tx.text(0, 0.92, text, va="top", fontfamily="DejaVu Sans Mono", fontsize=9.5)
    tx.text(
        0,
        0.015,
        "4 signs overlap in BEV at different heights; S1 selects one.\nThis crop has signals: [] and signal_phases: unavailable.\nNo light phase or stop/yield recommendation is invented.\nAn empty array alone does not prove absence in the world.",
        va="bottom",
        fontsize=10,
        linespacing=1.4,
    )
    save(fig, "state-05-traffic.png")


def commands():
    s = MAIN
    e = s["ego"]
    c = s["vehicle_constraints"]
    fig, ax, tx = base(
        s,
        "06 / Control context: measured motion versus commands",
        "Same offline snapshot | initialized commands, not a model response",
        (-5, 5),
        (-4, 8),
    )
    b = e["box_center_rig_m"]
    tag(ax, b[0], b[1], "E1", GREEN, (35, 30))
    obj = {
        "ego": {
            k: e[k]
            for k in ("speed_mps", "current_target_speed_mps", "commanded_steering_rad")
        },
        "decision_dt_s": s["decision_dt_s"],
        "vehicle_constraints": c,
    }
    panel(
        tx,
        "Initialized context for this offline snapshot",
        obj,
        "Commands shown here are initialized from ego kinematics.\nAt dt = 0.2 s, rate bounds allow at most 0.6 m/s\nand 0.16 rad change per decision, before absolute bounds.\nConstraints bound commands, not instantaneous actual motion.\nNo JEV decision or historical command is implied.",
    )
    save(fig, "state-06-control.png")


TRANSLATIONS = {}
CJK_FONT = None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("en", "zh-CN"), default="en")
    args = parser.parse_args()
    if args.language == "zh-CN":
        TRANSLATIONS = json.loads(
            (ROOT / "docs/translations/figure-labels.zh-CN.json").read_text()
        )
        CJK_FONT = Path(
            os.environ.get(
                "JEV_DOC_FONT", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
            )
        )
        if not CJK_FONT.is_file():
            parser.error(
                "Install Noto Sans CJK or set JEV_DOC_FONT to a CJK font file / 请安装中文字体或设置 JEV_DOC_FONT"
            )
        OUT = OUT / "zh-CN"
        OUT.mkdir(parents=True, exist_ok=True)
    for render in (ego, road, actors, navigation, traffic, commands):
        render()
    print("Wrote 6 state-to-BEV figures to", OUT)

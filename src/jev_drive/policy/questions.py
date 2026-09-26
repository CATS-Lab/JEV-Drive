"""Versioned prompt definitions; no precomputed maneuver recommendations."""

VERSION = "jev-drive-v1.0"
COMMON = (
    "Control an ego vehicle in a synchronous driving simulation using the structured state. "
    "Coordinates are ego rig +x forward, +y left. Follow navigation, remain on drivable roads, "
    "avoid collisions, and comply with provided traffic-control facts. Unknown signal phases "
    "are unknown, not green. Reason yourself from lane geometry and actors; no maneuver labels "
    "are provided. Your update applies once for decision_dt_s, with the supplied rate and absolute "
    "limits, then a constant-curvature 4-second reference is tracked by an MPC. "
    "Use current physical speed and commanded steering/target speed. "
    "Choose the control update for this step, considering the other control axis. "
)


def build(config):
    if config.mode == "score":
        return {
            "speed": {
                "type": "score",
                "instructions": COMMON
                + "What signed target-speed increment should be applied now? Rate levels ordered from deceleration to acceleration. Level 4 is zero increment. The actual increment is rate-limited by acceleration * decision_dt_s.",
                "criteria": [
                    f"Change target speed by {(i-4)*config.speed_score_gain:+.3f} m/s before rate limits."
                    for i in range(9)
                ],
            },
            "steering": {
                "type": "score",
                "instructions": COMMON
                + "What signed steering-command increment should be applied now? Positive is left and negative is right. The new command equals current commanded_steering_rad plus this increment; level 4 makes no change.",
                "criteria": [
                    f"Change steering command by {(i-4)*config.steering_score_gain:+.4f} radians before rate limits."
                    for i in range(9)
                ],
            },
        }
    return {
        "speed": {
            "type": "choice",
            "instructions": COMMON
            + f"Choose the speed update. We apply delta_v = {config.choice_speed_gain} * (P_accelerate - P_decelerate), then rate and absolute limits.",
            "criteria": {
                "accelerate": "Increase target speed.",
                "hold": "Keep target speed.",
                "decelerate": "Decrease target speed.",
            },
        },
        "steering": {
            "type": "choice",
            "instructions": COMMON
            + f"Choose left, straight, or right using current self-motion and scene. We apply delta_steering = {config.choice_steering_gain} * (P_left - P_right) to the current steering command, then rate and absolute limits.",
            "criteria": {"left": "Left.", "straight": "Straight.", "right": "Right."},
        },
    }

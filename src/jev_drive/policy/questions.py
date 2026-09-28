"""Versioned prompt definitions; no precomputed maneuver recommendations."""

VERSION = "jev-drive-v1.3"
COMMON = (
    "Control an ego vehicle in a synchronous driving simulation using the structured state. "
    "Coordinates are ego rig +x forward, +y left. Follow navigation, remain on drivable roads, "
    "avoid collisions, and comply with provided traffic-control facts. Unknown signal phases "
    "are unknown, not green. Reason yourself from lane geometry and actors; no maneuver labels "
    "are provided. Your update applies once for decision_dt_s, with the supplied rate and absolute "
    "limits, then a constant-curvature 4-second reference is tracked by an MPC. "
    "Within each lane's centerline_segments, points run in that lane's direction of travel; "
    "use the local tangent between consecutive points to interpret its direction on curves. "
    "Lane left/right boundaries and neighbors are relative to that direction, not ego heading. "
    "Drive in the lane's direction; do not drive against traffic or enter opposing lanes. "
    "Lane boundaries delimit individual lanes, not necessarily the outer road edge. "
    "Cross a shared lane boundary only for a safe, legal lane change into a same-direction lane, "
    "respecting any supplied marking restrictions. An unknown boundary type is not permission "
    "to cross. Keep the entire vehicle footprint within the drivable roadway, not just its center; "
    "do not leave the road or use sidewalks, shoulders, or medians as travel lanes. "
    "road.road_boundaries.edges contains source-map road edges, distinct from lane dividers. "
    "Do not cross or overlap these road edges with any part of the vehicle. Use lane geometry "
    "to identify the roadway side; road edges are open polylines, not closed area polygons. "
    "An empty edge list only means no edge is represented in the local input, not that all "
    "surrounding space is drivable. Missing neighbors, "
    "missing geometry, and ROI clipping endpoints do not establish a physical road boundary "
    "or extra drivable space. If a safe continuation is uncertain, slow down or stop. "
    "Navigation contains an ordered sequence of map-derived road corridors, each listing "
    "same-direction lane IDs, not a target trajectory or a required lane-change schedule. "
    "Choose your own lane and safe maneuver timing to reach successive corridors. Corridor "
    "membership does not authorize crossing a lane marking. IDs outside the current road ROI "
    "refer to map sections ahead, not missing obstacles. If navigation is unavailable, do not "
    "invent a route; slow down or stop safely. "
    "Navigation does not override road boundaries, traffic direction, or collision avoidance. "
    "Do not collide with or overlap any actor's footprint. Consider the ego vehicle's full "
    "dimensions, actor dimensions, positions and velocities; anticipate closing gaps over "
    "the upcoming motion rather than checking only current separation. Maintain clearance "
    "and enough following distance to brake. If the intended motion would intersect an actor, "
    "reduce speed or stop before contact; do not assume other actors will yield or move aside. "
    "Collision avoidance and staying within road boundaries take priority over route progress. "
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

"""Versioned prompt definitions; no precomputed maneuver recommendations."""

from ..control.action_mapping import speed_increments, steering_targets, choice_targets

VERSION = "jev-drive-v1.8"
COMMON = (
    "Control an ego vehicle in a synchronous driving simulation using the structured state. "
    "Coordinates are ego rig +x forward, +y left. Follow navigation, remain on drivable roads, "
    "avoid collisions, and comply with provided traffic-control facts. Unknown signal phases "
    "are unknown, not green. Reason yourself from lane geometry and actors; no maneuver labels "
    "are provided. Your speed update applies once for decision_dt_s. Steering selects a new absolute "
    "reference angle, not an increment added repeatedly. Rate limits apply to both commands. "
    "A constant-curvature 4-second reference starts from measured speed and ramps toward "
    "the speed target within acceleration limits before MPC tracking. If initial speed exceeds "
    "the configured cap, recover gradually without an instantaneous speed jump. "
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
    "Lane attributes provide source use_types (including shoulders, entry/exit, HOV), "
    "vehicle_types and lane_direction maneuver categories. These are map facts, not a "
    "command to perform a maneuver. Do not treat shoulders as ordinary travel lanes; HOV "
    "eligibility is unknown. Navigation excludes known shoulders and HOV lanes. "
    "Boundary source_samples carry style/color at source vertices; VIRTUAL is not a "
    "painted divider. Respect solid markings, curbs and barriers. Unverified speed_limit "
    "units and zero values must not be interpreted as a valid numeric regulatory limit; "
    "max_target_speed_mps is a controller cap, not a posted road limit. "
    "Map areas distinguish crosswalks, islands, gore areas, buffer zones, intersections "
    "and road markings; do not treat all polygons as forbidden or all as drivable. "
    "Respect the supplied signal/sign/stop-line lane associations. Unknown or missing "
    "associations do not establish that a control applies to every nearby lane. "
    "Actor positions are box centers; ego box center is offset from its rig origin. "
    "Actor relative velocities subtract ego translational velocity and use current ego "
    "axes. Use ego longitudinal and lateral speeds when reasoning about actor motion. "
    "observation_scope reports cropping and nearest-K omissions; unlisted space is not "
    "verified clear. No future actor trajectory is supplied. "
    "Use current physical speed and commanded steering/target speed. "
    "vehicle_constraints.control_mapping specifies exact action values, units, update equations "
    "and reference trajectory equations. Use these to evaluate the motion resulting from each action. "
    "The numerical action in each criterion is applied subject to those limits. "
    "Choose the control update for this step, considering the other control axis. "
)


SPEED_LEVELS = [
    "Brake as strongly as allowed: an imminent collision or road departure requires urgent speed reduction.",
    "Brake firmly: a rapidly closing gap, nearby stopping requirement or tight bend leaves little margin.",
    "Reduce speed moderately: approaching traffic, a bend or narrowing usable road requires more clearance.",
    "Ease off gently: modest excess speed or slowly reducing clearance calls for a small slowdown.",
    "Maintain the current target speed: it is appropriate for the visible road, traffic and stopping distance.",
    "Increase speed gently: there is clear safe space and only a small increase is appropriate.",
    "Increase speed moderately: an open same-direction lane and sufficient braking clearance support progress.",
    "Accelerate firmly: substantially below a suitable speed on a clear, aligned road with ample clearance.",
    "Accelerate as strongly as allowed: very low speed on a clearly open, aligned road with no nearby conflict.",
]
STEERING_LEVELS = [
    "Command strong right steering: a sharp right bend or large leftward path error requires a large rightward correction within usable roadway.",
    "Command firm right steering: a pronounced right bend or substantial leftward path error requires a clear rightward correction.",
    "Command moderate right steering: a right bend or leftward path error requires a moderate correction toward safe road space.",
    "Command gentle right steering: a broad right bend or small leftward path error needs only a slight rightward correction.",
    "Command straight ahead with zero reference steering: the current heading already points along a safe continuation; unwind any previous turning command.",
    "Command gentle left steering: a broad left bend or small rightward path error needs only a slight leftward correction.",
    "Command moderate left steering: a left bend or rightward path error requires a moderate correction toward safe road space.",
    "Command firm left steering: a pronounced left bend or substantial rightward path error requires a clear leftward correction.",
    "Command strong left steering: a sharp left bend or large rightward path error requires a large leftward correction within usable roadway.",
]


def build(config):
    selection = (
        "The returned continuous score is mapped through a continuous neutral deadzone to control using vehicle_constraints.control_mapping; "
        "integer criteria are anchors and fractional scores produce intermediate commands. Scores inside the neutral deadzone request zero speed increment and zero absolute steering, unwinding previous steering under rate limits. "
        if config.mode == "score" else "The returned validated choice label is executed. "
    )
    speed_instruction = COMMON + selection + (
        "Select the speed action appropriate to the current scene. Deceleration must "
        "be sufficient for visible hazards; acceleration requires a clear safe continuation."
    )
    steering_instruction = COMMON + selection + (
        "Select the absolute reference steering appropriate to the upcoming motion. "
        "Positive steering turns left; negative turns right. This is a new steering target, "
        "not an increment. Straight means return the reference steering to zero under rate "
        "limits; it does not mean hold an existing turn. Consider heading and position "
        "relative to lane geometry. "
        "If turning cannot avoid a hazard safely, also choose adequate braking."
    )
    if config.mode == "score":
        return {
            "speed": {
                "type": "score",
                "instructions": speed_instruction,
                "criteria": [f"{text} Requested target-speed change: {value:+.6g} m/s for this decision, before rate and speed limits." for text, value in zip(SPEED_LEVELS, speed_increments(config))],
            },
            "steering": {
                "type": "score",
                "instructions": steering_instruction,
                "criteria": [f"{text} Absolute reference steering target: {value:+.6g} rad, before steering-rate and angle limits." for text, value in zip(STEERING_LEVELS, steering_targets(config))],
            },
        }
    result = {
        "speed": {
            "type": "choice",
            "instructions": speed_instruction,
            "criteria": {
                "accelerate": "Increase target speed only when the road ahead and braking clearance are sufficient.",
                "hold": "Maintain current target speed when appropriate for road geometry and traffic.",
                "decelerate": "Reduce target speed for a hazard, stopping need, bend or insufficient clearance.",
            },
        },
        "steering": {
            "type": "choice",
            "instructions": steering_instruction,
            "criteria": {
                "left": "Set a leftward reference steering target to follow a left bend or correct a rightward path error safely.",
                "straight": "Set zero reference steering when current heading follows a safe continuation; unwind previous turning.",
                "right": "Set a rightward reference steering target to follow a right bend or correct a leftward path error safely.",
            },
        },
    }
    targets = choice_targets(config)
    for axis, question in result.items():
        for label, text in question["criteria"].items():
            value = targets[axis][label]
            action = "Requested target-speed change" if axis == "speed" else "Absolute reference steering target"
            unit = "m/s" if axis == "speed" else "rad"
            question["criteria"][label] = f"{text} {action}: {value:+.6g} {unit}, before limits."
    return result

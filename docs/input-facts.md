# Structured input corrections: v1.4

English | [简体中文](input-facts.zh-CN.md)

Inputs expose source map facts; JEV still makes driving decisions. v1.4 restores attributes omitted by the intermediate VectorMap conversion without introducing recorded intermediate ego waypoints or a safety override.

| Input | Source and meaning |
|---|---|
| `road.lanes[].attributes` | Raw lane use, vehicle restrictions, maneuver category, map-end attributes and speed-limit string. `lane_direction` is a maneuver category; centerline ordering still defines travel direction. |
| Boundary `source_samples` | Source boundary vertex positions, styles and colors. Spatial changes remain explicit; `type` is the uniform source value or `mixed`. |
| `road.road_boundaries` | Independent road edges, added in v1.3, distinct from lane dividers. |
| `road.map_areas` | Crosswalks, islands, gore areas, buffer zones, intersections and road markings, with categories, lane links and clipping flags. Invalid polygons are reported by ID rather than repaired into invented geometry. |
| Traffic-control lane links | Resolve both ends by actual entity IDs, correcting reversed LIGHT_TO_LANE parsing and enriching sign/wait-line links. Signs retain source orientation. Null placeholder rows are not traffic lights. |
| Ego lateral motion | Lateral speed, lateral acceleration and motion provenance supplement longitudinal motion. |
| `observation_scope` | Actor ROI, nearest-K selection, candidate/selected/omitted counts, relative velocity semantics and box reference points. Unlisted space is not verified clear. |

Road-corridor routing excludes source-labeled `SHOULDER_LANE` and, because occupant eligibility is unavailable, `HOV_LANE`. Other lane uses and vehicle restrictions remain exposed for JEV to interpret. Known shoulders are no longer ordinary route candidates.

The raw `speed_limit` string is preserved with `speed_limit_unit: "unverified"` and `speed_limit_mps: null`. No verified unit definition is available yet; neither conversion nor treating zero as a known zero-speed restriction is justified. `max_target_speed_mps` is a controller cap, not a posted road limit. Missing dynamic signal phases remain `unknown`; fixing lane links does not create signal observations.

Area polygons come from source `location` geometry, clipped to the ROI with holes and disconnected pieces preserved. Crosswalks, intersections and islands have different meanings; not every polygon is forbidden or drivable. Marking samples describe source vertices, not inferred crossing permission.

Independent modules: `integration/map_facts.py`, `state/lane_attributes.py`, `state/map_areas.py`, and `state/observation_scope.py`. Archived v1.2 rollouts omitted these facts and the independent road-edge layer. Their lane labels may include shoulders and must not be interpreted as four ordinary travel lanes. No paid API rerun accompanied this correction.

Repeated style/color annotations retain the first and last source samples of each constant run, including both sides of every change. Boundary `segments` still carry the geometry; this compacts annotations without straightening the road. New facts increase payload size; offline character counts are not model token counts, and API context capacity has not been exercised with the new input.

# From a BEV scene to structured fields

English | [简体中文](bev-state-guide.zh-CN.md)

Each figure pairs **actual scene geometry on the left** with **the corresponding structured fields on the right**. Colors and labels identify the same objects in both panels. Click an image to inspect the full-resolution PNG.

All six figures use **one offline snapshot at 0.2 seconds** from scene `clipgt-01330416-9f29-4799-86a6-c4b2f8593375`. It was selected for its 16 nearby actors with available velocity estimates, two stop lines and four signs. Values are rounded to 3 decimals in labels; the saved JSON retains full precision. No JEV API call was needed. The command context in Figure 06 is initialized from this snapshot using the implementation's `ControlState.initialize`; it is not a previous live decision.

## 01. Ego state

The green rectangle comes from body dimensions and the box-center offset. The black cross is the rig origin. Coordinates are +x forward and +y left, so the horizontal plotting coordinate is −y.

![Ego box, rig origin and matching state.ego fields](images/state-01-ego.png)

`speed_mps` is the longitudinal velocity component. Body geometry, measured motion and command targets are separate quantities. Builder: [ego.py](../src/jev_drive/state/ego.py).

## 02. Road geometry and lane identity

Blue highlights one retained lane; purple/orange highlight its left/right boundaries. P0–P2 correspond to the first three sampled centerline vertices shown in the right panel. L1 identifies the selected source lane, not a new lane ID.

![Selected lane, sampled vertices and matching road fields](images/state-02-road.png)

`roi_m` is `[x_min, x_max, y_min, y_max]` in meters; the default road crop is `[-20, 80, -15, 15]`. Centerlines are sampled at 5 m spacing with endpoints retained. Disconnected `segments` must not be joined across gaps. Neighbor/successor IDs preserve source topology; `references_outside_roi` differs from `unresolved_references`. Builder: [road_graph.py](../src/jev_drive/state/road_graph.py).

## 03. Nearby actors

A1 points to the orange vehicle and its actual array entry. Other retained actors are shown with their source IDs. The velocity arrow shows the selected actor's relative velocity multiplied by one second for display. It is a vector illustration, not a predicted trajectory; the label leader only identifies the box.

![Selected actor box and its structured fields](images/state-03-actors.png)

The default actor crop is `[-30, 80, -20, 20]`; at most the nearest 16 objects are retained. Relative velocity is actor velocity minus ego velocity, rotated into ego axes; it excludes a rotating-frame position-derivative correction. Missing velocity is `null`; ambiguous or missing lane matches yield `lane_id: null`. Builders: [actors.py](../src/jev_drive/state/actors.py), [lane_matching.py](../src/jev_drive/state/lane_matching.py).

## 04. Navigation route

Navigation now supplies ordered groups of adjacent same-direction lane IDs, rather than a GT-derived route polyline. JEV chooses lanes and maneuver timing using the map and traffic. Only the trip endpoint is used as the default destination; intermediate GT waypoints are excluded. See [road-level navigation](navigation.md) for the input example, destination configuration and unavailable-map behavior.

## 05. Stop lines and signs

This same selected snapshot contains two stop-line segments and four signs. W1 selects one line; S1 selects one sign. The signs nearly overlap in top view but have different heights. The source category is preserved as recorded; the builder does not manufacture numeric regulatory values or lane associations.

![Stop lines and signs with their structured source fields](images/state-05-traffic.png)

There are no retained signal objects in this selected crop. This is represented as `signals: []`, with signal-phase availability `unavailable`; an empty crop is not evidence that the entire world has no traffic lights. For a signal object without a current phase observation, the interface uses `phase: "unknown"`. No synthetic red/green signal has been added to these real-scene figures.

Signal observations must be at or before the current time. The default freshness limit is 1 second; stale samples retain their timestamp/source but report `phase: "unknown"` and `phase_stale: true`. Availability is recorded separately from object arrays. Builders: [traffic_signals.py](../src/jev_drive/state/traffic_signals.py), [stop_lines.py](../src/jev_drive/state/stop_lines.py), [traffic_signs.py](../src/jev_drive/state/traffic_signs.py).

## 06. Command context and constraints

Measured ego speed and command targets are separate quantities. This offline example initializes the target speed and steering from the snapshot using `ControlState.initialize`, then adds the same `vehicle_constraints` and timing fields that `JevModel` supplies before a client call. These fields describe how a decision can change the commands, not instantaneous guarantees about physical motion.

![Measured ego state alongside command state and vehicle constraints](images/state-06-control.png)

Default limits allow target-speed changes of at most 0.6 m/s and steering changes of at most 0.16 rad per 0.2-second decision, followed by absolute bounds. See [vehicle_constraints.py](../src/jev_drive/state/vehicle_constraints.py) and [limits.py](../src/jev_drive/control/limits.py).

### Where to inspect the complete state

The builders produce a versioned envelope (`kind: jev.scene_snapshot`, `schema_version: 1`) in `DriveRequest.renderer_data`. Its `state` contains the five scene components; session/time/frame metadata and provenance are separate. `JevModel` adds command fields, vehicle constraints and timing before calling the client. Original renderer bytes are not sent to JEV.

Read `outputs/<snapshot>/state.json` to inspect the builder envelope. Read a decision event's `state` in `outputs/<run>/decisions.jsonl` for the exact model input, including added context. See [state_builder.py](../src/jev_drive/state/state_builder.py), [schema.py](../src/jev_drive/state/schema.py) and [jev_model.py](../src/jev_drive/policy/jev_model.py).

## Data and reproducibility

The small examples contain only structured scene state and basic scene metadata; they contain no credentials, API response, model weights or original USDZ archive.

- [Selected snapshot and initialized command context](examples/driving-state.json): source for all six figures.
- [Rendering script](../scripts/render-state-guide.py): draws directly from that JSON file using NumPy and Matplotlib. It requires no simulator, network access or JEV provider.

From an environment with the project dependencies installed:

```bash
python scripts/render-state-guide.py
```

For how these inputs flow through the simulator and policy, see [how JEV-Drive works](full-workflow.md).

The default command renders English labels. For Chinese figures, install Noto Sans CJK or set `JEV_DOC_FONT` to a CJK font file, then run:

```bash
python scripts/render-state-guide.py --language zh-CN
```

Field names and data values stay unchanged between languages.

Overlapping source actor boxes can be filtered before model input; see [actor filtering and offline comparisons](actor-filter.md).

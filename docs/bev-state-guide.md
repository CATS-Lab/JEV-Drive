# From a BEV scene to structured fields

Each figure pairs **actual scene geometry on the left** with **the corresponding structured fields on the right**. Colors and labels identify the same objects in both panels. Click an image to inspect the full-resolution PNG.

All six figures use **one offline snapshot at 0.2 seconds** from scene `clipgt-01330416-9f29-4799-86a6-c4b2f8593375`. It was selected for its 16 nearby actors with available velocity estimates, two stop lines and four signs. Values are rounded to 3 decimals in labels; the saved JSON retains full precision. No JEV API call was needed. The command context in Figure 06 is initialized from this snapshot using the implementation's `ControlState.initialize`; it is not a previous live decision.

## 01. Ego state

The green rectangle comes from body dimensions and the box-center offset. The black cross is the rig origin. Coordinates are +x forward and +y left, so the horizontal plotting coordinate is −y.

![Ego box, rig origin and matching state.ego fields](images/state-01-ego.png)

## 02. Road geometry and lane identity

Blue highlights one retained lane; purple/orange highlight its left/right boundaries. P0–P2 correspond to the first three sampled centerline vertices shown in the right panel. L1 identifies the selected source lane, not a new lane ID.

![Selected lane, sampled vertices and matching road fields](images/state-02-road.png)

## 03. Nearby actors

A1 points to the orange vehicle and its actual array entry. Other retained actors are shown with their source IDs. The velocity arrow shows the selected actor's relative velocity multiplied by one second for display. It is a vector illustration, not a predicted trajectory; the label leader only identifies the box.

![Selected actor box and its structured fields](images/state-03-actors.png)

## 04. Navigation route

R0, R4, R8, R12 and R16 label actual indices in `route_segments[0]`. The blue curve is navigation input; it is not a JEV-generated reference trajectory.

![Route samples and matching navigation array entries](images/state-04-navigation.png)

## 05. Stop lines and signs

This same selected snapshot contains two stop-line segments and four signs. W1 selects one line; S1 selects one sign. The signs nearly overlap in top view but have different heights. The source category is preserved as recorded; the builder does not manufacture numeric regulatory values or lane associations.

![Stop lines and signs with their structured source fields](images/state-05-traffic.png)

There are no retained signal objects in this selected crop. This is represented as `signals: []`, with signal-phase availability `unavailable`; an empty crop is not evidence that the entire world has no traffic lights. For a signal object without a current phase observation, the interface uses `phase: "unknown"`. No synthetic red/green signal has been added to these real-scene figures.

## 06. Command context and constraints

Measured ego speed and command targets are separate quantities. This offline example initializes the target speed and steering from the snapshot using `ControlState.initialize`, then adds the same `vehicle_constraints` and timing fields that `JevModel` supplies before a client call. These fields describe how a decision can change the commands, not instantaneous guarantees about physical motion.

![Measured ego state alongside command state and vehicle constraints](images/state-06-control.png)

## Data and reproducibility

The small examples contain only structured scene state and basic scene metadata; they contain no credentials, API response, model weights or original USDZ archive.

- [Selected snapshot and initialized command context](examples/driving-state.json): source for all six figures.
- [Rendering script](../scripts/render-state-guide.py): draws directly from that JSON file using NumPy and Matplotlib. It requires no simulator, network access or JEV provider.

From an environment with the project dependencies installed:

```bash
python scripts/render-state-guide.py
```

For the complete field schema explanations, see the [structured-state guide](structured-state.md). For how these inputs flow through the simulator and policy, see the [complete workflow](full-workflow.md).

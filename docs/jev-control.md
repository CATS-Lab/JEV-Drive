# From JEV answers to driving control

English | [简体中文](jev-control.zh-CN.md)

Prompt **`jev-drive-v1.6`** asks JEV for a speed action and an **absolute reference steering target**. The model chooses the driving action; our code applies command limits and generates a reference for AlpaSim's MPC.

```mermaid
flowchart LR
    A[Structured state + two questions] --> B[JEV action probabilities]
    B --> C[Select explicit action]
    C --> D[Speed update + absolute steering target]
    D --> E[Rate limits + speed-ramped trajectory]
    E --> F[AlpaSim MPC and vehicle dynamics]
```

## Questions and safety instructions

The shared prompt requires the whole vehicle to remain within source road edges, avoid collision, follow lane travel directions, avoid shoulders and respect known traffic-control facts. Road-corridor navigation does not prescribe GT waypoints or override safety. Unknown signals remain unknown. These are model instructions, not a collision-prevention guarantee.

Every level is a standalone semantic description: it names a driving situation and the corresponding action. Steering levels distinguish a sharp bend or large path error from a broad bend or small error, and specify the correction direction. Straight means **zero reference steering**, unwinding the previous turn within the steering-rate limit. It does not mean maintaining an existing turn. Exact English criteria are in [questions.py](../src/jev_drive/policy/questions.py).

In v1.6, every Score criterion and Choice label also states its numerical speed increment (m/s) or absolute steering target (rad). These descriptions and execution share `control/action_mapping.py`. The model receives `vehicle_constraints.control_mapping`: the active action table, rate/absolute-limit equations, gradual overspeed recovery, and the speed-ramp/constant-curvature reference equations. Values are generated from the active configuration. The prompt version changes because existing v1.5 answers were produced without this contract and cannot seed v1.6 rollouts.

## Score mode

Each axis has nine ordered levels. We validate the returned Score and probabilities, then execute the **unique highest-probability level**. The continuous score is retained for diagnostics; it is not accumulated into control. A tie for highest probability fails the decision explicitly instead of inventing an averaged action.

| Level | Speed action | Steering target | Default steering angle |
|---:|---|---|---:|
| 0 | Strongest allowed braking for imminent danger | Strong right | −0.400 rad |
| 1 | Firm braking for rapidly closing hazards | Firm right | −0.150 rad |
| 2 | Moderate slowing for reduced clearance | Moderate right | −0.060 rad |
| 3 | Gentle slowing for modest excess speed | Gentle right | −0.015 rad |
| 4 | Maintain an appropriate target speed | Straight; unwind previous turn | 0 rad |
| 5 | Gentle acceleration with clear space | Gentle left | +0.015 rad |
| 6 | Moderate acceleration on an open lane | Moderate left | +0.060 rad |
| 7 | Firm acceleration when substantially too slow | Firm left | +0.150 rad |
| 8 | Strongest allowed acceleration from low speed with ample clearance | Strong left | +0.400 rad |

These are two separate questions, not paired actions. Numeric magnitudes are applied in code; the model's criteria describe situations and actions.

```text
speed increment = (selected_speed_level − 4) × speed_score_gain
steering target = steering_targets[selected_steering_level]
steering change = steering target − previous steering command
```

Defaults are `speed_score_gain=0.25 m/s` and `steering_score_gain=0.015 rad`. Gentle, moderate and firm steering magnitudes use 1×, 4× and 10× the steering gain, capped by the angle bound; strong steering uses the full configured bound. This retains fine correction resolution without losing the available turning range. Repeated gentle-left decisions continue to request +0.015 rad, rather than accumulating larger turns. For a returned score of 3.99 whose most probable steering level is 4, the target is exactly zero. A prior −0.20 rad command moves to −0.04 rad, then zero at the default 0.2-second interval and 0.8 rad/s rate limit.

## Choice mode

Choice executes its returned, validated `choice` label, rather than a probability difference. `accelerate`, `hold` and `decelerate` request `+choice_speed_gain`, zero and `−choice_speed_gain`. `left`, `straight` and `right` request absolute steering targets `+choice_steering_gain`, zero and `−choice_steering_gain`.

Default gains are 1 m/s and 0.06 rad. The same rate limits apply. Straight explicitly returns the steering reference toward zero in both modes.

## Initialization and limits

The initial command speed equals measured forward speed, **including speeds above the configured cap**. Initial steering is estimated from measured yaw rate and that same actual speed. Negative initial longitudinal speed is unsupported and rejected.

Normal speed commands use the configured acceleration/deceleration and speed bounds. If the initial target exceeds the cap, it is brought down gradually at the configured deceleration rate; the command can temporarily remain above the cap during this recovery. This is necessary to avoid an instantaneous speed discontinuity.

For a 31.23 m/s start, 15 m/s cap and 3 m/s² deceleration limit, the first 0.2-second update is **30.63 m/s**, not 15 m/s. Steering targets are also subject to absolute-angle and rate limits.

## Reference trajectory and execution

The four-second reference starts at **measured speed** and ramps toward the updated target under the configured acceleration limits. Distance is the integral of that speed profile. The bicycle model maps distance to position and heading using constant reference curvature `tan(steering) / wheelbase`; references are regenerated every 0.2 seconds.

The command and reference limits do not mathematically guarantee identical limits on the vehicle's measured acceleration: MPC tracking and vehicle dynamics can differ. Native-controller regression tests cover the high-speed-start case, in addition to analytic command/reference checks.

## Audit and compatibility

`decisions.jsonl` retains `raw_response`, `score_diagnostics.selected_level`, `control_before`, `increments.requested_steering_target_rad`, `control`, and the trajectory's speed profile. Outcome events record actual simulated motion. Identical duplicate requests are cached, so their actions are not applied twice.

This changes the control contract from v1.4. Old rollout responses must not be replayed as v1.5 decisions; recovery checks prompt versions before using seed answers. Old experiments and GIFs remain historical records, not evidence for the corrected controller.

See [recovery and coverage](recovery.md), [road navigation](navigation.md) and [structured input facts](input-facts.md).

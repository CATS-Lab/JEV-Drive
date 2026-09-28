# Rollout recovery and coverage

[简体中文](recovery.zh-CN.md)

```bash
scripts/jev-drive --config configs/default.json retry-scene \
  --artifact "$JEV_ARTIFACT" --steps 99 \
  --rewind-steps 5 --max-retries 3 --output outputs/recovery-scene
```

Set `--steps` to the available closed-loop duration of the artifact (99 decisions for the local 20-second recordings, after 0.2-second warmup). Use a new output directory. The configured backend is used; recovery does not depend on Vercel.

When a sampled check detects a collision or supported violation, the attempt stops. The next attempt starts the native simulator from its original initial state, replays cached answers until five decisions before the failed decision, then requests new JEV answers. At a 0.2-second interval this rewinds one second. Replayed answers make no API calls. Policy inputs are compared throughout replay and at the recovery point: integers/identifiers must match; floating-point values tolerate 0.001 in their native units, with one millimetre of rounding tolerance for map fields. A larger mismatch stops the scene as an infrastructure failure.

JEV receives explicit `retry_context` describing the failed simulated branch when it makes new decisions after rewind. This is recovery feedback about a previous attempt, so recovered results are reported separately from the first attempt. Neither branch supplies intermediate GT waypoints.

A site gets at most three retries **after the initial attempt**. Failures within five decisions of the site's first failure, or within five metres of its original position, share a budget even if the violation changes. Each scene also caps new decision requests at `steps × (max_retries + 1)`. Rate-limit HTTP retries follow the client's existing retry policy; these are distinct from scene retries. Authentication/credit failures stop the batch. API failures do not trigger a fabricated fallback policy.

## What triggers recovery

Checks request controller poses every 50 ms. They check ego's oriented full footprint and vertical extent against all current scene actors after the same conservative overlap filter used by the input pipeline, without the input's nearest-16 truncation. Contact requires more than 0.02 m² of planar overlap and more than 0.2 m of vertical overlap. Raw traffic tracks remain unchanged.

Other triggers are overlap longer than 0.1 m with a source **road edge**, motion faster than 1 m/s opposed by over 120° to every containing lane's local centerline direction, and the ego box center lying exclusively in explicitly marked shoulder lanes. Lane/map checks reject geometry more than 1.5 m vertically from the ego footprint's bottom. These geometric thresholds are evaluation assumptions, not ground-truth traffic adjudication. Ordinary lane boundaries and ROI crop boundaries do not trigger the road-edge check.

Missing traffic-light phases, unknown speed-limit units, stop-sign compliance and solid-marking crossing remain **unassessed**. Being outside the road without an observed source-road-edge contact also remains unassessed. Geometry can be incomplete; sampled checks can miss contacts between samples. A run without a detected violation is not a guarantee of legal or collision-free driving. An invalid initial navigation or an initial geometry violation excludes the scene before API calls and is reported separately.

## Reading the results

`experiment.json` retains every attempt, failure, retry site and these metrics:

- **First-attempt safe time coverage:** complete decision intervals before the first detected violation, divided by requested intervals.
- **Best-branch safe time coverage:** the largest continuous checked prefix of any one attempt. Branch lengths are never added together.
- **First-pass completion / completion after retries:** separate outcomes; retries never erase an initial failure.
- **Corridor visit fraction:** fraction of the *initial planned road corridors* visited by the ego center during accepted samples. It is a discrete visitation metric, not route-distance or destination coverage.
- **Distance, stationary fraction, unknown-lane samples, new decision requests and replay counts:** retained per attempt so standing still is distinguishable from driving the route.

Each attempt keeps decisions, source/cache events, sampled checks, controller trajectories and native logs. Run `scripts/render-scene-previews.py --run <attempt-directory> --artifact "$JEV_ARTIFACT"` for separate panorama and lane GIFs. The panorama has GT above JEV. Translucent gray areas mark the road-corridor lane IDs actually provided to JEV at each decision, in both panels; they show navigation areas rather than an exact target trajectory. The terminal failure frame retains the last decision navigation. The detected terminal failure pose is included when available. Do not splice failed branches into a single successful trajectory.

For a fixed set of scenes, use `python -m jev_drive.evaluation.suite --manifest scenes.json --config configs/default.json --output outputs/recovery-suite --render-script scripts/render-scene-previews.py` in the configured Python/AlpaSim environment. The manifest has `{"scenes":[{"tag":"example","artifact":"/absolute/path/scene.usdz"}]}`. The suite updates bilingual indexes and aggregate metrics after each scene; unfinished scenes are clearly listed and not silently treated as passes.

### Height handling without ground contact

The native structured-state harness disables ground contact. Its integrated ego height can drift away from the source road surface, so raw 3D box heights can miss an otherwise overlapping road actor. Evaluation `local_road_surface_v1` aligns only the ego box bottom to the median centerline height of the closest source lane polygons (within 2 m, distance tie tolerance 0.05 m). Actors retain their source heights; steering, physics and JEV inputs are unchanged. Candidate heights differing by more than 1.5 m, or no nearby lane surface, stop assessment with `assessment_failed`, rather than count as a pass or a driving violation. Each sample records the adjustment and source lane IDs. This is sampled road-surface-aligned occupancy, not a ground-contact physics guarantee.

A scene manifest may specify `seed_log` per scene. Replay checks the complete state and current prompt version before reusing an answer; only new branch decisions call the API. Evaluation revisions can therefore recheck existing answers without repeating their API cost.

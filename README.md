# JEV-Drive

A research interface connecting **structured AlpaSim scene state → JEV decisions → AlpaSim vehicle motion**. JEV chooses incremental target-speed and steering commands; AlpaSim's MPC and vehicle dynamics execute the resulting reference trajectory. This implementation uses JEV through Vercel AI Gateway (`typesafe-ai/jev`). It does not use the Alpamayo driving model.

This repository contains the integration code, modular state builders, configuration, tests, and a small AlpaSim runtime patch. Scene datasets, model weights, API credentials, experiment outputs, and the AlpaSim source tree are not included.

## Architecture

```text
AlpaSim PolicyEvent
  → runtime_bridge + AlpasimAdapter
  → SceneSnapshot → independent state builders
  → versioned JSON in DriveRequest.renderer_data
  → JEV gRPC driver → JevModel → JevClient (Vercel)
  → bounded speed/steering increments → reference trajectory
  → AlpaSim MPC + vehicle dynamics → next scene state
```

| Interface | Location | Responsibility |
|---|---|---|
| Simulator adapter | `src/jev_drive/integration/alpasim_adapter.py` | Current/past ego and actor state; source map and traffic-control facts |
| Runtime bridge | `src/jev_drive/integration/runtime_bridge.py` | Package the state at each policy step |
| Transport schema | `src/jev_drive/state/schema.py` | Version, session, timestamp, frame and finite-value validation |
| State builders | `src/jev_drive/state/` | Separate modules for ego, roads, actors, lane matching, navigation, signals, stop lines, signs and vehicle constraints |
| Driver service | `src/jev_drive/integration/driver_service.py` | AlpaSim `EgodriverService` gRPC interface |
| Policy | `src/jev_drive/policy/jev_model.py` | Per-session decision state and response interpretation |
| Replaceable backend | `src/jev_drive/policy/jev_client.py` | Vercel authentication, evaluation requests, validation and retries |
| Control conversion | `src/jev_drive/control/` | Score/Choice mapping, rate limits and trajectory generation |

The transport has `kind=jev.scene_snapshot`, `schema_version=1`, session and simulation timestamps, and an ego-local frame (+x forward, +y left, +z up). Original renderer bytes are preserved separately, not sent to JEV. A replacement backend implements `async decide(state, questions)`; see the existing client and model for the response contract. The CLI also calls `async close()` on the client.

## Visual guide to structured inputs

See [Structured state: a visual guide](docs/structured-state.md) for diagrams of ego state, road geometry, actors, navigation, traffic controls and command constraints, with small JSON examples and links to each builder.

## Installation

Use Linux and **Python 3.12**. State construction and mocked API tests can run without AlpaSim:

```bash
git clone https://github.com/CATS-Lab/JEV-Drive.git
cd JEV-Drive
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
scripts/test -q
```

Simulator integration tests skip when AlpaSim packages are unavailable. They make no paid JEV requests.

For simulation, first provision a working [AlpaSim environment](https://github.com/NVlabs/alpasim) with its runtime, controller, gRPC, utils (including geometry), and their dependencies installed. The integration was tested against upstream commit **`3032e0cfabbd9547e83d204d5bb011bb8e0c78e0`**. Installing JEV-Drive alone does not install that simulator stack. Activate that Python 3.12 environment and install JEV-Drive there with `python -m pip install -e '.[test]'`.

Create a separate checkout for the opt-in runtime hook:

```bash
git clone https://github.com/NVlabs/alpasim.git .vendor/alpasim
git -C .vendor/alpasim checkout 3032e0cfabbd9547e83d204d5bb011bb8e0c78e0
git -C .vendor/alpasim apply --check "$PWD/patches/alpasim-jev-runtime.patch"
git -C .vendor/alpasim apply "$PWD/patches/alpasim-jev-runtime.patch"
export ALPASIM_ROOT="$PWD/.vendor/alpasim"
```

`scripts/jev-drive` and `scripts/test` prepend this patched runtime to `PYTHONPATH`. They use `python` from the activated environment, or an interpreter specified by `JEV_PYTHON`. Keep installed AlpaSim packages compatible with the pinned checkout. Applying the patch twice will fail; apply it once to a clean checkout.

## Usage

Obtain a compatible AlpaSim USDZ scene separately. Set its local path:

```bash
export JEV_ARTIFACT=/absolute/path/to/scene.usdz
```

Inspect structured input without calling JEV:

```bash
scripts/jev-drive snapshot --artifact "$JEV_ARTIFACT" --output outputs/snapshot
scripts/jev-drive rebuild-state \
  --snapshot outputs/snapshot/snapshot.json \
  --output outputs/snapshot/rebuilt-state.json
```

For a real JEV rollout, set `AI_GATEWAY_API_KEY` in the same shell. An interactive Bash prompt avoids putting the key in command history:

```bash
read -rsp 'Vercel AI Gateway key: ' AI_GATEWAY_API_KEY; echo
export AI_GATEWAY_API_KEY
scripts/jev-drive --config configs/default.json native-simulate \
  --artifact "$JEV_ARTIFACT" --steps 5 --output outputs/first-run
```

This sends the cropped structured scene state to `https://ai-gateway.vercel.sh/v1/evaluate` and consumes the Vercel account's quota. Credentials are read only from `AI_GATEWAY_API_KEY`. Use a fresh output directory for each run.

| Config | Behavior |
|---|---|
| `configs/default.json` | Score control; fail on API errors |
| `configs/choice.json` | Choice control; fail on API errors |
| `configs/full-scene.json` | Score control; wait/retry HTTP 429; minimum 1 s between request starts |

For a compatible **20-second recording**, the native harness uses a 0.2-second recorded warmup followed by **99 decisions at 0.2 seconds**:

```bash
scripts/jev-drive --config configs/full-scene.json native-simulate \
  --artifact "$JEV_ARTIFACT" --steps 99 --output outputs/full-scene
```

The step count is explicit, not automatically inferred for arbitrary scenes. The 4-second reference trajectory horizon is not the scene duration.

With retries enabled, valid `Retry-After` seconds or HTTP dates take precedence. Otherwise waits are 5, 10, 20, 40, then 60 seconds. The same frozen decision is retried until success or cancellation; simulation time does not advance during the wait. Non-429 errors still fail the rollout. No substitute policy is used. Ctrl+C cancels the run.

To keep a run alive across SSH disconnection, enter a tmux session **from the configured shell**, then run the simulation command above:

```bash
tmux -L jev-drive new -s jev-drive
```

Detach with Ctrl+B, release both keys, then press lowercase D. Reattach with `tmux -L jev-drive attach -t jev-drive`. An already-running tmux server may have an older environment; export the key inside its shell if needed.

### External runtime

Start the driver with `scripts/jev-drive serve --host 127.0.0.1 --port 6789 --output outputs/driver`. In the external AlpaSim runtime, use the patched checkout, make `jev_drive` importable, and set:

- `JEV_DRIVE_ENABLED=1`
- `JEV_CONFIG=/absolute/path/to/config.json`
- `JEV_SCENE_MANIFEST=/absolute/path/to/manifest.json`

The manifest is a JSON object mapping **internal scene IDs** to runtime-visible USDZ paths; file UUIDs and internal IDs can differ. The native launcher creates this mapping automatically. Configure the runtime driver endpoint, 200000 µs policy interval, ego noise off, explicit traffic mode, and no driver RPC deadline if indefinite 429 waits are enabled. Container mounts must expose the same configuration and scene paths inside the runtime.

## Debugging and tests

Every structured-input component is a separate Python module. Builders accept a saved `SceneSnapshot` and `Config`, allowing independent debugging without API calls:

```python
import json
from pathlib import Path
from jev_drive.config import Config
from jev_drive.state.snapshot import SceneSnapshot
from jev_drive.state.traffic_signals import build

snapshot = SceneSnapshot.from_dict(json.loads(Path("outputs/snapshot/snapshot.json").read_text()))
print(build(snapshot, Config()))
```

Run core tests with `scripts/test -q`. To include scene-dependent integration tests, export `JEV_TEST_ARTIFACT` pointing to the compatible 20-second scene used for validation, with populated nearby actors and nonzero initial speed, then run the same command. Tests use fixed/mocked decisions, not the paid API. The full-scene test expects 99 steps to reach the recording end.

Outputs include `decisions.jsonl` (state, response, command, retry and outcome events), `summary.json`, native `.asl` rollouts, controller CSVs, and BEV PNG/GIF visualizations after successful runs. API usage and provider metadata are retained when supplied. HTTP diagnostic logs redact credentials. Outputs can contain scene data and should remain outside the repository.

## Status and limitations

A real one-step Vercel JEV rollout was verified locally. A 99-step native integration test passed with a fixed test client; this is not evidence of full-scene JEV driving performance. Live full-scene JEV evaluation is still in progress and has encountered upstream HTTP 429 responses. A fresh AlpaSim installation on a separate machine has not been validated.

The native launcher is headless, uses recorded traffic replay, and disables photorealistic rendering and ground-contact correction. Traffic is not reactive. Inputs are privileged structured simulator state, not perception outputs. Missing signal phases remain explicitly unknown; static signal geometry alone does not establish right of way.

Default speed-command changes are limited to ±3 m/s² (±0.6 m/s per 0.2-second decision), with separate steering rate/angle bounds. These constrain commands, not guaranteed physical vehicle motion. API latency is allowed to pause simulation, so this is not a real-time capability claim. Successful rollout completion does not establish collision-free or rule-compliant driving.

AlpaSim and externally obtained datasets remain subject to their own licenses and access terms.

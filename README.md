# JEV-Drive

A research interface connecting **structured AlpaSim scene state → JEV decisions → AlpaSim vehicle motion**. JEV chooses incremental target-speed and steering commands; AlpaSim's MPC and vehicle dynamics execute the resulting reference trajectory. The default client calls the official TypeSafe JEV API (`jev-latest`). It does not use the Alpamayo driving model.

This repository contains the integration code, modular state builders, configuration, tests, and a small AlpaSim runtime patch. Small structured-state examples and derived BEV figures are included for documentation. Full scene datasets, model weights, API credentials, experiment outputs, and the AlpaSim source tree are not included.

## Architecture

```text
AlpaSim PolicyEvent
  → runtime_bridge + AlpasimAdapter
  → SceneSnapshot → independent state builders
  → versioned JSON in DriveRequest.renderer_data
  → JEV gRPC driver → JevModel → replaceable JEV client
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
| Official JEV client | `src/jev_drive/policy/jev_client.py` | TypeSafe JEV API using `TYPESAFE_API_KEY` |
| Control conversion | `src/jev_drive/control/` | Score/Choice mapping, rate limits and trajectory generation |

The transport has `kind=jev.scene_snapshot`, `schema_version=1`, session and simulation timestamps, and an ego-local frame (+x forward, +y left, +z up). Original renderer bytes are preserved separately, not sent to JEV. A replacement backend implements `async decide(state, questions)`; see the existing client and model for the response contract. The CLI also calls `async close()` on the client.

## Complete workflow

See the [end-to-end implementation flowchart](docs/full-workflow.md) for startup, structured state, JEV decisions, MPC execution and saved outputs. The workflow does not require a particular JEV service provider.

## Visual guide to structured inputs

Start with the [real-scene BEV field guide](docs/bev-state-guide.md): each figure places an annotated scene beside its actual structured fields.

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

### Run with the official JEV API

Obtain a key from TypeSafe and export `TYPESAFE_API_KEY` in the shell that launches the driver. The default model is `jev-latest`, and the endpoint is `https://api.typesafe.ai/v1/systemone`, following the [official quick start](https://docs.typesafe.ai/introduction/quickstart).

```bash
read -rsp 'TypeSafe JEV API key: ' TYPESAFE_API_KEY; echo
export TYPESAFE_API_KEY
scripts/jev-drive --config configs/default.json native-simulate \
  --artifact "$JEV_ARTIFACT" --steps 5 --output outputs/first-run
```

The client sends `{model, state, questions}` with bearer authentication and reads typed results from `answers`. Use a fresh output directory for each run. `JevModel` depends only on `async decide(state, questions)`, so authentication and transport stay separate from scene builders and control logic.

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

All three configs above use the official JEV API. The [local development adapter](docs/local-development.md) is opt-in and is not a prerequisite for users.

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

## License

Original JEV-Drive code and documentation are licensed under the [MIT License](LICENSE).
The AlpaSim runtime patch retains the applicable upstream Apache-2.0 terms;
scene-derived examples and figures remain subject to their source data terms.
See [third-party notices](THIRD_PARTY_NOTICES.md) for attribution and scope.

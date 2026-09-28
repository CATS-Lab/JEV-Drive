# Setup and usage

English | [简体中文](setup.zh-CN.md)

Run all commands from the JEV-Drive repository root. For the project overview, return to the [README](../README.md).

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

All three configs above use the official JEV API. The [local development adapter](local-development.md) is opt-in and is not a prerequisite for users.

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

## Labeled rollout previews

Generate a fixed-view panorama and an ego-following lane close-up from an existing run, without API calls:

```bash
PYTHONPATH=src python scripts/render-scene-previews.py \
  --run /absolute/path/to/run --artifact "$JEV_ARTIFACT"
```

The script uses the AlpaSim Python environment and a Noto Sans CJK font at `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`. Both English and Chinese GIFs are saved under `previews/labeled-panorama-NNN/` and `previews/labeled-lanes-NNN/`. It matches GT and simulated poses at recorded decision timestamps. Stable colors and IDs connect only one-to-one map segments; new IDs at junction branches do not necessarily mean a lane change. Use `--views panorama` or `--views lanes` to regenerate one view.

Panorama GIFs place GT above JEV, with the full width available to each view. Lane close-ups retain GT on the left and JEV on the right.

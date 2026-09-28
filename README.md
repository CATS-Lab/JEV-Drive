# JEV-Drive: Using JEV to Drive in AlpaSim from Structured Scene State

English | [简体中文](README.zh-CN.md)

JEV-Drive uses TypeSafe's [JEV](https://docs.typesafe.ai/introduction) to drive an ego vehicle in NVIDIA's [AlpaSim](https://github.com/NVlabs/alpasim). JEV reads structured ego state, lanes, nearby actors, navigation and traffic controls, then selects speed and steering changes. AlpaSim's MPC and vehicle dynamics execute the resulting reference trajectory.

**Structured scene state → JEV decisions → bounded control → AlpaSim motion → next observation.**

The default client uses the [official JEV API](https://docs.typesafe.ai/introduction/quickstart) (`jev-latest`). Policy input comes from structured simulator state; this project does not use the Alpamayo driving model.

Navigation now uses [map-derived road corridors](docs/navigation.md), not intermediate GT waypoints. The example rollouts below were recorded before this change.

## Examples

Same scene and timestamps: **93 decision frames spanning 18.4 s** from a partial JEV Score rollout, recorded with the [development client](docs/local-development.md). Four same-direction lanes are labeled **L1–L4, left to right**. GT follows the original recorded trajectory: **L3 → L2 → L3**; JEV later moves into L4 and drifts outside the mapped lanes. This run stopped at decision 94 on response validation, before the probability-rounding fix.

**Fixed-view panorama — GT above, JEV below; vehicles travel to the right.**

<p align="center">
  <img src="docs/images/lane-panorama.gif" width="960" alt="Horizontal fixed-view GT and JEV comparison with four consistently colored lanes">
</p>

**Lane close-up — GT left, JEV right; each camera follows its ego vehicle.**

<p align="center">
  <img src="docs/images/lane-closeup.gif" width="800" alt="GT and JEV lane close-up showing stable lane labels, body-center lane and boundary overlap">
</p>

Lane colors and IDs stay consistent across both views. Green is the ego vehicle; a red outline in the close-up marks body overlap with a mapped boundary. Highway classification is unverified; map edges do not identify painted marking types.

## Understand the implementation

- **[How JEV produces control](docs/jev-control.md)** — questions, Score/Choice answers, command limits and trajectory generation, with a worked example.
- [Five-module workflow](docs/full-workflow.md) — how the implementation fits together.
- [BEV state guide](docs/bev-state-guide.md) — annotated scene elements beside their actual input fields.

## Quick start

Requirements: **Linux, Python 3.12, a configured AlpaSim environment, a compatible USDZ scene and a TypeSafe API key**. Complete the [setup instructions](docs/setup.md), including the AlpaSim runtime patch, then run from the repository root:

```bash
export JEV_ARTIFACT=/absolute/path/to/scene.usdz
read -rsp 'TypeSafe JEV API key: ' TYPESAFE_API_KEY; echo
export TYPESAFE_API_KEY
scripts/jev-drive --config configs/default.json native-simulate \
  --artifact "$JEV_ARTIFACT" --steps 5 --output outputs/first-run
```

Use a new output directory for each run. Results include decision logs, simulated motion and BEV visualizations. See [setup and usage](docs/setup.md#usage) for offline snapshots, Choice mode, full-scene runs, tmux and external runtime integration.

The repository includes interface code, configurations, a runtime patch and small documentation examples. Obtain the AlpaSim installation and full scene data separately. An optional [local development adapter](docs/local-development.md) is documented separately.

## License

Original code and documentation: [MIT](LICENSE) ([Chinese reference translation](LICENSE.zh-CN.md)). The AlpaSim patch retains applicable Apache-2.0 terms; scene examples and figures retain their source-data terms. See [third-party notices](THIRD_PARTY_NOTICES.md).

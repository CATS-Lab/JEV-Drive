# Third-party notices

The MIT license in `LICENSE` covers original JEV-Drive code and documentation.
It does not replace third-party licenses or grant rights to externally sourced
scene data, model weights, or hosted services.

## AlpaSim runtime patch

- Upstream: https://github.com/NVlabs/alpasim
- Base commit: `3032e0cfabbd9547e83d204d5bb011bb8e0c78e0`
- File modified: `src/runtime/alpasim_runtime/events/policy.py`
- Upstream file notice: `Copyright (c) 2026 NVIDIA Corporation`
- Upstream license: Apache License, Version 2.0; a copy of the upstream license
  file, including its existing notice, is in [LICENSES/AlpaSim-Apache-2.0.txt](LICENSES/AlpaSim-Apache-2.0.txt).

`patches/alpasim-jev-runtime.patch` adds an opt-in `JEV_DRIVE_ENABLED` hook that
calls the JEV-Drive runtime bridge before querying the driver. This patch contains
upstream context and JEV-Drive changes; it does not relicense AlpaSim under MIT.
The upstream source header remains intact when the patch is applied. The full
AlpaSim source tree is obtained separately and is not vendored in this repository.

## Scene examples and derived figures

`docs/examples/driving-state.json` and all six figures in `docs/images/` derive
from an offline snapshot at 0.2 seconds in the locally available AlpaSim scene
`clipgt-01330416-9f29-4799-86a6-c4b2f8593375`. They contain extracted structured
facts, initialized command context and visualizations, not original USDZ archives
or a live JEV model response.

Underlying scene data and any rights in derived examples remain subject to the
original dataset's license and access terms. This repository does not grant MIT
rights to those underlying data. Dataset permission terms are not established
by the AlpaSim software license. The original plotting script is JEV-Drive code
and is covered by MIT.

## Other dependencies and services

Installed Python dependencies retain their own licenses. JEV model weights and
hosted API services are not distributed here and remain subject to their
respective terms. Using a different JEV client does not change these ownership
or licensing boundaries.

# Local development adapter

English | [简体中文](local-development.zh-CN.md)

The public default is the [official TypeSafe JEV API](https://docs.typesafe.ai/introduction/quickstart): `backend: "typesafe"`, `jev-latest`, `TYPESAFE_API_KEY`. The adapter in `policy/jev_client.py` is the normal user entry point.

For this project's local development, the maintainers currently cannot register for direct JEV access, so a separate Vercel adapter is retained. This is a local access workaround, not a requirement for JEV-Drive users or a claim about general registration availability.

Select it explicitly:

```bash
read -rsp 'Vercel AI Gateway key: ' AI_GATEWAY_API_KEY; echo
export AI_GATEWAY_API_KEY
scripts/jev-drive --config configs/vercel-dev.json native-simulate \
  --artifact "$JEV_ARTIFACT" --steps 99 --output outputs/local-dev-run
```

`configs/vercel-dev.json` sets `backend: "vercel"`, model `typesafe-ai/jev`, and endpoint `https://ai-gateway.vercel.sh/v1/evaluate`. Vercel-specific identity and credentials are isolated in [vercel_client.py](../src/jev_drive/policy/vercel_client.py); shared JSON request/response handling lives in [http_client.py](../src/jev_drive/policy/http_client.py).

Official and development clients read only their own credential environment variable. An exported gateway key does not change the default backend. The program does not fall back to another provider on authentication failure, HTTP errors or malformed answers. Unknown backends and mismatched endpoints fail configuration validation. To pin an official model version, set its documented model ID in the official config.

The optional retry behavior is shared: when `retry_429` is enabled, valid `Retry-After` seconds or HTTP dates take precedence; otherwise waits are 5, 10, 20, 40, then 60 seconds. The same frozen request is retried without advancing the simulation. Other failures remain fatal. The public default config is fail-fast; full-scene and local-development configs enable 429 waiting.

## Verification

The official request path is checked with offline mocked HTTP tests for its endpoint, model, bearer key, answer handling and control integration. A successful authenticated call to the official service has not been performed in this environment. Development Vercel results do not establish official-service access. No live API call is required to run the test suite.

# Bundled JEV adapter

These are implementation details of `policy/jev_client.py`, not requirements of the JEV-Drive architecture. The bundled CLI creates this adapter; a different provider requires replacing that construction with a compatible client.

- Model: `typesafe-ai/jev`
- Endpoint: `https://ai-gateway.vercel.sh/v1/evaluate`
- Credential: `AI_GATEWAY_API_KEY` from the environment

With retries enabled, valid `Retry-After` seconds or HTTP dates take precedence. Otherwise waits are 5, 10, 20, 40, then 60 seconds. The same frozen decision is retried until success or cancellation; simulation time does not advance during the wait. Non-429 errors still fail the rollout. No substitute policy is used. Ctrl+C cancels the run.

The diagrams in the [complete workflow](full-workflow.md) focus on the provider-independent simulation and client boundary.

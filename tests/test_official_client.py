"""Offline official API contract and strict backend/credential selection."""

import json
from pathlib import Path
import httpx
import pytest
from jev_drive.config import Config
from jev_drive.policy.client_factory import create_client
from jev_drive.policy.jev_client import JevAPIError, JevClient
from jev_drive.policy.vercel_client import VercelJevClient
from jev_drive.policy.jev_model import JevModel
from jev_drive.policy.questions import build
from jev_drive.state.state_builder import JevStateBuilder
from jev_drive.logging.decision_log import DecisionLog
from test_core import score_response, snapshot


@pytest.mark.asyncio
async def test_official_default_request_through_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "official-test-key")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gateway-must-not-be-used")
    response = score_response(8, 8)
    response.update(
        model="jev-1.13.0", usage={"input_tokens": 100, "output_tokens": 20}
    )
    requests = []
    config = Config()

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["Authorization"] == "Bearer official-test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "jev-latest"
        assert payload["questions"] == build(config)
        assert set(payload) == {"model", "state", "questions"}
        assert b"key" not in request.content
        return httpx.Response(200, json=response)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    client = create_client(config)
    assert isinstance(client, JevClient) and client.source_label == "typesafe_official"
    model = JevModel(config, client, DecisionLog(tmp_path))
    model.start("session")
    try:
        result = await model.predict(JevStateBuilder(config).build(snapshot()))
        assert len(requests) == 1
        assert json.loads(requests[0].content)["state"] == result["state"]
        assert result["raw_response"] == response
        assert result["increments"]["applied_delta_speed"] == pytest.approx(0.6)
    finally:
        await client.close()


@pytest.mark.parametrize("key", [None, "", " ", "bad\nkey"])
def test_official_requires_own_key_without_gateway_fallback(monkeypatch, key):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gateway-must-not-be-used")
    monkeypatch.setenv("JEV_API_KEY", "legacy-must-not-be-used")
    if key is None:
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("TYPESAFE_API_KEY", key)
    with pytest.raises(JevAPIError, match="missing or malformed TYPESAFE_API_KEY"):
        create_client(Config())


@pytest.mark.asyncio
async def test_explicit_development_provider(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gateway-test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    cfg = Config(backend="vercel")
    client = create_client(cfg)
    try:
        assert isinstance(client, VercelJevClient)
        assert cfg.model == "typesafe-ai/jev"
        assert cfg.endpoint == "https://ai-gateway.vercel.sh/v1/evaluate"
    finally:
        await client.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"backend": "unknown"},
        {"endpoint": "https://ai-gateway.vercel.sh/v1/evaluate"},
        {"backend": "vercel", "endpoint": "https://api.typesafe.ai/v1/systemone"},
    ],
)
def test_reject_mismatched_provider_endpoint(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs)


def test_shipped_public_configs_use_official_endpoint():
    root = Path(__file__).resolve().parents[1]
    for name in ("default", "choice", "full-scene"):
        cfg = Config.load(root / "configs" / f"{name}.json")
        assert cfg.backend == "typesafe"
        assert cfg.model == "jev-latest"
        assert cfg.endpoint == "https://api.typesafe.ai/v1/systemone"
    assert Config.load(root / "configs/vercel-dev.json").backend == "vercel"

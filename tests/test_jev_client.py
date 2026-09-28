"""Offline checks of the Vercel evaluation contract and fail-fast behavior."""

from copy import deepcopy
import json
import httpx
import pytest
from jev_drive.config import Config as BaseConfig
from jev_drive.logging.decision_log import DecisionLog
from jev_drive.policy.http_client import JevAPIError
from jev_drive.policy.vercel_client import VercelJevClient as JevClient
from jev_drive.policy.jev_model import JevModel
from jev_drive.policy.questions import build
from jev_drive.state.state_builder import JevStateBuilder
from test_core import score_response, snapshot


def Config(**kwargs):
    return BaseConfig(backend="vercel", **kwargs)


def gateway_response(mode):
    if mode == "score":
        answers = score_response(8, 8)["answers"]
        for answer in answers.values():
            del answer["confidence"]
            del answer["legend"]
    else:
        answers = {
            "speed": {
                "type": "choice",
                "choice": "accelerate",
                "probabilities": {"accelerate": 0.7, "hold": 0.2, "decelerate": 0.1},
            },
            "steering": {
                "type": "choice",
                "choice": "left",
                "probabilities": {"left": 0.7, "straight": 0.2, "right": 0.1},
            },
        }
    return {
        "model": "typesafe-ai/jev",
        "answers": answers,
        "usage": {"inputTokens": 100, "outputTokens": 20},
        "providerMetadata": {
            "gateway": {
                "routing": {"finalProvider": "typesafe-ai"},
                "cost": "0.0000042",
            }
        },
    }


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test-gateway-credential")
    monkeypatch.setenv("JEV_API_KEY", "unused-legacy-credential")
    monkeypatch.setenv("TYPESAFE_API_KEY", "unused-legacy-credential")
    real_client = httpx.AsyncClient

    def make(handler, config=None):
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: real_client(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        )
        return JevClient(config or Config())

    return make


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,steering", [("score", 0.16), ("choice", 0.06)])
async def test_gateway_request_to_model_preserves_answers_and_metadata(
    make_client, tmp_path, mode, steering
):
    requests = []
    config = Config(mode=mode)
    response = gateway_response(mode)

    def handle(request):
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://ai-gateway.vercel.sh/v1/evaluate"
        assert request.headers["Authorization"] == "Bearer test-gateway-credential"
        assert request.headers["Content-Type"] == "application/json"
        payload = json.loads(request.content)
        assert payload["model"] == "typesafe-ai/jev"
        assert payload["questions"] == build(config)
        assert set(payload) == {"model", "state", "questions"}
        assert b"credential" not in request.content
        return httpx.Response(200, json=response)

    client = make_client(handle, config)
    model = JevModel(config, client, DecisionLog(tmp_path))
    model.start("session")
    try:
        result = await model.predict(JevStateBuilder(config).build(snapshot()))
        assert len(requests) == 1
        assert json.loads(requests[0].content)["state"] == result["state"]
        assert result["raw_response"] == response
        assert result["increments"]["applied_delta_speed"] == pytest.approx(0.6)
        assert result["increments"]["applied_delta_steering"] == pytest.approx(steering)
        record = json.loads((tmp_path / "decisions.jsonl").read_text())
        assert record["raw_response"] == response
        assert (
            "test-gateway-credential" not in (tmp_path / "decisions.jsonl").read_text()
        )
    finally:
        await client.close()


@pytest.mark.parametrize("key", [None, "", " ", "test\ncredential"])
def test_requires_gateway_environment_key(monkeypatch, tmp_path, key):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "JEV-API.txt").write_text("unused-legacy-credential")
    monkeypatch.setenv("JEV_API_KEY", "unused-legacy-credential")
    monkeypatch.setenv("TYPESAFE_API_KEY", "unused-legacy-credential")
    if key is None:
        monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    else:
        monkeypatch.setenv("AI_GATEWAY_API_KEY", key)

    def unexpected_client(**kwargs):
        pytest.fail("invalid credentials must fail before creating an HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected_client)
    with pytest.raises(JevAPIError, match="^missing or malformed AI_GATEWAY_API_KEY$"):
        JevClient(Config())


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 422, 429, 302])
async def test_http_failure_has_no_retry_redirect_or_body_leak(make_client, status):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={"error": "test-gateway-credential"},
            headers={"Location": "https://example.invalid/redirect"},
        )

    client = make_client(handle)
    try:
        with pytest.raises(JevAPIError, match=f"^JEV HTTP {status}$") as error:
            await client.decide({}, build(Config()))
        assert len(requests) == 1
        assert error.value.diagnostics["status_code"] == status
        assert "test-gateway-credential" not in json.dumps(error.value.diagnostics)
        assert "[REDACTED]" in error.value.diagnostics["response_body"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_transport_error_is_not_a_policy_response(make_client):
    def handle(request):
        raise httpx.ReadTimeout("test-gateway-credential", request=request)

    client = make_client(handle)
    try:
        with pytest.raises(JevAPIError, match="^JEV transport failed: ReadTimeout$"):
            await client.decide({}, build(Config()))
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"answers": {}},
        {"answers": {"speed": [], "steering": {"type": "score"}}},
    ],
)
async def test_malformed_gateway_response_fails_contract(make_client, payload):
    client = make_client(lambda _: httpx.Response(200, json=payload))
    try:
        with pytest.raises(JevAPIError, match="^JEV response contract invalid$"):
            await client.decide({}, build(Config()))
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["probabilities", "confidence", "score"])
async def test_optional_metadata_does_not_weaken_control_validation(
    make_client, tmp_path, invalid
):
    response = deepcopy(gateway_response("score"))
    answer = response["answers"]["speed"]
    if invalid == "probabilities":
        answer["probabilities"]["8"] = 0.5
    elif invalid == "confidence":
        answer["confidence"] = 2.0
    else:
        answer["score"] = 9.0
    client = make_client(lambda _: httpx.Response(200, json=response))
    model = JevModel(Config(), client, DecisionLog(tmp_path))
    model.start("session")
    try:
        with pytest.raises(ValueError):
            await model.predict(JevStateBuilder(Config()).build(snapshot()))
        assert model.sessions["session"]["failed"]
        assert model.sessions["session"]["control"] is None
        failure = json.loads((tmp_path / "decisions.jsonl").read_text())
        assert failure["event"] == "failure"
        assert json.loads(failure["raw_response_json"]) == response
        assert failure["request_state"]["ego"]["current_target_speed_mps"] == 10.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_modal_action_drives_control_and_score_difference_is_logged(
    make_client, tmp_path
):
    # Synthetic regression: the failed live run did not retain its raw response.
    response = gateway_response("score")
    response["answers"]["speed"]["score"] = 4.4
    client = make_client(lambda _: httpx.Response(200, json=response))
    model = JevModel(Config(), client, DecisionLog(tmp_path))
    model.start("session")
    try:
        result = await model.predict(JevStateBuilder(Config()).build(snapshot()))
        assert result["increments"]["raw_delta_speed"] == pytest.approx(1.0)
        assert result["control"]["target_speed"] == pytest.approx(10.6)
        assert result["score_diagnostics"]["speed"] == pytest.approx(
            {
                "reported_score": 4.4,
                "selected_level": 8,
                "raw_probability_sum": 1.0,
                "probability_weighted_mean": 8.0,
                "reported_minus_mean": -3.6,
            }
        )
        record = json.loads((tmp_path / "decisions.jsonl").read_text())
        assert record["raw_response"] == response
        assert record["score_diagnostics"] == result["score_diagnostics"]
        assert not model.sessions["session"]["failed"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rate_limit_evidence_survives_rollout_failure(make_client, tmp_path):
    body = {"error": {"message": "Rate limit exceeded", "type": "rate_limit_exceeded"}}

    def handle(request):
        return httpx.Response(
            429,
            json=body,
            headers={
                "retry-after": "30",
                "x-vercel-id": "test-request-id",
                "x-ratelimit-remaining-tokens": "0",
                "authorization": "Bearer test-gateway-credential",
                "set-cookie": "sensitive-cookie",
            },
        )

    client = make_client(handle)
    model = JevModel(Config(), client, DecisionLog(tmp_path))
    model.start("session")
    try:
        with pytest.raises(JevAPIError, match="JEV HTTP 429"):
            await model.predict(JevStateBuilder(Config()).build(snapshot()))
        failure = json.loads((tmp_path / "decisions.jsonl").read_text())
        details = failure["error_details"]
        assert details["status_code"] == 429
        assert json.loads(details["response_body"]) == body
        assert details["headers"] == {
            "retry-after": "30",
            "x-vercel-id": "test-request-id",
            "x-ratelimit-remaining-tokens": "0",
        }
        assert model.sessions["session"]["failed"]
        assert model.sessions["session"]["control"] is None
        assert "test-gateway-credential" not in json.dumps(failure)
        assert "sensitive-cookie" not in json.dumps(failure)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_error_diagnostics_are_bounded_and_redacted(make_client):
    client = make_client(
        lambda _: httpx.Response(
            429,
            text="test-gateway-credential Bearer another-secret " + "x" * 10000,
            headers={
                "x-request-id": "test-gateway-credential",
                "retry-after": "z" * 1000,
            },
        )
    )
    try:
        with pytest.raises(JevAPIError) as error:
            await client.decide({}, build(Config()))
        details = error.value.diagnostics
        assert len(details["response_body"]) <= 4096
        assert len(details["headers"]["retry-after"]) <= 256
        assert "test-gateway-credential" not in json.dumps(details)
        assert "another-secret" not in json.dumps(details)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_429_retries_same_step_and_applies_control_once(
    make_client, monkeypatch, tmp_path
):
    import asyncio

    config = Config(retry_429=True)
    requests, waits = [], []
    response = gateway_response("score")

    def handle(request):
        requests.append(request.content)
        if len(requests) <= 2:
            return httpx.Response(
                429,
                json={"error": "upstream busy"},
                headers={"retry-after": "7"} if len(requests) == 1 else {},
            )
        return httpx.Response(200, json=response)

    client = make_client(handle, config)
    log = DecisionLog(tmp_path)
    client.on_event = log.write
    model = JevModel(config, client, log)
    model.start("session")

    async def sleep(delay):
        waits.append(delay)
        assert model.sessions["session"]["control"] is None
        assert model.sessions["session"]["last_timestamp"] == -1

    monkeypatch.setattr(asyncio, "sleep", sleep)
    envelope = JevStateBuilder(config).build(snapshot())
    try:
        result = await model.predict(envelope)
        assert await model.predict(envelope) == result
        assert waits == [7.0, 10.0]
        assert len(requests) == 3 and len(set(requests)) == 1
        assert result["control"]["target_speed"] == pytest.approx(10.6)
        rows = [json.loads(line) for line in log.path.read_text().splitlines()]
        assert [r["event"] for r in rows] == ["api_retry", "api_retry", "decision"]
        assert all(r["timestamp_us"] == envelope["timestamp_us"] for r in rows)
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 402, 422, 500])
async def test_non_429_still_fails_with_retry_enabled(make_client, status):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json={"error": "failure"})

    client = make_client(handle, Config(retry_429=True))
    try:
        with pytest.raises(JevAPIError, match=f"JEV HTTP {status}"):
            await client.decide({}, build(Config()))
        assert len(requests) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_waiting_retry_can_be_cancelled(make_client, monkeypatch):
    import asyncio

    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(429, json={"error": "busy"})

    async def stop(delay):
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", stop)
    client = make_client(handle, Config(retry_429=True))
    try:
        with pytest.raises(asyncio.CancelledError):
            await client.decide({}, build(Config()))
        assert len(calls) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_retry_backoff_is_capped(make_client, monkeypatch):
    import asyncio

    waits = []
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        return (
            httpx.Response(429, json={})
            if calls < 6
            else httpx.Response(200, json=gateway_response("score"))
        )

    async def sleep(delay):
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    client = make_client(
        handle, Config(retry_429=True, retry_initial_s=5, retry_max_s=12)
    )
    try:
        await client.decide({}, build(Config()))
        assert waits == [5, 10, 12, 12, 12]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_optional_503_retry_preserves_request_and_retry_after(
    make_client, monkeypatch
):
    import asyncio

    calls, waits, events = [], [], []

    def handle(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "7"}, json={})
        return httpx.Response(200, json=gateway_response("score"))

    async def sleep(delay):
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    client = make_client(handle, Config(api_503_retries=3))
    client.on_event = events.append
    try:
        await client.decide({"timestamp_us": 123}, build(Config()))
        assert len(calls) == 2 and calls[0] == calls[1]
        assert waits == [7]
        assert events[0]["error_details"]["status_code"] == 503
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_503_retry_limit_survives_interleaved_429(make_client, monkeypatch):
    import asyncio

    calls = []

    def handle(request):
        calls.append(1)
        return httpx.Response(429 if len(calls) % 2 == 0 else 503, json={})

    async def sleep(delay):
        pass

    monkeypatch.setattr(asyncio, "sleep", sleep)
    client = make_client(handle, Config(api_503_retries=2, retry_429=True))
    try:
        with pytest.raises(JevAPIError, match="503"):
            await client.decide({}, build(Config()))
        assert len(calls) == 5
    finally:
        await client.close()


@pytest.mark.parametrize("value", [-1, 11, True, 1.5])
def test_invalid_503_retry_limit(value):
    with pytest.raises(ValueError):
        Config(api_503_retries=value)

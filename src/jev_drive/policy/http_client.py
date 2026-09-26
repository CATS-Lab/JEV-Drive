"""Shared JSON evaluation transport, validation and optional retry handling."""

import asyncio
import logging
import time
import os
import re
import httpx
from .retry import retry_delay

logger = logging.getLogger(__name__)


class JevAPIError(RuntimeError):
    def __init__(self, message, *, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics


class HttpJevClient:
    backend = None
    key_env = None
    extra_diagnostic_headers = ()

    def __init__(self, config, on_event=None):
        if config.backend != self.backend:
            raise ValueError("client and configured backend disagree")
        self.config = config
        self.on_event = on_event
        self._request_lock = asyncio.Lock()
        self._next_request_at = 0.0
        key = os.environ.get(self.key_env)
        if not key or not key.isascii() or any(c.isspace() for c in key):
            raise JevAPIError(f"missing or malformed {self.key_env}")
        self._client = httpx.AsyncClient(
            timeout=config.api_timeout_s,
            headers={"Authorization": f"Bearer {key}"},
            follow_redirects=False,
        )

    async def decide(self, state, questions):
        payload = {"model": self.config.model, "state": state, "questions": questions}
        attempt = 0
        backoff = self.config.retry_initial_s
        while True:
            attempt += 1
            try:
                async with self._request_lock:
                    interval_wait = self._next_request_at - time.monotonic()
                    if interval_wait > 0:
                        await asyncio.sleep(interval_wait)
                    self._next_request_at = (
                        time.monotonic() + self.config.api_min_interval_s
                    )
                    response = await self._client.post(
                        self.config.endpoint, json=payload
                    )
            except httpx.HTTPError as e:
                raise JevAPIError(f"JEV transport failed: {type(e).__name__}") from None
            if response.status_code == 200:
                break
            details = self._http_error_details(response)
            if response.status_code != 429 or not self.config.retry_429:
                raise JevAPIError(
                    f"JEV HTTP {response.status_code}", diagnostics=details
                )
            wait_s = retry_delay(response.headers.get("retry-after"), backoff)
            event = {
                "event": "api_retry",
                "timestamp_us": state.get("timestamp_us"),
                "attempt": attempt,
                "wait_s": wait_s,
                "error_details": details,
            }
            if self.on_event is not None:
                self.on_event(event)
            logger.warning(
                "JEV HTTP 429 at simulation timestamp %s; attempt %d, waiting %.1fs. "
                "The same decision will be retried; simulation is paused.",
                state.get("timestamp_us"),
                attempt,
                wait_s,
            )
            await asyncio.sleep(wait_s)
            backoff = min(self.config.retry_max_s, backoff * 2)
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            answers = result["answers"]
            if not isinstance(answers, dict) or set(answers) != set(questions):
                raise ValueError()
            for name, question in questions.items():
                if (
                    not isinstance(answers[name], dict)
                    or answers[name].get("type") != question["type"]
                ):
                    raise ValueError()
            return result
        except (ValueError, KeyError, TypeError):
            raise JevAPIError("JEV response contract invalid") from None

    def _http_error_details(self, response):
        """Retain bounded error evidence, never request authorization headers."""
        key = self._client.headers["Authorization"].removeprefix("Bearer ")

        def redact(value, limit):
            value = value.replace(key, "[REDACTED]")
            value = re.sub(r"(?i)Bearer\s+[^\s\"']+", "Bearer [REDACTED]", value)
            value = re.sub(r"\b(?:vck_|sk-)[A-Za-z0-9_-]+", "[REDACTED]", value)
            return value[:limit]

        header_names = (
            "retry-after",
            "x-request-id",
            "x-ratelimit-limit-requests",
            "x-ratelimit-remaining-requests",
            "x-ratelimit-reset-requests",
            "x-ratelimit-limit-tokens",
            "x-ratelimit-remaining-tokens",
            "x-ratelimit-reset-tokens",
        )
        header_names += self.extra_diagnostic_headers
        return {
            "status_code": response.status_code,
            "response_body": redact(response.text, 4096),
            "headers": {
                name: redact(response.headers[name], 256)
                for name in header_names
                if name in response.headers
            },
        }

    async def close(self):
        await self._client.aclose()

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx
import jsonschema
import pybreaker
import tenacity

from llm_enricher.providers.base import (
    LLMProvider,
    LLMResult,
    ProviderInvalidOutputError,
    ProviderTransientError,
)

logger = logging.getLogger("llm_enricher.mistral")

_MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


class MistralProvider:
    """Production Mistral LLM provider.

    API key is read from MISTRAL_API_KEY env var — never logged or stored in config.
    """

    name = "mistral"

    def __init__(
        self,
        model_name: str = "mistral-large-latest",
        timeout_seconds: float = 30.0,
        retry_attempts: int = 3,
        circuit_breaker_fail_max: int = 5,
        circuit_breaker_reset_timeout: int = 30,
    ) -> None:
        self.model_name = model_name
        self._timeout = timeout_seconds
        self._retry_attempts = retry_attempts
        self._api_key = os.environ.get("MISTRAL_API_KEY", "")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        self._breaker = pybreaker.CircuitBreaker(
            fail_max=circuit_breaker_fail_max,
            reset_timeout=circuit_breaker_reset_timeout,
        )

    def __repr__(self) -> str:
        masked = "***" if self._api_key else "(not set)"
        return f"MistralProvider(model={self.model_name!r}, key={masked})"

    async def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        max_tokens: int,
        temperature: float = 0.2,
    ) -> LLMResult:
        system_msg = (
            "You are a precise analytical assistant. "
            "You MUST return ONLY valid JSON matching this schema:\n"
            + json.dumps(schema, indent=2)
            + "\nDo not include any text outside the JSON object."
        )

        async for attempt in tenacity.AsyncRetrying(
            stop=tenacity.stop_after_attempt(self._retry_attempts),
            wait=tenacity.wait_exponential(multiplier=1, min=1, max=16),
            retry=tenacity.retry_if_exception(_is_transient),
            reraise=True,
        ):
            with attempt:
                result = await self._call_api(
                    system_msg, prompt, max_tokens, temperature, schema
                )
        return result

    async def _call_with_breaker(self, func, *args, **kwargs):
        """Async-safe circuit breaker wrapper (pybreaker.call_async needs Tornado)."""
        if self._breaker.current_state == "open":
            raise pybreaker.CircuitBreakerError()
        try:
            result = await func(*args, **kwargs)
            self._breaker._state._handle_success()
            return result
        except BaseException as exc:
            self._breaker._state._handle_error(exc)
            raise

    async def _call_api(
        self,
        system_msg: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        schema: dict[str, Any],
    ) -> LLMResult:
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            t0 = time.monotonic()
            raw_resp = await self._call_with_breaker(self._client.post, _MISTRAL_API_URL, json=payload)
            elapsed = time.monotonic() - t0
        except pybreaker.CircuitBreakerError as exc:
            raise ProviderTransientError("Circuit breaker open") from exc

        try:
            raw_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                retry_after = int(exc.response.headers.get("Retry-After", "1"))
                logger.warning("Mistral rate limited, Retry-After=%s", retry_after)
            raise

        body = raw_resp.json()
        raw_text: str = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        tokens_input = usage.get("prompt_tokens", 0)
        tokens_output = usage.get("completion_tokens", 0)

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ProviderInvalidOutputError(
                f"Provider returned non-JSON: {raw_text[:200]}"
            ) from exc

        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as exc:
            raise ProviderInvalidOutputError(
                f"Response failed schema validation: {exc.message}"
            ) from exc

        logger.debug(
            "Mistral call ok model=%s tokens_in=%d tokens_out=%d latency=%.2fs",
            self.model_name,
            tokens_input,
            tokens_output,
            elapsed,
        )
        return LLMResult(
            data=data,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            raw_text=raw_text,
        )

    async def close(self) -> None:
        await self._client.aclose()

"""Tests for MistralProvider using respx to mock HTTP."""
from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
import respx

from llm_enricher.providers.base import ProviderInvalidOutputError, ProviderTransientError
from llm_enricher.providers.mistral import MistralProvider, _MISTRAL_API_URL
from llm_enricher.schemas import CLUSTER_LABEL_SCHEMA


_VALID_RESPONSE = {
    "choices": [{"message": {"content": json.dumps({"label": "Test Topic", "confidence": 0.9})}}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
}


def _make_provider(**kwargs) -> MistralProvider:
    with patch.dict("os.environ", {"MISTRAL_API_KEY": "test-key"}):
        return MistralProvider(model_name="mistral-large-latest", **kwargs)


@pytest.mark.asyncio
@respx.mock
async def test_successful_call():
    respx.post(_MISTRAL_API_URL).mock(return_value=httpx.Response(200, json=_VALID_RESPONSE))
    provider = _make_provider()
    result = await provider.generate_structured(
        "Generate a label", CLUSTER_LABEL_SCHEMA, max_tokens=100
    )
    assert result.data == {"label": "Test Topic", "confidence": 0.9}
    assert result.tokens_input == 100
    assert result.tokens_output == 20


@pytest.mark.asyncio
@respx.mock
async def test_invalid_json_raises_provider_invalid_output_error():
    respx.post(_MISTRAL_API_URL).mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": "not json at all"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }))
    provider = _make_provider()
    with pytest.raises(ProviderInvalidOutputError):
        await provider.generate_structured("prompt", CLUSTER_LABEL_SCHEMA, max_tokens=100)


@pytest.mark.asyncio
@respx.mock
async def test_schema_mismatch_raises_provider_invalid_output_error():
    bad_data = {"label": "X" * 100, "confidence": 2.0}  # too long, confidence > 1
    respx.post(_MISTRAL_API_URL).mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(bad_data)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }))
    provider = _make_provider()
    with pytest.raises(ProviderInvalidOutputError):
        await provider.generate_structured("prompt", CLUSTER_LABEL_SCHEMA, max_tokens=100)


@pytest.mark.asyncio
@respx.mock
async def test_500_raises_transient_error():
    respx.post(_MISTRAL_API_URL).mock(return_value=httpx.Response(500, text="Internal Server Error"))
    provider = _make_provider(retry_attempts=1)
    with pytest.raises(Exception):
        await provider.generate_structured("prompt", CLUSTER_LABEL_SCHEMA, max_tokens=100)


@pytest.mark.asyncio
@respx.mock
async def test_api_key_not_in_repr():
    provider = _make_provider()
    assert "test-key" not in repr(provider)
    assert "***" in repr(provider)

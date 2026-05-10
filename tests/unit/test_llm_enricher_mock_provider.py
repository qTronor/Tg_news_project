"""Tests for MockProvider: determinism and schema conformance."""
from __future__ import annotations

import pytest
import jsonschema

from llm_enricher.providers.mock import MockProvider
from llm_enricher.schemas import OUTPUT_SCHEMAS, SUPPORTED_ENRICHMENT_TYPES


@pytest.fixture
def provider():
    return MockProvider()


def _make_prompt(enrichment_type: str, language: str) -> str:
    return f"# enrichment_type={enrichment_type} language={language}\nsome content"


@pytest.mark.asyncio
@pytest.mark.parametrize("etype", list(SUPPORTED_ENRICHMENT_TYPES))
@pytest.mark.parametrize("lang", ["ru", "en", "other"])
async def test_deterministic(provider, etype, lang):
    prompt = _make_prompt(etype, lang)
    schema = OUTPUT_SCHEMAS[etype]
    r1 = await provider.generate_structured(prompt, schema, max_tokens=200)
    r2 = await provider.generate_structured(prompt, schema, max_tokens=200)
    assert r1.data == r2.data


@pytest.mark.asyncio
@pytest.mark.parametrize("etype", list(SUPPORTED_ENRICHMENT_TYPES))
async def test_schema_conformance_en(provider, etype):
    prompt = _make_prompt(etype, "en")
    schema = OUTPUT_SCHEMAS[etype]
    result = await provider.generate_structured(prompt, schema, max_tokens=200)
    jsonschema.validate(result.data, schema)


@pytest.mark.asyncio
@pytest.mark.parametrize("etype", list(SUPPORTED_ENRICHMENT_TYPES))
async def test_schema_conformance_ru(provider, etype):
    prompt = _make_prompt(etype, "ru")
    schema = OUTPUT_SCHEMAS[etype]
    result = await provider.generate_structured(prompt, schema, max_tokens=200)
    jsonschema.validate(result.data, schema)


@pytest.mark.asyncio
async def test_token_counts_are_positive(provider):
    prompt = _make_prompt("cluster_label", "en")
    schema = OUTPUT_SCHEMAS["cluster_label"]
    result = await provider.generate_structured(prompt, schema, max_tokens=100)
    assert result.tokens_input > 0
    assert result.tokens_output > 0


@pytest.mark.asyncio
async def test_fallback_for_unknown_lang(provider):
    prompt = _make_prompt("cluster_label", "zh")
    schema = OUTPUT_SCHEMAS["cluster_label"]
    result = await provider.generate_structured(prompt, schema, max_tokens=100)
    assert "label" in result.data
    assert "confidence" in result.data

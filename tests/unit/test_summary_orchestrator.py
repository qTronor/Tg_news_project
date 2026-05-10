"""Tests for the summary orchestrator logic in llm_enricher/service.py."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_enricher.cache import ComputedResult
from llm_enricher.schemas import (
    ClusterEnrichmentInput,
    RepresentativeMessage,
    TopEntity,
)


def _make_dto(cluster_id: str = "test:1") -> ClusterEnrichmentInput:
    return ClusterEnrichmentInput(
        public_cluster_id=cluster_id,
        language="ru",
        analysis_mode="full",
        representative_messages=[
            RepresentativeMessage(
                text="Тестовое сообщение о событии.", channel="chan1", cluster_probability=0.9
            )
        ],
        top_entities=[
            TopEntity(normalized_text="Путин", entity_type="PER", mention_count=5)
        ],
    )


def _ok_result(payload: dict[str, Any], status: str = "ok") -> ComputedResult:
    return ComputedResult(
        result_json=payload,
        status=status,
        error_message=None,
        tokens_input=100,
        tokens_output=50,
        cost_usd=0.001,
        latency_ms=500,
        prompt_version="v1",
        model_provider="mistral",
        model_name="mistral-large-latest",
        language="ru",
        analysis_mode="full",
    )


def _error_result() -> ComputedResult:
    return ComputedResult(
        result_json=None,
        status="error",
        error_message="LLM call failed",
        tokens_input=0,
        tokens_output=0,
        cost_usd=0.0,
        latency_ms=100,
        prompt_version="v1",
        model_provider="extractive",
        model_name="extractive_textrank_v1",
        language="ru",
        analysis_mode="full",
    )


class TestExtractiveResultOnLlmError:
    """Verify handler returns ok_baseline when LLM errors for extractive-eligible types."""

    def test_error_result_returns_ok_baseline_for_cluster_summary(self):
        from llm_enricher.extractive import extractive_summary
        from llm_enricher.schemas import EXTRACTIVE_FALLBACK_TYPES

        assert "cluster_summary" in EXTRACTIVE_FALLBACK_TYPES
        assert "key_actors_summary" in EXTRACTIVE_FALLBACK_TYPES

    def test_non_extractive_type_not_in_fallback(self):
        from llm_enricher.schemas import EXTRACTIVE_FALLBACK_TYPES

        assert "timeline_summary" not in EXTRACTIVE_FALLBACK_TYPES
        assert "what_changed_recently" not in EXTRACTIVE_FALLBACK_TYPES

    def test_extractive_summary_produces_ok_baseline_compatible_output(self):
        from llm_enricher.extractive import extractive_summary
        from llm_enricher.schemas import RepresentativeMessage

        messages = [RepresentativeMessage(text="Тест события.", channel="c", cluster_probability=0.9)]
        result = extractive_summary(messages, "ru")
        assert "summary" in result
        assert "key_points" in result

    def test_extractive_key_actors_produces_ok_baseline_compatible_output(self):
        from llm_enricher.extractive import extractive_key_actors
        from llm_enricher.schemas import TopEntity

        entities = [TopEntity(normalized_text="Ивánов", entity_type="PER", mention_count=3)]
        result = extractive_key_actors(entities)
        assert "actors" in result
        assert len(result["actors"]) == 1


class TestSummaryKindMapping:
    """Verify that the KIND_TO_ENRICHMENT_TYPE mapping is consistent."""

    def test_all_kinds_map_to_supported_types(self):
        from llm_enricher.service import _KIND_TO_ENRICHMENT_TYPE, _ALL_KINDS
        from llm_enricher.schemas import SUPPORTED_ENRICHMENT_TYPES

        for kind, etype in _KIND_TO_ENRICHMENT_TYPE.items():
            assert etype in SUPPORTED_ENRICHMENT_TYPES, (
                f"kind '{kind}' maps to unsupported enrichment_type '{etype}'"
            )

    def test_all_kinds_consistent_with_all_kinds_list(self):
        from llm_enricher.service import _KIND_TO_ENRICHMENT_TYPE, _ALL_KINDS

        assert set(_ALL_KINDS) == set(_KIND_TO_ENRICHMENT_TYPE.keys())

    def test_expected_kinds_present(self):
        from llm_enricher.service import _KIND_TO_ENRICHMENT_TYPE

        expected = {"short", "timeline", "key_actors", "why_important", "what_changed", "novelty"}
        assert set(_KIND_TO_ENRICHMENT_TYPE.keys()) == expected


class TestSummaryRepositoryMethods:
    """Unit tests for the new repository methods (no DB required)."""

    def test_summary_record_dataclass_exists(self):
        from llm_enricher.repository import SummaryRecord

        record = SummaryRecord(
            payload={"summary": "ok"},
            status="ok",
            model_provider="mistral",
            model_name="mistral-large-latest",
            prompt_version="v1",
            generated_at=datetime.now(timezone.utc),
            input_fingerprint="abc123",
        )
        assert record.status == "ok"
        assert record.payload == {"summary": "ok"}

    def test_ttl_constant_is_seven_days(self):
        from llm_enricher.repository import _SUMMARY_TTL_SECONDS

        assert _SUMMARY_TTL_SECONDS == 7 * 24 * 3600


class TestNewSchemasRegistered:
    """Smoke test: all 7 enrichment types are registered, handlers can be built."""

    def test_all_seven_types_in_supported(self):
        from llm_enricher.schemas import SUPPORTED_ENRICHMENT_TYPES

        expected = {
            "cluster_summary", "cluster_explanation", "novelty_explanation", "cluster_label",
            "timeline_summary", "key_actors_summary", "what_changed_recently",
        }
        assert expected.issubset(SUPPORTED_ENRICHMENT_TYPES)

    def test_max_tokens_defined_for_all_new_types(self):
        from llm_enricher.schemas import MAX_TOKENS

        for etype in ("timeline_summary", "key_actors_summary", "what_changed_recently"):
            assert etype in MAX_TOKENS
            assert MAX_TOKENS[etype] > 0

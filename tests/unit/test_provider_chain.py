"""Unit tests for ner_extractor.providers.chain — ProviderChain span merging."""
from __future__ import annotations

from typing import List
from unittest.mock import MagicMock

import pytest

from ner_extractor.backends.base import Entity
from ner_extractor.providers.base import NerProvider, RunMetrics
from ner_extractor.providers.chain import ProviderChain, _merge_spans


def make_entity(text: str, start: int, end: int, entity_type: str = "PERSON", confidence: float = 1.0) -> Entity:
    return Entity(text=text, entity_type=entity_type, start=start, end=end, confidence=confidence, normalized=text)


def make_provider(name: str, language: str, entities: List[Entity]) -> NerProvider:
    """Build a minimal mock NerProvider."""
    p = MagicMock(spec=NerProvider)
    p.name = name
    p.version = "1.0.0"
    p.language = language
    p.provider_kind = "model"
    p.extract.return_value = entities
    p.extract_with_metadata.return_value = (
        entities,
        RunMetrics(
            provider_name=name,
            provider_version="1.0.0",
            language=language,
            entity_count=len(entities),
            latency_ms=1.0,
            success=True,
        ),
    )
    return p


class TestMergeSpans:
    def test_no_overlap(self):
        a = make_entity("Путин", 0, 5)
        b = make_entity("Москва", 10, 16)
        result = _merge_spans([a, b])
        assert len(result) == 2

    def test_identical_span_dedup(self):
        """Same span from two providers — keep higher confidence."""
        high = make_entity("Путин", 0, 5, confidence=1.0)
        low = make_entity("Путин", 0, 5, confidence=0.7)
        result = _merge_spans([low, high])
        assert len(result) == 1
        assert result[0].confidence == 1.0

    def test_longer_span_wins(self):
        """Overlapping spans — longest wins."""
        short = make_entity("Путин", 0, 5)
        long_ = make_entity("Владимир Путин", 0, 14)
        result = _merge_spans([short, long_])
        assert len(result) == 1
        assert result[0].text == "Владимир Путин"

    def test_non_overlapping_preserved(self):
        a = make_entity("Путин", 0, 5)
        b = make_entity("Навальный", 20, 29)
        c = make_entity("Москва", 40, 46)
        result = _merge_spans([a, b, c])
        assert len(result) == 3

    def test_sorted_by_start(self):
        b = make_entity("Б", 10, 11)
        a = make_entity("А", 0, 1)
        result = _merge_spans([b, a])
        assert result[0].text == "А"
        assert result[1].text == "Б"


class TestProviderChain:
    def test_runs_only_matching_language_providers(self):
        ru = make_provider("natasha", "ru", [make_entity("Путин", 0, 5)])
        en = make_provider("bert", "en", [make_entity("Trump", 10, 15)])
        chain = ProviderChain([ru, en])

        entities, metrics = chain.extract_with_metrics("Some text", "ru")
        assert len(entities) == 1
        assert entities[0].text == "Путин"
        assert len(metrics) == 1
        assert metrics[0].provider_name == "natasha"

    def test_chain_merges_from_both_providers(self):
        ru = make_provider("natasha", "ru", [make_entity("Путин", 0, 5)])
        rule = make_provider("rule_alias", "ru", [make_entity("Кремль", 10, 16, "LOC")])
        chain = ProviderChain([ru, rule])

        entities, metrics = chain.extract_with_metrics("Путин Кремль", "ru")
        assert len(entities) == 2
        assert len(metrics) == 2

    def test_rule_provider_adds_missed_alias(self):
        """RuleBasedAliasProvider finds an alias the model missed."""
        model = make_provider("natasha", "ru", [])  # model found nothing
        rule_alias = make_provider("rule_alias", "ru", [make_entity("НАТО", 0, 4, "ORG")])
        chain = ProviderChain([model, rule_alias])

        entities, _ = chain.extract_with_metrics("НАТО и мир", "ru")
        assert len(entities) == 1
        assert entities[0].text == "НАТО"

    def test_empty_text_returns_empty(self):
        ru = make_provider("natasha", "ru", [])
        chain = ProviderChain([ru])
        entities, metrics = chain.extract_with_metrics("", "ru")
        assert entities == []

    def test_provider_exception_is_handled(self):
        p = MagicMock(spec=NerProvider)
        p.name = "broken"
        p.language = "ru"
        p.extract_with_metadata.side_effect = RuntimeError("model crash")
        chain = ProviderChain([p])
        # Should not raise
        entities, metrics = chain.extract_with_metrics("some text", "ru")
        assert entities == []
        assert metrics == []

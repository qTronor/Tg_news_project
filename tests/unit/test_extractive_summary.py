"""Tests for extractive baseline summarizer."""
from __future__ import annotations

import pytest

from llm_enricher.extractive import extractive_key_actors, extractive_summary
from llm_enricher.schemas import RepresentativeMessage, TopEntity


def _make_messages(texts: list[str]) -> list[RepresentativeMessage]:
    return [
        RepresentativeMessage(text=t, channel="test_channel", cluster_probability=0.9)
        for t in texts
    ]


def _make_entities(names: list[str]) -> list[TopEntity]:
    return [
        TopEntity(normalized_text=n, entity_type="PER", mention_count=i + 1)
        for i, n in enumerate(names)
    ]


class TestExtractiveSummary:
    def test_non_empty_input_returns_nonempty_summary(self):
        messages = _make_messages([
            "Президент провёл встречу с главами регионов.",
            "Обсуждались вопросы экономики и безопасности.",
            "По итогам встречи подписан ряд соглашений.",
        ])
        result = extractive_summary(messages, language="ru")
        assert isinstance(result, dict)
        assert "summary" in result
        assert "key_points" in result
        assert len(result["summary"]) > 0

    def test_empty_input_returns_empty_summary(self):
        result = extractive_summary([], language="ru")
        assert result == {"summary": "", "key_points": []}

    def test_single_empty_text_returns_empty(self):
        messages = _make_messages([""])
        result = extractive_summary(messages, language="ru")
        assert result["summary"] == ""
        assert result["key_points"] == []

    def test_key_points_capped_at_five(self):
        messages = _make_messages(
            [f"Это предложение номер {i} о событии в мире." for i in range(20)]
        )
        result = extractive_summary(messages, language="ru", max_sentences=3)
        assert len(result["key_points"]) <= 5

    def test_english_language_supported(self):
        messages = _make_messages([
            "The president held talks with regional governors.",
            "Key topics included the economy and public safety.",
            "Several agreements were signed after the meeting.",
        ])
        result = extractive_summary(messages, language="en")
        assert isinstance(result["summary"], str)

    def test_returns_schema_compatible_structure(self):
        messages = _make_messages(["Краткое сообщение о событии."])
        result = extractive_summary(messages, language="ru")
        assert set(result.keys()) == {"summary", "key_points"}
        assert isinstance(result["key_points"], list)


class TestExtractiveKeyActors:
    def test_returns_actors_from_entities(self):
        entities = _make_entities(["Путин", "Байден", "ООН"])
        result = extractive_key_actors(entities)
        assert "actors" in result
        assert len(result["actors"]) == 3

    def test_empty_entities_returns_empty_actors(self):
        result = extractive_key_actors([])
        assert result == {"actors": []}

    def test_capped_at_five_actors(self):
        entities = _make_entities([f"Actor{i}" for i in range(10)])
        result = extractive_key_actors(entities)
        assert len(result["actors"]) <= 5

    def test_actor_has_required_fields(self):
        entities = _make_entities(["Иванов"])
        actor = extractive_key_actors(entities)["actors"][0]
        assert "name" in actor
        assert "role" in actor
        assert "why_matters" in actor
        assert "mention_count" in actor

    def test_mention_count_preserved(self):
        entities = [TopEntity(normalized_text="Смит", entity_type="PER", mention_count=42)]
        actor = extractive_key_actors(entities)["actors"][0]
        assert actor["mention_count"] == 42

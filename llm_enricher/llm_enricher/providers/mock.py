from __future__ import annotations

import json
import re
from typing import Any

from llm_enricher.providers.base import LLMProvider, LLMResult


_FIXTURES: dict[tuple[str, str], dict[str, Any]] = {
    ("cluster_summary", "ru"): {
        "summary": "Тестовый кластер о политических событиях в России. Включает сообщения из нескольких каналов.",
        "key_points": ["Ключевая тема: политика", "Высокая активность в последние 24 часа"],
    },
    ("cluster_summary", "en"): {
        "summary": "Test cluster about political events. Messages from multiple channels over 24h.",
        "key_points": ["Key topic: politics", "High activity in last 24 hours"],
    },
    ("cluster_summary", "other"): {
        "summary": "(Partial coverage) Test cluster with mixed language content.",
        "key_points": ["Key topic detected", "Partial language support applied"],
    },
    ("cluster_explanation", "ru"): {
        "why_important": "Кластер важен из-за высокого числа уникальных каналов и новых сущностей.",
        "drivers": [
            {"name": "unique_channels", "weight": 0.4, "explanation": "Множество источников"},
            {"name": "novel_entities", "weight": 0.3, "explanation": "Новые упомянутые лица"},
        ],
    },
    ("cluster_explanation", "en"): {
        "why_important": "Cluster is important due to high unique channel count and novel entities.",
        "drivers": [
            {"name": "unique_channels", "weight": 0.4, "explanation": "Multiple sources"},
            {"name": "novel_entities", "weight": 0.3, "explanation": "New mentioned entities"},
        ],
    },
    ("cluster_explanation", "other"): {
        "why_important": "(Partial coverage) High activity detected across channels.",
        "drivers": [
            {"name": "unique_channels", "weight": 0.4, "explanation": "Multiple sources detected"},
        ],
    },
    ("novelty_explanation", "ru"): {
        "novelty_verdict": "new",
        "rationale": "Тема появилась менее 6 часов назад и ещё не наблюдалась в предыдущих окнах.",
    },
    ("novelty_explanation", "en"): {
        "novelty_verdict": "new",
        "rationale": "Topic emerged less than 6 hours ago and was not seen in previous windows.",
    },
    ("novelty_explanation", "other"): {
        "novelty_verdict": "ongoing",
        "rationale": "(Partial coverage) Topic appears to be ongoing based on activity patterns.",
    },
    ("cluster_label", "ru"): {"label": "Политика и выборы", "confidence": 0.87},
    ("cluster_label", "en"): {"label": "Politics and Elections", "confidence": 0.87},
    ("cluster_label", "other"): {"label": "Mixed Language Topic", "confidence": 0.60},
}


def _extract_marker(prompt: str) -> tuple[str, str]:
    """Extract enrichment_type and language from the marker comment in prompt."""
    m = re.search(r"# enrichment_type=(\S+) language=(\S+)", prompt)
    if m:
        return m.group(1), m.group(2)
    return "cluster_summary", "en"


class MockProvider:
    """Deterministic mock LLM provider for dev/test. Returns fixture data."""

    name = "mock"
    model_name = "mock-v1"

    async def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        max_tokens: int,
        temperature: float = 0.2,
    ) -> LLMResult:
        enrichment_type, language = _extract_marker(prompt)
        key = (enrichment_type, language)
        data = _FIXTURES.get(key) or _FIXTURES.get((enrichment_type, "en"), {})
        raw = json.dumps(data)
        return LLMResult(
            data=data,
            tokens_input=len(prompt) // 4,
            tokens_output=len(raw) // 4,
            raw_text=raw,
        )

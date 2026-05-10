"""ProviderChain: orchestrates NER providers with longest-span-wins merge."""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from ner_extractor.backends.base import Entity
from ner_extractor.providers.base import NerProvider, RunMetrics

logger = logging.getLogger("ner_extractor.providers.chain")


class ProviderChain:
    """Run each provider in order and merge spans via longest-span-wins.

    Tie-break (same start, same end): highest confidence wins.
    """

    def __init__(self, providers: List[NerProvider]) -> None:
        self._providers = providers

    def extract(self, text: str, language: str) -> List[Entity]:
        """Extract entities from text using all providers; return deduplicated list."""
        entities, _ = self.extract_with_metrics(text, language)
        return entities

    def extract_with_metrics(
        self, text: str, language: str
    ) -> Tuple[List[Entity], List[RunMetrics]]:
        """Extract entities and collect per-provider run metrics."""
        all_entities: List[Entity] = []
        all_metrics: List[RunMetrics] = []

        for provider in self._providers:
            # only run providers that match the text language (or have no language)
            if getattr(provider, "language", "") and provider.language != language:
                continue
            try:
                entities, metrics = provider.extract_with_metadata(text, language)
                all_entities.extend(entities)
                all_metrics.append(metrics)
            except Exception:  # noqa: BLE001
                logger.exception("Provider %s raised during extraction", provider.name)

        merged = _merge_spans(all_entities)
        return merged, all_metrics


def _merge_spans(entities: List[Entity]) -> List[Entity]:
    """Longest-span-wins deduplication; confidence tiebreak on equal spans."""
    if not entities:
        return []

    # sort by start asc, then by span length desc, then by confidence desc
    sorted_ents = sorted(
        entities,
        key=lambda e: (e.start, -(e.end - e.start), -e.confidence),
    )

    result: List[Entity] = []
    # track covered character intervals
    covered: List[Tuple[int, int]] = []

    for ent in sorted_ents:
        if _overlaps(ent.start, ent.end, covered):
            continue
        result.append(ent)
        covered.append((ent.start, ent.end))

    return sorted(result, key=lambda e: e.start)


def _overlaps(start: int, end: int, covered: List[Tuple[int, int]]) -> bool:
    for cs, ce in covered:
        if start < ce and end > cs:
            return True
    return False

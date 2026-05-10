"""Extended provider protocol — wraps NerBackend with metadata emission."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ner_extractor.backends.base import Entity, NerBackend


@dataclass
class RunMetrics:
    provider_name: str
    provider_version: str
    language: str
    entity_count: int
    latency_ms: float
    success: bool
    error: Optional[str] = None


class NerProvider(NerBackend):
    """Extended NER backend that can also emit per-run metrics."""

    provider_kind: str  # "model" | "rule" | "llm"

    def extract_with_metadata(
        self, text: str, language: str
    ) -> Tuple[List[Entity], RunMetrics]:
        """Default: call extract() and build basic metrics."""
        import time

        t0 = time.monotonic()
        try:
            entities = self.extract(text)
            latency_ms = (time.monotonic() - t0) * 1000
            return entities, RunMetrics(
                provider_name=self.name,
                provider_version=self.version,
                language=language,
                entity_count=len(entities),
                latency_ms=round(latency_ms, 2),
                success=True,
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.monotonic() - t0) * 1000
            return [], RunMetrics(
                provider_name=self.name,
                provider_version=self.version,
                language=language,
                entity_count=0,
                latency_ms=round(latency_ms, 2),
                success=False,
                error=str(exc),
            )

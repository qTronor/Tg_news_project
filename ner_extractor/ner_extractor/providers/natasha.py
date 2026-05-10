"""Thin NerProvider adapter over NatashaRuBackend."""
from __future__ import annotations

from typing import List

from ner_extractor.backends.base import Entity
from ner_extractor.backends.natasha_ru import NatashaRuBackend
from ner_extractor.providers.base import NerProvider, RunMetrics


class NatashaProvider(NerProvider):
    provider_kind = "model"

    def __init__(self, **backend_kwargs) -> None:
        self._backend = NatashaRuBackend(**backend_kwargs)

    @property
    def name(self) -> str:
        return self._backend.name

    @property
    def version(self) -> str:
        return self._backend.version

    @property
    def language(self) -> str:
        return self._backend.language

    def extract(self, text: str) -> List[Entity]:
        return self._backend.extract(text)

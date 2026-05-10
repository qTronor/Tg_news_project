"""LLM NER provider stub — enabled only when ENABLE_LLM_NER=true.

Full integration with llm_enricher is a follow-up task.
"""
from __future__ import annotations

import logging
from typing import List

from ner_extractor.backends.base import Entity
from ner_extractor.providers.base import NerProvider

logger = logging.getLogger("ner_extractor.providers.llm")


class LLMNERProvider(NerProvider):
    name = "llm_ner"
    version = "0.0.0"
    provider_kind = "llm"

    def __init__(self, language: str = "") -> None:
        self.language = language
        logger.info("LLMNERProvider loaded (stub — returns empty list)")

    def extract(self, text: str) -> List[Entity]:
        return []

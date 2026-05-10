"""HuggingFace transformers NER backend for English text.

Uses ``dslim/bert-base-NER`` via the HF ``pipeline`` API with
``aggregation_strategy='simple'`` to get clean entity spans without B/I/O
prefix noise. Lazy-loaded on first call; thread-safe via double-checked
locking.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import List, Optional

from ner_extractor.backends.base import Entity


logger = logging.getLogger("ner_extractor.backends.transformers_en")

# dslim/bert-base-NER uses 4-class labels that map cleanly onto the canonical set.
_DSLIM_TYPE_MAP = {
    "PER": "PERSON",
    "ORG": "ORG",
    "LOC": "LOC",
    "MISC": "MISC",
}


class TransformersEnBackend:
    """dslim/bert-base-NER English NER via HF transformers pipeline.

    Entity normalisation for EN is intentionally minimal: truecase (preserve
    original capitalisation) + strip leading/trailing whitespace. Lemmatisation
    is not applied on v1 because English NER spans are already in their
    surface form (proper nouns don't inflect in English).
    """

    language = "en"

    def __init__(
        self,
        *,
        name: str = "dslim/bert-base-NER",
        version: str = "1.0.0",
        device: str = "auto",
        batch_size: int = 8,
        min_entity_length: int = 2,
        confidence_threshold: float = 0.80,
        cache_dir: Optional[str] = None,
    ) -> None:
        self.name = name
        self.version = version
        self._device_str = device
        self._batch_size = batch_size
        self._min_entity_length = min_entity_length
        self._confidence_threshold = confidence_threshold
        self._cache_dir = cache_dir
        self._pipeline = None
        self._lock = threading.Lock()

    def _resolve_device_id(self) -> int:
        """Return torch device id for HF pipeline (0 = first GPU, -1 = CPU)."""
        normalized = (self._device_str or "auto").strip().lower()
        if normalized == "auto":
            try:
                import torch
                return 0 if torch.cuda.is_available() else -1
            except ImportError:
                return -1
        if normalized.startswith("cuda"):
            return 0
        return -1

    def _ensure_loaded(self):
        if self._pipeline is not None:
            return
        with self._lock:
            if self._pipeline is not None:
                return
            from transformers import pipeline

            kwargs = {"aggregation_strategy": "simple"}
            if self._cache_dir:
                kwargs["model_kwargs"] = {"cache_dir": self._cache_dir}
            device_id = self._resolve_device_id()
            logger.info(
                "loading HF NER pipeline model=%s device_id=%d", self.name, device_id
            )
            self._pipeline = pipeline(
                "ner",
                model=self.name,
                device=device_id,
                **kwargs,
            )
            logger.info("HF NER pipeline loaded model=%s", self.name)

    def extract(self, text: str) -> List[Entity]:
        if not text or not text.strip():
            return []

        self._ensure_loaded()
        assert self._pipeline is not None

        try:
            raw_entities = self._pipeline(text)
        except Exception:  # noqa: BLE001
            logger.exception("HF NER pipeline failed for text len=%d", len(text))
            return []

        entities: List[Entity] = []
        seen = set()
        for ent in raw_entities:
            raw_type = ent.get("entity_group", "")
            canonical_type = _DSLIM_TYPE_MAP.get(raw_type.upper())
            if canonical_type is None:
                continue
            score = float(ent.get("score", 0.0))
            if score < self._confidence_threshold:
                continue
            surface = ent.get("word", "").strip()
            if len(surface) < self._min_entity_length:
                continue
            start = int(ent.get("start", 0))
            end = int(ent.get("end", start + len(surface)))

            normalized = self._normalize(surface)
            dedup_key = (normalized.lower(), start, end)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            entities.append(
                Entity(
                    text=surface,
                    entity_type=canonical_type,
                    start=start,
                    end=end,
                    confidence=round(score, 4),
                    normalized=normalized,
                )
            )
        return entities

    @staticmethod
    def _normalize(text: str) -> str:
        """Strip whitespace and fix HF tokenizer artefacts (## subword markers)."""
        cleaned = re.sub(r"\s+", " ", text).strip()
        cleaned = cleaned.replace(" ##", "").replace("##", "")
        return cleaned

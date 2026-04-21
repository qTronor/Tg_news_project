"""Emotion classification backends (RU CEDR-tiny, EN DistilRoBERTa).

Both backends conform to :class:`EmotionBackend` and emit probabilities for
the canonical emotion set. Each model's native labels are mapped onto that
common vocabulary; labels the model doesn't predict are simply absent from
the returned dict (caller writes SQL NULL). This is the "explicit partial"
approach: a RU message gets anger/fear/joy/sadness/surprise, an EN message
adds disgust, an AR message gets none. The stub-style null placeholder pattern
(every field = None regardless of capability) is removed.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

import numpy as np

from sentiment_analyzer.backends.base import (
    CANONICAL_EMOTIONS,
    EmotionScore,
    load_hf_model,
    resolve_device,
    run_classification_batch,
)


logger = logging.getLogger("sentiment_analyzer.backends.emotion")

# cointegrated/rubert-tiny2-cedr-emotion-detection predicts:
#   no_emotion, joy, sadness, surprise, fear, anger
# "no_emotion" is not canonical and is skipped — the dominant_label check
# naturally falls through to the next-highest scoring real emotion.
_RU_CEDR_MAP: Dict[str, str] = {
    "joy": "joy",
    "sadness": "sadness",
    "surprise": "surprise",
    "fear": "fear",
    "anger": "anger",
}

# j-hartmann/emotion-english-distilroberta-base predicts 7 Ekman emotions:
#   anger, disgust, fear, joy, neutral, sadness, surprise
# "neutral" dropped for the same reason as CEDR "no_emotion".
_EN_DISTILROBERTA_MAP: Dict[str, str] = {
    "anger": "anger",
    "disgust": "disgust",
    "fear": "fear",
    "joy": "joy",
    "sadness": "sadness",
    "surprise": "surprise",
}


class HFEmotionBackend:
    """HF sequence-classification emotion backend.

    Same lazy-load + batched-forward shape as the sentiment backend. Inputs
    longer than ``max_length`` are truncated rather than chunked because
    short-text emotion signals degrade under mean-pooling over chunks; if
    that ever matters for very long docs, switch to chunked-max per emotion.
    """

    def __init__(
        self,
        *,
        name: str,
        version: str,
        language: str,
        device: str,
        use_float16: bool,
        batch_size: int,
        max_length: int,
        cache_dir: Optional[str],
        label_map: Dict[str, str],
    ) -> None:
        self.name = name
        self.version = version
        self.language = language
        self._device = resolve_device(device)
        self.device = self._device.type
        self.batch_size = batch_size
        self._use_float16 = use_float16
        self._max_length = max_length
        self._cache_dir = cache_dir
        self._label_map = label_map
        self._tokenizer = None
        self._model = None
        self._id2label: Dict[int, str] = {}
        self._load_lock = threading.Lock()

    def ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            self._tokenizer, self._model, _ = load_hf_model(
                model_name=self.name,
                cache_dir=self._cache_dir,
                device=self._device,
                use_float16=self._use_float16,
                local_path=None,
            )
            self._id2label = {
                int(k): str(v).lower() for k, v in self._model.config.id2label.items()
            }

    def score_batch(self, texts: List[str]) -> List[EmotionScore]:
        self.ensure_loaded()
        if not texts:
            return []
        bs = max(1, self.batch_size)
        results: List[EmotionScore] = []
        for start in range(0, len(texts), bs):
            batch = texts[start : start + bs]
            safe_batch = [t if t and t.strip() else " " for t in batch]
            probs = run_classification_batch(
                self._tokenizer, self._model, safe_batch, self._device, self._max_length
            )
            for i, text in enumerate(batch):
                if not text or not text.strip():
                    results.append(EmotionScore())
                    continue
                row = probs[i]
                mapped: Dict[str, float] = {}
                for idx, raw_label in self._id2label.items():
                    canonical = self._label_map.get(raw_label)
                    if canonical is None:
                        continue
                    # Handle the case where two raw labels map to the same
                    # canonical emotion: keep the max (shouldn't happen with
                    # the maps above, but keeps behaviour safe if extended).
                    val = float(row[idx])
                    if canonical not in mapped or val > mapped[canonical]:
                        mapped[canonical] = val
                dominant_label = None
                dominant_score = 0.0
                if mapped:
                    dominant_label = max(mapped, key=mapped.get)
                    dominant_score = mapped[dominant_label]
                # Round for stable DB/event output (avoids noisy diffs).
                rounded = {k: round(v, 4) for k, v in mapped.items()}
                results.append(
                    EmotionScore(
                        probabilities=rounded,
                        dominant_label=dominant_label,
                        dominant_score=round(dominant_score, 4),
                    )
                )
        return results


def build_ru_emotion_backend(
    *,
    name: str,
    version: str,
    device: str,
    use_float16: bool,
    batch_size: int,
    max_length: int,
    cache_dir: Optional[str],
) -> HFEmotionBackend:
    return HFEmotionBackend(
        name=name,
        version=version,
        language="ru",
        device=device,
        use_float16=use_float16,
        batch_size=batch_size,
        max_length=max_length,
        cache_dir=cache_dir,
        label_map=_RU_CEDR_MAP,
    )


def build_en_emotion_backend(
    *,
    name: str,
    version: str,
    device: str,
    use_float16: bool,
    batch_size: int,
    max_length: int,
    cache_dir: Optional[str],
) -> HFEmotionBackend:
    return HFEmotionBackend(
        name=name,
        version=version,
        language="en",
        device=device,
        use_float16=use_float16,
        batch_size=batch_size,
        max_length=max_length,
        cache_dir=cache_dir,
        label_map=_EN_DISTILROBERTA_MAP,
    )


__all__ = [
    "HFEmotionBackend",
    "build_ru_emotion_backend",
    "build_en_emotion_backend",
    "CANONICAL_EMOTIONS",
]

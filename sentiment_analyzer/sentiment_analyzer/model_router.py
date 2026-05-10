"""Language-aware model router for sentiment and emotion backends.

Keeps one backend instance per model (lazy-loaded on first use). Thread-safe
through the backend's own double-checked locking; the router itself is
stateless after construction.
"""
from __future__ import annotations

import logging
from typing import Optional

from sentiment_analyzer.backends.base import EmotionBackend, SentimentBackend
from sentiment_analyzer.backends.emotion import (
    build_en_emotion_backend,
    build_ru_emotion_backend,
)
from sentiment_analyzer.backends.hf_sentiment import HFSentimentBackend
from sentiment_analyzer.config import ModelsConfig


logger = logging.getLogger("sentiment_analyzer.model_router")

# Languages that get full sentiment analysis via the multilingual XLM-R backend.
# Everything outside this set (and outside "ru") returns None → pipeline skip.
_MULTILINGUAL_SUPPORTED = frozenset({"en", "de", "fr", "es", "it", "pt", "nl", "tr"})


class ModelRouter:
    """Selects the correct sentiment / emotion backend for a given language.

    ``pick_sentiment`` always returns a backend (RU model for Russian, XLM-R
    for any other supported language). ``pick_emotion`` returns None for
    languages without an emotion model so callers can record explicit partial
    coverage rather than crashing.
    """

    def __init__(self, config: ModelsConfig) -> None:
        self._config = config

        ru_cfg = config.ru
        self._ru_sentiment: HFSentimentBackend = HFSentimentBackend(
            name=ru_cfg.name,
            version=ru_cfg.version,
            language="ru",
            device=ru_cfg.device,
            use_float16=ru_cfg.use_float16,
            batch_size=ru_cfg.batch_size,
            max_length=ru_cfg.max_length,
            chunk_overlap=ru_cfg.chunk_overlap,
            neutral_threshold=ru_cfg.neutral_threshold,
            cache_dir=ru_cfg.cache_dir,
            local_path=ru_cfg.local_path,
        )

        ml_cfg = config.multilingual
        self._multilingual_sentiment: HFSentimentBackend = HFSentimentBackend(
            name=ml_cfg.name,
            version=ml_cfg.version,
            language="multilingual",
            device=ml_cfg.device,
            use_float16=ml_cfg.use_float16,
            batch_size=ml_cfg.batch_size,
            max_length=ml_cfg.max_length,
            chunk_overlap=ml_cfg.chunk_overlap,
            neutral_threshold=ml_cfg.neutral_threshold,
            cache_dir=ml_cfg.cache_dir,
            local_path=ml_cfg.local_path,
        )

        emo_ru_cfg = config.emotion_ru
        self._ru_emotion = (
            build_ru_emotion_backend(
                name=emo_ru_cfg.name,
                version=emo_ru_cfg.version,
                device=emo_ru_cfg.device,
                use_float16=emo_ru_cfg.use_float16,
                batch_size=emo_ru_cfg.batch_size,
                max_length=emo_ru_cfg.max_length,
                cache_dir=emo_ru_cfg.cache_dir,
            )
            if emo_ru_cfg.enabled and emo_ru_cfg.name
            else None
        )

        emo_en_cfg = config.emotion_en
        self._en_emotion = (
            build_en_emotion_backend(
                name=emo_en_cfg.name,
                version=emo_en_cfg.version,
                device=emo_en_cfg.device,
                use_float16=emo_en_cfg.use_float16,
                batch_size=emo_en_cfg.batch_size,
                max_length=emo_en_cfg.max_length,
                cache_dir=emo_en_cfg.cache_dir,
            )
            if emo_en_cfg.enabled and emo_en_cfg.name
            else None
        )

    # ── public API ──────────────────────────────────────────────────────────

    def pick_sentiment(self, language: str) -> SentimentBackend:
        """Return the sentiment backend for ``language``.

        RU → rubert-tiny. Everything else (including EN and all XLM-R-capable
        languages) → multilingual XLM-R. Callers should pre-filter languages
        via ``is_supported`` before invoking this.
        """
        if language == "ru":
            return self._ru_sentiment
        return self._multilingual_sentiment

    def pick_emotion(self, language: str) -> Optional[EmotionBackend]:
        """Return the emotion backend for ``language``, or None if not covered."""
        if language == "ru":
            return self._ru_emotion
        if language == "en":
            return self._en_emotion
        return None

    def is_supported(self, language: str) -> bool:
        """True if ``language`` has a sentiment backend (full analysis possible)."""
        return language == "ru" or language in _MULTILINGUAL_SUPPORTED

    def sentiment_model_language(self, language: str) -> str:
        """The ``model_language`` label stored in DB / event for tracing."""
        return "ru" if language == "ru" else "multilingual"

    def log_backends(self) -> None:
        logger.info(
            "model_router ru_sentiment=%s multilingual_sentiment=%s "
            "ru_emotion=%s en_emotion=%s",
            self._ru_sentiment.name,
            self._multilingual_sentiment.name,
            self._ru_emotion.name if self._ru_emotion else "disabled",
            self._en_emotion.name if self._en_emotion else "disabled",
        )

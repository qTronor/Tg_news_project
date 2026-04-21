"""Pluggable inference backends for sentiment + emotion classification.

Backends are grouped by language family (RU-specific, multilingual) and task
(sentiment vs emotion) so the service layer can route each message to the
appropriate pair without caring about model internals.
"""
from sentiment_analyzer.backends.base import (
    EmotionBackend,
    EmotionScore,
    SentimentBackend,
    SentimentScore,
    resolve_device,
)

__all__ = [
    "EmotionBackend",
    "EmotionScore",
    "SentimentBackend",
    "SentimentScore",
    "resolve_device",
]

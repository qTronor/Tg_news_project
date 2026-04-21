"""Base protocols + shared helpers for sentiment/emotion backends."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol

import numpy as np
import torch


logger = logging.getLogger("sentiment_analyzer.backends")

# Canonical 3-class sentiment vocabulary the pipeline persists.
CANONICAL_SENTIMENT_LABELS = ("negative", "neutral", "positive")

# Canonical emotion set the DB understands. Per-backend label maps are
# normalized to this vocabulary. Missing labels for a given language stay
# None in both the event payload and the sentiment_results columns (explicit
# partial coverage, not a stub placeholder).
CANONICAL_EMOTIONS = ("anger", "fear", "joy", "sadness", "surprise", "disgust")


@dataclass(frozen=True)
class SentimentScore:
    label: str
    score: float
    positive_prob: float
    negative_prob: float
    neutral_prob: float


@dataclass(frozen=True)
class EmotionScore:
    """Per-emotion probabilities.

    ``probabilities`` keys are restricted to CANONICAL_EMOTIONS; emotions that
    the underlying model does not predict are simply omitted (callers render
    them as JSON null / SQL NULL).
    """

    probabilities: Dict[str, float] = field(default_factory=dict)
    dominant_label: Optional[str] = None
    dominant_score: float = 0.0


class SentimentBackend(Protocol):
    """Language-specific sentiment classifier.

    Implementations must guarantee:
      * ``score_batch`` returns one :class:`SentimentScore` per input text,
        in order. Inputs may be empty strings — return a neutral default
        rather than crashing (upstream already handles empty text routing).
      * Loading happens lazily on the first call; a subsequent call should
        not re-load.
      * ``name`` / ``version`` / ``language`` are stable and used for the
        Kafka event's ``model`` block and the DB ``model_*`` columns.
    """

    name: str
    version: str
    language: str
    device: str
    batch_size: int

    def score_batch(self, texts: List[str]) -> List[SentimentScore]:
        ...


class EmotionBackend(Protocol):
    name: str
    version: str
    language: str
    device: str
    batch_size: int

    def score_batch(self, texts: List[str]) -> List[EmotionScore]:
        ...


def resolve_device(requested_device: str) -> torch.device:
    """Pick a torch device honoring ``auto`` and gracefully degrading to CPU.

    Centralised here so every backend logs the same decision shape. CUDA
    selection is logged only on downgrade to CPU so happy-path logs stay
    compact.
    """

    normalized = (requested_device or "auto").strip().lower()
    if normalized == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if normalized.startswith("cuda") and not torch.cuda.is_available():
        logger.warning(
            "cuda requested but unavailable, falling back to cpu requested=%s",
            requested_device,
        )
        return torch.device("cpu")
    return torch.device(normalized)


def softmax(logits: np.ndarray) -> np.ndarray:
    """Numerically stable softmax along the last axis."""

    shifted = logits - np.max(logits, axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


def chunk_token_ids(
    token_ids: List[int],
    chunk_size: int,
    overlap: int,
) -> List[List[int]]:
    """Slide a ``chunk_size`` window with ``overlap`` tokens over ``token_ids``.

    Used so that messages longer than the model context get averaged rather
    than truncated (the previous behaviour preserved verbatim).
    """

    if not token_ids:
        return []
    step = max(1, chunk_size - max(0, overlap))
    chunks: List[List[int]] = []
    for start in range(0, len(token_ids), step):
        chunk = token_ids[start : start + chunk_size]
        chunks.append(chunk)
        if start + chunk_size >= len(token_ids):
            break
    return chunks


def normalize_label(raw: str, label_map: Dict[str, str]) -> str:
    """Resolve raw backend label to one of CANONICAL_SENTIMENT_LABELS.

    ``label_map`` should map any of the backend's output strings (typically
    HF's ``id2label`` values, lowercased) to the canonical label. Unknown
    labels fall back to ``"neutral"`` with a warning so surprising model
    changes are visible in logs but don't crash the pipeline.
    """

    key = raw.strip().lower()
    if key in label_map:
        return label_map[key]
    logger.warning(
        "unknown sentiment label %r, defaulting to neutral (map=%s)",
        raw,
        sorted(label_map.keys()),
    )
    return "neutral"


def load_hf_model(
    model_name: str,
    cache_dir: Optional[str],
    device: torch.device,
    use_float16: bool,
    local_path: Optional[str] = None,
):
    """Load a HuggingFace AutoModelForSequenceClassification + tokenizer.

    Split out so ru/multilingual sentiment and both emotion backends share
    the same load path — identical cache, dtype, device, and eval-mode
    handling. Returns ``(tokenizer, model, source_tag)``.
    """

    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    kwargs = {}
    if device.type == "cuda" and use_float16 and torch.cuda.is_available():
        kwargs["torch_dtype"] = torch.float16
    if cache_dir:
        kwargs["cache_dir"] = cache_dir

    source = local_path if local_path and Path(local_path).exists() else model_name
    tokenizer = AutoTokenizer.from_pretrained(source, cache_dir=cache_dir)
    model = AutoModelForSequenceClassification.from_pretrained(source, **kwargs).to(device)
    model.eval()
    tag = f"local:{local_path}" if source == local_path else f"hub:{model_name}"
    logger.info(
        "loaded HF model source=%s device=%s num_labels=%d dtype=%s",
        tag,
        device.type,
        model.config.num_labels,
        "float16" if kwargs.get("torch_dtype") is torch.float16 else "float32",
    )
    return tokenizer, model, tag


def run_classification_batch(
    tokenizer,
    model,
    texts: List[str],
    device: torch.device,
    max_length: int,
) -> np.ndarray:
    """Run one tokenize+forward pass over a batch of short texts.

    Returns softmax probabilities of shape ``(len(texts), num_labels)``. Only
    suitable for inputs that fit in ``max_length`` — chunking for long docs
    is handled by the sentiment backends themselves (they call this fn per
    batch of chunks).
    """

    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    encoded = {k: v.to(device) for k, v in encoded.items()}
    with torch.inference_mode():
        outputs = model(**encoded)
    logits = outputs.logits.detach().cpu().float().numpy()
    return softmax(logits)

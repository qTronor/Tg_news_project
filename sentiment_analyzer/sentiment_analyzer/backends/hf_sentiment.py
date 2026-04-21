"""HuggingFace-based sentiment backend (used for both RU and multilingual EN).

One concrete class handles both roles — RU (``blanchefort/rubert-base-cased-sentiment``)
and multilingual (``cardiffnlp/twitter-xlm-roberta-base-sentiment``) share the
same tokenize/forward/softmax/chunk-average pipeline. The only per-model
difference is the label map from raw id2label strings to the canonical
``positive/neutral/negative`` vocabulary.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

import numpy as np

from sentiment_analyzer.backends.base import (
    CANONICAL_SENTIMENT_LABELS,
    SentimentScore,
    chunk_token_ids,
    load_hf_model,
    normalize_label,
    resolve_device,
    run_classification_batch,
    softmax,
)


logger = logging.getLogger("sentiment_analyzer.backends.hf_sentiment")

# Per-model label normalizers. Keys are lowercased raw id2label values the
# model can emit; values are canonical pipeline labels.
_RU_BLANCHEFORT_LABELS: Dict[str, str] = {
    "negative": "negative",
    "neutral": "neutral",
    "positive": "positive",
    "label_0": "neutral",   # blanchefort ordering: 0=neutral, 1=positive, 2=negative
    "label_1": "positive",
    "label_2": "negative",
}
_RU_COINTEGRATED_LABELS: Dict[str, str] = {
    "negative": "negative",
    "neutral": "neutral",
    "positive": "positive",
    "label_0": "negative",
    "label_1": "neutral",
    "label_2": "positive",
}
_XLMR_CARDIFF_LABELS: Dict[str, str] = {
    "negative": "negative",
    "neutral": "neutral",
    "positive": "positive",
    "label_0": "negative",
    "label_1": "neutral",
    "label_2": "positive",
}

_KNOWN_LABEL_MAPS = {
    "blanchefort/rubert-base-cased-sentiment": _RU_BLANCHEFORT_LABELS,
    "cointegrated/rubert-tiny-sentiment-balanced": _RU_COINTEGRATED_LABELS,
    "cointegrated/rubert-tiny-sentiment": _RU_COINTEGRATED_LABELS,
    "cardiffnlp/twitter-xlm-roberta-base-sentiment": _XLMR_CARDIFF_LABELS,
}


class HFSentimentBackend:
    """Single-model HF sentiment wrapper.

    Thread-safe lazy load (first call pays the model download + init cost).
    Designed so RU and multilingual backends are just two instances with
    different config, not two classes.
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
        chunk_overlap: int,
        neutral_threshold: float,
        cache_dir: Optional[str],
        local_path: Optional[str] = None,
        label_map: Optional[Dict[str, str]] = None,
    ) -> None:
        self.name = name
        self.version = version
        self.language = language
        self._device = resolve_device(device)
        self.device = self._device.type
        self.batch_size = batch_size
        self._use_float16 = use_float16
        self._max_length = max_length
        self._chunk_overlap = chunk_overlap
        self._neutral_threshold = neutral_threshold
        self._cache_dir = cache_dir
        self._local_path = local_path
        self._label_map = label_map or _KNOWN_LABEL_MAPS.get(name) or {
            lbl: lbl for lbl in CANONICAL_SENTIMENT_LABELS
        }
        self._tokenizer = None
        self._model = None
        self._source_tag: Optional[str] = None
        self._load_lock = threading.Lock()

    # ── loading ────────────────────────────────────────────────────────

    def ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            self._tokenizer, self._model, self._source_tag = load_hf_model(
                model_name=self.name,
                cache_dir=self._cache_dir,
                device=self._device,
                use_float16=self._use_float16,
                local_path=self._local_path,
            )
            # Id2label → lowercased-key view used by normalize_label.
            id2label = self._model.config.id2label
            lc_map = {str(v).lower(): str(v).lower() for v in id2label.values()}
            # Merge explicit overrides on top of the identity map.
            merged = {**lc_map, **self._label_map}
            self._label_map = merged
            self._id2label = {int(k): str(v).lower() for k, v in id2label.items()}

    # ── inference ──────────────────────────────────────────────────────

    def score_batch(self, texts: List[str]) -> List[SentimentScore]:
        self.ensure_loaded()
        results: List[SentimentScore] = []
        # One-by-one chunking per doc, but with a batched forward over the
        # chunks of each doc. This gives a meaningful speedup over the old
        # per-chunk forward while keeping chunk-average semantics.
        for text in texts:
            results.append(self._score_single(text))
        return results

    def _score_single(self, text: str) -> SentimentScore:
        if not text or not text.strip():
            return SentimentScore(
                label="neutral",
                score=1.0,
                positive_prob=0.0,
                negative_prob=0.0,
                neutral_prob=1.0,
            )
        assert self._tokenizer is not None and self._model is not None

        token_ids = self._tokenizer.encode(text, add_special_tokens=False)
        specials = self._tokenizer.num_special_tokens_to_add(pair=False)
        chunk_size = max(1, self._max_length - specials)
        chunks = chunk_token_ids(token_ids, chunk_size, self._chunk_overlap)
        if not chunks:
            return SentimentScore(
                label="neutral",
                score=1.0,
                positive_prob=0.0,
                negative_prob=0.0,
                neutral_prob=1.0,
            )
        # Rebuild text-form chunks by decoding; simpler than building input_ids
        # tensors manually for each chunk and lets the tokenizer add specials
        # consistently with training. Slight CPU cost; negligible vs forward.
        chunk_texts = [self._tokenizer.decode(c, skip_special_tokens=True) for c in chunks]

        # Batch forward across all chunks of this doc.
        import torch  # local import to keep module import side-effect light

        probs_all: List[np.ndarray] = []
        bs = max(1, self.batch_size)
        for start in range(0, len(chunk_texts), bs):
            batch = chunk_texts[start : start + bs]
            probs = run_classification_batch(
                self._tokenizer, self._model, batch, self._device, self._max_length
            )
            probs_all.append(probs)
        all_probs = np.concatenate(probs_all, axis=0)
        mean_probs = all_probs.mean(axis=0)

        pred_id = int(np.argmax(mean_probs))
        raw_label = self._id2label.get(pred_id, str(pred_id))
        label = normalize_label(raw_label, self._label_map)
        score = float(mean_probs[pred_id])
        if score < self._neutral_threshold:
            label = "neutral"

        idx = self._canonical_indices()
        def _p(lbl: str) -> float:
            i = idx.get(lbl)
            return float(mean_probs[i]) if i is not None else 0.0

        return SentimentScore(
            label=label,
            score=score,
            positive_prob=_p("positive"),
            negative_prob=_p("negative"),
            neutral_prob=_p("neutral"),
        )

    def _canonical_indices(self) -> Dict[str, int]:
        """Map canonical labels → model output indices using id2label + label_map."""

        result: Dict[str, int] = {}
        for int_id, raw in self._id2label.items():
            canonical = self._label_map.get(raw.lower())
            if canonical in CANONICAL_SENTIMENT_LABELS:
                result[canonical] = int_id
        return result

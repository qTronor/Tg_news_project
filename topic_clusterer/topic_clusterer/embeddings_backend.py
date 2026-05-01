"""Embeddings backends for topic clustering.

Two implementations share a common interface:
- ``TorchEmbeddingsBackend``: default, wraps sentence-transformers (current behaviour).
- ``OnnxEmbeddingsBackend``: optional, uses optimum[onnxruntime] for CPU-only or
  CUDAExecutionProvider. Activated via ``model.backend = "onnx"`` in config.

Both are lazy-loaded; ``compute`` blocks the caller so it must be wrapped in
``asyncio.run_in_executor`` (as done by the service).
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional, Protocol

import numpy as np


logger = logging.getLogger("topic_clusterer.embeddings_backend")


class EmbeddingsBackend(Protocol):
    """Protocol for sentence-embedding backends."""

    name: str

    def compute(
        self,
        text: str,
        normalize: bool = True,
        batch_size: int = 32,
    ) -> np.ndarray:
        ...

    def ensure_loaded(self) -> None:
        ...


class TorchEmbeddingsBackend:
    """sentence-transformers / SentenceTransformer wrapper (default backend)."""

    def __init__(
        self,
        *,
        model_name: str,
        device: str = "auto",
        use_float16: bool = True,
        cache_dir: Optional[str] = None,
    ) -> None:
        self.name = model_name
        self._device = device
        self._use_float16 = use_float16
        self._cache_dir = cache_dir
        self._sbert = None
        self._lock = threading.Lock()

    def ensure_loaded(self) -> None:
        if self._sbert is not None:
            return
        with self._lock:
            if self._sbert is not None:
                return
            from sentence_transformers import SentenceTransformer

            kwargs: dict = {"device": self._resolve_device()}
            if self._cache_dir:
                kwargs["cache_folder"] = self._cache_dir
            logger.info(
                "loading sbert model name=%s device=%s", self.name, kwargs["device"]
            )
            self._sbert = SentenceTransformer(self.name, **kwargs)
            if kwargs["device"] == "cuda" and self._use_float16:
                self._sbert.half()
            logger.info("sbert model loaded name=%s", self.name)

    def compute(
        self,
        text: str,
        normalize: bool = True,
        batch_size: int = 32,
    ) -> np.ndarray:
        self.ensure_loaded()
        assert self._sbert is not None
        return self._sbert.encode(
            text,
            normalize_embeddings=normalize,
            batch_size=batch_size,
            show_progress_bar=False,
        )

    def _resolve_device(self) -> str:
        normalized = (self._device or "auto").strip().lower()
        if normalized == "auto":
            try:
                import torch
                return "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                return "cpu"
        try:
            import torch
            if normalized.startswith("cuda") and not torch.cuda.is_available():
                logger.warning(
                    "cuda requested but unavailable, falling back to cpu"
                )
                return "cpu"
        except ImportError:
            return "cpu"
        return normalized


class OnnxEmbeddingsBackend:
    """ONNX Runtime backend via optimum for CPU / GPU inference.

    The ONNX model must be exported first:
        optimum-cli export onnx --model <model_name> <onnx_dir>
    or use ``scripts/export_sbert_onnx.py``.

    Requires: ``optimum[onnxruntime]>=1.17.0``, ``onnxruntime>=1.16.0``
    (or ``onnxruntime-gpu`` for CUDA provider).
    """

    def __init__(
        self,
        *,
        model_name: str,
        onnx_path: str,
        provider: str = "CPUExecutionProvider",
    ) -> None:
        self.name = model_name
        self._onnx_path = Path(onnx_path)
        self._provider = provider
        self._model = None
        self._tokenizer = None
        self._lock = threading.Lock()

    def ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                from optimum.onnxruntime import ORTModelForFeatureExtraction
                from transformers import AutoTokenizer
            except ImportError as exc:
                raise RuntimeError(
                    "ONNX backend requires optimum[onnxruntime]: "
                    "pip install 'optimum[onnxruntime]>=1.17.0'"
                ) from exc

            logger.info(
                "loading ONNX model path=%s provider=%s", self._onnx_path, self._provider
            )
            self._tokenizer = AutoTokenizer.from_pretrained(str(self._onnx_path))
            self._model = ORTModelForFeatureExtraction.from_pretrained(
                str(self._onnx_path),
                provider=self._provider,
            )
            logger.info("ONNX model loaded path=%s", self._onnx_path)

    def compute(
        self,
        text: str,
        normalize: bool = True,
        batch_size: int = 32,
    ) -> np.ndarray:
        self.ensure_loaded()
        assert self._tokenizer is not None and self._model is not None

        import torch

        encoded = self._tokenizer(
            text,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        with torch.inference_mode():
            outputs = self._model(**encoded)
        # Mean pooling over token embeddings (CLS token or mean of all tokens)
        token_embeddings = outputs.last_hidden_state
        attention_mask = encoded["attention_mask"]
        input_mask_expanded = (
            attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        )
        embedding = (
            torch.sum(token_embeddings * input_mask_expanded, 1)
            / torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        )
        vec = embedding.squeeze(0).detach().cpu().float().numpy()
        if normalize:
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
        return vec


def build_embeddings_backend(config) -> EmbeddingsBackend:
    """Factory: pick torch or onnx backend based on ``config.model``."""
    backend = getattr(config.model, "backend", "torch")
    if backend == "onnx":
        onnx_path = getattr(config.model, "onnx_path", None)
        if not onnx_path:
            raise ValueError("model.onnx_path must be set when model.backend='onnx'")
        provider = getattr(config.model, "onnx_provider", "CPUExecutionProvider")
        return OnnxEmbeddingsBackend(
            model_name=config.model.sbert_model,
            onnx_path=onnx_path,
            provider=provider,
        )
    # default: torch
    return TorchEmbeddingsBackend(
        model_name=config.model.sbert_model,
        device=config.model.device,
        use_float16=config.model.use_float16,
        cache_dir=config.model.cache_dir,
    )

"""Shared ML runtime helpers for the ner_extractor service.

Identical copies of this module live in preprocessor and sentiment_analyzer
to avoid a monorepo shared-package dependency (each service has its own Docker
build context).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


def pick_device(requested: str) -> str:
    """Resolve a device string, degrading to CPU if CUDA is requested but absent.

    Returns ``"cuda"`` or ``"cpu"``. The result is always loggable and safe to
    pass directly to ``torch.device()``.
    """
    normalized = (requested or "auto").strip().lower()
    try:
        import torch

        if normalized == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        elif normalized.startswith("cuda") and not torch.cuda.is_available():
            logger.warning(
                "pick_device: cuda requested but unavailable, using cpu requested=%s",
                requested,
            )
            device = "cpu"
        else:
            device = normalized
    except ImportError:
        device = "cpu"
    return device


def get_cache_dir(config_cache_dir: Optional[str], env_var: str = "HF_HOME") -> Optional[Path]:
    """Resolve the HuggingFace model cache directory.

    Priority: explicit config value → env var → None (HF default).
    """
    if config_cache_dir:
        return Path(config_cache_dir)
    env_val = os.environ.get(env_var)
    if env_val:
        return Path(env_val)
    return None


def log_model_init(
    name: str,
    version: str,
    device: str,
    backend: str,
) -> None:
    """Emit a consistent structured log line when a model is loaded."""
    logger.info(
        "model_init name=%s version=%s device=%s backend=%s",
        name,
        version,
        device,
        backend,
    )

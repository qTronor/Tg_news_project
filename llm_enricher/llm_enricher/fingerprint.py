from __future__ import annotations

import hashlib
import json
from typing import Any


def input_fingerprint(data: Any) -> str:
    """Return sha256 hex digest of canonical JSON representation of data."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_key(
    public_cluster_id: str,
    enrichment_type: str,
    language: str,
    prompt_version: str,
    model_name: str,
    fingerprint: str,
) -> str:
    """Deterministic cache key for a specific enrichment request."""
    raw = "|".join(
        [public_cluster_id, enrichment_type, language, prompt_version, model_name, fingerprint]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

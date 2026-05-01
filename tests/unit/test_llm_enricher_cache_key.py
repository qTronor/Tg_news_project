"""Tests for cache_key composition and sensitivity."""
from __future__ import annotations

from llm_enricher import fingerprint as fp


_BASE = dict(
    public_cluster_id="run1:cluster0",
    enrichment_type="cluster_label",
    language="ru",
    prompt_version="v1",
    model_name="mistral-large-latest",
    fingerprint="deadbeef" * 8,
)


def test_identical_inputs_same_key():
    assert fp.cache_key(**_BASE) == fp.cache_key(**_BASE)


def test_key_is_64_hex_chars():
    key = fp.cache_key(**_BASE)
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)


def test_different_cluster_different_key():
    a = fp.cache_key(**{**_BASE, "public_cluster_id": "run1:cluster0"})
    b = fp.cache_key(**{**_BASE, "public_cluster_id": "run1:cluster1"})
    assert a != b


def test_different_enrichment_type_different_key():
    a = fp.cache_key(**{**_BASE, "enrichment_type": "cluster_label"})
    b = fp.cache_key(**{**_BASE, "enrichment_type": "cluster_summary"})
    assert a != b


def test_different_language_different_key():
    a = fp.cache_key(**{**_BASE, "language": "ru"})
    b = fp.cache_key(**{**_BASE, "language": "en"})
    assert a != b


def test_different_prompt_version_different_key():
    a = fp.cache_key(**{**_BASE, "prompt_version": "v1"})
    b = fp.cache_key(**{**_BASE, "prompt_version": "v2"})
    assert a != b


def test_different_model_different_key():
    a = fp.cache_key(**{**_BASE, "model_name": "mistral-large-latest"})
    b = fp.cache_key(**{**_BASE, "model_name": "mistral-small-latest"})
    assert a != b


def test_different_fingerprint_different_key():
    a = fp.cache_key(**{**_BASE, "fingerprint": "aaa"})
    b = fp.cache_key(**{**_BASE, "fingerprint": "bbb"})
    assert a != b

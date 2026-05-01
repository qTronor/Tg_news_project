"""Tests for fingerprint and cache_key stability."""
from __future__ import annotations

from llm_enricher import fingerprint as fp


def test_same_data_same_fingerprint():
    data = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}
    assert fp.input_fingerprint(data) == fp.input_fingerprint(data)


def test_field_reorder_same_fingerprint():
    d1 = {"b": 2, "a": 1}
    d2 = {"a": 1, "b": 2}
    assert fp.input_fingerprint(d1) == fp.input_fingerprint(d2)


def test_numeric_change_different_fingerprint():
    d1 = {"importance_score": 0.75}
    d2 = {"importance_score": 0.76}
    assert fp.input_fingerprint(d1) != fp.input_fingerprint(d2)


def test_none_vs_missing_different():
    d1 = {"label": None}
    d2 = {}
    assert fp.input_fingerprint(d1) != fp.input_fingerprint(d2)


def test_fingerprint_is_hex_64():
    result = fp.input_fingerprint({"x": 1})
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_cache_key_stability():
    key = fp.cache_key("cluster-1", "cluster_label", "ru", "v1", "mistral-large-latest", "abc123")
    key2 = fp.cache_key("cluster-1", "cluster_label", "ru", "v1", "mistral-large-latest", "abc123")
    assert key == key2
    assert len(key) == 64


def test_cache_key_sensitive_to_prompt_version():
    base = dict(public_cluster_id="c1", enrichment_type="cluster_label", language="ru",
                model_name="m", fingerprint="fp")
    k1 = fp.cache_key(**{**base, "prompt_version": "v1"})
    k2 = fp.cache_key(**{**base, "prompt_version": "v2"})
    assert k1 != k2


def test_cache_key_sensitive_to_model():
    base = dict(public_cluster_id="c1", enrichment_type="cluster_label", language="ru",
                prompt_version="v1", fingerprint="fp")
    k1 = fp.cache_key(**{**base, "model_name": "mistral-large-latest"})
    k2 = fp.cache_key(**{**base, "model_name": "mistral-small-latest"})
    assert k1 != k2

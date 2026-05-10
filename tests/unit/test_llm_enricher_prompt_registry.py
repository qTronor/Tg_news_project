"""Tests for PromptRegistry: version resolution and language fallback."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from llm_enricher.prompts import PromptRegistry


def _make_registry(files: dict[str, str]) -> tuple[PromptRegistry, Path]:
    """Create a temp dir with given file tree and return a PromptRegistry rooted there."""
    tmp = tempfile.mkdtemp()
    root = Path(tmp)
    for rel_path, content in files.items():
        full = root / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    return PromptRegistry(root), root


def test_resolves_latest_version():
    registry, _ = _make_registry({
        "cluster_label/en/v1.txt": "# v1 $cluster_id",
        "cluster_label/en/v2.txt": "# v2 $cluster_id",
    })
    template, version = registry.get("cluster_label", "en", "latest")
    assert version == "v2"
    assert "v2" in template.template


def test_explicit_version():
    registry, _ = _make_registry({
        "cluster_label/en/v1.txt": "# v1 $cluster_id",
        "cluster_label/en/v2.txt": "# v2 $cluster_id",
    })
    template, version = registry.get("cluster_label", "en", "v1")
    assert version == "v1"
    assert "v1" in template.template


def test_lang_fallback_other_to_en():
    """When 'other' dir is missing, falls back to 'en'."""
    registry, _ = _make_registry({
        "cluster_label/en/v1.txt": "# en fallback $cluster_id",
    })
    template, version = registry.get("cluster_label", "other")
    assert "en fallback" in template.template
    assert version == "v1"


def test_lang_fallback_unknown_to_other_to_en():
    """Unknown lang falls back through 'other' if present."""
    registry, _ = _make_registry({
        "cluster_label/other/v1.txt": "# other fallback $cluster_id",
        "cluster_label/en/v1.txt": "# en fallback $cluster_id",
    })
    template, version = registry.get("cluster_label", "zh")
    assert "other fallback" in template.template


def test_missing_type_raises():
    registry, _ = _make_registry({
        "cluster_label/en/v1.txt": "# ok",
    })
    with pytest.raises(FileNotFoundError):
        registry.get("nonexistent_type", "en")


def test_caching_returns_same_object():
    registry, _ = _make_registry({
        "cluster_label/en/v1.txt": "# $cluster_id",
    })
    result1 = registry.get("cluster_label", "en")
    result2 = registry.get("cluster_label", "en")
    assert result1[0] is result2[0]


def test_template_substitution():
    registry, _ = _make_registry({
        "cluster_label/en/v1.txt": "Cluster: $cluster_id Label",
    })
    template, _ = registry.get("cluster_label", "en")
    rendered = template.safe_substitute(cluster_id="abc-123")
    assert "abc-123" in rendered

"""Tests for output JSON schema validation."""
from __future__ import annotations

import pytest
import jsonschema

from llm_enricher.schemas import (
    CLUSTER_LABEL_SCHEMA,
    CLUSTER_SUMMARY_SCHEMA,
    CLUSTER_EXPLANATION_SCHEMA,
    NOVELTY_EXPLANATION_SCHEMA,
    OUTPUT_SCHEMAS,
    SUPPORTED_ENRICHMENT_TYPES,
)


def test_all_types_in_output_schemas():
    for etype in ("cluster_summary", "cluster_explanation", "novelty_explanation", "cluster_label"):
        assert etype in OUTPUT_SCHEMAS


def test_cluster_label_valid():
    jsonschema.validate({"label": "Politics", "confidence": 0.9}, CLUSTER_LABEL_SCHEMA)


def test_cluster_label_missing_field_invalid():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"label": "Politics"}, CLUSTER_LABEL_SCHEMA)


def test_cluster_label_confidence_out_of_range_invalid():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"label": "X", "confidence": 1.5}, CLUSTER_LABEL_SCHEMA)


def test_cluster_label_too_long_invalid():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"label": "X" * 81, "confidence": 0.5}, CLUSTER_LABEL_SCHEMA)


def test_cluster_summary_valid():
    jsonschema.validate(
        {"summary": "A summary.", "key_points": ["point 1", "point 2"]},
        CLUSTER_SUMMARY_SCHEMA,
    )


def test_cluster_summary_too_many_key_points_invalid():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"summary": "ok", "key_points": ["a", "b", "c", "d", "e", "f"]},
            CLUSTER_SUMMARY_SCHEMA,
        )


def test_novelty_explanation_valid():
    jsonschema.validate(
        {"novelty_verdict": "new", "rationale": "New topic."},
        NOVELTY_EXPLANATION_SCHEMA,
    )


def test_novelty_explanation_invalid_verdict():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"novelty_verdict": "unknown", "rationale": "X"},
            NOVELTY_EXPLANATION_SCHEMA,
        )


def test_cluster_explanation_valid():
    jsonschema.validate(
        {
            "why_important": "High channel diversity.",
            "drivers": [{"name": "channels", "weight": 0.4, "explanation": "Many sources"}],
        },
        CLUSTER_EXPLANATION_SCHEMA,
    )


def test_cluster_explanation_extra_fields_invalid():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"why_important": "ok", "drivers": [], "extra_field": "bad"},
            CLUSTER_EXPLANATION_SCHEMA,
        )

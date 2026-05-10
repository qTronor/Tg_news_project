"""Tests for the 3 new summary JSON Schema contracts."""
from __future__ import annotations

import pytest
import jsonschema

from llm_enricher.schemas import (
    KEY_ACTORS_SUMMARY_SCHEMA,
    TIMELINE_SUMMARY_SCHEMA,
    WHAT_CHANGED_RECENTLY_SCHEMA,
    OUTPUT_SCHEMAS,
    SUPPORTED_ENRICHMENT_TYPES,
)


class TestNewTypesRegistered:
    def test_timeline_summary_in_output_schemas(self):
        assert "timeline_summary" in OUTPUT_SCHEMAS

    def test_key_actors_summary_in_output_schemas(self):
        assert "key_actors_summary" in OUTPUT_SCHEMAS

    def test_what_changed_recently_in_output_schemas(self):
        assert "what_changed_recently" in OUTPUT_SCHEMAS

    def test_all_new_types_in_supported_enrichment_types(self):
        for etype in ("timeline_summary", "key_actors_summary", "what_changed_recently"):
            assert etype in SUPPORTED_ENRICHMENT_TYPES


class TestTimelineSummarySchema:
    def test_valid_full_payload(self):
        jsonschema.validate(
            {
                "events": [
                    {"when": "1 мая", "what": "Лидеры встретились в Москве.", "source_channel": "channel1"},
                    {"when": "3 мая", "what": "Переговоры провалились."},
                ]
            },
            TIMELINE_SUMMARY_SCHEMA,
        )

    def test_empty_events_valid(self):
        jsonschema.validate({"events": []}, TIMELINE_SUMMARY_SCHEMA)

    def test_missing_required_when_invalid(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"events": [{"what": "Событие без даты."}]},
                TIMELINE_SUMMARY_SCHEMA,
            )

    def test_missing_required_what_invalid(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"events": [{"when": "1 мая"}]},
                TIMELINE_SUMMARY_SCHEMA,
            )

    def test_too_many_events_invalid(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"events": [{"when": str(i), "what": "x"} for i in range(7)]},
                TIMELINE_SUMMARY_SCHEMA,
            )

    def test_extra_fields_invalid(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"events": [], "extra": "bad"},
                TIMELINE_SUMMARY_SCHEMA,
            )


class TestKeyActorsSummarySchema:
    def test_valid_full_payload(self):
        jsonschema.validate(
            {
                "actors": [
                    {
                        "name": "Путин",
                        "role": "Президент России",
                        "why_matters": "Основной переговорщик.",
                        "mention_count": 15,
                    }
                ]
            },
            KEY_ACTORS_SUMMARY_SCHEMA,
        )

    def test_empty_actors_valid(self):
        jsonschema.validate({"actors": []}, KEY_ACTORS_SUMMARY_SCHEMA)

    def test_too_many_actors_invalid(self):
        actor = {"name": "X", "role": "Y", "why_matters": "Z", "mention_count": 1}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"actors": [actor] * 6},
                KEY_ACTORS_SUMMARY_SCHEMA,
            )

    def test_missing_name_invalid(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"actors": [{"role": "R", "why_matters": "W", "mention_count": 1}]},
                KEY_ACTORS_SUMMARY_SCHEMA,
            )

    def test_negative_mention_count_invalid(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"actors": [{"name": "X", "role": "R", "why_matters": "W", "mention_count": -1}]},
                KEY_ACTORS_SUMMARY_SCHEMA,
            )


class TestWhatChangedRecentlySchema:
    def test_valid_full_payload(self):
        jsonschema.validate(
            {
                "summary": "За последние дни активность выросла.",
                "changes": [
                    {
                        "period": "последние 2 дня",
                        "change_description": "Число каналов удвоилось.",
                        "severity": 0.8,
                    }
                ],
            },
            WHAT_CHANGED_RECENTLY_SCHEMA,
        )

    def test_empty_changes_valid(self):
        jsonschema.validate(
            {"summary": "Без изменений.", "changes": []},
            WHAT_CHANGED_RECENTLY_SCHEMA,
        )

    def test_too_many_changes_invalid(self):
        change = {"period": "p", "change_description": "d", "severity": 0.5}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"summary": "ok", "changes": [change] * 5},
                WHAT_CHANGED_RECENTLY_SCHEMA,
            )

    def test_severity_out_of_range_invalid(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {
                    "summary": "ok",
                    "changes": [{"period": "p", "change_description": "d", "severity": 1.5}],
                },
                WHAT_CHANGED_RECENTLY_SCHEMA,
            )

    def test_missing_summary_invalid(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"changes": []},
                WHAT_CHANGED_RECENTLY_SCHEMA,
            )

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]


class MultilingualContractTest(unittest.TestCase):
    def test_preprocessed_multilingual_contract_matches_schema(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "preprocessed_message.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator = Draft7Validator(schema, format_checker=FormatChecker())
        event = {
            "event_id": "demo:1",
            "event_type": "preprocessed",
            "event_timestamp": "2026-04-13T10:00:00Z",
            "event_version": "v1.0.0",
            "source_system": "preprocessor",
            "trace_id": "550e8400-e29b-41d4-a716-446655440000",
            "payload": {
                "message_id": 1,
                "channel": "demo",
                "original_text": "El banco central subio la tasa",
                "cleaned_text": "el banco central subio la tasa",
                "normalized_text": "el banco central subio la tasa",
                "language": "other",
                "original_language": "other",
                "language_confidence": 1.0,
                "is_supported_for_full_analysis": False,
                "analysis_mode": "partial",
                "translation_status": "not_requested",
                "tokens": ["el", "banco", "central", "subio", "la", "tasa"],
                "sentences_count": 1,
                "word_count": 6,
            },
        }

        errors = sorted(validator.iter_errors(event), key=lambda error: error.path)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()

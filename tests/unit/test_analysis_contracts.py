from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sentiment_analyzer"))
sys.path.insert(0, str(ROOT / "ner_extractor"))
sys.path.insert(0, str(ROOT / "topic_clusterer"))

from ner_extractor.service import EntitySpan, NerExtractorService
from topic_clusterer.config import AppConfig as TopicConfig
from topic_clusterer.schemas import JsonSchemaValidator
from topic_clusterer.service import (
    ClusteringRunBatch,
    SQLITE_INIT_SQL,
    SQLITE_SCHEMA_PATCHES,
    TopicClustererService,
)


class AnalysisContractsUnitTest(unittest.TestCase):
    def test_ner_co_occurrence_relations_are_unique(self) -> None:
        entities = [
            EntitySpan("ЦБ", "ORG", 0, 2, "Центральный Банк"),
            EntitySpan("Банк России", "ORG", 4, 16, "Центральный Банк"),
            EntitySpan("Москва", "LOC", 18, 24, "Москва"),
        ]

        relations = NerExtractorService._build_co_occurrence_relations(entities)

        self.assertEqual(
            relations,
            [("Центральный Банк", "Москва", "ORG", "LOC")],
        )

    def test_topic_assignment_event_matches_schema(self) -> None:
        service = TopicClustererService.__new__(TopicClustererService)
        service._config = TopicConfig()
        service._output_validator = JsonSchemaValidator(
            ROOT / "schemas" / "topic_assignment.schema.json"
        )

        batch = ClusteringRunBatch(
            run_id="run_test",
            run_timestamp=datetime(2026, 4, 13, 10, 0, tzinfo=timezone.utc),
            algo_version="similarity_fallback_v1.0.0",
            window_start=datetime(2026, 4, 13, 9, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 13, 10, 0, tzinfo=timezone.utc),
            total_messages=1,
            total_clustered=1,
            total_noise=0,
            n_clusters=1,
            config_json={"strategy": "similarity_fallback"},
            duration_seconds=0.01,
            assignments=[
                {
                    "event_id": "demo:1",
                    "channel": "demo",
                    "message_id": 1,
                    "cluster_id": 0,
                    "cluster_probability": 0.99,
                    "bucket_id": "2026-04-13T09:00:00+00:00",
                    "message_date": datetime(2026, 4, 13, 10, 0, tzinfo=timezone.utc),
                    "trace_id": "550e8400-e29b-41d4-a716-446655440000",
                }
            ],
        )

        event = service._build_topic_assignment_event(batch, batch.assignments[0])
        service._output_validator.validate(event)

        self.assertEqual(event["payload"]["topic_id"], "run_test:0")
        self.assertEqual(event["payload"]["cluster_id"], 0)

    def test_preprocessed_multilingual_contract_matches_schema(self) -> None:
        validator = JsonSchemaValidator(
            ROOT / "schemas" / "preprocessed_message.schema.json"
        )
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

        validator.validate(event)

    def test_topic_small_batch_fallback_creates_singleton_clusters(self) -> None:
        service = TopicClustererService.__new__(TopicClustererService)
        service._config = TopicConfig()
        service._db = sqlite3.connect(":memory:", check_same_thread=False)
        for statement in SQLITE_INIT_SQL.strip().split(";"):
            statement = statement.strip()
            if statement:
                service._db.execute(statement)
        for statement in SQLITE_SCHEMA_PATCHES:
            try:
                service._db.execute(statement)
            except sqlite3.OperationalError:
                pass

        service._db.execute(
            """
            INSERT INTO message_embeddings (
                event_id, channel, message_id, text, embedding, trace_id, event_timestamp, clustered
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            [
                "demo:1",
                "demo",
                1,
                "первая новость",
                json_dumps([1.0, 0.0]),
                "550e8400-e29b-41d4-a716-446655440000",
                "2026-04-13T10:00:00+00:00",
            ],
        )
        service._db.execute(
            """
            INSERT INTO message_embeddings (
                event_id, channel, message_id, text, embedding, trace_id, event_timestamp, clustered
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            [
                "demo:2",
                "demo",
                2,
                "вторая новость",
                json_dumps([0.0, 1.0]),
                "550e8400-e29b-41d4-a716-446655440001",
                "2026-04-13T10:05:00+00:00",
            ],
        )
        service._db.commit()

        batch = service._build_clustering_run()

        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(batch.total_messages, 2)
        self.assertEqual(batch.n_clusters, 2)
        self.assertEqual(
            sorted(assignment["cluster_id"] for assignment in batch.assignments),
            [0, 1],
        )

    def test_topic_run_id_is_deterministic_for_same_batch(self) -> None:
        run_id_1 = TopicClustererService._make_run_id(
            ["demo:2", "demo:1"],
            "similarity_fallback_v1.0.0",
        )
        run_id_2 = TopicClustererService._make_run_id(
            ["demo:1", "demo:2"],
            "similarity_fallback_v1.0.0",
        )

        self.assertEqual(run_id_1, run_id_2)


def json_dumps(value: list[float]) -> str:
    return json.dumps(value)

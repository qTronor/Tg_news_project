from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import MethodType
from uuid import UUID, uuid4

import asyncpg
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sentiment_analyzer"))
sys.path.insert(0, str(ROOT / "ner_extractor"))
sys.path.insert(0, str(ROOT / "topic_clusterer"))

from ner_extractor.config import AppConfig as NerConfig
from ner_extractor.schemas import JsonSchemaValidator as NerSchemaValidator
from ner_extractor.service import EntitySpan, MessageContext as NerContext, NerExtractorService
from sentiment_analyzer.config import AppConfig as SentimentConfig
from sentiment_analyzer.schemas import JsonSchemaValidator as SentimentSchemaValidator
from sentiment_analyzer.service import (
    MessageContext as SentimentContext,
    SentimentAnalyzerService,
)
from topic_clusterer.config import AppConfig as TopicConfig
from topic_clusterer.schemas import JsonSchemaValidator as TopicSchemaValidator
from topic_clusterer.service import (
    SQLITE_INIT_SQL,
    SQLITE_SCHEMA_PATCHES,
    HealthState as TopicHealthState,
    MessageContext as TopicContext,
    TopicClustererService,
)


class FakeProducer:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict, str]] = []

    async def send_and_wait(self, topic, value, key=None, headers=None):  # noqa: ANN001
        import json

        decoded = json.loads(value.decode("utf-8"))
        self.events.append((topic, decoded, key.decode("utf-8") if key else ""))


@unittest.skipUnless(os.getenv("TEST_DATABASE_DSN"), "TEST_DATABASE_DSN is required")
class AnalysisPipelineIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.dsn = os.environ["TEST_DATABASE_DSN"]
        self.schema = f"test_analysis_{uuid4().hex[:8]}"
        self.admin_conn = await asyncpg.connect(self.dsn)
        try:
            await self.admin_conn.execute(f'CREATE SCHEMA "{self.schema}"')
            await self.admin_conn.execute(f'SET search_path TO "{self.schema}"')
            await self.admin_conn.execute(
                (ROOT / "migrations" / "001_initial_schema.sql").read_text(encoding="utf-8")
            )
            await self.admin_conn.execute(
                (ROOT / "migrations" / "003_first_source.sql").read_text(encoding="utf-8")
            )
        except Exception as exc:
            self.skipTest(f"Unable to initialize test schema: {exc}")

        self.pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=1,
            max_size=1,
            server_settings={"search_path": self.schema},
        )

        self.event_id = "demo:1"
        self.trace_id = "550e8400-e29b-41d4-a716-446655440000"
        self.now = datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc)

        async with self.pool.acquire() as conn:
            raw_id = await conn.fetchval(
                """
                INSERT INTO raw_messages (
                    message_id, channel, text, message_date, views, forwards,
                    event_timestamp, trace_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id;
                """,
                1,
                "demo",
                "Центробанк в Москве сохранил ставку",
                self.now,
                100,
                3,
                self.now,
                self.trace_id,
            )
            await conn.execute(
                """
                INSERT INTO preprocessed_messages (
                    raw_message_id, message_id, channel, event_id, original_text, cleaned_text,
                    normalized_text, language, tokens, sentences_count, word_count,
                    has_urls, has_mentions, has_hashtags, urls, mentions, hashtags,
                    normalized_text_hash, simhash64, url_fingerprints, primary_url_fingerprint,
                    preprocessing_version, event_timestamp, trace_id, processing_time_ms
                )
                VALUES (
                    $1, 1, 'demo', $2, 'Центробанк в Москве сохранил ставку',
                    'центробанк в москве сохранил ставку',
                    'центробанк в москва сохранить ставка',
                    'ru', ARRAY['центробанк', 'москва', 'ставка'], 1, 4,
                    FALSE, FALSE, FALSE, ARRAY[]::text[], ARRAY[]::text[], ARRAY[]::text[],
                    'hash-1', 12345, ARRAY[]::text[], NULL, 'test', $3, $4, 1.5
                );
                """,
                raw_id,
                self.event_id,
                self.now,
                self.trace_id,
            )

    async def asyncTearDown(self) -> None:
        if hasattr(self, "pool"):
            await self.pool.close()
        if hasattr(self, "admin_conn"):
            await self.admin_conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            await self.admin_conn.close()

    async def test_analysis_services_write_rows_and_publish_events(self) -> None:
        test_case = self
        sentiment_producer = FakeProducer()
        sentiment_service = SentimentAnalyzerService.__new__(SentimentAnalyzerService)
        sentiment_service._config = SentimentConfig()
        sentiment_service._pool = self.pool
        sentiment_service._producer = sentiment_producer
        sentiment_service._output_validator = SentimentSchemaValidator(
            ROOT / "schemas" / "sentiment_enriched.schema.json"
        )

        async def fake_analyze(self, text: str) -> dict:  # noqa: ANN001
            test_case.assertIn("Центробанк", text)
            return {
                "label": "neutral",
                "score": 0.91,
                "positive_prob": 0.03,
                "negative_prob": 0.06,
                "neutral_prob": 0.91,
            }

        sentiment_service._analyze_sentiment = MethodType(fake_analyze, sentiment_service)

        await sentiment_service._process_once(
            SentimentContext(
                event_id=self.event_id,
                processing_event_id=f"sentiment-analyzer:{self.event_id}",
                event_type="preprocessed",
                event_timestamp=self.now.isoformat().replace("+00:00", "Z"),
                event_timestamp_dt=self.now,
                trace_id=self.trace_id,
                trace_id_uuid=UUID(self.trace_id),
                message_id=1,
                channel="demo",
                original_text="Центробанк в Москве сохранил ставку",
                payload={},
                key=self.event_id,
                topic="preprocessed.messages",
                partition=0,
                offset=0,
            )
        )

        ner_producer = FakeProducer()
        ner_service = NerExtractorService.__new__(NerExtractorService)
        ner_service._config = NerConfig()
        ner_service._pool = self.pool
        ner_service._producer = ner_producer
        ner_service._output_validator = NerSchemaValidator(
            ROOT / "schemas" / "ner_enriched.schema.json"
        )
        ner_service._extract_entities = MethodType(
            lambda self, text: [  # noqa: ARG005
                EntitySpan("Центробанк", "ORG", 0, 11, "Центральный Банк"),
                EntitySpan("Москве", "LOC", 14, 20, "Москва"),
            ],
            ner_service,
        )

        await ner_service._process_once(
            NerContext(
                event_id=self.event_id,
                processing_event_id=f"ner-extractor:{self.event_id}",
                event_type="preprocessed",
                event_timestamp=self.now.isoformat().replace("+00:00", "Z"),
                event_timestamp_dt=self.now,
                trace_id=self.trace_id,
                trace_id_uuid=UUID(self.trace_id),
                message_id=1,
                channel="demo",
                original_text="Центробанк в Москве сохранил ставку",
                payload={},
                key=self.event_id,
                topic="preprocessed.messages",
                partition=0,
                offset=0,
            )
        )

        topic_producer = FakeProducer()
        topic_service = TopicClustererService.__new__(TopicClustererService)
        topic_service._config = TopicConfig()
        topic_service._pool = self.pool
        topic_service._producer = topic_producer
        topic_service._db = sqlite3.connect(":memory:", check_same_thread=False)
        for statement in SQLITE_INIT_SQL.strip().split(";"):
            statement = statement.strip()
            if statement:
                topic_service._db.execute(statement)
        for statement in SQLITE_SCHEMA_PATCHES:
            try:
                topic_service._db.execute(statement)
            except sqlite3.OperationalError:
                pass
        topic_service._output_validator = TopicSchemaValidator(
            ROOT / "schemas" / "topic_assignment.schema.json"
        )
        topic_service._stop_event = asyncio.Event()
        topic_service._clustering_lock = asyncio.Lock()
        topic_service._health = TopicHealthState()

        async def fake_embedding(self, text: str) -> np.ndarray:  # noqa: ANN001
            test_case.assertTrue(text)
            return np.array([1.0, 0.0], dtype=np.float32)

        topic_service._compute_embedding = MethodType(fake_embedding, topic_service)

        await topic_service._ingest_once(
            TopicContext(
                event_id=self.event_id,
                processing_event_id=f"topic-clusterer:{self.event_id}",
                event_type="preprocessed",
                event_timestamp=self.now.isoformat().replace("+00:00", "Z"),
                event_timestamp_dt=self.now,
                trace_id=self.trace_id,
                trace_id_uuid=UUID(self.trace_id),
                message_id=1,
                channel="demo",
                original_text="центробанк москва ставка",
                payload={},
                key=self.event_id,
                topic="preprocessed.messages",
                partition=0,
                offset=0,
            )
        )

        async with self.pool.acquire() as conn:
            sentiment_count = await conn.fetchval(
                "SELECT count(*) FROM sentiment_results WHERE event_id = $1;",
                self.event_id,
            )
            ner_count = await conn.fetchval(
                "SELECT count(*) FROM ner_results WHERE event_id = $1;",
                self.event_id,
            )
            relation_count = await conn.fetchval(
                "SELECT count(*) FROM entity_relations WHERE channel = 'demo' AND message_id = 1;",
            )
            cluster_count = await conn.fetchval(
                "SELECT count(*) FROM cluster_assignments WHERE event_id = $1;",
                self.event_id,
            )

        self.assertEqual(sentiment_count, 1)
        self.assertEqual(ner_count, 2)
        self.assertEqual(relation_count, 1)
        self.assertEqual(cluster_count, 1)

        self.assertEqual(len(sentiment_producer.events), 1)
        self.assertEqual(sentiment_producer.events[0][0], "sentiment.enriched")
        self.assertEqual(len(ner_producer.events), 1)
        self.assertEqual(ner_producer.events[0][0], "ner.enriched")
        self.assertEqual(len(topic_producer.events), 1)
        self.assertEqual(topic_producer.events[0][0], "topic.assignments")

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analytics_api"))
sys.path.insert(0, str(ROOT / "source_resolver"))
sys.path.insert(0, str(ROOT / "topic_clusterer"))

from analytics_api.config import AppConfig as AnalyticsConfig
from analytics_api.service import AnalyticsApiService
from source_resolver.resolution import ResolvedSource
from source_resolver.service import ClusterMessage, SourceResolverService
from topic_clusterer.service import ClusteringRunBatch, TopicClustererService


@unittest.skipUnless(os.getenv("TEST_DATABASE_DSN"), "TEST_DATABASE_DSN is required")
class FirstSourcePostgresIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.dsn = os.environ["TEST_DATABASE_DSN"]
        self.schema = f"test_first_source_{uuid4().hex[:8]}"
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

    async def asyncTearDown(self) -> None:
        if hasattr(self, "pool"):
            await self.pool.close()
        if hasattr(self, "admin_conn"):
            await self.admin_conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            await self.admin_conn.close()

    async def test_migration_cluster_assignment_source_resolution_and_api_payload(self) -> None:
        source_event_id = "demo:0"
        event_id = "demo:1"
        now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        earlier = datetime(2026, 4, 9, 11, 0, tzinfo=timezone.utc)

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO raw_messages (
                    message_id, channel, text, message_date, views, forwards,
                    event_timestamp, trace_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
                """,
                0,
                "demo",
                "Source message",
                earlier,
                20,
                4,
                earlier,
                uuid4(),
            )
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
                "Original message",
                now,
                10,
                2,
                now,
                uuid4(),
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
                    $1, 1, 'demo', $2, 'Original message', 'Original message',
                    'original message', 'ru', ARRAY['original', 'message'], 1, 2,
                    FALSE, FALSE, FALSE, ARRAY[]::text[], ARRAY[]::text[], ARRAY[]::text[],
                    'hash-1', 12345, ARRAY[]::text[], NULL, 'test', $3, $4, 1.5
                );
                """,
                raw_id,
                event_id,
                now,
                uuid4(),
            )

        clusterer = TopicClustererService.__new__(TopicClustererService)
        clusterer._pool = self.pool
        batch = ClusteringRunBatch(
            run_id="run_test",
            run_timestamp=now,
            algo_version="test",
            window_start=now,
            window_end=now,
            total_messages=1,
            total_clustered=1,
            total_noise=0,
            n_clusters=1,
            config_json={"test": True},
            duration_seconds=0.01,
            assignments=[
                {
                    "event_id": event_id,
                    "channel": "demo",
                    "message_id": 1,
                    "cluster_id": 1,
                    "cluster_probability": 0.98,
                    "bucket_id": "bucket-1",
                    "message_date": now,
                }
            ],
        )
        await clusterer._persist_clustering_run_pg(batch)

        source_service = SourceResolverService.__new__(SourceResolverService)
        message = ClusterMessage(
            event_id=event_id,
            channel="demo",
            message_id=1,
            message_date=now,
            text="Original message",
            normalized_text="original message",
            tokens=["original", "message"],
            normalized_text_hash="hash-1",
            simhash64=12345,
            url_fingerprints=[],
            primary_url_fingerprint=None,
            entities=set(),
            channel_id=1001,
            reply_to_message_id=None,
            forward_from_channel=None,
            forward_from_channel_id=None,
            forward_from_message_id=None,
            forward_origin_type=None,
            public_cluster_id="run_test:1",
        )
        exact = ResolvedSource(
            source_type="exact_forward",
            confidence=1.0,
            source_event_id=source_event_id,
            source_channel="demo",
            source_message_id=0,
            source_message_date=earlier,
            source_snippet="Source message",
            explanation={"summary": "Exact forward metadata"},
            evidence={"forward_from_message_id": 0},
        )
        inferred = ResolvedSource(
            source_type="earliest_in_cluster",
            confidence=0.35,
            source_event_id=source_event_id,
            source_channel="demo",
            source_message_id=0,
            source_message_date=earlier,
            source_snippet="Source message",
            explanation={"summary": "Fallback"},
            evidence={"fallback": "earliest_in_cluster"},
        )

        async with self.pool.acquire() as conn:
            await source_service._upsert_message_resolution(conn, message, "exact", exact)
            await source_service._upsert_cluster_resolution(
                conn,
                "run_test:1",
                "run_test",
                1,
                "exact",
                exact,
            )
            await source_service._upsert_cluster_resolution(
                conn,
                "run_test:1",
                "run_test",
                1,
                "inferred",
                inferred,
            )
            await source_service._upsert_propagation_link(conn, message, exact, inferred)

            api_service = AnalyticsApiService(AnalyticsConfig())
            payload = await api_service._build_first_source_payload(conn, "run_test:1")

            self.assertIsNotNone(payload)
            self.assertEqual(payload["source_status"], "exact")
            self.assertEqual(payload["exact_source"]["source_type"], "exact_forward")
            self.assertEqual(len(payload["propagation_chain"]), 1)

            column_exists = await conn.fetchval(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = $1
                  AND table_name = 'cluster_assignments'
                  AND column_name = 'public_cluster_id';
                """,
                self.schema,
            )
            self.assertEqual(column_exists, 1)

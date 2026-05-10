from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    import asyncpg
except ModuleNotFoundError:  # pragma: no cover - depends on local integration env
    asyncpg = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analytics_api"))

if asyncpg is not None:
    from analytics_api.config import AppConfig  # noqa: E402
    from analytics_api.service import AnalyticsApiService  # noqa: E402


@unittest.skipUnless(
    os.getenv("TEST_DATABASE_DSN") and asyncpg is not None,
    "TEST_DATABASE_DSN and asyncpg are required",
)
class TopicComparisonPgIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.dsn = os.environ["TEST_DATABASE_DSN"]
        self.schema = f"test_topic_compare_{uuid4().hex[:8]}"
        self.admin_conn = await asyncpg.connect(self.dsn)
        try:
            await self.admin_conn.execute(f'CREATE SCHEMA "{self.schema}"')
            await self.admin_conn.execute(f'SET search_path TO "{self.schema}"')
            for migration in ("001_initial_schema.sql", "003_first_source.sql", "011_topic_comparison_cache.sql"):
                await self.admin_conn.execute(
                    (ROOT / "migrations" / migration).read_text(encoding="utf-8")
                )
        except Exception as exc:
            self.skipTest(f"Unable to initialize test schema: {exc}")

        self.pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=1,
            max_size=1,
            server_settings={"search_path": self.schema},
        )
        self.service = AnalyticsApiService.__new__(AnalyticsApiService)
        self.service._config = AppConfig()

    async def asyncTearDown(self) -> None:
        if hasattr(self, "pool"):
            await self.pool.close()
        if hasattr(self, "admin_conn"):
            await self.admin_conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            await self.admin_conn.close()

    async def test_build_topic_comparison_from_postgres_and_cache(self) -> None:
        now = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO cluster_runs_pg (
                    run_id, run_timestamp, algo_version, window_start, window_end,
                    total_messages, total_clustered, total_noise, n_clusters
                )
                VALUES ('run_cmp', $1, 'test', $1, $1 + interval '2 hours', 4, 4, 0, 2);
                """,
                now,
            )
            await _insert_cluster_message(conn, "run_cmp", 0, "rbc", 1, now, "hash-shared", "Central Bank")
            await _insert_cluster_message(conn, "run_cmp", 0, "rbc", 2, now, "hash-a", "Moscow")
            await _insert_cluster_message(conn, "run_cmp", 1, "banksta", 3, now, "hash-shared", "Central Bank")
            await _insert_cluster_message(conn, "run_cmp", 1, "banksta", 4, now, "hash-b", "Moscow")

            result = await self.service._build_topic_comparison(
                conn,
                "run_cmp:0",
                "run_cmp:1",
                now.replace(hour=9),
                now.replace(hour=13),
            )
            cached = await self.service._build_topic_comparison(
                conn,
                "run_cmp:0",
                "run_cmp:1",
                now.replace(hour=9),
                now.replace(hour=13),
            )

        assert result is not None
        assert cached is not None
        self.assertIn(result["classification"], {"related_topics", "possible_subtopic_split", "same_topic"})
        self.assertGreater(result["similarity_score"], 0.45)
        self.assertFalse(result["cached"])
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["cluster_a_id"], "run_cmp:0")


async def _insert_cluster_message(
    conn: asyncpg.Connection,
    run_id: str,
    cluster_id: int,
    channel: str,
    message_id: int,
    message_date: datetime,
    normalized_hash: str,
    entity_text: str,
) -> None:
    event_id = f"{channel}:{message_id}"
    raw_id = await conn.fetchval(
        """
        INSERT INTO raw_messages (
            message_id, channel, text, message_date, event_timestamp, views, forwards
        )
        VALUES ($1, $2, $3, $4, $4, 10, 1)
        RETURNING id;
        """,
        message_id,
        channel,
        f"{entity_text} message",
        message_date,
    )
    preprocessed_id = await conn.fetchval(
        """
        INSERT INTO preprocessed_messages (
            raw_message_id, message_id, channel, event_id, original_text, cleaned_text,
            normalized_text, language, tokens, sentences_count, word_count,
            has_urls, has_mentions, has_hashtags, urls, mentions, hashtags,
            normalized_text_hash, preprocessing_version, event_timestamp, processing_time_ms
        )
        VALUES (
            $1, $2, $3, $4, $5, lower($5), lower($5), 'en', ARRAY[$6], 1, 2,
            FALSE, FALSE, FALSE, ARRAY[]::text[], ARRAY[]::text[], ARRAY[]::text[],
            $7, 'test', $8, 1.0
        )
        RETURNING id;
        """,
        raw_id,
        message_id,
        channel,
        event_id,
        f"{entity_text} message",
        entity_text,
        normalized_hash,
        message_date,
    )
    await conn.execute(
        """
        INSERT INTO sentiment_results (
            preprocessed_message_id, message_id, channel, event_id,
            sentiment_label, sentiment_score, positive_prob, negative_prob, neutral_prob,
            event_timestamp, analyzed_at
        )
        VALUES ($1, $2, $3, $4, 'neutral', 0.8, 0.1, 0.1, 0.8, $5, $5);
        """,
        preprocessed_id,
        message_id,
        channel,
        event_id,
        message_date,
    )
    await conn.execute(
        """
        INSERT INTO ner_results (
            preprocessed_message_id, message_id, channel, event_id,
            entity_text, entity_type, start_pos, end_pos, confidence,
            normalized_text, model_name, model_version, event_timestamp, extracted_at
        )
        VALUES ($1, $2, $3, $4, $5, 'ORG', 0, 4, 0.9, lower($5), 'test', 'test', $6, $6);
        """,
        preprocessed_id,
        message_id,
        channel,
        event_id,
        entity_text,
        message_date,
    )
    await conn.execute(
        """
        INSERT INTO cluster_assignments (
            run_id, cluster_id, event_id, channel, message_id, raw_message_id,
            preprocessed_message_id, cluster_probability, message_date
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, 0.95, $8);
        """,
        run_id,
        cluster_id,
        event_id,
        channel,
        message_id,
        raw_id,
        preprocessed_id,
        message_date,
    )


if __name__ == "__main__":
    unittest.main()

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

from analytics_api.config import AppConfig  # noqa: E402
from analytics_api.service import AnalyticsApiService  # noqa: E402


@unittest.skipUnless(os.getenv("TEST_DATABASE_DSN"), "TEST_DATABASE_DSN is required")
class TopicEvolutionPgIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.dsn = os.environ["TEST_DATABASE_DSN"]
        self.schema = f"test_evolution_{uuid4().hex[:8]}"
        self.admin_conn = await asyncpg.connect(self.dsn)
        await self.admin_conn.execute(f'CREATE SCHEMA "{self.schema}"')
        await self.admin_conn.execute(f'SET search_path TO "{self.schema}"')
        for migration in ("001_initial_schema.sql", "003_first_source.sql", "010_topic_timeline_evolution.sql"):
            await self.admin_conn.execute((ROOT / "migrations" / migration).read_text(encoding="utf-8"))
        self.pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=1,
            max_size=1,
            server_settings={"search_path": self.schema},
        )

    async def asyncTearDown(self) -> None:
        await self.pool.close()
        await self.admin_conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
        await self.admin_conn.close()

    async def test_rebuild_writes_timeline_points_and_events(self) -> None:
        cluster_id = "run_demo:0"
        run_id = "run_demo"
        base = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO cluster_runs_pg (
                    run_id, run_timestamp, algo_version, total_messages, total_clustered, n_clusters
                ) VALUES ($1, $2, 'test', 3, 3, 1);
                """,
                run_id,
                base,
            )
            for idx, channel in enumerate(("a", "a", "b"), start=1):
                raw_id = await conn.fetchval(
                    """
                    INSERT INTO raw_messages (
                        message_id, channel, text, message_date, event_timestamp
                    ) VALUES ($1, $2, $3, $4, $4)
                    RETURNING id;
                    """,
                    idx,
                    channel,
                    f"text {idx}",
                    base.replace(hour=10 + idx - 1),
                )
                event_id = f"{channel}:{idx}"
                preprocessed_id = await conn.fetchval(
                    """
                    INSERT INTO preprocessed_messages (
                        raw_message_id, message_id, channel, event_id, original_text,
                        cleaned_text, event_timestamp
                    ) VALUES ($1, $2, $3, $4, 'text', 'text', $5)
                    RETURNING id;
                    """,
                    raw_id,
                    idx,
                    channel,
                    event_id,
                    base,
                )
                await conn.execute(
                    """
                    INSERT INTO cluster_assignments (
                        run_id, cluster_id, event_id, channel, message_id,
                        raw_message_id, preprocessed_message_id, message_date
                    ) VALUES ($1, 0, $2, $3, $4, $5, $6, $7);
                    """,
                    run_id,
                    event_id,
                    channel,
                    idx,
                    raw_id,
                    preprocessed_id,
                    base.replace(hour=10 + idx - 1),
                )

        service = AnalyticsApiService(AppConfig())
        async with self.pool.acquire() as conn:
            result = await service._rebuild_topic_timeline(
                conn,
                cluster_id,
                base,
                base.replace(hour=13),
                "1h",
            )
            point_count = await conn.fetchval("SELECT count(*) FROM topic_timeline_points;")
            event_count = await conn.fetchval("SELECT count(*) FROM topic_evolution_events;")

        self.assertEqual(result, {"points": 3, "events": 2})
        self.assertEqual(point_count, 3)
        self.assertGreaterEqual(event_count, 2)


if __name__ == "__main__":
    unittest.main()

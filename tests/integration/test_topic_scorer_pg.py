"""Integration tests for topic_scorer against a real PostgreSQL database.

Run with:
    TEST_DATABASE_DSN=postgresql://postgres:postgres@localhost/telegram_news_test \
        python -m pytest tests/integration/test_topic_scorer_pg.py -v

Requires:
    - migrations 001..009 applied to the test DB.
    - asyncpg installed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "topic_scorer"))

from topic_scorer.config import AppConfig, PostgresConfig, ScoringConfig
from topic_scorer.features import compute_per_run_stats, compute_raw_features, normalize_features
from topic_scorer.repository import TopicScorerRepository
from topic_scorer.schemas import ClusterFeatures
from topic_scorer.scoring import score_cluster
from topic_scorer.service import TopicScorerService


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@unittest.skipUnless(os.getenv("TEST_DATABASE_DSN"), "TEST_DATABASE_DSN is required")
class TopicScorerIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Seeds a minimal cluster run and verifies round-trip scoring."""

    async def asyncSetUp(self) -> None:
        self.dsn = os.environ["TEST_DATABASE_DSN"]
        self.schema = f"test_scorer_{uuid4().hex[:8]}"
        self.conn = await asyncpg.connect(self.dsn)
        await self.conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
        await self.conn.execute(f'SET search_path = "{self.schema}", public')

        # Seed: cluster run
        self.run_id = f"test-run-{uuid4().hex[:8]}"
        now = _utc_now()
        await self.conn.execute(
            """
            INSERT INTO cluster_runs_pg
                (run_id, run_timestamp, algo_version, total_messages,
                 total_clustered, total_noise, n_clusters)
            VALUES ($1, $2, 'test-v1', 10, 10, 0, 2)
            """,
            self.run_id,
            now,
        )

        # Seed: raw_messages (minimal, using public schema tables)
        self.event_ids = []
        for i in range(6):
            eid = f"ch_test:msg_{i}"
            self.event_ids.append(eid)
            msg_date = now - timedelta(hours=i)
            await self.conn.execute(
                """
                INSERT INTO raw_messages
                    (event_id, channel, message_id, message_date, raw_text, source)
                VALUES ($1, $2, $3, $4, $5, 'telegram')
                ON CONFLICT DO NOTHING
                """,
                eid,
                "ch_test",
                i,
                msg_date,
                f"test message {i}",
            )

        # Seed: cluster_assignments — cluster 0 gets 4 messages, cluster 1 gets 2
        for i, eid in enumerate(self.event_ids[:4]):
            await self.conn.execute(
                """
                INSERT INTO cluster_assignments
                    (run_id, cluster_id, event_id, channel, message_id, cluster_probability)
                VALUES ($1, 0, $2, 'ch_test', $3, 0.9)
                ON CONFLICT DO NOTHING
                """,
                self.run_id,
                eid,
                i,
            )
        for i, eid in enumerate(self.event_ids[4:]):
            await self.conn.execute(
                """
                INSERT INTO cluster_assignments
                    (run_id, cluster_id, event_id, channel, message_id, cluster_probability)
                VALUES ($1, 1, $2, 'ch_test', $3, 0.8)
                ON CONFLICT DO NOTHING
                """,
                self.run_id,
                eid,
                i + 10,
            )

    async def asyncTearDown(self) -> None:
        # Clean up seeded data (cascade deletes via FK)
        await self.conn.execute(
            "DELETE FROM cluster_runs_pg WHERE run_id = $1", self.run_id
        )
        await self.conn.close()

    async def test_score_run_produces_rows(self) -> None:
        cfg = AppConfig(
            postgres=PostgresConfig(
                host="localhost",
                port=5432,
                database=self.dsn.split("/")[-1],
                user=self.dsn.split("://")[1].split(":")[0],
                password=self.dsn.split(":")[2].split("@")[0],
            )
        )
        svc = TopicScorerService(cfg)
        await svc.run_batch(run_id=self.run_id)

        rows = await self.conn.fetch(
            "SELECT * FROM topic_scores WHERE run_id = $1", self.run_id
        )
        self.assertGreaterEqual(len(rows), 1)

        for row in rows:
            score = row["importance_score"]
            level = row["importance_level"]
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)
            self.assertIn(level, {"low", "medium", "high", "critical"})

            bd = json.loads(row["score_breakdown_json"])
            self.assertIn("components", bd)
            self.assertIn("final_score", bd)

            fj = json.loads(row["features_json"])
            self.assertIn("message_count", fj)

    async def test_idempotent_rescoring(self) -> None:
        """Running batch twice should not raise and produces additional history rows."""
        cfg = AppConfig(
            postgres=PostgresConfig(
                host="localhost",
                port=5432,
                database=self.dsn.split("/")[-1],
                user=self.dsn.split("://")[1].split(":")[0],
                password=self.dsn.split(":")[2].split("@")[0],
            )
        )
        svc = TopicScorerService(cfg)
        await svc.run_batch(run_id=self.run_id)
        count_after_first = await self.conn.fetchval(
            "SELECT COUNT(*) FROM topic_scores WHERE run_id = $1", self.run_id
        )
        await svc.run_batch(run_id=self.run_id)
        count_after_second = await self.conn.fetchval(
            "SELECT COUNT(*) FROM topic_scores WHERE run_id = $1", self.run_id
        )
        # Second run appends more rows (history preserved)
        self.assertGreater(count_after_second, count_after_first)

    async def test_view_returns_latest(self) -> None:
        cfg = AppConfig(
            postgres=PostgresConfig(
                host="localhost",
                port=5432,
                database=self.dsn.split("/")[-1],
                user=self.dsn.split("://")[1].split(":")[0],
                password=self.dsn.split(":")[2].split("@")[0],
            )
        )
        svc = TopicScorerService(cfg)
        await svc.run_batch(run_id=self.run_id)
        await svc.run_batch(run_id=self.run_id)

        cluster_ids = await self.conn.fetch(
            "SELECT DISTINCT public_cluster_id FROM topic_scores WHERE run_id = $1",
            self.run_id,
        )
        view_ids = await self.conn.fetch(
            "SELECT public_cluster_id FROM topic_scores_latest WHERE run_id = $1",
            self.run_id,
        )
        # View must have at most one row per cluster
        self.assertEqual(
            len(set(r["public_cluster_id"] for r in view_ids)),
            len(view_ids),
        )


if __name__ == "__main__":
    unittest.main()

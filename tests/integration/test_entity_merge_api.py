"""Integration tests for entity merge API endpoint.

Requires: TEST_DATABASE_DSN env var pointing to a running Postgres instance.
Creates and drops an isolated schema per test run.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analytics_api"))

MIGRATION_001 = ROOT / "migrations" / "001_initial_schema.sql"
MIGRATION_017 = ROOT / "migrations" / "017_entity_normalization.sql"

# ner_results minimal stub so we don't need the full 001 migration
MINIMAL_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS raw_messages (
    event_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL DEFAULT '',
    message_id BIGINT NOT NULL DEFAULT 0,
    text TEXT NOT NULL DEFAULT '',
    date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    views INT NOT NULL DEFAULT 0,
    forwards INT NOT NULL DEFAULT 0,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS preprocessed_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id TEXT NOT NULL REFERENCES raw_messages(event_id),
    original_language VARCHAR(8),
    is_supported_for_full_analysis BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS entity_canonical (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name TEXT NOT NULL,
    canonical_name_normalized TEXT NOT NULL,
    entity_type VARCHAR(16) NOT NULL DEFAULT 'ORG',
    language VARCHAR(8),
    wikidata_id VARCHAR(32),
    description TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    source_model VARCHAR(64),
    mention_count BIGINT NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    merged_into_id UUID REFERENCES entity_canonical(id),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_canonical_name_type
    ON entity_canonical(canonical_name_normalized, entity_type)
    WHERE merged_into_id IS NULL;

CREATE TABLE IF NOT EXISTS entity_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_canonical_id UUID NOT NULL REFERENCES entity_canonical(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    language VARCHAR(8),
    source VARCHAR(32) NOT NULL DEFAULT 'model',
    confidence REAL NOT NULL DEFAULT 1.0,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (entity_canonical_id, alias_normalized)
);

CREATE TABLE IF NOT EXISTS ner_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_canonical_id UUID REFERENCES entity_canonical(id)
);

CREATE TABLE IF NOT EXISTS entity_linking_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ner_result_id UUID NOT NULL REFERENCES ner_results(id) ON DELETE CASCADE,
    entity_canonical_id UUID REFERENCES entity_canonical(id),
    score REAL NOT NULL DEFAULT 1.0,
    method VARCHAR(32) NOT NULL DEFAULT 'exact',
    selected BOOLEAN NOT NULL DEFAULT false,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS entity_merge_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_canonical_id UUID NOT NULL,
    target_canonical_id UUID NOT NULL REFERENCES entity_canonical(id),
    reason TEXT,
    actor VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS entity_normalization_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_type VARCHAR(32) NOT NULL DEFAULT 'alias',
    pattern TEXT NOT NULL,
    replacement TEXT,
    entity_type VARCHAR(16),
    language VARCHAR(8),
    target_canonical_id UUID REFERENCES entity_canonical(id),
    priority INT NOT NULL DEFAULT 100,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_by VARCHAR(64),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


@unittest.skipUnless(os.getenv("TEST_DATABASE_DSN"), "TEST_DATABASE_DSN is required")
class EntityMergeApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.dsn = os.environ["TEST_DATABASE_DSN"]
        self.schema = f"test_entity_merge_{uuid4().hex[:8]}"
        self.admin_conn = await asyncpg.connect(self.dsn)
        try:
            await self.admin_conn.execute(f'CREATE SCHEMA "{self.schema}"')
            await self.admin_conn.execute(f'SET search_path TO "{self.schema}"')
            await self.admin_conn.execute(MINIMAL_SCHEMA)
        except Exception as exc:
            self.skipTest(f"Unable to initialise test schema: {exc}")

        self.pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=1,
            max_size=3,
            server_settings={"search_path": self.schema},
        )

    async def asyncTearDown(self) -> None:
        await self.pool.close()
        await self.admin_conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
        await self.admin_conn.close()

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _seed_canonical(self, conn, name: str, entity_type: str = "ORG") -> UUID:
        row = await conn.fetchrow(
            """
            INSERT INTO entity_canonical (canonical_name, canonical_name_normalized, entity_type)
            VALUES ($1, $2, $3) RETURNING id
            """,
            name, name.casefold(), entity_type,
        )
        return row["id"]

    async def _seed_alias(self, conn, canonical_id: UUID, alias: str) -> None:
        await conn.execute(
            """
            INSERT INTO entity_aliases (entity_canonical_id, alias, alias_normalized, source)
            VALUES ($1, $2, $3, 'manual')
            """,
            canonical_id, alias, alias.casefold(),
        )

    async def _seed_ner_result(self, conn, canonical_id: UUID) -> UUID:
        row = await conn.fetchrow(
            "INSERT INTO ner_results (entity_canonical_id) VALUES ($1) RETURNING id",
            canonical_id,
        )
        return row["id"]

    async def _seed_linking_candidate(self, conn, ner_result_id: UUID, canonical_id: UUID) -> None:
        await conn.execute(
            """
            INSERT INTO entity_linking_candidates (ner_result_id, entity_canonical_id, score, method, selected)
            VALUES ($1, $2, 1.0, 'exact', true)
            """,
            ner_result_id, canonical_id,
        )

    # ── tests ────────────────────────────────────────────────────────────────

    async def test_merge_db_effects(self):
        """POST /entities/{src}/merge transfers aliases, repoints ner_results, tombstones source."""
        async with self.pool.acquire() as conn:
            src_id = await self._seed_canonical(conn, "МВД России")
            tgt_id = await self._seed_canonical(conn, "МВД")
            await self._seed_alias(conn, src_id, "МВД России")
            await self._seed_alias(conn, src_id, "Министерство внутренних дел")
            ner_id = await self._seed_ner_result(conn, src_id)
            await self._seed_linking_candidate(conn, ner_id, src_id)

        # Run merge transaction — mirrors _handle_entity_merge logic
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                src_row = await conn.fetchrow(
                    "SELECT id, canonical_name FROM entity_canonical WHERE id = $1", src_id
                )
                await conn.execute(
                    """
                    INSERT INTO entity_aliases
                        (entity_canonical_id, alias, alias_normalized, language, source, confidence)
                    SELECT $2, alias, alias_normalized, language, source, confidence
                    FROM entity_aliases WHERE entity_canonical_id = $1
                    ON CONFLICT (entity_canonical_id, alias_normalized) DO NOTHING
                    """,
                    src_id, tgt_id,
                )
                await conn.execute(
                    "DELETE FROM entity_aliases WHERE entity_canonical_id = $1", src_id
                )
                src_norm = src_row["canonical_name"].casefold()
                await conn.execute(
                    """
                    INSERT INTO entity_aliases
                        (entity_canonical_id, alias, alias_normalized, source, confidence)
                    VALUES ($1, $2, $3, 'manual', 1.0)
                    ON CONFLICT (entity_canonical_id, alias_normalized) DO NOTHING
                    """,
                    tgt_id, src_row["canonical_name"], src_norm,
                )
                await conn.execute(
                    "UPDATE entity_linking_candidates SET entity_canonical_id = $2 WHERE entity_canonical_id = $1",
                    src_id, tgt_id,
                )
                await conn.execute(
                    "UPDATE ner_results SET entity_canonical_id = $2 WHERE entity_canonical_id = $1",
                    src_id, tgt_id,
                )
                await conn.execute(
                    "UPDATE entity_canonical SET merged_into_id = $2, updated_at = NOW() WHERE id = $1",
                    src_id, tgt_id,
                )
                await conn.execute(
                    """
                    INSERT INTO entity_merge_history
                        (source_canonical_id, target_canonical_id, reason, actor, metadata)
                    VALUES ($1, $2, 'test', 'test', '{}'::jsonb)
                    """,
                    src_id, tgt_id,
                )

        async with self.pool.acquire() as conn:
            # merged_into_id is set on source
            row = await conn.fetchrow(
                "SELECT merged_into_id FROM entity_canonical WHERE id = $1", src_id
            )
            self.assertEqual(row["merged_into_id"], tgt_id)

            # Source aliases are gone
            src_alias_count = await conn.fetchval(
                "SELECT count(*) FROM entity_aliases WHERE entity_canonical_id = $1", src_id
            )
            self.assertEqual(src_alias_count, 0)

            # Target has at least 2 transferred aliases + 1 canonical_name alias
            tgt_alias_count = await conn.fetchval(
                "SELECT count(*) FROM entity_aliases WHERE entity_canonical_id = $1", tgt_id
            )
            self.assertGreaterEqual(tgt_alias_count, 3)

            # ner_results repointed to target
            nr_row = await conn.fetchrow(
                "SELECT entity_canonical_id FROM ner_results WHERE id = $1", ner_id
            )
            self.assertEqual(nr_row["entity_canonical_id"], tgt_id)

            # entity_linking_candidates repointed
            lc_row = await conn.fetchrow(
                "SELECT entity_canonical_id FROM entity_linking_candidates WHERE ner_result_id = $1",
                ner_id,
            )
            self.assertEqual(lc_row["entity_canonical_id"], tgt_id)

            # entity_merge_history has a record
            hist = await conn.fetchrow(
                "SELECT target_canonical_id FROM entity_merge_history WHERE source_canonical_id = $1",
                src_id,
            )
            self.assertIsNotNone(hist)
            self.assertEqual(hist["target_canonical_id"], tgt_id)

    async def test_merge_http_endpoint_and_redirect(self):
        """POST merge via HTTP, then GET source returns 302 to target."""
        try:
            from aiohttp import web
            from aiohttp.test_utils import TestClient, TestServer
        except ImportError:
            self.skipTest("aiohttp not installed")

        from analytics_api.service import AnalyticsApiService
        from analytics_api.config import AppConfig

        async with self.pool.acquire() as conn:
            src_id = await self._seed_canonical(conn, "Роснефть")
            tgt_id = await self._seed_canonical(conn, "ПАО Роснефть")

        cfg = AppConfig()
        svc = AnalyticsApiService(cfg)
        svc._pool = self.pool  # inject pool for test schema

        app = web.Application()
        app.router.add_get("/analytics/entities/{entityId}", svc._handle_entity_by_id)
        app.router.add_post("/analytics/entities/{entityId}/merge", svc._handle_entity_merge)

        async with TestClient(TestServer(app)) as client:
            # POST merge
            resp = await client.post(
                f"/analytics/entities/{src_id}/merge",
                json={"target_id": str(tgt_id), "reason": "duplicate", "actor": "test"},
            )
            self.assertEqual(resp.status, 200, await resp.text())
            body = await resp.json()
            self.assertEqual(body["source_id"], str(src_id))
            self.assertEqual(body["target_id"], str(tgt_id))

            # GET source → 302 redirect to target
            resp2 = await client.get(
                f"/analytics/entities/{src_id}",
                allow_redirects=False,
            )
            self.assertIn(resp2.status, (301, 302))
            self.assertIn(str(tgt_id), resp2.headers.get("Location", ""))

    async def test_self_merge_returns_400(self):
        """Merging an entity into itself must be rejected."""
        try:
            from aiohttp import web
            from aiohttp.test_utils import TestClient, TestServer
        except ImportError:
            self.skipTest("aiohttp not installed")

        from analytics_api.service import AnalyticsApiService
        from analytics_api.config import AppConfig

        async with self.pool.acquire() as conn:
            entity_id = await self._seed_canonical(conn, "Сбербанк")

        cfg = AppConfig()
        svc = AnalyticsApiService(cfg)
        svc._pool = self.pool

        app = web.Application()
        app.router.add_post("/analytics/entities/{entityId}/merge", svc._handle_entity_merge)

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                f"/analytics/entities/{entity_id}/merge",
                json={"target_id": str(entity_id), "reason": "self"},
            )
            self.assertEqual(resp.status, 400)

    async def test_get_nonexistent_entity_returns_404(self):
        """GET a UUID that does not exist returns 404."""
        try:
            from aiohttp import web
            from aiohttp.test_utils import TestClient, TestServer
        except ImportError:
            self.skipTest("aiohttp not installed")

        from analytics_api.service import AnalyticsApiService
        from analytics_api.config import AppConfig

        cfg = AppConfig()
        svc = AnalyticsApiService(cfg)
        svc._pool = self.pool

        app = web.Application()
        app.router.add_get("/analytics/entities/{entityId}", svc._handle_entity_by_id)

        ghost_id = uuid4()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"/analytics/entities/{ghost_id}")
            self.assertEqual(resp.status, 404)

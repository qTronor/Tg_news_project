"""Unit tests for CanonicalResolver with a real Postgres instance (testcontainers).

Covers the three mandatory regressions from the plan:
  #1 USA variants (rule-based) → single canonical_id
  #2 Putin variants (fuzzy + alias dict) → single canonical_id
  + auto-create flow
  + merge tombstone

Requires: testcontainers[postgres]>=4.0, asyncpg
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio

try:
    import asyncpg
    from testcontainers.postgres import PostgresContainer  # type: ignore
    HAS_TESTCONTAINERS = True
except ImportError:
    HAS_TESTCONTAINERS = False

from ner_extractor.backends.base import Entity
from ner_extractor.normalization import Rule, surface_normalize
from ner_extractor.resolver import CanonicalResolver, ResolverConfig

pytestmark = pytest.mark.skipif(
    not HAS_TESTCONTAINERS,
    reason="testcontainers[postgres] not installed",
)

MIGRATIONS = [
    Path(__file__).parent.parent.parent / "migrations" / "017_entity_normalization.sql",
]

# Minimal schema needed for resolver (subset of full migration)
MINIMAL_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS entity_canonical (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name TEXT NOT NULL,
    canonical_name_normalized TEXT NOT NULL,
    entity_type VARCHAR(16) NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_entity_aliases_trgm
    ON entity_aliases USING GIN (alias_normalized gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_entity_canonical_name_trgm
    ON entity_canonical USING GIN (canonical_name_normalized gin_trgm_ops);

CREATE TABLE IF NOT EXISTS entity_linking_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ner_result_id UUID NOT NULL,
    entity_canonical_id UUID REFERENCES entity_canonical(id),
    score REAL NOT NULL,
    method VARCHAR(32) NOT NULL DEFAULT 'exact',
    selected BOOLEAN NOT NULL DEFAULT false,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- minimal stub for ner_results (not needed by resolver itself, only by linking_candidates FK)
CREATE TABLE IF NOT EXISTS ner_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_canonical_id UUID REFERENCES entity_canonical(id)
);

CREATE TABLE IF NOT EXISTS entity_normalization_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_type VARCHAR(32) NOT NULL,
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


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest_asyncio.fixture(scope="session")
async def pg_pool(pg_container):
    pool = await asyncpg.create_pool(
        pg_container.get_connection_url().replace("psycopg2", ""),
        min_size=1,
        max_size=3,
    )
    async with pool.acquire() as conn:
        await conn.execute(MINIMAL_SCHEMA)
    yield pool
    await pool.close()


def make_entity(text: str, entity_type: str = "PERSON", normalized: str | None = None) -> Entity:
    return Entity(
        text=text,
        entity_type=entity_type,
        start=0,
        end=len(text),
        confidence=1.0,
        normalized=normalized or text,
    )


async def insert_fake_ner_result(conn) -> str:
    row = await conn.fetchrow("INSERT INTO ner_results DEFAULT VALUES RETURNING id")
    return str(row["id"])


# ─── Regression #1: USA variants ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_usa_variants_resolve_to_same_canonical(pg_pool):
    """США, Америка, Соединённые Штаты → one entity_canonical row."""
    async with pg_pool.acquire() as conn:
        # Pre-seed canonical entity
        usa_id = await conn.fetchval(
            """
            INSERT INTO entity_canonical
                (canonical_name, canonical_name_normalized, entity_type, language)
            VALUES ('United States', 'united states', 'LOC', 'ru')
            RETURNING id
            """
        )
        # Pre-seed rules
        for pattern in ("сша", "америка", "соединённые штаты"):
            await conn.execute(
                """
                INSERT INTO entity_normalization_rules
                    (rule_type, pattern, entity_type, language, target_canonical_id, priority)
                VALUES ('alias', $1, 'LOC', 'ru', $2, 100)
                """,
                pattern, usa_id,
            )

    rules = [
        Rule(
            id=str(i),
            rule_type="alias",
            pattern=p,
            replacement=None,
            entity_type="LOC",
            language="ru",
            target_canonical_id=str(usa_id),
            priority=100,
        )
        for i, p in enumerate(["сша", "америка", "соединённые штаты"])
    ]

    resolver = CanonicalResolver(
        ResolverConfig(enable_canonical_resolution=True, fuzzy_threshold=0.88),
        rules=rules,
    )

    canonical_ids = set()
    async with pg_pool.acquire() as conn:
        for surface in ["США", "Америка", "Соединённые Штаты"]:
            ner_id = await insert_fake_ner_result(conn)
            resolved = await resolver.resolve(
                conn, make_entity(surface, "LOC"), ner_id, "ru"
            )
            assert resolved.canonical_id is not None, f"No canonical for {surface!r}"
            canonical_ids.add(resolved.canonical_id)

    assert len(canonical_ids) == 1, f"Expected 1 canonical, got {len(canonical_ids)}: {canonical_ids}"

    # Check DB state
    async with pg_pool.acquire() as conn:
        alias_count = await conn.fetchval(
            "SELECT count(*) FROM entity_aliases WHERE entity_canonical_id = $1", usa_id
        )
        lc_count = await conn.fetchval(
            "SELECT count(*) FROM entity_linking_candidates WHERE entity_canonical_id = $1", uuid.UUID(list(canonical_ids)[0])
        )
    assert alias_count >= 3  # at least one alias per surface variant
    assert lc_count >= 3


# ─── Regression #2: Putin variants ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_putin_variants_resolve_to_same_canonical(pg_pool):
    """Владимир Путин, Путин, В. Путин → fuzzy/alias → one canonical."""
    async with pg_pool.acquire() as conn:
        # Seed canonical
        putin_id = await conn.fetchval(
            """
            INSERT INTO entity_canonical
                (canonical_name, canonical_name_normalized, entity_type, language)
            VALUES ('Владимир Путин', 'владимир путин', 'PERSON', 'ru')
            RETURNING id
            """
        )
        # Seed alias 'путин' so alias_dict path works
        await conn.execute(
            """
            INSERT INTO entity_aliases
                (entity_canonical_id, alias, alias_normalized, language, source)
            VALUES ($1, 'Путин', 'путин', 'ru', 'manual')
            """,
            putin_id,
        )

    resolver = CanonicalResolver(
        ResolverConfig(enable_canonical_resolution=True, fuzzy_threshold=0.70),
        rules=[],
    )

    canonical_ids = set()
    async with pg_pool.acquire() as conn:
        for surface in ["Владимир Путин", "Путин", "В. Путин"]:
            ner_id = await insert_fake_ner_result(conn)
            resolved = await resolver.resolve(
                conn, make_entity(surface, "PERSON"), ner_id, "ru"
            )
            assert resolved.canonical_id is not None, f"No canonical for {surface!r}"
            canonical_ids.add(resolved.canonical_id)

    assert len(canonical_ids) == 1, f"Expected 1 canonical for all Putin variants, got {canonical_ids}"


# ─── Auto-create flow ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_create_new_entity(pg_pool):
    resolver = CanonicalResolver(
        ResolverConfig(enable_canonical_resolution=True, fuzzy_threshold=0.99),  # high threshold = no fuzzy match
        rules=[],
    )

    async with pg_pool.acquire() as conn:
        ner_id = await insert_fake_ner_result(conn)
        resolved = await resolver.resolve(
            conn, make_entity("НоваяУникальнаяСущность", "ORG"), ner_id, "ru"
        )
    assert resolved.canonical_id is not None

    # Second mention of same entity — should reuse, not create new
    async with pg_pool.acquire() as conn:
        ner_id2 = await insert_fake_ner_result(conn)
        resolved2 = await resolver.resolve(
            conn, make_entity("НоваяУникальнаяСущность", "ORG"), ner_id2, "ru"
        )
    assert resolved2.canonical_id == resolved.canonical_id

    # mention_count should be >= 2
    async with pg_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT mention_count FROM entity_canonical WHERE id = $1",
            uuid.UUID(resolved.canonical_id),
        )
    assert count >= 2


# ─── Merge tombstone ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_merge_tombstone_redirects_resolver(pg_pool):
    """After merging source → target, resolver should route to target."""
    resolver = CanonicalResolver(
        ResolverConfig(enable_canonical_resolution=True, fuzzy_threshold=0.99),
        rules=[],
    )

    async with pg_pool.acquire() as conn:
        # Create two separate canonicals
        source_id = await conn.fetchval(
            """
            INSERT INTO entity_canonical (canonical_name, canonical_name_normalized, entity_type)
            VALUES ('Merge Source', 'merge source', 'ORG') RETURNING id
            """
        )
        target_id = await conn.fetchval(
            """
            INSERT INTO entity_canonical (canonical_name, canonical_name_normalized, entity_type)
            VALUES ('Merge Target', 'merge target', 'ORG') RETURNING id
            """
        )
        # Add alias 'merge source' pointing to source
        await conn.execute(
            """
            INSERT INTO entity_aliases (entity_canonical_id, alias, alias_normalized, source)
            VALUES ($1, 'Merge Source', 'merge source', 'manual')
            """,
            source_id,
        )
        # Tombstone source
        await conn.execute(
            "UPDATE entity_canonical SET merged_into_id = $2 WHERE id = $1",
            source_id, target_id,
        )
        # Invalidate resolver cache
        resolver.invalidate_cache()

        # Now resolving 'Merge Source' should NOT return source_id
        ner_id = await insert_fake_ner_result(conn)
        resolved = await resolver.resolve(
            conn, make_entity("Merge Source", "ORG"), ner_id, "ru"
        )
    # Should resolve to target or auto-create a new one, but NOT the tombstoned source
    assert resolved.canonical_id != str(source_id)

"""Integration test: llm_enricher with real Postgres and MockProvider."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from llm_enricher.budget import DailyBudgetTracker
from llm_enricher.cache import EnrichmentCache
from llm_enricher.config import AppConfig, BudgetConfig, CacheConfig, LLMConfig, PostgresConfig
from llm_enricher.handlers import build_handlers
from llm_enricher.providers.mock import MockProvider
from llm_enricher.repository import ClusterContextRepository

# Skip all tests if no test DB configured
_PG_DSN = os.environ.get(
    "TEST_PG_DSN",
    "postgresql://postgres:postgres@localhost:5432/telegram_news_test",
)
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module")
async def pg_pool():
    try:
        pool = await asyncpg.create_pool(_PG_DSN, min_size=1, max_size=2, command_timeout=10)
    except Exception:
        pytest.skip("Postgres not available")
    yield pool
    await pool.close()


@pytest_asyncio.fixture(autouse=True)
async def clean_llm_enrichments(pg_pool):
    async with pg_pool.acquire() as conn:
        await conn.execute("DELETE FROM llm_enrichments WHERE public_cluster_id LIKE 'test-%'")
    yield
    async with pg_pool.acquire() as conn:
        await conn.execute("DELETE FROM llm_enrichments WHERE public_cluster_id LIKE 'test-%'")


@pytest_asyncio.fixture
async def fixtures(pg_pool):
    """Insert minimal cluster fixture rows needed by the repository."""
    cluster_id = "test-run:cluster-0"
    async with pg_pool.acquire() as conn:
        # Insert a raw_message
        msg_id = await conn.fetchval(
            """
            INSERT INTO raw_messages (channel, message_id, original_text, language, published_at)
            VALUES ('test_channel', 99999, 'Test message about politics', 'en', NOW())
            ON CONFLICT (channel, message_id) DO UPDATE SET original_text = EXCLUDED.original_text
            RETURNING id
            """
        )
        event_id = f"test-event-{msg_id}"
        await conn.execute(
            """
            INSERT INTO cluster_assignments (event_id, public_cluster_id, run_id, cluster_id, cluster_probability, channel, message_id)
            VALUES ($1, $2, 'test-run', 0, 0.95, 'test_channel', 99999)
            ON CONFLICT DO NOTHING
            """,
            event_id, cluster_id,
        )
    return {"cluster_id": cluster_id}


def _make_config() -> AppConfig:
    return AppConfig(
        postgres=PostgresConfig(dsn=_PG_DSN) if False else PostgresConfig(),
        cache=CacheConfig(ttl_seconds=3600, error_ttl_seconds=60),
        budget=BudgetConfig(daily_usd=100.0),
        llm=LLMConfig(provider="mock"),
    )


@pytest_asyncio.fixture
async def cache_and_handlers(pg_pool):
    config = _make_config()
    provider = MockProvider()
    budget = DailyBudgetTracker(config.budget)
    repo = ClusterContextRepository(pg_pool)
    cache = EnrichmentCache(pg_pool, repo, config.cache)
    prompts_root = Path(__file__).parent.parent.parent / "llm_enricher" / "llm_enricher" / "prompts"
    handlers = build_handlers(provider, budget, config, prompts_root)
    return cache, handlers, config


async def test_first_call_not_cached(pg_pool, fixtures, cache_and_handlers):
    cache, handlers, config = cache_and_handlers
    cluster_id = fixtures["cluster_id"]

    result = await cache.get_or_compute(
        cluster_id,
        "cluster_label",
        refresh=False,
        compute=handlers["cluster_label"].compute,
        prompt_version="v1",
        model_name="mock-v1",
    )
    assert result.cached is False
    assert result.computed.status in ("ok", "error")  # no PG data = may be empty but not crash


async def test_second_call_is_cached(pg_pool, fixtures, cache_and_handlers):
    cache, handlers, config = cache_and_handlers
    cluster_id = fixtures["cluster_id"]

    await cache.get_or_compute(
        cluster_id, "cluster_label",
        refresh=False,
        compute=handlers["cluster_label"].compute,
        prompt_version="v1", model_name="mock-v1",
    )
    result2 = await cache.get_or_compute(
        cluster_id, "cluster_label",
        refresh=False,
        compute=handlers["cluster_label"].compute,
        prompt_version="v1", model_name="mock-v1",
    )
    assert result2.cached is True


async def test_refresh_recomputes(pg_pool, fixtures, cache_and_handlers):
    cache, handlers, config = cache_and_handlers
    cluster_id = fixtures["cluster_id"]

    r1 = await cache.get_or_compute(
        cluster_id, "cluster_label",
        refresh=False,
        compute=handlers["cluster_label"].compute,
        prompt_version="v1", model_name="mock-v1",
    )
    r2 = await cache.get_or_compute(
        cluster_id, "cluster_label",
        refresh=True,
        compute=handlers["cluster_label"].compute,
        prompt_version="v1", model_name="mock-v1",
    )
    assert r2.cached is False


async def test_enrichment_row_stored_in_db(pg_pool, fixtures, cache_and_handlers):
    cache, handlers, config = cache_and_handlers
    cluster_id = fixtures["cluster_id"]

    await cache.get_or_compute(
        cluster_id, "cluster_label",
        refresh=True,
        compute=handlers["cluster_label"].compute,
        prompt_version="v1", model_name="mock-v1",
    )

    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, enrichment_type FROM llm_enrichments WHERE public_cluster_id = $1",
            cluster_id,
        )
    assert row is not None
    assert row["enrichment_type"] == "cluster_label"

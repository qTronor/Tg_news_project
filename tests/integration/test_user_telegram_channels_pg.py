from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "auth_service"))
sys.path.insert(0, str(ROOT / "rbc_telegram_collector"))

from app.routes.sources import add_telegram_channel
from app.schemas import TelegramChannelCreateRequest
from collector.backfill import process_pending_validations
from collector.config import AnalyticsDbConfig, AppConfig
from collector.registry import RegistryStore
from collector.sources.telegram import ValidatedTelegramChannel


def _to_async_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql+asyncpg://", 1)
    return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)


class _FakeValidationSource:
    def __init__(self, metadata: ValidatedTelegramChannel) -> None:
        self._metadata = metadata

    async def validate_channel(self, _channel_ref: str) -> ValidatedTelegramChannel:
        return self._metadata


@unittest.skipUnless(os.getenv("TEST_DATABASE_DSN"), "TEST_DATABASE_DSN is required")
class UserTelegramChannelsIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.dsn = os.environ["TEST_DATABASE_DSN"]
        self.async_dsn = _to_async_dsn(self.dsn)
        self.schema = f"test_user_sources_{uuid4().hex[:8]}"
        self.admin_conn = await asyncpg.connect(self.dsn)
        await self.admin_conn.execute(f'CREATE SCHEMA "{self.schema}"')
        await self.admin_conn.execute(f'SET search_path TO "{self.schema}"')
        await self.admin_conn.execute(
            (ROOT / "migrations" / "001_initial_schema.sql").read_text(encoding="utf-8")
        )
        await self.admin_conn.execute(
            (ROOT / "migrations" / "003_first_source.sql").read_text(encoding="utf-8")
        )
        await self.admin_conn.execute(
            (ROOT / "migrations" / "004_user_telegram_channels.sql").read_text(encoding="utf-8")
        )

        self.pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=1,
            max_size=1,
            server_settings={"search_path": self.schema},
        )

        self.engine = create_async_engine(self.async_dsn, future=True)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        parsed = urlparse(self.dsn.replace("postgres://", "postgresql://", 1))
        self.registry_cfg = AnalyticsDbConfig(
            enabled=True,
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 5432,
            database=parsed.path.lstrip("/"),
            user=parsed.username or "postgres",
            password=parsed.password or "",
            schema=self.schema,
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        await self.pool.close()
        await self.admin_conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
        await self.admin_conn.close()

    async def _session(self) -> AsyncSession:
        session = self.session_factory()
        await session.execute(text(f'SET search_path TO "{self.schema}"'))
        return session

    async def test_source_add_inserts_registry_row(self) -> None:
        session = await self._session()
        user = SimpleNamespace(id=uuid4())
        try:
            response = await add_telegram_channel(
                TelegramChannelCreateRequest(
                    channel="https://t.me/NewPublicFeed",
                    start_date=date(2026, 4, 14),
                ),
                user=user,
                analytics_db=session,
            )
            await session.commit()
        finally:
            await session.close()

        self.assertEqual(response.channel_name, "NewPublicFeed")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT name, status, validation_status, added_by_user_id
                FROM channels
                WHERE lower(name) = lower($1);
                """,
                "NewPublicFeed",
            )
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "pending_validation")
        self.assertEqual(row["validation_status"], "pending")
        self.assertEqual(str(row["added_by_user_id"]), str(user.id))

    async def test_duplicate_detection_against_raw_messages(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO raw_messages (
                    message_id,
                    channel,
                    text,
                    message_date,
                    event_timestamp,
                    trace_id
                )
                VALUES ($1, $2, $3, $4, $5, $6);
                """,
                1,
                "Cbpub",
                "legacy",
                datetime(2026, 4, 13, 9, 0, tzinfo=timezone.utc),
                datetime(2026, 4, 13, 9, 0, tzinfo=timezone.utc),
                uuid4(),
            )

        session = await self._session()
        user = SimpleNamespace(id=uuid4())
        try:
            with self.assertRaises(HTTPException) as ctx:
                await add_telegram_channel(
                    TelegramChannelCreateRequest(
                        channel="cbpub",
                        start_date=date(2026, 4, 14),
                    ),
                    user=user,
                    analytics_db=session,
                )
        finally:
            await session.close()

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["error"], "duplicate")

    async def test_validation_creates_jobs_and_job_completion_updates_progress(self) -> None:
        channel_id = uuid4()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO channels (
                    id,
                    name,
                    source_type,
                    input_value,
                    telegram_url,
                    added_at,
                    requested_start_date,
                    historical_limit_date,
                    status,
                    validation_status,
                    live_enabled,
                    backfill_total_days,
                    backfill_completed_days,
                    backfill_failed_days
                )
                VALUES (
                    $1,
                    'banksta',
                    'telegram',
                    '@banksta',
                    'https://t.me/banksta',
                    NOW(),
                    DATE '2026-04-10',
                    DATE '2026-01-01',
                    'pending_validation',
                    'pending',
                    FALSE,
                    0,
                    0,
                    0
                );
                """,
                channel_id,
            )

        registry = RegistryStore(self.registry_cfg)
        await registry.start()
        try:
            await process_pending_validations(
                source=_FakeValidationSource(
                    ValidatedTelegramChannel(
                        name="banksta",
                        url="https://t.me/banksta",
                        channel_id=2001,
                        title="Banksta",
                        description="Finance",
                        subscriber_count=4200,
                    )
                ),
                registry=registry,
                cfg=AppConfig(channels=[]),
                today=date(2026, 4, 14),
            )

            async with self.pool.acquire() as conn:
                channel_row = await conn.fetchrow(
                    """
                    SELECT validation_status, live_enabled, backfill_total_days
                    FROM channels
                    WHERE id = $1;
                    """,
                    channel_id,
                )
                job_rows = await conn.fetch(
                    """
                    SELECT id, job_date, priority, status
                    FROM channel_backfill_jobs
                    WHERE channel_id = $1
                    ORDER BY priority DESC, job_date DESC;
                    """,
                    channel_id,
                )

            self.assertEqual(channel_row["validation_status"], "validated")
            self.assertTrue(channel_row["live_enabled"])
            self.assertEqual(channel_row["backfill_total_days"], 2)
            self.assertEqual(
                [row["job_date"] for row in job_rows],
                [date(2026, 4, 11), date(2026, 4, 10)],
            )

            await registry.mark_backfill_job_completed(
                job_id=job_rows[0]["id"],
                channel_id=channel_id,
                job_date=date(2026, 4, 11),
                messages_published=15,
            )
            await registry.mark_backfill_job_completed(
                job_id=await self.pool.fetchval(
                    """
                    SELECT id
                    FROM channel_backfill_jobs
                    WHERE channel_id = $1 AND job_date = $2;
                    """,
                    channel_id,
                    date(2026, 4, 10),
                ),
                channel_id=channel_id,
                job_date=date(2026, 4, 10),
                messages_published=20,
            )

            async with self.pool.acquire() as conn:
                progress_row = await conn.fetchrow(
                    """
                    SELECT status, backfill_completed_days, backfill_failed_days, backfill_last_completed_date
                    FROM channels
                    WHERE id = $1;
                    """,
                    channel_id,
                )

            self.assertEqual(progress_row["status"], "ready")
            self.assertEqual(progress_row["backfill_completed_days"], 2)
            self.assertEqual(progress_row["backfill_failed_days"], 0)
            self.assertEqual(progress_row["backfill_last_completed_date"], date(2026, 4, 11))
        finally:
            await registry.stop()

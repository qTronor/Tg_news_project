from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional
from uuid import UUID

import asyncpg

from collector.config import AnalyticsDbConfig


@dataclass(frozen=True)
class RegistryChannel:
    id: UUID
    name: str
    input_value: Optional[str]
    telegram_url: Optional[str]
    telegram_channel_id: Optional[int]
    title: Optional[str]
    description: Optional[str]
    subscriber_count: Optional[int]
    requested_start_date: Optional[date]
    historical_limit_date: date
    status: str
    validation_status: str
    validation_error: Optional[str]
    live_enabled: bool
    added_by_user_id: Optional[UUID]
    added_at: datetime
    backfill_total_days: int
    backfill_completed_days: int
    backfill_failed_days: int
    last_live_collected_at: Optional[datetime]

    @property
    def channel_ref(self) -> str:
        return self.telegram_url or self.name


@dataclass(frozen=True)
class BackfillJob:
    id: UUID
    channel_id: UUID
    channel_name: str
    channel_ref: str
    job_date: date
    priority: int
    attempt_count: int


class RegistryStore:
    def __init__(self, config: AnalyticsDbConfig) -> None:
        self._config = config
        self._pool: asyncpg.Pool | None = None

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    async def start(self) -> None:
        if not self.enabled or self._pool is not None:
            return
        pool_kwargs = {
            "dsn": self._config.dsn(),
            "min_size": self._config.min_size,
            "max_size": self._config.max_size,
            "command_timeout": self._config.command_timeout,
        }
        if self._config.schema:
            pool_kwargs["server_settings"] = {"search_path": self._config.schema}
        self._pool = await asyncpg.create_pool(
            **pool_kwargs,
        )

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def fetch_pending_validation_channels(self, limit: int = 50) -> list[RegistryChannel]:
        if not self.enabled:
            return []
        rows = await self._fetch(
            """
            SELECT
                id,
                name,
                input_value,
                telegram_url,
                telegram_channel_id,
                title,
                description,
                subscriber_count,
                requested_start_date,
                historical_limit_date,
                status,
                validation_status,
                validation_error,
                live_enabled,
                added_by_user_id,
                added_at,
                backfill_total_days,
                backfill_completed_days,
                backfill_failed_days,
                last_live_collected_at
            FROM channels
            WHERE source_type = 'telegram'
              AND validation_status = 'pending'
            ORDER BY added_at ASC, name ASC
            LIMIT $1;
            """,
            limit,
        )
        return [self._to_channel(row) for row in rows]

    async def fetch_live_channels(self) -> list[RegistryChannel]:
        if not self.enabled:
            return []
        rows = await self._fetch(
            """
            SELECT
                id,
                name,
                input_value,
                telegram_url,
                telegram_channel_id,
                title,
                description,
                subscriber_count,
                requested_start_date,
                historical_limit_date,
                status,
                validation_status,
                validation_error,
                live_enabled,
                added_by_user_id,
                added_at,
                backfill_total_days,
                backfill_completed_days,
                backfill_failed_days,
                last_live_collected_at
            FROM channels
            WHERE source_type = 'telegram'
              AND validation_status = 'validated'
              AND live_enabled = TRUE
            ORDER BY added_at ASC, name ASC;
            """
        )
        return [self._to_channel(row) for row in rows]

    async def mark_validation_failed(self, channel_id: UUID, reason: str) -> None:
        if not self.enabled:
            return
        await self._execute(
            """
            UPDATE channels
            SET
                status = 'validation_failed',
                validation_status = 'failed',
                validation_error = $2,
                live_enabled = FALSE
            WHERE id = $1;
            """,
            channel_id,
            reason,
        )

    async def mark_validation_success(
        self,
        *,
        channel_id: UUID,
        canonical_name: str,
        telegram_url: str,
        telegram_channel_id: int,
        title: str | None,
        description: str | None,
        subscriber_count: int | None,
        requested_start_date: date,
        historical_limit_date: date,
        total_backfill_days: int,
    ) -> None:
        if not self.enabled:
            return
        await self._execute(
            """
            UPDATE channels
            SET
                name = $2,
                telegram_url = $3,
                telegram_channel_id = $4,
                title = COALESCE($5, title),
                description = COALESCE($6, description),
                subscriber_count = COALESCE($7, subscriber_count),
                requested_start_date = $8,
                historical_limit_date = $9,
                status = 'live_enabled',
                validation_status = 'validated',
                validation_error = NULL,
                live_enabled = TRUE,
                backfill_total_days = $10,
                backfill_completed_days = 0,
                backfill_failed_days = 0,
                backfill_last_completed_date = NULL
            WHERE id = $1;
            """,
            channel_id,
            canonical_name,
            telegram_url,
            telegram_channel_id,
            title,
            description,
            subscriber_count,
            requested_start_date,
            historical_limit_date,
            total_backfill_days,
        )
        if total_backfill_days == 0:
            await self.update_channel_progress(channel_id)

    async def create_backfill_jobs(self, channel_id: UUID, job_dates: Iterable[date]) -> int:
        if not self.enabled:
            return 0
        dates = list(job_dates)
        if not dates:
            return 0
        records = [
            (channel_id, job_date, len(dates) - index)
            for index, job_date in enumerate(dates)
        ]
        await self._executemany(
            """
            INSERT INTO channel_backfill_jobs (
                channel_id,
                job_date,
                priority,
                status,
                attempt_count,
                messages_published
            )
            VALUES ($1, $2, $3, 'pending', 0, 0)
            ON CONFLICT (channel_id, job_date) DO NOTHING;
            """,
            records,
        )
        return len(records)

    async def lease_backfill_jobs(
        self,
        *,
        limit: int,
        retry_backoff_seconds: int,
    ) -> list[BackfillJob]:
        if not self.enabled or limit <= 0:
            return []
        rows = await self._fetch(
            """
            WITH candidates AS (
                SELECT DISTINCT ON (j.channel_id)
                    j.id,
                    j.channel_id,
                    j.job_date,
                    j.priority,
                    j.attempt_count,
                    c.name AS channel_name,
                    COALESCE(c.telegram_url, c.name) AS channel_ref
                FROM channel_backfill_jobs j
                JOIN channels c
                    ON c.id = j.channel_id
                WHERE c.source_type = 'telegram'
                  AND c.validation_status = 'validated'
                  AND c.live_enabled = TRUE
                  AND j.status IN ('pending', 'retrying')
                  AND NOT EXISTS (
                      SELECT 1
                      FROM channel_backfill_jobs running
                      WHERE running.channel_id = j.channel_id
                        AND running.status = 'running'
                  )
                  AND (
                      j.status = 'pending'
                      OR j.updated_at <= NOW() - make_interval(secs => $1::int)
                  )
                ORDER BY j.channel_id, j.priority DESC, j.job_date DESC
            )
            SELECT *
            FROM candidates
            ORDER BY priority DESC, job_date DESC
            LIMIT $2;
            """,
            retry_backoff_seconds,
            limit,
        )
        return [
            BackfillJob(
                id=row["id"],
                channel_id=row["channel_id"],
                channel_name=row["channel_name"],
                channel_ref=row["channel_ref"],
                job_date=row["job_date"],
                priority=row["priority"],
                attempt_count=row["attempt_count"],
            )
            for row in rows
        ]

    async def mark_backfill_job_running(self, *, job_id: UUID, channel_id: UUID) -> None:
        if not self.enabled:
            return
        await self._execute(
            """
            UPDATE channel_backfill_jobs
            SET
                status = 'running',
                attempt_count = attempt_count + 1,
                started_at = NOW(),
                finished_at = NULL,
                last_error = NULL
            WHERE id = $1;
            """,
            job_id,
        )
        await self.update_channel_progress(channel_id)

    async def mark_backfill_job_completed(
        self,
        *,
        job_id: UUID,
        channel_id: UUID,
        job_date: date,
        messages_published: int,
    ) -> None:
        if not self.enabled:
            return
        await self._execute(
            """
            UPDATE channel_backfill_jobs
            SET
                status = 'completed',
                finished_at = NOW(),
                messages_published = $2,
                last_error = NULL
            WHERE id = $1;
            """,
            job_id,
            messages_published,
        )
        await self._execute(
            """
            UPDATE channels
            SET backfill_last_completed_date = GREATEST(
                COALESCE(backfill_last_completed_date, $2),
                $2
            )
            WHERE id = $1;
            """,
            channel_id,
            job_date,
        )
        await self.update_channel_progress(channel_id)

    async def mark_backfill_job_retrying(
        self,
        *,
        job_id: UUID,
        channel_id: UUID,
        error: str,
    ) -> None:
        if not self.enabled:
            return
        await self._execute(
            """
            UPDATE channel_backfill_jobs
            SET
                status = 'retrying',
                finished_at = NOW(),
                last_error = $2
            WHERE id = $1;
            """,
            job_id,
            error,
        )
        await self.update_channel_progress(channel_id)

    async def mark_backfill_job_failed(
        self,
        *,
        job_id: UUID,
        channel_id: UUID,
        error: str,
    ) -> None:
        if not self.enabled:
            return
        await self._execute(
            """
            UPDATE channel_backfill_jobs
            SET
                status = 'failed',
                finished_at = NOW(),
                last_error = $2
            WHERE id = $1;
            """,
            job_id,
            error,
        )
        await self.update_channel_progress(channel_id)

    async def update_channel_progress(self, channel_id: UUID) -> None:
        if not self.enabled:
            return
        await self._execute(
            """
            WITH stats AS (
                SELECT
                    channel_id,
                    count(*) FILTER (WHERE status = 'completed') AS completed_days,
                    count(*) FILTER (WHERE status = 'failed') AS failed_days,
                    count(*) FILTER (WHERE status = 'pending') AS pending_days,
                    count(*) FILTER (WHERE status = 'running') AS running_days,
                    count(*) FILTER (WHERE status = 'retrying') AS retrying_days
                FROM channel_backfill_jobs
                WHERE channel_id = $1
                GROUP BY channel_id
            )
            UPDATE channels c
            SET
                backfill_completed_days = COALESCE(stats.completed_days, 0),
                backfill_failed_days = COALESCE(stats.failed_days, 0),
                status = CASE
                    WHEN c.validation_status = 'failed' THEN 'validation_failed'
                    WHEN c.live_enabled = FALSE THEN 'pending_validation'
                    WHEN COALESCE(stats.pending_days, 0) + COALESCE(stats.running_days, 0) + COALESCE(stats.retrying_days, 0) > 0
                        THEN 'backfilling'
                    WHEN c.backfill_total_days = 0 AND c.last_live_collected_at IS NOT NULL
                        THEN 'ready'
                    WHEN c.backfill_total_days > 0
                         AND COALESCE(stats.completed_days, 0) + COALESCE(stats.failed_days, 0) >= c.backfill_total_days
                        THEN 'ready'
                    ELSE 'live_enabled'
                END
            FROM stats
            WHERE c.id = $1
               OR (c.id = $1 AND stats.channel_id IS NULL);
            """,
            channel_id,
        )
        await self._execute(
            """
            UPDATE channels
            SET
                backfill_completed_days = 0,
                backfill_failed_days = 0,
                status = CASE
                    WHEN validation_status = 'failed' THEN 'validation_failed'
                    WHEN live_enabled = FALSE THEN 'pending_validation'
                    WHEN backfill_total_days = 0 AND last_live_collected_at IS NOT NULL THEN 'ready'
                    ELSE 'live_enabled'
                END
            WHERE id = $1
              AND NOT EXISTS (
                  SELECT 1
                  FROM channel_backfill_jobs
                  WHERE channel_id = $1
              );
            """,
            channel_id,
        )

    async def mark_live_collected(self, channel_name: str, collected_at: datetime) -> None:
        if not self.enabled:
            return
        await self._execute(
            """
            UPDATE channels
            SET
                last_live_collected_at = $2,
                status = CASE
                    WHEN backfill_total_days = 0 AND validation_status = 'validated' THEN 'ready'
                    ELSE status
                END
            WHERE lower(name) = lower($1);
            """,
            channel_name,
            collected_at,
        )

    async def channel_has_raw_data(self, channel_name: str) -> bool:
        if not self.enabled:
            return False
        result = await self._fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM raw_messages
                WHERE lower(channel) = lower($1)
            );
            """,
            channel_name,
        )
        return bool(result)

    async def _fetch(self, query: str, *args):
        pool = self._require_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def _fetchval(self, query: str, *args):
        pool = self._require_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def _execute(self, query: str, *args) -> str:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def _executemany(self, query: str, args: Iterable[tuple]) -> None:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            await conn.executemany(query, list(args))

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("RegistryStore is not started")
        return self._pool

    def _to_channel(self, row: asyncpg.Record) -> RegistryChannel:
        return RegistryChannel(
            id=row["id"],
            name=row["name"],
            input_value=row["input_value"],
            telegram_url=row["telegram_url"],
            telegram_channel_id=row["telegram_channel_id"],
            title=row["title"],
            description=row["description"],
            subscriber_count=row["subscriber_count"],
            requested_start_date=row["requested_start_date"],
            historical_limit_date=row["historical_limit_date"],
            status=row["status"],
            validation_status=row["validation_status"],
            validation_error=row["validation_error"],
            live_enabled=row["live_enabled"],
            added_by_user_id=row["added_by_user_id"],
            added_at=row["added_at"],
            backfill_total_days=int(row["backfill_total_days"] or 0),
            backfill_completed_days=int(row["backfill_completed_days"] or 0),
            backfill_failed_days=int(row["backfill_failed_days"] or 0),
            last_live_collected_at=row["last_live_collected_at"],
        )

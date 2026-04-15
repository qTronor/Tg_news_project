from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import asyncpg

from collector.config import AppConfig
from collector.registry import BackfillJob, RegistryChannel, RegistryStore
from collector.sinks.kafka_raw import KafkaRawSink
from collector.sources.telegram import (
    TelegramChannelError,
    TelegramChannelSource,
    ValidatedTelegramChannel,
)

HISTORICAL_LOWER_BOUND = date(2026, 1, 1)

logger = logging.getLogger("collector.backfill")


def plan_backfill_dates(
    *,
    requested_start_date: date,
    today: date,
    lookback_days: int,
    lower_bound: date = HISTORICAL_LOWER_BOUND,
) -> list[date]:
    effective_start = max(requested_start_date, lower_bound)
    live_window_start = today - timedelta(days=lookback_days - 1)
    newest_backfill_day = live_window_start - timedelta(days=1)
    if effective_start > newest_backfill_day:
        return []

    days: list[date] = []
    current = newest_backfill_day
    while current >= effective_start:
        days.append(current)
        current -= timedelta(days=1)
    return days


async def process_pending_validations(
    *,
    source: TelegramChannelSource,
    registry: RegistryStore,
    cfg: AppConfig,
    today: date | None = None,
) -> int:
    if not registry.enabled:
        return 0

    current_day = today or datetime.now(timezone.utc).date()
    channels = await registry.fetch_pending_validation_channels()
    processed = 0
    for channel in channels:
        processed += 1
        await _validate_channel(
            source=source,
            registry=registry,
            channel=channel,
            cfg=cfg,
            today=current_day,
        )
    return processed


async def run_backfill_cycle(
    *,
    source: TelegramChannelSource,
    registry: RegistryStore,
    kafka_sink: KafkaRawSink | None,
    cfg: AppConfig,
) -> int:
    if not registry.enabled or not cfg.backfill.enabled:
        return 0

    jobs = await registry.lease_backfill_jobs(
        limit=min(cfg.backfill.global_concurrency, cfg.backfill.max_jobs_per_cycle),
        retry_backoff_seconds=cfg.backfill.retry_backoff_seconds,
    )
    completed = 0
    for job in jobs:
        await _run_single_backfill_job(
            source=source,
            registry=registry,
            kafka_sink=kafka_sink,
            cfg=cfg,
            job=job,
        )
        completed += 1
    return completed


async def _validate_channel(
    *,
    source: TelegramChannelSource,
    registry: RegistryStore,
    channel: RegistryChannel,
    cfg: AppConfig,
    today: date,
) -> None:
    try:
        metadata = await source.validate_channel(channel.channel_ref)
        requested_start_date = min(
            max(channel.requested_start_date or HISTORICAL_LOWER_BOUND, HISTORICAL_LOWER_BOUND),
            today,
        )
        job_dates = plan_backfill_dates(
            requested_start_date=requested_start_date,
            today=today,
            lookback_days=cfg.collection.lookback_days,
        )
        await registry.mark_validation_success(
            channel_id=channel.id,
            canonical_name=metadata.name,
            telegram_url=metadata.url,
            telegram_channel_id=metadata.channel_id,
            title=metadata.title,
            description=metadata.description,
            subscriber_count=metadata.subscriber_count,
            requested_start_date=requested_start_date,
            historical_limit_date=HISTORICAL_LOWER_BOUND,
            total_backfill_days=len(job_dates),
        )
        if job_dates:
            await registry.create_backfill_jobs(channel.id, job_dates)
        logger.info(
            "validation_success channel=%s channel_id=%s requested_start_date=%s backfill_days=%s",
            metadata.name,
            channel.id,
            requested_start_date,
            len(job_dates),
        )
    except TelegramChannelError as exc:
        await registry.mark_validation_failed(channel.id, exc.message)
        logger.warning(
            "validation_failed channel=%s channel_id=%s reason=%s detail=%s",
            channel.name,
            channel.id,
            exc.reason,
            exc.message,
        )
    except asyncpg.UniqueViolationError as exc:
        await registry.mark_validation_failed(channel.id, "Validated channel already exists.")
        logger.warning(
            "validation_failed channel=%s channel_id=%s reason=duplicate detail=%s",
            channel.name,
            channel.id,
            str(exc),
        )


async def _run_single_backfill_job(
    *,
    source: TelegramChannelSource,
    registry: RegistryStore,
    kafka_sink: KafkaRawSink | None,
    cfg: AppConfig,
    job: BackfillJob,
) -> None:
    await registry.mark_backfill_job_running(job_id=job.id, channel_id=job.channel_id)
    logger.info(
        "backfill_job_running channel=%s channel_id=%s job_date=%s attempt=%s",
        job.channel_name,
        job.channel_id,
        job.job_date,
        job.attempt_count + 1,
    )

    had_raw_data_before = await registry.channel_has_raw_data(job.channel_name)

    try:
        items = [
            item
            async for item in source.iter_messages_for_day(
                job.channel_ref,
                day=job.job_date,
            )
        ]
        published = 0
        if kafka_sink is not None and items:
            published = await kafka_sink.publish(items)
        await registry.mark_backfill_job_completed(
            job_id=job.id,
            channel_id=job.channel_id,
            job_date=job.job_date,
            messages_published=published,
        )
        logger.info(
            "backfill_job_completed channel=%s channel_id=%s job_date=%s messages_published=%s",
            job.channel_name,
            job.channel_id,
            job.job_date,
            published,
        )
        if not had_raw_data_before and published > 0:
            logger.info(
                "first_data_available_emitted channel=%s channel_id=%s job_date=%s emitted_at=%s",
                job.channel_name,
                job.channel_id,
                job.job_date,
                datetime.now(timezone.utc).isoformat(),
            )
    except TelegramChannelError as exc:
        await _handle_backfill_error(
            registry=registry,
            cfg=cfg,
            job=job,
            error=exc,
        )
    except Exception as exc:
        await _handle_backfill_error(
            registry=registry,
            cfg=cfg,
            job=job,
            error=TelegramChannelError(
                reason="inaccessible",
                message=str(exc),
                permanent=False,
            ),
        )


async def _handle_backfill_error(
    *,
    registry: RegistryStore,
    cfg: AppConfig,
    job: BackfillJob,
    error: TelegramChannelError,
) -> None:
    logger.warning(
        "backfill_job_error channel=%s channel_id=%s job_date=%s reason=%s detail=%s",
        job.channel_name,
        job.channel_id,
        job.job_date,
        error.reason,
        error.message,
    )

    if error.permanent and error.reason in {"not_found", "private", "inaccessible"}:
        await registry.mark_backfill_job_failed(
            job_id=job.id,
            channel_id=job.channel_id,
            error=error.message,
        )
        await registry.mark_validation_failed(job.channel_id, error.message)
        return

    attempt_number = job.attempt_count + 1
    if attempt_number >= cfg.backfill.max_attempts:
        await registry.mark_backfill_job_failed(
            job_id=job.id,
            channel_id=job.channel_id,
            error=error.message,
        )
        return

    await registry.mark_backfill_job_retrying(
        job_id=job.id,
        channel_id=job.channel_id,
        error=error.message,
    )
    if error.reason == "flood_wait" and error.retry_after_seconds:
        sleep_seconds = min(error.retry_after_seconds, cfg.backfill.flood_sleep_cap_seconds)
        await asyncio.sleep(sleep_seconds)

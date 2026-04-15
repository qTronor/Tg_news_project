from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics_db import get_analytics_db
from ..dependencies import get_current_user
from ..models import User
from ..schemas import (
    ApiErrorResponse,
    TelegramChannelCreateRequest,
    TelegramChannelProgress,
    TelegramChannelStatus,
)
from ..source_registry import (
    HISTORICAL_LOWER_BOUND,
    SourceRegistryError,
    build_feed_path,
    derive_channel_status,
    normalize_requested_start_date,
    normalize_telegram_channel_input,
)

router = APIRouter(prefix="/sources/telegram", tags=["sources"])
logger = logging.getLogger("auth_service.sources")

CHANNEL_SELECT_SQL = """
WITH job_stats AS (
    SELECT
        channel_id,
        count(*) FILTER (WHERE status = 'pending') AS backfill_pending_days,
        count(*) FILTER (WHERE status = 'running') AS backfill_running_days,
        count(*) FILTER (WHERE status = 'retrying') AS backfill_retrying_days,
        COALESCE(sum(messages_published), 0) AS backfill_messages_published
    FROM channel_backfill_jobs
    GROUP BY channel_id
)
SELECT
    c.id,
    c.name,
    c.input_value,
    c.telegram_url,
    c.telegram_channel_id,
    c.requested_start_date,
    c.historical_limit_date,
    c.status AS registry_status,
    c.validation_status,
    c.validation_error,
    c.live_enabled,
    c.backfill_total_days,
    c.backfill_completed_days,
    c.backfill_failed_days,
    c.backfill_last_completed_date,
    c.last_live_collected_at,
    c.added_at,
    c.added_by_user_id,
    COALESCE(js.backfill_pending_days, 0) AS backfill_pending_days,
    COALESCE(js.backfill_running_days, 0) AS backfill_running_days,
    COALESCE(js.backfill_retrying_days, 0) AS backfill_retrying_days,
    COALESCE(js.backfill_messages_published, 0) AS backfill_messages_published,
    COALESCE(raw_stats.raw_message_count, 0) AS raw_message_count,
    first_data.first_message_at,
    first_data.first_message_event_id
FROM channels c
LEFT JOIN job_stats js
    ON js.channel_id = c.id
LEFT JOIN LATERAL (
    SELECT count(*) AS raw_message_count
    FROM raw_messages rm
    WHERE lower(rm.channel) = lower(c.name)
) AS raw_stats ON TRUE
LEFT JOIN LATERAL (
    SELECT
        rm.message_date AS first_message_at,
        rm.event_id AS first_message_event_id
    FROM raw_messages rm
    WHERE lower(rm.channel) = lower(c.name)
    ORDER BY rm.message_date ASC, rm.event_id ASC
    LIMIT 1
) AS first_data ON TRUE
WHERE c.source_type = 'telegram'
"""

FIND_CHANNEL_SQL = text(
    CHANNEL_SELECT_SQL
    + """
AND c.added_by_user_id = :user_id
AND lower(c.name) = lower(:channel_name)
LIMIT 1
"""
)

LIST_CHANNELS_SQL = text(
    CHANNEL_SELECT_SQL
    + """
AND c.added_by_user_id = :user_id
ORDER BY c.added_at DESC, c.name ASC
"""
)

FIND_EXISTING_CHANNEL_SQL = text(
    """
SELECT
    name,
    status,
    validation_status,
    validation_error
FROM channels
WHERE source_type = 'telegram'
  AND lower(name) = lower(:channel_name)
LIMIT 1
"""
)

FIND_EXISTING_RAW_CHANNEL_SQL = text(
    """
SELECT channel
FROM raw_messages
WHERE lower(channel) = lower(:channel_name)
LIMIT 1
"""
)

INSERT_CHANNEL_SQL = text(
    """
INSERT INTO channels (
    name,
    source_type,
    input_value,
    telegram_url,
    added_by_user_id,
    added_at,
    requested_start_date,
    historical_limit_date,
    status,
    validation_status,
    validation_error,
    live_enabled,
    backfill_total_days,
    backfill_completed_days,
    backfill_failed_days,
    backfill_last_completed_date,
    last_live_collected_at
)
VALUES (
    :name,
    'telegram',
    :input_value,
    :telegram_url,
    :added_by_user_id,
    NOW(),
    :requested_start_date,
    :historical_limit_date,
    'pending_validation',
    'pending',
    NULL,
    FALSE,
    0,
    0,
    0,
    NULL,
    NULL
)
RETURNING id
"""
)


@router.post(
    "/channels",
    response_model=TelegramChannelStatus,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        409: {"model": ApiErrorResponse},
        422: {"model": ApiErrorResponse},
    },
)
async def add_telegram_channel(
    body: TelegramChannelCreateRequest,
    user: User = Depends(get_current_user),
    analytics_db: AsyncSession = Depends(get_analytics_db),
):
    try:
        channel_name = normalize_telegram_channel_input(body.channel)
        requested_start_date = normalize_requested_start_date(body.start_date)
    except SourceRegistryError as exc:
        raise _http_error(exc)

    logger.info(
        "add_channel_requested user_id=%s channel=%s input=%s start_date=%s",
        user.id,
        channel_name,
        body.channel,
        requested_start_date,
    )

    existing_row = (
        await analytics_db.execute(
            FIND_EXISTING_CHANNEL_SQL,
            {"channel_name": channel_name},
        )
    ).mappings().one_or_none()
    if existing_row is not None:
        logger.info(
            "add_channel_duplicate_registry user_id=%s channel=%s validation_status=%s registry_status=%s",
            user.id,
            existing_row["name"],
            existing_row["validation_status"],
            existing_row["status"],
        )
        raise _duplicate_error(existing_row["name"], existing_row)

    raw_row = (
        await analytics_db.execute(
            FIND_EXISTING_RAW_CHANNEL_SQL,
            {"channel_name": channel_name},
        )
    ).mappings().one_or_none()
    if raw_row is not None:
        logger.info(
            "add_channel_duplicate_raw user_id=%s channel=%s",
            user.id,
            raw_row["channel"],
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate",
                "detail": "Channel already exists in historical raw data.",
                "meta": {"channel_name": raw_row["channel"]},
            },
        )

    inserted_id = await analytics_db.scalar(
        INSERT_CHANNEL_SQL,
        {
            "name": channel_name,
            "input_value": body.channel.strip(),
            "telegram_url": f"https://t.me/{channel_name}",
            "added_by_user_id": user.id,
            "requested_start_date": requested_start_date,
            "historical_limit_date": HISTORICAL_LOWER_BOUND,
        },
    )
    if inserted_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "insert_failed",
                "detail": "Unable to create Telegram channel request.",
            },
        )

    logger.info(
        "add_channel_inserted user_id=%s channel=%s requested_start_date=%s channel_id=%s",
        user.id,
        channel_name,
        requested_start_date,
        inserted_id,
    )
    row = await _fetch_channel_row(analytics_db, user.id, channel_name)
    if row is None:
        raise HTTPException(status_code=500, detail="Inserted channel was not found.")
    return _to_status_payload(row)


@router.get("/channels", response_model=list[TelegramChannelStatus])
async def list_telegram_channels(
    user: User = Depends(get_current_user),
    analytics_db: AsyncSession = Depends(get_analytics_db),
):
    result = await analytics_db.execute(LIST_CHANNELS_SQL, {"user_id": user.id})
    return [_to_status_payload(row) for row in result.mappings().all()]


@router.get("/channels/{channel_name}", response_model=TelegramChannelStatus)
async def get_telegram_channel(
    channel_name: str,
    user: User = Depends(get_current_user),
    analytics_db: AsyncSession = Depends(get_analytics_db),
):
    row = await _fetch_channel_row(analytics_db, user.id, channel_name)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return _to_status_payload(row)


@router.get(
    "/channels/{channel_name}/progress",
    response_model=TelegramChannelProgress,
    responses={409: {"model": ApiErrorResponse}},
)
async def get_telegram_channel_progress(
    channel_name: str,
    user: User = Depends(get_current_user),
    analytics_db: AsyncSession = Depends(get_analytics_db),
):
    row = await _fetch_channel_row(analytics_db, user.id, channel_name)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    payload = _to_status_payload(row)
    if payload.status == "validation_failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "validation_failed",
                "detail": payload.validation_error or "Channel validation failed.",
                "meta": {"channel_name": payload.channel_name},
            },
        )
    return TelegramChannelProgress(**payload.model_dump())


async def _fetch_channel_row(
    analytics_db: AsyncSession,
    user_id: Any,
    channel_name: str,
):
    result = await analytics_db.execute(
        FIND_CHANNEL_SQL,
        {"user_id": user_id, "channel_name": channel_name},
    )
    return result.mappings().one_or_none()


def _to_status_payload(row: Any) -> TelegramChannelStatus:
    row_dict = dict(row)
    ui_status = derive_channel_status(row_dict)
    first_message_available = row_dict["first_message_at"] is not None
    return TelegramChannelStatus(
        channel_name=row_dict["name"],
        input_value=row_dict["input_value"],
        telegram_url=row_dict["telegram_url"],
        telegram_channel_id=row_dict["telegram_channel_id"],
        requested_start_date=row_dict["requested_start_date"],
        historical_limit_date=row_dict["historical_limit_date"],
        status=ui_status,
        validation_status=row_dict["validation_status"],
        validation_error=row_dict["validation_error"],
        live_enabled=bool(row_dict["live_enabled"]),
        backfill_total_days=int(row_dict["backfill_total_days"] or 0),
        backfill_completed_days=int(row_dict["backfill_completed_days"] or 0),
        backfill_failed_days=int(row_dict["backfill_failed_days"] or 0),
        backfill_pending_days=int(row_dict["backfill_pending_days"] or 0),
        backfill_running_days=int(row_dict["backfill_running_days"] or 0),
        backfill_retrying_days=int(row_dict["backfill_retrying_days"] or 0),
        backfill_messages_published=int(row_dict["backfill_messages_published"] or 0),
        backfill_last_completed_date=row_dict["backfill_last_completed_date"],
        last_live_collected_at=row_dict["last_live_collected_at"],
        added_at=row_dict["added_at"],
        added_by_user_id=row_dict["added_by_user_id"],
        first_message_at=row_dict["first_message_at"],
        first_message_event_id=row_dict["first_message_event_id"],
        first_message_available=first_message_available,
        raw_message_count=int(row_dict["raw_message_count"] or 0),
        feed_path=build_feed_path(row_dict["name"], first_message_available),
    )


def _duplicate_error(channel_name: str, row: dict[str, Any]) -> HTTPException:
    if row["validation_status"] == "pending" or row["status"] == "pending_validation":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "validation_pending",
                "detail": "Channel validation is still in progress.",
                "meta": {"channel_name": channel_name},
            },
        )
    if row["validation_status"] == "failed" or row["status"] == "validation_failed":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "validation_failed",
                "detail": row["validation_error"] or "Channel validation failed.",
                "meta": {"channel_name": channel_name},
            },
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error": "duplicate",
            "detail": "Channel already exists in the registry.",
            "meta": {"channel_name": channel_name},
        },
    )


def _http_error(exc: SourceRegistryError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error": exc.error_type,
            "detail": exc.message,
            "meta": exc.meta,
        },
    )

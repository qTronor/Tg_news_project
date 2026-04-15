from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "rbc_telegram_collector"))

from collector.backfill import plan_backfill_dates, process_pending_validations
from collector.config import AppConfig
from collector.events import build_raw_message_event
from collector.models import CollectedMessage
from collector.registry import RegistryChannel
from collector.sources.telegram import (
    TelegramChannelError,
    ValidatedTelegramChannel,
)


class _FakeRegistry:
    enabled = True

    def __init__(self, pending_channels: list[RegistryChannel]) -> None:
        self.pending_channels = pending_channels
        self.success_calls: list[dict] = []
        self.failed_calls: list[tuple] = []
        self.created_jobs: list[tuple] = []

    async def fetch_pending_validation_channels(self, limit: int = 50):
        return self.pending_channels[:limit]

    async def mark_validation_success(self, **kwargs):
        self.success_calls.append(kwargs)

    async def create_backfill_jobs(self, channel_id, job_dates):
        dates = list(job_dates)
        self.created_jobs.append((channel_id, dates))
        return len(dates)

    async def mark_validation_failed(self, channel_id, reason: str):
        self.failed_calls.append((channel_id, reason))


class _FakeSource:
    def __init__(self, responses):
        self.responses = responses

    async def validate_channel(self, channel_ref: str):
        value = self.responses[channel_ref]
        if isinstance(value, Exception):
            raise value
        return value


def _registry_channel(name: str, requested_start_date: date) -> RegistryChannel:
    return RegistryChannel(
        id=uuid4(),
        name=name,
        input_value=name,
        telegram_url=f"https://t.me/{name}",
        telegram_channel_id=None,
        title=None,
        description=None,
        subscriber_count=None,
        requested_start_date=requested_start_date,
        historical_limit_date=date(2026, 1, 1),
        status="pending_validation",
        validation_status="pending",
        validation_error=None,
        live_enabled=False,
        added_by_user_id=None,
        added_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc),
        backfill_total_days=0,
        backfill_completed_days=0,
        backfill_failed_days=0,
        last_live_collected_at=None,
    )


class CollectorBackfillUnitTest(unittest.IsolatedAsyncioTestCase):
    def test_plan_backfill_dates_is_newest_first_and_respects_live_window(self) -> None:
        self.assertEqual(
            plan_backfill_dates(
                requested_start_date=date(2026, 4, 10),
                today=date(2026, 4, 14),
                lookback_days=3,
            ),
            [date(2026, 4, 11), date(2026, 4, 10)],
        )

    async def test_pending_validation_transitions_to_validated_and_failed(self) -> None:
        success_channel = _registry_channel("banksta", date(2026, 4, 10))
        failed_channel = _registry_channel("private_demo", date(2026, 4, 10))
        registry = _FakeRegistry([success_channel, failed_channel])
        source = _FakeSource(
            {
                "https://t.me/banksta": ValidatedTelegramChannel(
                    name="banksta",
                    url="https://t.me/banksta",
                    channel_id=1001,
                    title="Banksta",
                    description="Finance channel",
                    subscriber_count=1200,
                ),
                "https://t.me/private_demo": TelegramChannelError(
                    reason="private",
                    message="Telegram channel is private or inaccessible.",
                    permanent=True,
                ),
            }
        )

        await process_pending_validations(
            source=source,
            registry=registry,
            cfg=AppConfig(channels=[]),
            today=date(2026, 4, 14),
        )

        self.assertEqual(len(registry.success_calls), 1)
        self.assertEqual(registry.success_calls[0]["canonical_name"], "banksta")
        self.assertEqual(
            registry.created_jobs[0][1],
            [date(2026, 4, 11), date(2026, 4, 10)],
        )
        self.assertEqual(len(registry.failed_calls), 1)
        self.assertEqual(registry.failed_calls[0][0], failed_channel.id)

    def test_overlapping_replay_keeps_same_event_id_for_downstream_idempotency(self) -> None:
        message = CollectedMessage(
            source="telegram",
            channel="rbc_news",
            message_id=777,
            date_utc=datetime(2026, 4, 14, 9, 0, tzinfo=timezone.utc),
            text="Repeated replay payload",
        )

        first_key, first_event = build_raw_message_event(message)
        second_key, second_event = build_raw_message_event(message)

        self.assertEqual(first_key, "rbc_news:777")
        self.assertEqual(second_key, first_key)
        self.assertEqual(first_event["event_id"], second_event["event_id"])
        self.assertEqual(first_event["payload"]["channel"], second_event["payload"]["channel"])

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "auth_service"))

from app.routes.sources import add_telegram_channel
from app.schemas import TelegramChannelCreateRequest


class _FakeMappings:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return _FakeMappings(self._row)


class _FakeSession:
    def __init__(self, rows):
        self._rows = list(rows)

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._rows.pop(0))

    async def scalar(self, *_args, **_kwargs):
        raise AssertionError("scalar() should not be reached in duplicate tests")


class AuthSourcesRouteUnitTest(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_detection_against_existing_channel_row(self) -> None:
        session = _FakeSession(
            [
                {
                    "name": "rbc_news",
                    "status": "ready",
                    "validation_status": "validated",
                    "validation_error": None,
                }
            ]
        )
        user = SimpleNamespace(id=uuid4())

        with self.assertRaises(HTTPException) as ctx:
            await add_telegram_channel(
                TelegramChannelCreateRequest(channel="@rbc_news", start_date=date(2026, 4, 14)),
                user=user,
                analytics_db=session,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["error"], "duplicate")

    async def test_duplicate_detection_against_raw_messages_channel(self) -> None:
        session = _FakeSession(
            [
                None,
                {"channel": "Cbpub"},
            ]
        )
        user = SimpleNamespace(id=uuid4())

        with self.assertRaises(HTTPException) as ctx:
            await add_telegram_channel(
                TelegramChannelCreateRequest(channel="cbpub", start_date=date(2026, 4, 14)),
                user=user,
                analytics_db=session,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["error"], "duplicate")
        self.assertEqual(ctx.exception.detail["meta"]["channel_name"], "Cbpub")

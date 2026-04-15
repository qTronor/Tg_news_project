from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "auth_service"))

from app.source_registry import (
    HISTORICAL_LOWER_BOUND,
    SourceRegistryError,
    normalize_requested_start_date,
    normalize_telegram_channel_input,
)


class SourceRegistryNormalizationTest(unittest.TestCase):
    def test_normalizes_public_username_and_link(self) -> None:
        self.assertEqual(normalize_telegram_channel_input("@Rbc_News"), "Rbc_News")
        self.assertEqual(
            normalize_telegram_channel_input("https://t.me/banksta"),
            "banksta",
        )
        self.assertEqual(
            normalize_telegram_channel_input("t.me/Cbpub"),
            "Cbpub",
        )

    def test_rejects_private_or_invalid_links(self) -> None:
        with self.assertRaises(SourceRegistryError) as private_link:
            normalize_telegram_channel_input("https://t.me/+privateInvite")
        self.assertEqual(private_link.exception.error_type, "invalid_link_or_username")

        with self.assertRaises(SourceRegistryError) as invalid_link:
            normalize_telegram_channel_input("https://example.com/channel")
        self.assertEqual(invalid_link.exception.error_type, "invalid_link_or_username")

    def test_rejects_dates_before_historical_floor(self) -> None:
        with self.assertRaises(SourceRegistryError) as ctx:
            normalize_requested_start_date(date(2025, 12, 31))
        self.assertEqual(ctx.exception.error_type, "date_before_limit")
        self.assertEqual(
            ctx.exception.meta["historical_limit_date"],
            HISTORICAL_LOWER_BOUND.isoformat(),
        )

    def test_clamps_future_dates_to_today(self) -> None:
        self.assertEqual(
            normalize_requested_start_date(
                date(2026, 4, 20),
                today=date(2026, 4, 14),
            ),
            date(2026, 4, 14),
        )

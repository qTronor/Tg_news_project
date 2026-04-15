from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "rbc_telegram_collector"))

from collector.events import build_raw_message_event
from collector.models import CollectedMessage


class CollectorEventMappingTest(unittest.TestCase):
    def test_build_raw_message_event_preserves_event_id_and_optional_provenance(self) -> None:
        item = CollectedMessage(
            source="telegram",
            channel="rbc_news",
            message_id=123,
            date_utc=datetime(2026, 4, 9, 8, 30, tzinfo=timezone.utc),
            text="Test news",
            channel_id=777000,
            permalink="https://t.me/rbc_news/123",
            grouped_id=55,
            edit_date=datetime(2026, 4, 9, 8, 31, tzinfo=timezone.utc),
            reply_to_message_id=120,
            reply_to_top_message_id=119,
            post_author="editor",
            is_forwarded=True,
            forward_from_channel="source_news",
            forward_from_channel_id=555,
            forward_from_message_id=42,
            forward_date=datetime(2026, 4, 9, 8, 0, tzinfo=timezone.utc),
            forward_origin_type="channel",
            media={"type": "MessageMediaPhoto"},
        )

        event_id, event = build_raw_message_event(item)

        self.assertEqual(event_id, "rbc_news:123")
        self.assertEqual(event["event_id"], "rbc_news:123")
        self.assertEqual(event["payload"]["channel_id"], 777000)
        self.assertEqual(event["payload"]["permalink"], "https://t.me/rbc_news/123")
        self.assertEqual(event["payload"]["grouped_id"], 55)
        self.assertEqual(event["payload"]["reply_to_message_id"], 120)
        self.assertEqual(event["payload"]["reply_to_top_message_id"], 119)
        self.assertEqual(event["payload"]["post_author"], "editor")
        self.assertTrue(event["payload"]["is_forwarded"])
        self.assertEqual(event["payload"]["forward_from_channel"], "source_news")
        self.assertEqual(event["payload"]["forward_from_channel_id"], 555)
        self.assertEqual(event["payload"]["forward_from_message_id"], 42)
        self.assertEqual(event["payload"]["forward_origin_type"], "channel")
        self.assertEqual(event["payload"]["media"], {"type": "photo"})

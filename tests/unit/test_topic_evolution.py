from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analytics_api"))

from analytics_api.topic_evolution import (  # noqa: E402
    TopicEntity,
    TopicMessage,
    build_timeline_points,
    detect_evolution_events,
    floor_bucket,
    normalize_bucket_size,
)


class TopicEvolutionUnitTest(unittest.TestCase):
    def test_bucket_floor_supports_15m_1h_1d(self) -> None:
        dt = datetime(2026, 4, 22, 10, 37, 45, tzinfo=timezone.utc)

        self.assertEqual(floor_bucket(dt, "15m").minute, 30)
        self.assertEqual(floor_bucket(dt, "1h").minute, 0)
        self.assertEqual(floor_bucket(dt, "1d").hour, 0)

    def test_invalid_bucket_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_bucket_size("5m")

    def test_small_topic_builds_single_point_and_created_event(self) -> None:
        messages = [
            TopicMessage(
                event_id="demo:1",
                channel="demo",
                message_date=datetime(2026, 4, 22, 10, 3, tzinfo=timezone.utc),
                sentiment_label="neutral",
                signed_sentiment=0.0,
            )
        ]

        points = build_timeline_points(messages, {}, "15m")
        events = detect_evolution_events(points)

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].message_count, 1)
        self.assertEqual(points[0].new_channels, ["demo"])
        self.assertEqual([event.event_type for event in events], ["topic_created"])

    def test_evolution_events_are_detected_from_bucket_changes(self) -> None:
        messages = [
            *[
                TopicMessage(
                    event_id=f"a:{i}",
                    channel="a",
                    message_date=datetime(2026, 4, 22, 10, i, tzinfo=timezone.utc),
                    sentiment_label="neutral",
                    signed_sentiment=0.0,
                )
                for i in range(2)
            ],
            *[
                TopicMessage(
                    event_id=f"b:{i}",
                    channel="b",
                    message_date=datetime(2026, 4, 22, 11, i, tzinfo=timezone.utc),
                    sentiment_label="negative",
                    signed_sentiment=-0.8,
                )
                for i in range(5)
            ],
            TopicMessage(
                event_id="b:decline",
                channel="b",
                message_date=datetime(2026, 4, 22, 12, 1, tzinfo=timezone.utc),
                sentiment_label="negative",
                signed_sentiment=-0.8,
            ),
        ]
        entities = {
            "b:0": [
                TopicEntity(
                    event_id="b:0",
                    entity_key="central-bank",
                    entity_text="Central Bank",
                    entity_type="ORG",
                )
            ]
        }

        points = build_timeline_points(messages, entities, "1h")
        event_types = [event.event_type for event in detect_evolution_events(points)]

        self.assertIn("topic_created", event_types)
        self.assertIn("new_channel_joined", event_types)
        self.assertIn("new_actor_detected", event_types)
        self.assertIn("sentiment_shift", event_types)
        self.assertIn("growth_spike", event_types)
        self.assertIn("decline_started", event_types)


if __name__ == "__main__":
    unittest.main()

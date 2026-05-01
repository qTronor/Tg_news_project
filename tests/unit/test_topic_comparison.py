from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analytics_api"))

from analytics_api.topic_comparison import TopicComparisonProfile, compare_topics  # noqa: E402


class TopicComparisonUnitTest(unittest.TestCase):
    def test_same_topic_when_entities_time_channels_and_messages_match(self) -> None:
        left = _profile(
            "run:1",
            entities={"central bank": 5, "moscow": 2},
            channels={"rbc": 4, "banksta": 2},
            message_hash="hash-a",
            sentiment=0.1,
        )
        right = _profile(
            "run:2",
            entities={"central bank": 4, "moscow": 2, "rate": 1},
            channels={"rbc": 3, "banksta": 1},
            message_hash="hash-a",
            sentiment=0.05,
        )

        result = compare_topics(left, right)

        self.assertEqual(result["classification"], "same_topic")
        self.assertGreaterEqual(result["similarity_score"], 0.74)
        self.assertTrue(result["is_same_topic"])
        self.assertIn("entities", result["breakdown"])
        self.assertEqual(result["evidence"]["messages"]["shared_fingerprints"], ["normalized_text_hash:hash-a"])

    def test_possible_subtopic_split_when_entities_overlap_but_channels_and_sentiment_diverge(self) -> None:
        left = _profile(
            "run:1",
            entities={"central bank": 8, "rates": 4},
            channels={"rbc": 6},
            sentiment=0.6,
        )
        right = _profile(
            "run:2",
            entities={"central bank": 6, "rates": 3, "inflation": 2},
            channels={"marketwatch": 5},
            sentiment=-0.2,
        )

        result = compare_topics(left, right)

        self.assertEqual(result["classification"], "possible_subtopic_split")
        self.assertFalse(result["is_same_topic"])
        self.assertTrue(result["explanation"]["subtopic_split_signals"])

    def test_different_topics_when_explainable_signals_do_not_overlap(self) -> None:
        left = _profile(
            "run:1",
            entities={"central bank": 3},
            channels={"rbc": 3},
            days_offset=0,
        )
        right = _profile(
            "run:2",
            entities={"oil": 3},
            channels={"energy": 3},
            days_offset=20,
        )

        result = compare_topics(left, right)

        self.assertEqual(result["classification"], "different_topics")
        self.assertLess(result["similarity_score"], 0.45)
        self.assertIn("Entity overlap is weak.", result["explanation"]["negative_factors"])

    def test_identical_cluster_id_short_circuits_to_same_topic(self) -> None:
        left = _profile("run:1", entities={}, channels={})
        right = _profile("run:1", entities={"x": 1}, channels={"a": 1})

        result = compare_topics(left, right)

        self.assertEqual(result["similarity_score"], 1.0)
        self.assertEqual(result["classification"], "same_topic")
        self.assertEqual(result["breakdown"]["identity"]["contribution"], 1.0)


def _profile(
    cluster_id: str,
    entities: dict[str, int],
    channels: dict[str, int],
    message_hash: str | None = None,
    sentiment: float = 0.0,
    days_offset: int = 0,
) -> TopicComparisonProfile:
    start = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc) + timedelta(days=days_offset)
    messages = [
        {
            "event_id": f"{cluster_id}:message",
            "normalized_text_hash": message_hash,
            "primary_url_fingerprint": None,
        }
    ]
    return TopicComparisonProfile(
        cluster_id=cluster_id,
        label=cluster_id,
        message_count=max(1, sum(channels.values())),
        first_seen=start,
        last_seen=start.replace(hour=12),
        avg_sentiment=sentiment,
        entities=entities,
        entity_labels={key: {"text": key, "type": "ORG"} for key in entities},
        channels=channels,
        messages=messages,
    )


if __name__ == "__main__":
    unittest.main()

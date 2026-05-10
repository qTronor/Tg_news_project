from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analytics_api"))

from analytics_api.topic_review import clamp_confidence, json_value, review_reasons_for_candidate


class TopicReviewUnitTest(unittest.TestCase):
    def test_review_reasons_include_new_low_confidence_and_growth(self) -> None:
        row = {
            "confidence_score": 0.42,
            "stability_score": 0.8,
            "total_messages": 100,
            "total_noise": 10,
            "recent_count": 12,
            "previous_count": 4,
            "active_label": None,
            "active_label_source": None,
        }

        reasons = {reason for reason, _, _ in review_reasons_for_candidate(row)}

        self.assertIn("new_topic", reasons)
        self.assertIn("low_confidence", reasons)
        self.assertIn("rapid_growth", reasons)

    def test_review_reasons_include_outlier_and_history_conflict(self) -> None:
        row = {
            "confidence_score": 0.6,
            "stability_score": 0.7,
            "total_messages": 100,
            "total_noise": 40,
            "recent_count": 1,
            "previous_count": 10,
            "active_label": "Auto label",
            "active_label_source": "auto",
        }

        reasons = {reason for reason, _, _ in review_reasons_for_candidate(row)}

        self.assertIn("high_outlier_ratio", reasons)
        self.assertIn("history_conflict", reasons)

    def test_confidence_is_clamped_for_human_actions(self) -> None:
        self.assertEqual(clamp_confidence(-3), 0.0)
        self.assertEqual(clamp_confidence(4), 1.0)
        self.assertIsNone(clamp_confidence(""))

    def test_json_value_decodes_jsonb_strings(self) -> None:
        self.assertEqual(json_value('{"reason":"new_topic"}', {}), {"reason": "new_topic"})
        self.assertEqual(json_value("not-json", {"fallback": True}), {"fallback": True})


if __name__ == "__main__":
    unittest.main()

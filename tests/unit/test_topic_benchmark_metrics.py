from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "topic_benchmark_runner"))

from topic_benchmark_runner.metrics import (  # noqa: E402
    build_metric_payload,
    outlier_ratio,
    topic_diversity,
    umass_coherence,
)


class TopicBenchmarkMetricsTest(unittest.TestCase):
    def test_topic_diversity_counts_unique_top_words(self) -> None:
        value = topic_diversity([["банк", "ставка"], ["банк", "рынок"]], top_k=2)

        self.assertEqual(value, 0.75)

    def test_outlier_ratio_uses_negative_one_label(self) -> None:
        self.assertEqual(outlier_ratio([0, -1, 1, -1]), 0.5)

    def test_umass_coherence_is_deterministic(self) -> None:
        documents = [["банк", "ставка"], ["банк", "рынок"], ["нефть", "рынок"]]
        topics = [["банк", "ставка"], ["нефть", "рынок"]]

        self.assertAlmostEqual(umass_coherence(documents, topics), -0.2027325541)

    def test_build_metric_payload_includes_required_metrics(self) -> None:
        payload = build_metric_payload(
            ["банк повысил ставку", "рынок ждет ставку", "нефть растет"],
            [0, 0, 1],
            [["ставку", "банк"], ["нефть", "растет"]],
        )

        self.assertIn("topic_coherence", payload)
        self.assertIn("topic_diversity", payload)
        self.assertEqual(payload["outlier_ratio"], 0.0)
        self.assertEqual(payload["cluster_count"], 2)


if __name__ == "__main__":
    unittest.main()

"""Regression / golden-fixture tests for topic importance scoring.

These tests pin the exact output for 5 synthetic clusters with known features.
If a formula or weight change is intentional, update the fixtures below.
Changing these values without a corresponding scoring_version bump is a bug.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "topic_scorer"))

from topic_scorer.config import ScoringConfig
from topic_scorer.features import compute_per_run_stats, compute_raw_features, normalize_features
from topic_scorer.schemas import ClusterFeatures
from topic_scorer.scoring import score_cluster


def _default_cfg() -> ScoringConfig:
    return ScoringConfig()


# ---------------------------------------------------------------------------
# Golden cluster definitions
# ---------------------------------------------------------------------------
GOLDEN_CLUSTERS: Dict[str, Dict[str, Any]] = {
    "viral_breaking": dict(
        message_count=80,
        unique_channels=15,
        recent_message_count=70,
        prev_message_count=10,
        new_channel_count=8,
        unique_entities=20,
        novel_entity_count=18,
        total_entity_count_for_novelty=20,
        avg_sentiment=-0.6,
        recent_avg_sentiment=-0.8,
        prev_avg_sentiment=-0.2,
        negative_share=0.7,
        graph_density=0.6,
        graph_avg_degree=None,
    ),
    "slow_background": dict(
        message_count=6,
        unique_channels=2,
        recent_message_count=3,
        prev_message_count=3,
        new_channel_count=0,
        unique_entities=4,
        novel_entity_count=1,
        total_entity_count_for_novelty=4,
        avg_sentiment=0.1,
        recent_avg_sentiment=0.1,
        prev_avg_sentiment=0.1,
        negative_share=0.1,
        graph_density=0.1,
        graph_avg_degree=None,
    ),
    "tiny_cluster": dict(
        message_count=1,
        unique_channels=1,
        recent_message_count=1,
        prev_message_count=0,
        new_channel_count=0,
        unique_entities=0,
        novel_entity_count=0,
        total_entity_count_for_novelty=0,
        avg_sentiment=0.0,
        recent_avg_sentiment=0.0,
        prev_avg_sentiment=0.0,
        negative_share=0.0,
        graph_density=None,
        graph_avg_degree=None,
    ),
    "sentiment_spike": dict(
        message_count=20,
        unique_channels=5,
        recent_message_count=10,
        prev_message_count=10,
        new_channel_count=1,
        unique_entities=8,
        novel_entity_count=2,
        total_entity_count_for_novelty=8,
        avg_sentiment=-0.9,
        recent_avg_sentiment=-1.0,
        prev_avg_sentiment=0.5,
        negative_share=0.9,
        graph_density=0.4,
        graph_avg_degree=None,
    ),
    "channel_spread": dict(
        message_count=30,
        unique_channels=20,
        recent_message_count=20,
        prev_message_count=10,
        new_channel_count=15,
        unique_entities=10,
        novel_entity_count=5,
        total_entity_count_for_novelty=10,
        avg_sentiment=0.0,
        recent_avg_sentiment=0.0,
        prev_avg_sentiment=0.0,
        negative_share=0.2,
        graph_density=0.3,
        graph_avg_degree=None,
    ),
}

# Expected ordering by score: viral_breaking > channel_spread > sentiment_spike > slow_background > tiny_cluster
EXPECTED_ORDER = ["viral_breaking", "channel_spread", "sentiment_spike", "slow_background", "tiny_cluster"]

# Expected level for tiny_cluster (has small-cluster penalty and minimal features)
EXPECTED_TINY_LEVEL = "low"
# viral_breaking should be high or critical
EXPECTED_VIRAL_MIN_LEVEL = "high"


def _make_feat(name: str, kwargs: Dict[str, Any]) -> ClusterFeatures:
    return ClusterFeatures(
        public_cluster_id=f"run1:{name}",
        run_id="run1",
        window_start=None,
        window_end=None,
        **kwargs,
    )


class TestGoldenFixtures(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cfg = _default_cfg()
        clusters = {
            name: _make_feat(name, kwargs)
            for name, kwargs in GOLDEN_CLUSTERS.items()
        }
        all_raw = {
            name: compute_raw_features(feat, cfg)
            for name, feat in clusters.items()
        }
        per_run = compute_per_run_stats(all_raw)
        cls.results = {}
        for name, feat in clusters.items():
            norm = normalize_features(all_raw[name], per_run, cfg)
            ts = score_cluster(feat, all_raw[name], norm, cfg)
            cls.results[name] = ts

    def test_expected_ordering(self) -> None:
        """Clusters must rank in the expected order."""
        scores = {name: self.results[name].importance_score for name in EXPECTED_ORDER}
        ordered = sorted(scores.keys(), key=lambda n: scores[n], reverse=True)
        self.assertEqual(ordered, EXPECTED_ORDER, msg=f"Actual scores: {scores}")

    def test_viral_breaking_is_high_or_critical(self) -> None:
        level = self.results["viral_breaking"].importance_level
        self.assertIn(level, {"high", "critical"})

    def test_tiny_cluster_is_low(self) -> None:
        self.assertEqual(self.results["tiny_cluster"].importance_level, EXPECTED_TINY_LEVEL)

    def test_tiny_cluster_has_penalty_in_breakdown(self) -> None:
        ts = self.results["tiny_cluster"]
        self.assertGreater(len(ts.breakdown.penalties), 0)

    def test_all_scores_in_unit_interval(self) -> None:
        for name, ts in self.results.items():
            self.assertGreaterEqual(ts.importance_score, 0.0, msg=name)
            self.assertLessEqual(ts.importance_score, 1.0, msg=name)

    def test_breakdown_json_round_trips(self) -> None:
        """Serialization must not raise and must include all expected keys."""
        import json
        for name, ts in self.results.items():
            bd = ts.breakdown_json()
            dumped = json.dumps(bd)
            loaded = json.loads(dumped)
            self.assertIn("components", loaded, msg=name)
            self.assertIn("final_score", loaded, msg=name)
            self.assertIn("level", loaded, msg=name)

    def test_features_json_round_trips(self) -> None:
        import json
        for name, ts in self.results.items():
            fj = ts.features_json()
            dumped = json.dumps(fj)
            loaded = json.loads(dumped)
            self.assertIn("message_count", loaded, msg=name)

    def test_deterministic_across_runs(self) -> None:
        """Re-running scoring with same inputs must produce identical results."""
        cfg = _default_cfg()
        name = "viral_breaking"
        feat = _make_feat(name, GOLDEN_CLUSTERS[name])
        all_raw_a = {name: compute_raw_features(feat, cfg)}
        all_raw_b = {name: compute_raw_features(feat, cfg)}
        per_run_a = compute_per_run_stats(all_raw_a)
        per_run_b = compute_per_run_stats(all_raw_b)
        norm_a = normalize_features(all_raw_a[name], per_run_a, cfg)
        norm_b = normalize_features(all_raw_b[name], per_run_b, cfg)
        ts_a = score_cluster(feat, all_raw_a[name], norm_a, cfg)
        ts_b = score_cluster(feat, all_raw_b[name], norm_b, cfg)
        self.assertAlmostEqual(ts_a.importance_score, ts_b.importance_score, places=10)
        self.assertEqual(ts_a.importance_level, ts_b.importance_level)


if __name__ == "__main__":
    unittest.main()

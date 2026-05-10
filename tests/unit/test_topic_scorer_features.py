"""Unit tests for topic_scorer.features — pure deterministic logic."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "topic_scorer"))

from topic_scorer.config import ScoringConfig
from topic_scorer.features import (
    compute_per_run_stats,
    compute_raw_features,
    normalize_features,
)
from topic_scorer.schemas import ClusterFeatures


def _default_cfg() -> ScoringConfig:
    return ScoringConfig()


def _make_features(**kwargs) -> ClusterFeatures:
    defaults = dict(
        public_cluster_id="run1:0",
        run_id="run1",
        window_start=None,
        window_end=None,
        message_count=10,
        unique_channels=3,
        recent_message_count=7,
        prev_message_count=3,
        new_channel_count=1,
        unique_entities=5,
        novel_entity_count=3,
        total_entity_count_for_novelty=5,
        avg_sentiment=-0.3,
        recent_avg_sentiment=-0.5,
        prev_avg_sentiment=-0.1,
        negative_share=0.4,
        graph_density=0.25,
        graph_avg_degree=None,
    )
    defaults.update(kwargs)
    return ClusterFeatures(**defaults)


class TestComputeRawFeatures(unittest.TestCase):

    def test_growth_rate_positive(self) -> None:
        f = _make_features(recent_message_count=9, prev_message_count=3)
        raw = compute_raw_features(f, _default_cfg())
        # (9-3)/(3+eps) ≈ 2.0
        self.assertAlmostEqual(raw["growth_rate"], 2.0, places=2)

    def test_growth_rate_zero_prev(self) -> None:
        f = _make_features(recent_message_count=5, prev_message_count=0)
        raw = compute_raw_features(f, _default_cfg())
        # growth = 5/eps → clipped to 5.0
        self.assertAlmostEqual(raw["growth_rate"], 5.0, places=2)

    def test_growth_rate_decline_clipped(self) -> None:
        f = _make_features(recent_message_count=0, prev_message_count=100)
        raw = compute_raw_features(f, _default_cfg())
        self.assertGreaterEqual(raw["growth_rate"], -1.0)

    def test_message_count_log_scale(self) -> None:
        f = _make_features(message_count=0)
        raw = compute_raw_features(f, _default_cfg())
        self.assertAlmostEqual(raw["message_count"], 0.0)
        f2 = _make_features(message_count=100)
        raw2 = compute_raw_features(f2, _default_cfg())
        self.assertAlmostEqual(raw2["message_count"], math.log1p(100), places=5)

    def test_new_channel_ratio_full(self) -> None:
        f = _make_features(unique_channels=4, new_channel_count=4)
        raw = compute_raw_features(f, _default_cfg())
        self.assertAlmostEqual(raw["new_channel_ratio"], 1.0)

    def test_new_channel_ratio_zero_channels_safe(self) -> None:
        f = _make_features(unique_channels=0, new_channel_count=0)
        raw = compute_raw_features(f, _default_cfg())
        # Should not raise, ratio = 0/1 = 0
        self.assertAlmostEqual(raw["new_channel_ratio"], 0.0)

    def test_novelty_zero_when_no_ner(self) -> None:
        f = _make_features(total_entity_count_for_novelty=0, novel_entity_count=0)
        raw = compute_raw_features(f, _default_cfg())
        self.assertAlmostEqual(raw["novelty"], 0.0)

    def test_sentiment_intensity_uses_max(self) -> None:
        f = _make_features(avg_sentiment=-0.2, negative_share=0.6)
        raw = compute_raw_features(f, _default_cfg())
        self.assertAlmostEqual(raw["sentiment_intensity"], 0.6)

    def test_sentiment_shift_clipped(self) -> None:
        f = _make_features(recent_avg_sentiment=1.0, prev_avg_sentiment=-1.0)
        raw = compute_raw_features(f, _default_cfg())
        self.assertAlmostEqual(raw["sentiment_shift"], 1.0)

    def test_cluster_density_fallback(self) -> None:
        f = _make_features(graph_density=None)
        raw = compute_raw_features(f, _default_cfg())
        self.assertAlmostEqual(raw["cluster_density"], 0.3)

    def test_cluster_density_from_graph(self) -> None:
        f = _make_features(graph_density=0.75)
        raw = compute_raw_features(f, _default_cfg())
        self.assertAlmostEqual(raw["cluster_density"], 0.75)

    def test_all_features_bounded(self) -> None:
        f = _make_features(
            message_count=1000,
            unique_channels=50,
            recent_message_count=999,
            prev_message_count=1,
            new_channel_count=50,
            unique_entities=200,
            novel_entity_count=200,
            total_entity_count_for_novelty=200,
            avg_sentiment=-1.0,
            recent_avg_sentiment=-1.0,
            prev_avg_sentiment=1.0,
            negative_share=1.0,
            graph_density=1.0,
        )
        raw = compute_raw_features(f, _default_cfg())
        self.assertLessEqual(raw["growth_rate"], 5.0)
        self.assertGreaterEqual(raw["growth_rate"], -1.0)
        self.assertLessEqual(raw["new_channel_ratio"], 1.0)
        self.assertLessEqual(raw["novelty"], 1.0)
        self.assertLessEqual(raw["sentiment_intensity"], 1.0)
        self.assertLessEqual(raw["sentiment_shift"], 1.0)
        self.assertLessEqual(raw["cluster_density"], 1.0)

    def test_deterministic(self) -> None:
        f = _make_features()
        cfg = _default_cfg()
        result_a = compute_raw_features(f, cfg)
        result_b = compute_raw_features(f, cfg)
        self.assertEqual(result_a, result_b)


class TestNormalization(unittest.TestCase):

    def test_per_run_stats_computed(self) -> None:
        all_raw = {
            "c1": {"growth_rate": 0.0, "message_count": 1.0},
            "c2": {"growth_rate": 2.0, "message_count": 3.0},
        }
        stats = compute_per_run_stats(all_raw)
        self.assertAlmostEqual(stats["growth_rate"][0], 0.0)
        self.assertAlmostEqual(stats["growth_rate"][1], 2.0)

    def test_normalize_min_max(self) -> None:
        raw = {"growth_rate": 1.0, "message_count": 2.0}
        stats = {"growth_rate": (0.0, 2.0), "message_count": (1.0, 3.0)}
        norm = normalize_features(raw, stats, _default_cfg())
        self.assertAlmostEqual(norm["growth_rate"], 0.5)
        self.assertAlmostEqual(norm["message_count"], 0.5)

    def test_normalize_single_value_neutral(self) -> None:
        """When all values in run are equal, normalized value = 0.5."""
        raw = {"growth_rate": 3.0}
        stats = {"growth_rate": (3.0, 3.0)}  # min == max
        norm = normalize_features(raw, stats, _default_cfg())
        self.assertAlmostEqual(norm["growth_rate"], 0.5)

    def test_normalize_clamps_to_01(self) -> None:
        raw = {"growth_rate": 5.0}
        stats = {"growth_rate": (0.0, 4.0)}  # value exceeds max
        norm = normalize_features(raw, stats, _default_cfg())
        self.assertLessEqual(norm["growth_rate"], 1.0)
        self.assertGreaterEqual(norm["growth_rate"], 0.0)

    def test_empty_run_stats_safe(self) -> None:
        stats = compute_per_run_stats({})
        self.assertEqual(stats, {})


if __name__ == "__main__":
    unittest.main()

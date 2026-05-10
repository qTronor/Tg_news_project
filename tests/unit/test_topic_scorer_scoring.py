"""Unit tests for topic_scorer.scoring — formula, weights, level thresholds."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "topic_scorer"))

from topic_scorer.config import ScoringConfig, ScoringWeightsConfig, LevelThresholdsConfig
from topic_scorer.features import compute_raw_features, compute_per_run_stats, normalize_features
from topic_scorer.schemas import ClusterFeatures
from topic_scorer.scoring import score_cluster


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


def _score_with_defaults(feat: ClusterFeatures, cfg: ScoringConfig = None) -> float:
    if cfg is None:
        cfg = _default_cfg()
    raw = compute_raw_features(feat, cfg)
    per_run = compute_per_run_stats({"only": raw})
    norm = normalize_features(raw, per_run, cfg)
    ts = score_cluster(feat, raw, norm, cfg)
    return ts.importance_score


def _score_pair(feat_a: ClusterFeatures, feat_b: ClusterFeatures, cfg: ScoringConfig = None):
    """Score two clusters within the same per-run normalization context.

    Per-run min-max requires at least two different values to produce a
    meaningful ordering. Single-cluster runs always yield 0.5 per feature.
    """
    if cfg is None:
        cfg = _default_cfg()
    raw_a = compute_raw_features(feat_a, cfg)
    raw_b = compute_raw_features(feat_b, cfg)
    per_run = compute_per_run_stats({"a": raw_a, "b": raw_b})
    norm_a = normalize_features(raw_a, per_run, cfg)
    norm_b = normalize_features(raw_b, per_run, cfg)
    ts_a = score_cluster(feat_a, raw_a, norm_a, cfg)
    ts_b = score_cluster(feat_b, raw_b, norm_b, cfg)
    return ts_a.importance_score, ts_b.importance_score


class TestScoringMonotonicity(unittest.TestCase):

    def test_more_messages_higher_score(self) -> None:
        # Two clusters differ only in message_count → bigger should rank higher
        low_feat = _make_features(public_cluster_id="run1:low", message_count=2)
        high_feat = _make_features(public_cluster_id="run1:high", message_count=100)
        score_low, score_high = _score_pair(low_feat, high_feat)
        self.assertGreater(score_high, score_low)

    def test_higher_growth_rate_higher_score(self) -> None:
        slow = _make_features(
            public_cluster_id="run1:slow",
            recent_message_count=2,
            prev_message_count=10,
        )
        fast = _make_features(
            public_cluster_id="run1:fast",
            recent_message_count=50,
            prev_message_count=10,
        )
        score_slow, score_fast = _score_pair(slow, fast)
        self.assertGreater(score_fast, score_slow)

    def test_more_channels_higher_score(self) -> None:
        few = _make_features(
            public_cluster_id="run1:few",
            unique_channels=1,
            new_channel_count=0,
        )
        many = _make_features(
            public_cluster_id="run1:many",
            unique_channels=20,
            new_channel_count=5,
        )
        score_few, score_many = _score_pair(few, many)
        self.assertGreater(score_many, score_few)


class TestScoringBounds(unittest.TestCase):

    def test_score_in_unit_interval(self) -> None:
        score = _score_with_defaults(_make_features())
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_score_minimal_cluster(self) -> None:
        score = _score_with_defaults(_make_features(
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
        ))
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_weights_sum_to_one(self) -> None:
        cfg = _default_cfg()
        weights = cfg.weights.model_dump()
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=5)


class TestSmallClusterPenalty(unittest.TestCase):

    def test_penalty_applied_below_threshold(self) -> None:
        cfg = _default_cfg()
        big = _make_features(message_count=10)
        small = _make_features(message_count=1)
        score_big = _score_with_defaults(big, cfg)
        score_small = _score_with_defaults(small, cfg)
        self.assertGreater(score_big, score_small)

    def test_penalty_breakdown_recorded(self) -> None:
        cfg = _default_cfg()
        feat = _make_features(message_count=1)
        raw = compute_raw_features(feat, cfg)
        per_run = compute_per_run_stats({"only": raw})
        norm = normalize_features(raw, per_run, cfg)
        ts = score_cluster(feat, raw, norm, cfg)
        self.assertGreater(len(ts.breakdown.penalties), 0)
        self.assertAlmostEqual(ts.breakdown.penalty_factor, cfg.small_cluster_penalty)

    def test_no_penalty_at_threshold(self) -> None:
        cfg = _default_cfg()
        feat = _make_features(message_count=cfg.min_messages_for_full_score)
        raw = compute_raw_features(feat, cfg)
        per_run = compute_per_run_stats({"only": raw})
        norm = normalize_features(raw, per_run, cfg)
        ts = score_cluster(feat, raw, norm, cfg)
        self.assertEqual(ts.breakdown.penalties, [])
        self.assertAlmostEqual(ts.breakdown.penalty_factor, 1.0)


class TestLevelThresholds(unittest.TestCase):

    def _score_with_known_norm(self, norm_val: float, cfg: ScoringConfig) -> str:
        """Force all normalized features to norm_val to test level assignment."""
        feat = _make_features()
        raw = compute_raw_features(feat, cfg)
        norm = {k: norm_val for k in raw}
        ts = score_cluster(feat, raw, norm, cfg)
        return ts.importance_level

    def test_critical_level(self) -> None:
        cfg = _default_cfg()
        level = self._score_with_known_norm(1.0, cfg)
        self.assertEqual(level, "critical")

    def test_low_level(self) -> None:
        cfg = _default_cfg()
        level = self._score_with_known_norm(0.0, cfg)
        self.assertEqual(level, "low")

    def test_medium_level(self) -> None:
        cfg = ScoringConfig(
            level_thresholds=LevelThresholdsConfig(
                low=0.0, medium=0.3, high=0.7, critical=0.9
            )
        )
        feat = _make_features()
        raw = compute_raw_features(feat, cfg)
        norm = {k: 0.5 for k in raw}
        ts = score_cluster(feat, raw, norm, cfg)
        self.assertEqual(ts.importance_level, "medium")


class TestBreakdownJsonSchema(unittest.TestCase):

    def test_breakdown_json_has_all_components(self) -> None:
        cfg = _default_cfg()
        feat = _make_features()
        raw = compute_raw_features(feat, cfg)
        per_run = compute_per_run_stats({"only": raw})
        norm = normalize_features(raw, per_run, cfg)
        ts = score_cluster(feat, raw, norm, cfg)
        bd = ts.breakdown_json()
        expected_keys = set(cfg.weights.model_dump().keys())
        actual_keys = set(bd["components"].keys())
        self.assertEqual(actual_keys, expected_keys)

    def test_breakdown_json_contributions_sum_to_weighted_sum(self) -> None:
        cfg = _default_cfg()
        feat = _make_features()
        raw = compute_raw_features(feat, cfg)
        per_run = compute_per_run_stats({"only": raw})
        norm = normalize_features(raw, per_run, cfg)
        ts = score_cluster(feat, raw, norm, cfg)
        bd = ts.breakdown_json()
        total = sum(c["contribution"] for c in bd["components"].values())
        self.assertAlmostEqual(total, bd["raw_weighted_sum"], places=5)

    def test_scoring_version_in_result(self) -> None:
        cfg = ScoringConfig(version="v2-test")
        feat = _make_features()
        raw = compute_raw_features(feat, cfg)
        per_run = compute_per_run_stats({"only": raw})
        norm = normalize_features(raw, per_run, cfg)
        ts = score_cluster(feat, raw, norm, cfg)
        self.assertEqual(ts.scoring_version, "v2-test")


class TestConfigurableWeights(unittest.TestCase):

    def test_zero_weight_on_component_ignored(self) -> None:
        cfg = ScoringConfig(
            weights=ScoringWeightsConfig(
                growth_rate=0.0,
                message_count=1.0,
                unique_channels=0.0,
                new_channel_ratio=0.0,
                unique_entities=0.0,
                novelty=0.0,
                sentiment_intensity=0.0,
                sentiment_shift=0.0,
                cluster_density=0.0,
            )
        )
        feat = _make_features()
        raw = compute_raw_features(feat, cfg)
        per_run = compute_per_run_stats({"only": raw})
        norm = normalize_features(raw, per_run, cfg)
        ts = score_cluster(feat, raw, norm, cfg)
        bd = ts.breakdown_json()
        self.assertAlmostEqual(bd["components"]["growth_rate"]["contribution"], 0.0)


if __name__ == "__main__":
    unittest.main()

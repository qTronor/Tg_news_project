"""Importance scoring logic.

Takes normalized feature values and config weights, produces a TopicScore.
All arithmetic is pure Python — no DB, no I/O, fully unit-testable.
"""

from __future__ import annotations

from typing import Dict, List

from topic_scorer.config import ScoringConfig
from topic_scorer.schemas import (
    ClusterFeatures,
    ComponentScore,
    ScoreBreakdown,
    TopicScore,
)


def _importance_level(score: float, cfg: ScoringConfig) -> str:
    t = cfg.level_thresholds
    if score >= t.critical:
        return "critical"
    if score >= t.high:
        return "high"
    if score >= t.medium:
        return "medium"
    return "low"


def score_cluster(
    features: ClusterFeatures,
    raw_features: Dict[str, float],
    normalized_features: Dict[str, float],
    cfg: ScoringConfig,
) -> TopicScore:
    """Compute importance score + full breakdown for one cluster."""
    weights = cfg.weights.model_dump()

    components: Dict[str, ComponentScore] = {}
    weighted_sum = 0.0

    for name, weight in weights.items():
        raw_val = raw_features.get(name, 0.0)
        norm_val = normalized_features.get(name, 0.0)
        contribution = norm_val * weight
        weighted_sum += contribution
        components[name] = ComponentScore(
            raw=raw_val,
            normalized=norm_val,
            weight=weight,
            contribution=contribution,
        )

    # ---- Small-cluster penalty ----------------------------------------------
    penalties: List[str] = []
    penalty_factor = 1.0
    if features.message_count < cfg.min_messages_for_full_score:
        penalty_factor = cfg.small_cluster_penalty
        penalties.append(
            f"small_cluster: message_count={features.message_count} "
            f"< threshold={cfg.min_messages_for_full_score}"
        )

    final_score = min(1.0, max(0.0, weighted_sum * penalty_factor))
    level = _importance_level(final_score, cfg)

    breakdown = ScoreBreakdown(
        components=components,
        penalties=penalties,
        penalty_factor=penalty_factor,
        raw_weighted_sum=weighted_sum,
        final_score=final_score,
        level=level,
    )

    return TopicScore(
        public_cluster_id=features.public_cluster_id,
        run_id=features.run_id,
        importance_score=final_score,
        importance_level=level,
        breakdown=breakdown,
        features=features,
        scoring_version=cfg.version,
        window_start=features.window_start,
        window_end=features.window_end,
    )

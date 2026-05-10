"""Feature derivation from raw ClusterFeatures.

All computations are pure, deterministic, and safe for small clusters.
Returns a dict[feature_name -> float] in [0, ∞), ready for normalization.
"""

from __future__ import annotations

import math
from typing import Dict, Optional

from topic_scorer.config import ScoringConfig
from topic_scorer.schemas import ClusterFeatures


def compute_raw_features(f: ClusterFeatures, cfg: ScoringConfig) -> Dict[str, float]:
    """Return raw (un-normalized) feature values for a cluster."""
    eps = cfg.epsilon

    # ---- growth_rate -------------------------------------------------------
    # (recent - prev) / (prev + eps) — clipped to [-1, 5]
    prev = max(f.prev_message_count, 0)
    recent = max(f.recent_message_count, 0)
    growth_rate = (recent - prev) / (prev + eps)
    growth_rate = max(-1.0, min(5.0, growth_rate))

    # ---- message_count (log-scale) -----------------------------------------
    message_count_log = math.log1p(max(f.message_count, 0))

    # ---- unique_channels (log-scale) ----------------------------------------
    unique_channels_log = math.log1p(max(f.unique_channels, 0))

    # ---- new_channel_ratio ---------------------------------------------------
    total_ch = max(f.unique_channels, 1)
    new_channel_ratio = max(f.new_channel_count, 0) / total_ch

    # ---- unique_entities (log-scale) ----------------------------------------
    unique_entities_log = math.log1p(max(f.unique_entities, 0))

    # ---- novelty ------------------------------------------------------------
    # Fraction of entities that were "new" (not seen in history window)
    total_for_novelty = max(f.total_entity_count_for_novelty, 1)
    novelty = max(f.novel_entity_count, 0) / total_for_novelty

    # If NER didn't run (total_entity_count_for_novelty == 0), fall back to 0
    if f.total_entity_count_for_novelty == 0:
        novelty = 0.0

    # ---- sentiment_intensity -------------------------------------------------
    # max(|avg_sentiment|, negative_share) — both [0, 1]
    sentiment_intensity = max(abs(f.avg_sentiment), f.negative_share)
    sentiment_intensity = min(1.0, max(0.0, sentiment_intensity))

    # ---- sentiment_shift -----------------------------------------------------
    # |recent_sentiment - prev_sentiment| — in [0, 2] theoretically; clip to [0, 1]
    sentiment_shift = abs(f.recent_avg_sentiment - f.prev_avg_sentiment)
    sentiment_shift = min(1.0, sentiment_shift)

    # ---- cluster_density (from graph; fallback to neutral 0.3) ---------------
    if f.graph_density is not None:
        cluster_density = min(1.0, max(0.0, float(f.graph_density)))
    else:
        cluster_density = 0.3  # neutral fallback

    return {
        "growth_rate": float(growth_rate),
        "message_count": float(message_count_log),
        "unique_channels": float(unique_channels_log),
        "new_channel_ratio": float(new_channel_ratio),
        "unique_entities": float(unique_entities_log),
        "novelty": float(novelty),
        "sentiment_intensity": float(sentiment_intensity),
        "sentiment_shift": float(sentiment_shift),
        "cluster_density": float(cluster_density),
    }


def normalize_features(
    raw: Dict[str, float],
    per_run_stats: Dict[str, tuple[float, float]],
    cfg: ScoringConfig,
) -> Dict[str, float]:
    """Min-max normalize each feature using per-run statistics.

    per_run_stats: {feature_name -> (min_val, max_val)} computed across all
    clusters in the current run.

    Features where min == max (single cluster or all identical) → 0.5 neutral.
    """
    eps = cfg.epsilon
    normalized: Dict[str, float] = {}
    for name, value in raw.items():
        lo, hi = per_run_stats.get(name, (0.0, 1.0))
        span = hi - lo
        if span < eps:
            normalized[name] = 0.5
        else:
            normalized[name] = (value - lo) / span
        normalized[name] = min(1.0, max(0.0, normalized[name]))
    return normalized


def compute_per_run_stats(
    all_raw: Dict[str, Dict[str, float]],
) -> Dict[str, tuple[float, float]]:
    """Compute per-feature (min, max) across all clusters in a run."""
    if not all_raw:
        return {}
    feature_names = next(iter(all_raw.values())).keys()
    stats: Dict[str, tuple[float, float]] = {}
    for name in feature_names:
        values = [all_raw[cid][name] for cid in all_raw]
        stats[name] = (min(values), max(values))
    return stats

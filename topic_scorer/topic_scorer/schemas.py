from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ClusterFeatures:
    """Raw features extracted from DB for a single cluster."""

    public_cluster_id: str
    run_id: str
    window_start: Optional[datetime]
    window_end: Optional[datetime]

    # Volume
    message_count: int = 0
    unique_channels: int = 0

    # Growth: messages in recent half-window vs older half-window
    recent_message_count: int = 0
    prev_message_count: int = 0

    # Channel novelty: channels appearing for the first time in this cluster
    new_channel_count: int = 0

    # Entities
    unique_entities: int = 0

    # Novelty: entities not seen in the history window before this cluster's first_seen
    novel_entity_count: int = 0
    total_entity_count_for_novelty: int = 0

    # Sentiment
    avg_sentiment: float = 0.0          # signed: positive - negative in [-1, 1]
    recent_avg_sentiment: float = 0.0
    prev_avg_sentiment: float = 0.0
    negative_share: float = 0.0         # fraction of messages with negative label

    # Graph density (from graph_subgraph_metrics; may be None if not computed)
    graph_density: Optional[float] = None
    graph_avg_degree: Optional[float] = None

    # Timing
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None


@dataclass
class ComponentScore:
    """Score breakdown for a single feature component."""

    raw: float
    normalized: float
    weight: float
    contribution: float


@dataclass
class ScoreBreakdown:
    """Full explainable breakdown of a topic's importance score."""

    components: Dict[str, ComponentScore]
    penalties: List[str]
    penalty_factor: float
    raw_weighted_sum: float
    final_score: float
    level: str


@dataclass
class TopicScore:
    """Final scored result ready to be persisted."""

    public_cluster_id: str
    run_id: str
    importance_score: float
    importance_level: str
    breakdown: ScoreBreakdown
    features: ClusterFeatures
    scoring_version: str
    window_start: Optional[datetime]
    window_end: Optional[datetime]

    def breakdown_json(self) -> Dict[str, Any]:
        return {
            "components": {
                name: {
                    "raw": comp.raw,
                    "normalized": comp.normalized,
                    "weight": comp.weight,
                    "contribution": comp.contribution,
                }
                for name, comp in self.breakdown.components.items()
            },
            "penalties": self.breakdown.penalties,
            "penalty_factor": self.breakdown.penalty_factor,
            "raw_weighted_sum": self.breakdown.raw_weighted_sum,
            "final_score": self.breakdown.final_score,
            "level": self.breakdown.level,
        }

    def features_json(self) -> Dict[str, Any]:
        f = self.features
        return {
            "message_count": f.message_count,
            "unique_channels": f.unique_channels,
            "recent_message_count": f.recent_message_count,
            "prev_message_count": f.prev_message_count,
            "new_channel_count": f.new_channel_count,
            "unique_entities": f.unique_entities,
            "novel_entity_count": f.novel_entity_count,
            "total_entity_count_for_novelty": f.total_entity_count_for_novelty,
            "avg_sentiment": f.avg_sentiment,
            "recent_avg_sentiment": f.recent_avg_sentiment,
            "prev_avg_sentiment": f.prev_avg_sentiment,
            "negative_share": f.negative_share,
            "graph_density": f.graph_density,
            "graph_avg_degree": f.graph_avg_degree,
            "first_seen": f.first_seen.isoformat() if f.first_seen else None,
            "last_seen": f.last_seen.isoformat() if f.last_seen else None,
        }

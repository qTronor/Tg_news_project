"""Database read/write for topic scoring.

All SQL is isolated here so scoring logic stays pure Python.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

import asyncpg

from topic_scorer.config import ScoringConfig
from topic_scorer.schemas import ClusterFeatures, TopicScore

logger = logging.getLogger("topic_scorer.repository")

# ---------------------------------------------------------------------------
# Read: latest cluster run
# ---------------------------------------------------------------------------
SELECT_LATEST_RUN_SQL = """
SELECT run_id, run_timestamp, window_start, window_end
FROM cluster_runs_pg
ORDER BY run_timestamp DESC
LIMIT 1;
"""

# ---------------------------------------------------------------------------
# Read: cluster IDs in a run
# ---------------------------------------------------------------------------
SELECT_CLUSTERS_IN_RUN_SQL = """
SELECT DISTINCT public_cluster_id
FROM cluster_assignments
WHERE run_id = $1
  AND cluster_id >= 0;
"""

# ---------------------------------------------------------------------------
# Read: base features (volume, channels, sentiment timing) for all clusters
# in a run — single query, aggregated.
# ---------------------------------------------------------------------------
SELECT_BASE_FEATURES_SQL = """
WITH cluster_base AS (
    SELECT
        ca.public_cluster_id,
        ca.run_id,
        COUNT(*)                              AS message_count,
        COUNT(DISTINCT rm.channel)            AS unique_channels,
        MIN(rm.message_date)                  AS first_seen,
        MAX(rm.message_date)                  AS last_seen,
        -- Signed sentiment: positive_prob - negative_prob, fallback to label
        AVG(
            CASE
                WHEN sr.positive_prob IS NOT NULL OR sr.negative_prob IS NOT NULL
                    THEN COALESCE(sr.positive_prob, 0) - COALESCE(sr.negative_prob, 0)
                WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'positive'
                    THEN  COALESCE(sr.sentiment_score, 0)
                WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'negative'
                    THEN -COALESCE(sr.sentiment_score, 0)
                ELSE 0
            END
        )                                     AS avg_sentiment,
        -- Negative share
        AVG(CASE WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'negative'
                 THEN 1.0 ELSE 0.0 END)       AS negative_share
    FROM cluster_assignments ca
    JOIN raw_messages rm ON rm.event_id = ca.event_id
    LEFT JOIN sentiment_results sr ON sr.event_id = ca.event_id
    WHERE ca.run_id = $1
      AND ca.cluster_id >= 0
    GROUP BY ca.public_cluster_id, ca.run_id
)
SELECT * FROM cluster_base;
"""

# ---------------------------------------------------------------------------
# Read: sub-window counts for growth_rate and sentiment_shift.
# Split window at midpoint computed in Python; two aggregations joined.
# ---------------------------------------------------------------------------
SELECT_SUBWINDOW_FEATURES_SQL = """
WITH half AS (
    SELECT
        ca.public_cluster_id,
        COUNT(*) FILTER (WHERE rm.message_date >= $2) AS recent_count,
        COUNT(*) FILTER (WHERE rm.message_date < $2)  AS prev_count,
        AVG(
            CASE
                WHEN sr.positive_prob IS NOT NULL OR sr.negative_prob IS NOT NULL
                    THEN COALESCE(sr.positive_prob, 0) - COALESCE(sr.negative_prob, 0)
                WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'positive'
                    THEN  COALESCE(sr.sentiment_score, 0)
                WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'negative'
                    THEN -COALESCE(sr.sentiment_score, 0)
                ELSE 0
            END
        ) FILTER (WHERE rm.message_date >= $2)         AS recent_sentiment,
        AVG(
            CASE
                WHEN sr.positive_prob IS NOT NULL OR sr.negative_prob IS NOT NULL
                    THEN COALESCE(sr.positive_prob, 0) - COALESCE(sr.negative_prob, 0)
                WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'positive'
                    THEN  COALESCE(sr.sentiment_score, 0)
                WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'negative'
                    THEN -COALESCE(sr.sentiment_score, 0)
                ELSE 0
            END
        ) FILTER (WHERE rm.message_date < $2)          AS prev_sentiment
    FROM cluster_assignments ca
    JOIN raw_messages rm ON rm.event_id = ca.event_id
    LEFT JOIN sentiment_results sr ON sr.event_id = ca.event_id
    WHERE ca.run_id = $1
      AND ca.cluster_id >= 0
    GROUP BY ca.public_cluster_id
)
SELECT * FROM half;
"""

# ---------------------------------------------------------------------------
# Read: NER features — unique entities + novelty
# ---------------------------------------------------------------------------
SELECT_NER_FEATURES_SQL = """
WITH cluster_entities AS (
    SELECT
        ca.public_cluster_id,
        COUNT(DISTINCT COALESCE(nr.normalized_text, nr.entity_text)) AS unique_entities,
        COUNT(nr.id) AS total_mentions
    FROM cluster_assignments ca
    JOIN raw_messages rm ON rm.event_id = ca.event_id
    JOIN ner_results nr ON nr.event_id = ca.event_id
    WHERE ca.run_id = $1
      AND ca.cluster_id >= 0
    GROUP BY ca.public_cluster_id
),
-- Novel entities: first seen within the history window that started BEFORE
-- this cluster's window_start; i.e. not appearing in earlier messages.
-- We approximate novelty as entity texts that do NOT appear in any
-- cluster_assignment that pre-dates this cluster's first_seen by history_window_days.
novel_entities AS (
    SELECT
        ca.public_cluster_id,
        COUNT(DISTINCT COALESCE(nr.normalized_text, nr.entity_text)) AS novel_count,
        COUNT(DISTINCT COALESCE(nr.normalized_text, nr.entity_text)) AS candidate_count
    FROM cluster_assignments ca
    JOIN raw_messages rm ON rm.event_id = ca.event_id
    JOIN ner_results nr ON nr.event_id = ca.event_id
    WHERE ca.run_id = $1
      AND ca.cluster_id >= 0
      AND NOT EXISTS (
          SELECT 1
          FROM ner_results nr2
          JOIN raw_messages rm2 ON rm2.event_id = nr2.event_id
          WHERE COALESCE(nr2.normalized_text, nr2.entity_text)
                = COALESCE(nr.normalized_text, nr.entity_text)
            AND rm2.message_date < rm.message_date - ($2 || ' days')::INTERVAL
            AND rm2.message_date >= rm.message_date - ($2 || ' days')::INTERVAL - INTERVAL '14 days'
      )
    GROUP BY ca.public_cluster_id
)
SELECT
    ce.public_cluster_id,
    ce.unique_entities,
    ce.total_mentions,
    COALESCE(ne.novel_count, 0)     AS novel_entity_count,
    COALESCE(ne.candidate_count, 0) AS candidate_entity_count
FROM cluster_entities ce
LEFT JOIN novel_entities ne ON ne.public_cluster_id = ce.public_cluster_id;
"""

# ---------------------------------------------------------------------------
# Read: new channel ratio — channels whose earliest appearance in ALL
# cluster_assignments is within this cluster's window.
# ---------------------------------------------------------------------------
SELECT_NEW_CHANNELS_SQL = """
WITH cluster_channels AS (
    SELECT
        ca.public_cluster_id,
        rm.channel,
        MIN(rm.message_date) OVER (PARTITION BY rm.channel) AS channel_first_ever
    FROM cluster_assignments ca
    JOIN raw_messages rm ON rm.event_id = ca.event_id
    WHERE ca.run_id = $1
      AND ca.cluster_id >= 0
),
agg AS (
    SELECT
        public_cluster_id,
        COUNT(DISTINCT channel)                                     AS total_channels,
        COUNT(DISTINCT channel) FILTER (
            WHERE channel_first_ever >= NOW() - ($2 || ' days')::INTERVAL
        )                                                           AS new_channels
    FROM cluster_channels
    GROUP BY public_cluster_id
)
SELECT public_cluster_id, total_channels, new_channels FROM agg;
"""

# ---------------------------------------------------------------------------
# Read: graph density from graph_subgraph_metrics (best-effort)
# ---------------------------------------------------------------------------
SELECT_GRAPH_DENSITY_SQL = """
SELECT DISTINCT ON (public_cluster_id)
    public_cluster_id,
    (metrics_json->>'density')::REAL      AS graph_density,
    (metrics_json->>'avg_degree')::REAL   AS graph_avg_degree
FROM graph_subgraph_metrics
WHERE public_cluster_id = ANY($1::varchar[])
ORDER BY public_cluster_id, computed_at DESC;
"""

# ---------------------------------------------------------------------------
# Write: persist scored topics
# ---------------------------------------------------------------------------
INSERT_TOPIC_SCORE_SQL = """
INSERT INTO topic_scores (
    public_cluster_id,
    run_id,
    importance_score,
    importance_level,
    score_breakdown_json,
    features_json,
    scoring_version,
    window_start,
    window_end
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9);
"""

INSERT_SCORING_RUN_SQL = """
INSERT INTO topic_scoring_runs (
    trigger,
    cluster_run_id,
    topics_scored,
    errors,
    duration_seconds,
    scoring_version,
    finished_at
) VALUES ($1, $2, $3, $4, $5, $6, NOW())
RETURNING run_uuid;
"""


class TopicScorerRepository:
    def __init__(self, pool: asyncpg.Pool, cfg: ScoringConfig) -> None:
        self._pool = pool
        self._cfg = cfg

    async def get_latest_run_id(self) -> Optional[str]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(SELECT_LATEST_RUN_SQL)
            return row["run_id"] if row else None

    async def get_cluster_ids(self, run_id: str) -> List[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(SELECT_CLUSTERS_IN_RUN_SQL, run_id)
            return [r["public_cluster_id"] for r in rows]

    async def fetch_all_features(
        self,
        run_id: str,
        mid_point: datetime,
        history_days: int,
    ) -> Dict[str, ClusterFeatures]:
        """Fetch all feature types sequentially and merge by public_cluster_id."""
        async with self._pool.acquire() as conn:
            base_rows = await conn.fetch(SELECT_BASE_FEATURES_SQL, run_id)
            subw_rows = await conn.fetch(SELECT_SUBWINDOW_FEATURES_SQL, run_id, mid_point)
            ner_rows = await conn.fetch(SELECT_NER_FEATURES_SQL, run_id, str(history_days))
            chan_rows = await conn.fetch(SELECT_NEW_CHANNELS_SQL, run_id, str(history_days))

        features: Dict[str, ClusterFeatures] = {}

        for r in base_rows:
            cid = r["public_cluster_id"]
            features[cid] = ClusterFeatures(
                public_cluster_id=cid,
                run_id=run_id,
                window_start=None,
                window_end=None,
                message_count=r["message_count"] or 0,
                unique_channels=r["unique_channels"] or 0,
                avg_sentiment=float(r["avg_sentiment"] or 0.0),
                negative_share=float(r["negative_share"] or 0.0),
                first_seen=r["first_seen"],
                last_seen=r["last_seen"],
            )

        for r in subw_rows:
            cid = r["public_cluster_id"]
            if cid in features:
                features[cid].recent_message_count = r["recent_count"] or 0
                features[cid].prev_message_count = r["prev_count"] or 0
                features[cid].recent_avg_sentiment = float(r["recent_sentiment"] or 0.0)
                features[cid].prev_avg_sentiment = float(r["prev_sentiment"] or 0.0)

        for r in ner_rows:
            cid = r["public_cluster_id"]
            if cid in features:
                features[cid].unique_entities = r["unique_entities"] or 0
                features[cid].novel_entity_count = r["novel_entity_count"] or 0
                features[cid].total_entity_count_for_novelty = r["candidate_entity_count"] or 0

        for r in chan_rows:
            cid = r["public_cluster_id"]
            if cid in features:
                features[cid].new_channel_count = r["new_channels"] or 0

        # Graph density — best-effort batch lookup
        cluster_ids = list(features.keys())
        if cluster_ids:
            async with self._pool.acquire() as conn:
                graph_rows = await conn.fetch(SELECT_GRAPH_DENSITY_SQL, cluster_ids)
            for r in graph_rows:
                cid = r["public_cluster_id"]
                if cid in features:
                    features[cid].graph_density = r["graph_density"]
                    features[cid].graph_avg_degree = r["graph_avg_degree"]

        return features

    async def fetch_features_for_cluster(
        self,
        run_id: str,
        public_cluster_id: str,
        mid_point: datetime,
        history_days: int,
    ) -> Optional[ClusterFeatures]:
        """On-demand single-cluster feature fetch."""
        all_features = await self.fetch_all_features(run_id, mid_point, history_days)
        return all_features.get(public_cluster_id)

    async def persist_scores(self, scores: Sequence[TopicScore]) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    INSERT_TOPIC_SCORE_SQL,
                    [
                        (
                            s.public_cluster_id,
                            s.run_id,
                            s.importance_score,
                            s.importance_level,
                            json.dumps(s.breakdown_json()),
                            json.dumps(s.features_json()),
                            s.scoring_version,
                            s.window_start,
                            s.window_end,
                        )
                        for s in scores
                    ],
                )

    async def record_scoring_run(
        self,
        trigger: str,
        cluster_run_id: Optional[str],
        topics_scored: int,
        errors: int,
        duration_seconds: float,
        scoring_version: str,
    ) -> str:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                INSERT_SCORING_RUN_SQL,
                trigger,
                cluster_run_id,
                topics_scored,
                errors,
                duration_seconds,
                scoring_version,
            )
            return str(row["run_uuid"])

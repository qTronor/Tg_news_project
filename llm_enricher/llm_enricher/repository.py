from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg

from llm_enricher.schemas import (
    ClusterEnrichmentInput,
    EvolutionEvent,
    GraphTopNode,
    RepresentativeMessage,
    SentimentSummary,
    TimelineBucket,
    TopEntity,
)

logger = logging.getLogger("llm_enricher.repository")

_SUMMARY_TTL_SECONDS = 7 * 24 * 3600  # 7 days

_Q_READ_SUMMARY = """
SELECT payload_json, status, model_provider, model_name, prompt_version,
       generated_at, expires_at, input_fingerprint
FROM topic_summaries
WHERE public_cluster_id = $1 AND summary_kind = $2 AND language = $3
  AND expires_at > NOW();
"""

_Q_UPSERT_SUMMARY = """
INSERT INTO topic_summaries (
    public_cluster_id, summary_kind, language, prompt_version,
    model_provider, model_name, input_fingerprint,
    payload_json, status, generated_at, expires_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), $10)
ON CONFLICT (public_cluster_id, summary_kind, language) DO UPDATE SET
    prompt_version    = EXCLUDED.prompt_version,
    model_provider    = EXCLUDED.model_provider,
    model_name        = EXCLUDED.model_name,
    input_fingerprint = EXCLUDED.input_fingerprint,
    payload_json      = EXCLUDED.payload_json,
    status            = EXCLUDED.status,
    generated_at      = NOW(),
    expires_at        = EXCLUDED.expires_at;
"""

_Q_INSERT_RUN = """
INSERT INTO topic_summary_runs (
    public_cluster_id, triggered_by, language, kinds_requested,
    kinds_succeeded, kinds_failed, total_cost_usd, total_latency_ms,
    started_at, finished_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10);
"""


@dataclass
class SummaryRecord:
    payload: dict[str, Any]
    status: str
    model_provider: str
    model_name: str
    prompt_version: str
    generated_at: Optional[datetime]
    input_fingerprint: str

_Q_CLUSTER_LANG_SENTIMENT = """
WITH cluster_msgs AS (
    SELECT ca.event_id, ca.channel
    FROM cluster_assignments ca
    WHERE ca.public_cluster_id = $1
),
lang_vote AS (
    SELECT pm.language, COUNT(*) AS cnt
    FROM cluster_msgs cm
    JOIN preprocessed_messages pm ON pm.event_id = cm.event_id
    WHERE pm.language IS NOT NULL
    GROUP BY pm.language
    ORDER BY cnt DESC
    LIMIT 1
),
sentiment_agg AS (
    SELECT
        AVG(sr.positive_prob) AS positive_prob,
        AVG(sr.negative_prob) AS negative_prob,
        AVG(sr.neutral_prob) AS neutral_prob,
        mode() WITHIN GROUP (ORDER BY
            CASE
                WHEN sr.emotion_joy IS NOT NULL AND sr.emotion_joy > 0.4 THEN 'joy'
                WHEN sr.emotion_anger IS NOT NULL AND sr.emotion_anger > 0.4 THEN 'anger'
                WHEN sr.emotion_sadness IS NOT NULL AND sr.emotion_sadness > 0.4 THEN 'sadness'
                WHEN sr.emotion_fear IS NOT NULL AND sr.emotion_fear > 0.4 THEN 'fear'
                ELSE NULL
            END
        ) AS dominant_emotion
    FROM cluster_msgs cm
    JOIN sentiment_results sr ON sr.event_id = cm.event_id
)
SELECT
    (SELECT language FROM lang_vote) AS language,
    (SELECT positive_prob FROM sentiment_agg) AS positive_prob,
    (SELECT negative_prob FROM sentiment_agg) AS negative_prob,
    (SELECT neutral_prob FROM sentiment_agg) AS neutral_prob,
    (SELECT dominant_emotion FROM sentiment_agg) AS dominant_emotion;
"""

_Q_REPR_MESSAGES = """
SELECT rm.text AS original_text, rm.channel, rm.message_date AS published_at, ca.cluster_probability
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
ORDER BY ca.cluster_probability DESC
LIMIT 5;
"""

_Q_TOP_ENTITIES = """
SELECT nr.normalized_text, nr.entity_type, COUNT(*) AS mention_count
FROM cluster_assignments ca
JOIN ner_results nr ON nr.event_id = ca.event_id
WHERE ca.public_cluster_id = $1 AND nr.normalized_text IS NOT NULL
GROUP BY nr.normalized_text, nr.entity_type
ORDER BY mention_count DESC
LIMIT 10;
"""

_Q_IMPORTANCE = """
SELECT importance_score, importance_level, score_breakdown_json, features_json
FROM topic_scores_latest
WHERE public_cluster_id = $1;
"""

_Q_TIMELINE = """
SELECT
    bucket_start, bucket_end, message_count, unique_channel_count,
    top_entities_json, sentiment_json, new_channels_json
FROM topic_timeline_points
WHERE public_cluster_id = $1
ORDER BY bucket_start DESC
LIMIT 10;
"""

_Q_EVOLUTION = """
SELECT event_type, severity, summary, details_json
FROM topic_evolution_events
WHERE public_cluster_id = $1
ORDER BY created_at DESC
LIMIT 10;
"""

_Q_GRAPH_NODES = """
SELECT gtn.node_label, gtn.node_type, gtn.pagerank, gtn.bridge_score, gtn.is_bridge
FROM graph_subgraph_metrics gsm
JOIN graph_top_nodes gtn ON gtn.cache_key = gsm.cache_key
WHERE gsm.public_cluster_id = $1
ORDER BY gtn.rank ASC
LIMIT 5;
"""

_Q_GRAPH_COMMUNITY = """
SELECT gtc.summary_json
FROM graph_subgraph_metrics gsm
JOIN graph_topic_communities gtc ON gtc.cache_key = gsm.cache_key
WHERE gsm.public_cluster_id = $1
LIMIT 1;
"""

_Q_GRAPH_METRICS = """
SELECT metrics_json
FROM graph_subgraph_metrics
WHERE public_cluster_id = $1
LIMIT 1;
"""


def _lang_to_mode(language: Optional[str]) -> str:
    if language in ("ru", "en"):
        return "full"
    if language in (None, "und", ""):
        return "unknown"
    return "partial"


class ClusterContextRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _q(self, query: str, *args, one: bool = False):
        async with self._pool.acquire() as conn:
            if one:
                return await conn.fetchrow(query, *args)
            return await conn.fetch(query, *args)

    async def fetch(self, public_cluster_id: str) -> ClusterEnrichmentInput:
        # Run all queries concurrently; each gets its own pool connection
        (
            lang_row,
            repr_rows,
            entity_rows,
            importance_row,
            timeline_rows,
            evolution_rows,
            graph_nodes_rows,
            graph_community_row,
            graph_metrics_row,
        ) = await asyncio.gather(
            self._q(_Q_CLUSTER_LANG_SENTIMENT, public_cluster_id, one=True),
            self._q(_Q_REPR_MESSAGES, public_cluster_id),
            self._q(_Q_TOP_ENTITIES, public_cluster_id),
            self._q(_Q_IMPORTANCE, public_cluster_id, one=True),
            self._q(_Q_TIMELINE, public_cluster_id),
            self._q(_Q_EVOLUTION, public_cluster_id),
            self._q(_Q_GRAPH_NODES, public_cluster_id),
            self._q(_Q_GRAPH_COMMUNITY, public_cluster_id, one=True),
            self._q(_Q_GRAPH_METRICS, public_cluster_id, one=True),
        )

        language = lang_row["language"] if lang_row else "und"
        analysis_mode = _lang_to_mode(language)

        sentiment_summary: Optional[SentimentSummary] = None
        if lang_row and lang_row["positive_prob"] is not None:
            sentiment_summary = SentimentSummary(
                positive_prob=float(lang_row["positive_prob"] or 0),
                negative_prob=float(lang_row["negative_prob"] or 0),
                neutral_prob=float(lang_row["neutral_prob"] or 0),
                dominant_emotion=lang_row["dominant_emotion"],
            )

        repr_messages = [
            RepresentativeMessage(
                text=r["original_text"] or "",
                channel=r["channel"] or "",
                posted_at=str(r["published_at"]) if r["published_at"] else None,
                cluster_probability=float(r["cluster_probability"] or 0),
            )
            for r in repr_rows
        ]

        top_entities = [
            TopEntity(
                normalized_text=r["normalized_text"],
                entity_type=r["entity_type"],
                mention_count=int(r["mention_count"]),
            )
            for r in entity_rows
        ]

        importance_score: Optional[float] = None
        importance_level: Optional[str] = None
        score_breakdown: Optional[dict[str, Any]] = None
        features: Optional[dict[str, Any]] = None
        if importance_row:
            importance_score = float(importance_row["importance_score"] or 0)
            importance_level = importance_row["importance_level"]
            raw_bd = importance_row["score_breakdown_json"]
            raw_ft = importance_row["features_json"]
            score_breakdown = json.loads(raw_bd) if isinstance(raw_bd, str) else raw_bd
            features = json.loads(raw_ft) if isinstance(raw_ft, str) else raw_ft

        timeline_buckets = [
            TimelineBucket(
                bucket_start=str(r["bucket_start"]),
                bucket_end=str(r["bucket_end"]),
                message_count=int(r["message_count"] or 0),
                unique_channel_count=int(r["unique_channel_count"] or 0),
                top_entities=_parse_json(r["top_entities_json"]) or [],
                sentiment=_parse_json(r["sentiment_json"]) or {},
                new_channels=_parse_json(r["new_channels_json"]) or [],
            )
            for r in timeline_rows
        ]

        evolution_events = [
            EvolutionEvent(
                event_type=r["event_type"],
                severity=float(r["severity"] or 0),
                summary=r["summary"] or "",
                details=_parse_json(r["details_json"]) or {},
            )
            for r in evolution_rows
        ]

        graph_top_nodes = [
            GraphTopNode(
                node_label=r["node_label"],
                node_type=r["node_type"],
                pagerank=float(r["pagerank"] or 0),
                bridge_score=float(r["bridge_score"] or 0),
                is_bridge=bool(r["is_bridge"]),
            )
            for r in graph_nodes_rows
        ]

        graph_community_summary: Optional[dict[str, Any]] = None
        if graph_community_row:
            graph_community_summary = _parse_json(graph_community_row["summary_json"])

        graph_subgraph_metrics: Optional[dict[str, Any]] = None
        if graph_metrics_row:
            graph_subgraph_metrics = _parse_json(graph_metrics_row["metrics_json"])

        return ClusterEnrichmentInput(
            public_cluster_id=public_cluster_id,
            language=language or "und",
            analysis_mode=analysis_mode,
            importance_score=importance_score,
            importance_level=importance_level,
            score_breakdown=score_breakdown,
            features=features,
            representative_messages=repr_messages,
            top_entities=top_entities,
            sentiment_summary=sentiment_summary,
            timeline_buckets=timeline_buckets,
            evolution_events=evolution_events,
            graph_top_nodes=graph_top_nodes,
            graph_community_summary=graph_community_summary,
            graph_subgraph_metrics=graph_subgraph_metrics,
        )


    async def read_summary(
        self,
        public_cluster_id: str,
        summary_kind: str,
        language: str,
        input_fingerprint: str,
        refresh: bool,
    ) -> Optional[SummaryRecord]:
        if refresh:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_Q_READ_SUMMARY, public_cluster_id, summary_kind, language)
        if row is None:
            return None
        if row["input_fingerprint"] != input_fingerprint:
            return None
        raw = row["payload_json"]
        payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        return SummaryRecord(
            payload=payload,
            status=row["status"],
            model_provider=row["model_provider"],
            model_name=row["model_name"],
            prompt_version=row["prompt_version"],
            generated_at=row["generated_at"],
            input_fingerprint=row["input_fingerprint"],
        )

    async def upsert_summary(
        self,
        public_cluster_id: str,
        summary_kind: str,
        language: str,
        prompt_version: str,
        model_provider: str,
        model_name: str,
        input_fingerprint: str,
        payload: dict[str, Any],
        status: str,
    ) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=_SUMMARY_TTL_SECONDS)
        payload_str = json.dumps(payload, ensure_ascii=False)
        async with self._pool.acquire() as conn:
            await conn.execute(
                _Q_UPSERT_SUMMARY,
                public_cluster_id,
                summary_kind,
                language,
                prompt_version,
                model_provider,
                model_name,
                input_fingerprint,
                payload_str,
                status,
                expires_at,
            )

    async def record_run(
        self,
        public_cluster_id: str,
        triggered_by: str,
        language: str,
        kinds_requested: list[str],
        kinds_succeeded: list[str],
        kinds_failed: list[str],
        total_cost_usd: float,
        total_latency_ms: int,
        started_at: datetime,
    ) -> None:
        finished_at = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            await conn.execute(
                _Q_INSERT_RUN,
                public_cluster_id,
                triggered_by,
                language,
                kinds_requested,
                kinds_succeeded,
                kinds_failed,
                total_cost_usd,
                total_latency_ms,
                started_at,
                finished_at,
            )


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value

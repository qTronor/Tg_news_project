from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import unquote

import asyncpg
import httpx
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from analytics_api.config import AppConfig
from analytics_api.graph_analytics import ALGO_VERSION, analyze_topic_graph, build_topic_graph
from analytics_api.metrics import (
    API_REQUEST_LATENCY,
    API_REQUESTS_TOTAL,
    GRAPH_ANALYTICS_CACHE_TOTAL,
    GRAPH_ANALYTICS_DURATION,
    GRAPH_ANALYTICS_RUNS_TOTAL,
    TOPIC_COMPARISON_CACHE_TOTAL,
    TOPIC_COMPARISON_DURATION,
    TOPIC_COMPARISON_RUNS_TOTAL,
    TOPIC_TIMELINE_REBUILD_DURATION,
    TOPIC_TIMELINE_REBUILDS_TOTAL,
)
from analytics_api.topic_comparison import (
    ALGO_VERSION as TOPIC_COMPARISON_ALGO_VERSION,
    TopicComparisonProfile,
    compare_topics,
)
from analytics_api.topic_evolution import (
    EvolutionEvent,
    TimelinePoint,
    TopicEntity,
    TopicMessage,
    build_timeline_points,
    detect_evolution_events,
    floor_bucket,
    normalize_bucket_size,
)


logger = logging.getLogger("analytics_api")

SIGNED_SENTIMENT_SQL = """
CASE
    WHEN sr.positive_prob IS NOT NULL OR sr.negative_prob IS NOT NULL
        THEN COALESCE(sr.positive_prob, 0) - COALESCE(sr.negative_prob, 0)
    WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'positive'
        THEN COALESCE(sr.sentiment_score, 0)
    WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'negative'
        THEN -COALESCE(sr.sentiment_score, 0)
    ELSE 0
END
"""

SELECT_LATEST_RUN_SQL = """
SELECT run_id
FROM cluster_runs_pg
ORDER BY run_timestamp DESC
LIMIT 1;
"""

SELECT_CLUSTER_OVERVIEW_BASE_SQL = f"""
SELECT
    ca.public_cluster_id,
    count(*) AS message_count,
    count(DISTINCT rm.channel) AS channel_count,
    COALESCE(avg({SIGNED_SENTIMENT_SQL}), 0) AS avg_sentiment,
    min(rm.message_date) AS first_seen,
    max(rm.message_date) AS last_seen
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
LEFT JOIN sentiment_results sr ON sr.event_id = ca.event_id
WHERE ca.run_id = $1
  AND ca.cluster_id >= 0
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY ca.public_cluster_id
ORDER BY message_count DESC, last_seen DESC;
"""

SELECT_CLUSTER_OVERVIEW_DATES_SQL = """
SELECT ca.public_cluster_id, rm.message_date
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
WHERE ca.run_id = $1
  AND ca.cluster_id >= 0
  AND rm.message_date >= $2
  AND rm.message_date <= $3
ORDER BY rm.message_date ASC;
"""

SELECT_CLUSTER_OVERVIEW_ENTITIES_SQL = """
SELECT
    ca.public_cluster_id,
    lower(COALESCE(nr.normalized_text, nr.entity_text)) AS entity_key,
    COALESCE(max(nr.normalized_text), min(nr.entity_text)) AS entity_text,
    nr.entity_type,
    count(*) AS mention_count
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
JOIN ner_results nr ON nr.event_id = ca.event_id
WHERE ca.run_id = $1
  AND ca.cluster_id >= 0
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY
    ca.public_cluster_id,
    lower(COALESCE(nr.normalized_text, nr.entity_text)),
    nr.entity_type
ORDER BY ca.public_cluster_id, mention_count DESC, entity_text ASC;
"""

SELECT_CLUSTER_OVERVIEW_CHANNELS_SQL = """
SELECT
    ca.public_cluster_id,
    rm.channel,
    count(*) AS message_count
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
WHERE ca.run_id = $1
  AND ca.cluster_id >= 0
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY ca.public_cluster_id, rm.channel
ORDER BY ca.public_cluster_id, message_count DESC, rm.channel ASC;
"""

SELECT_CLUSTER_SOURCE_RESOLUTIONS_SQL = """
SELECT
    public_cluster_id,
    resolution_kind,
    source_type,
    source_confidence,
    source_event_id,
    source_channel,
    source_message_id,
    source_message_date,
    source_snippet,
    explanation_json,
    evidence_json
FROM cluster_source_resolutions
WHERE run_id = $1;
"""

SELECT_CLUSTER_STATS_SQL = f"""
SELECT
    count(*) AS message_count,
    count(DISTINCT rm.channel) AS channel_count,
    COALESCE(avg({SIGNED_SENTIMENT_SQL}), 0) AS avg_sentiment,
    min(rm.message_date) AS first_seen,
    max(rm.message_date) AS last_seen
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
LEFT JOIN sentiment_results sr ON sr.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND rm.message_date >= $2
  AND rm.message_date <= $3;
"""

SELECT_CLUSTER_DOCUMENTS_SQL = f"""
SELECT
    rm.event_id,
    rm.channel,
    rm.message_id,
    rm.permalink,
    rm.text,
    rm.message_date,
    COALESCE(rm.views, 0) AS views,
    COALESCE(rm.forwards, 0) AS forwards,
    ca.public_cluster_id,
    lower(COALESCE(sr.sentiment_label, 'neutral')) AS sentiment_label,
    COALESCE(sr.sentiment_score, 0) AS sentiment_confidence,
    COALESCE(sr.positive_prob, 0) AS positive_prob,
    COALESCE(sr.negative_prob, 0) AS negative_prob,
    COALESCE(sr.neutral_prob, 0) AS neutral_prob,
    {SIGNED_SENTIMENT_SQL} AS ui_sentiment_score
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
LEFT JOIN sentiment_results sr ON sr.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND rm.message_date >= $2
  AND rm.message_date <= $3
ORDER BY rm.message_date DESC, rm.event_id DESC
LIMIT $4 OFFSET $5;
"""

SELECT_CLUSTER_CHANNELS_SQL = """
SELECT rm.channel, count(*) AS message_count
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY rm.channel
ORDER BY message_count DESC, rm.channel ASC;
"""

SELECT_CLUSTER_TOP_ENTITIES_SQL = """
SELECT
    lower(COALESCE(nr.normalized_text, nr.entity_text)) AS entity_key,
    COALESCE(max(nr.normalized_text), min(nr.entity_text)) AS entity_text,
    nr.entity_type,
    count(*) AS mention_count
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
JOIN ner_results nr ON nr.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY lower(COALESCE(nr.normalized_text, nr.entity_text)), nr.entity_type
ORDER BY mention_count DESC, entity_text ASC
LIMIT $4;
"""

SELECT_CLUSTER_SENTIMENT_BREAKDOWN_SQL = """
SELECT lower(COALESCE(sr.sentiment_label, 'neutral')) AS sentiment_label, count(*) AS message_count
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
LEFT JOIN sentiment_results sr ON sr.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY lower(COALESCE(sr.sentiment_label, 'neutral'));
"""

SELECT_CLUSTER_VOLUME_TIMELINE_SQL = """
SELECT date_trunc($4::text, rm.message_date) AS bucket, count(*) AS message_count
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY bucket
ORDER BY bucket ASC;
"""

SELECT_TOPIC_TIMELINE_MESSAGES_SQL = f"""
SELECT
    ca.run_id,
    rm.event_id,
    rm.channel,
    rm.message_date,
    lower(COALESCE(sr.sentiment_label, 'neutral')) AS sentiment_label,
    {SIGNED_SENTIMENT_SQL} AS signed_sentiment
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
LEFT JOIN sentiment_results sr ON sr.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND ca.cluster_id >= 0
  AND rm.message_date >= $2
  AND rm.message_date <= $3
ORDER BY rm.message_date ASC, rm.event_id ASC;
"""

SELECT_TOPIC_TIMELINE_ENTITIES_SQL = """
SELECT
    nr.event_id,
    lower(COALESCE(nr.normalized_text, nr.entity_text)) AS entity_key,
    COALESCE(max(nr.normalized_text), min(nr.entity_text)) AS entity_text,
    nr.entity_type,
    count(*) AS mention_count
FROM ner_results nr
WHERE nr.event_id = ANY($1::varchar[])
GROUP BY nr.event_id, lower(COALESCE(nr.normalized_text, nr.entity_text)), nr.entity_type
ORDER BY nr.event_id ASC, mention_count DESC, entity_text ASC;
"""

SELECT_TOPIC_TIMELINE_POINTS_SQL = """
SELECT
    bucket_start,
    bucket_end,
    message_count,
    unique_channel_count,
    top_entities_json,
    sentiment_json,
    new_channels_json,
    event_ids_json,
    calculated_at
FROM topic_timeline_points
WHERE public_cluster_id = $1
  AND bucket_size = $2
  AND bucket_start >= $3
  AND bucket_start <= $4
ORDER BY bucket_start ASC;
"""

SELECT_TOPIC_EVOLUTION_EVENTS_SQL = """
SELECT
    event_type,
    event_time,
    bucket_start,
    severity,
    summary,
    details_json,
    created_at
FROM topic_evolution_events
WHERE public_cluster_id = $1
  AND bucket_size = $2
  AND event_time >= $3
  AND event_time <= $4
ORDER BY event_time ASC, event_type ASC;
"""

DELETE_TOPIC_TIMELINE_POINTS_SQL = """
DELETE FROM topic_timeline_points
WHERE public_cluster_id = $1
  AND bucket_size = $2
  AND bucket_start >= $3
  AND bucket_start <= $4;
"""

DELETE_TOPIC_EVOLUTION_EVENTS_SQL = """
DELETE FROM topic_evolution_events
WHERE public_cluster_id = $1
  AND bucket_size = $2
  AND event_time >= $3
  AND event_time <= $4;
"""

INSERT_TOPIC_TIMELINE_POINT_SQL = """
INSERT INTO topic_timeline_points (
    public_cluster_id,
    run_id,
    bucket_size,
    bucket_start,
    bucket_end,
    message_count,
    unique_channel_count,
    top_entities_json,
    sentiment_json,
    new_channels_json,
    event_ids_json,
    calculated_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, NOW())
ON CONFLICT (public_cluster_id, bucket_size, bucket_start) DO UPDATE SET
    run_id = EXCLUDED.run_id,
    bucket_end = EXCLUDED.bucket_end,
    message_count = EXCLUDED.message_count,
    unique_channel_count = EXCLUDED.unique_channel_count,
    top_entities_json = EXCLUDED.top_entities_json,
    sentiment_json = EXCLUDED.sentiment_json,
    new_channels_json = EXCLUDED.new_channels_json,
    event_ids_json = EXCLUDED.event_ids_json,
    calculated_at = EXCLUDED.calculated_at;
"""

INSERT_TOPIC_EVOLUTION_EVENT_SQL = """
INSERT INTO topic_evolution_events (
    public_cluster_id,
    run_id,
    bucket_size,
    event_type,
    event_time,
    bucket_start,
    severity,
    summary,
    details_json,
    created_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, NOW())
ON CONFLICT (public_cluster_id, bucket_size, event_type, bucket_start, summary) DO UPDATE SET
    run_id = EXCLUDED.run_id,
    event_time = EXCLUDED.event_time,
    severity = EXCLUDED.severity,
    details_json = EXCLUDED.details_json,
    created_at = EXCLUDED.created_at;
"""

INSERT_TOPIC_TIMELINE_REBUILD_RUN_SQL = """
INSERT INTO topic_timeline_rebuild_runs (
    public_cluster_id,
    run_id,
    bucket_size,
    window_start,
    window_end,
    points_written,
    events_written,
    status,
    error_message,
    finished_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW());
"""

SELECT_PROPAGATION_LINKS_SQL = """
SELECT
    mpl.child_event_id,
    mpl.child_channel,
    mpl.child_message_id,
    mpl.parent_event_id,
    mpl.parent_channel,
    mpl.parent_message_id,
    mpl.link_type,
    mpl.link_confidence,
    mpl.resolution_kind,
    mpl.explanation_json,
    mpl.evidence_json,
    child_rm.message_date AS child_message_date,
    parent_rm.message_date AS parent_message_date
FROM message_propagation_links mpl
LEFT JOIN raw_messages child_rm ON child_rm.event_id = mpl.child_event_id
LEFT JOIN raw_messages parent_rm ON parent_rm.event_id = mpl.parent_event_id
WHERE mpl.public_cluster_id = $1
ORDER BY child_rm.message_date ASC NULLS LAST, mpl.child_event_id ASC;
"""

SELECT_TOPIC_SCORES_FOR_RUN_SQL = """
SELECT
    public_cluster_id,
    importance_score,
    importance_level,
    score_breakdown_json,
    calculated_at
FROM topic_scores_latest
WHERE run_id = $1;
"""

SELECT_TOPIC_SCORE_FOR_CLUSTER_SQL = """
SELECT
    importance_score,
    importance_level,
    score_breakdown_json,
    calculated_at
FROM topic_scores_latest
WHERE public_cluster_id = $1
LIMIT 1;
"""

SELECT_TOPIC_COMPARISON_CACHE_SQL = """
SELECT result_json
FROM topic_comparison_cache
WHERE cache_key = $1
  AND expires_at > NOW();
"""

UPSERT_TOPIC_COMPARISON_CACHE_SQL = """
INSERT INTO topic_comparison_cache (
    cache_key,
    cluster_a_id,
    cluster_b_id,
    window_start,
    window_end,
    algorithm_version,
    result_json,
    computed_at,
    expires_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7::jsonb, NOW(), NOW() + ($8::text)::interval
)
ON CONFLICT (cache_key) DO UPDATE SET
    cluster_a_id = EXCLUDED.cluster_a_id,
    cluster_b_id = EXCLUDED.cluster_b_id,
    window_start = EXCLUDED.window_start,
    window_end = EXCLUDED.window_end,
    algorithm_version = EXCLUDED.algorithm_version,
    result_json = EXCLUDED.result_json,
    computed_at = EXCLUDED.computed_at,
    expires_at = EXCLUDED.expires_at;
"""

SELECT_TOPIC_COMPARE_PROFILE_SQL = f"""
SELECT
    ca.public_cluster_id,
    count(*) AS message_count,
    COALESCE(avg({SIGNED_SENTIMENT_SQL}), 0) AS avg_sentiment,
    min(rm.message_date) AS first_seen,
    max(rm.message_date) AS last_seen
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
LEFT JOIN sentiment_results sr ON sr.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND ca.cluster_id >= 0
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY ca.public_cluster_id;
"""

SELECT_TOPIC_COMPARE_ENTITIES_SQL = """
SELECT
    lower(COALESCE(nr.normalized_text, nr.entity_text)) AS entity_key,
    COALESCE(max(nr.normalized_text), min(nr.entity_text)) AS entity_text,
    nr.entity_type,
    count(*) AS mention_count
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
JOIN ner_results nr ON nr.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND ca.cluster_id >= 0
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY lower(COALESCE(nr.normalized_text, nr.entity_text)), nr.entity_type
ORDER BY mention_count DESC, entity_text ASC
LIMIT 100;
"""

SELECT_TOPIC_COMPARE_CHANNELS_SQL = """
SELECT rm.channel, count(*) AS message_count
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND ca.cluster_id >= 0
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY rm.channel
ORDER BY message_count DESC, rm.channel ASC
LIMIT 100;
"""

SELECT_TOPIC_COMPARE_MESSAGES_SQL = f"""
SELECT
    rm.event_id,
    rm.channel,
    rm.message_id,
    rm.permalink,
    rm.text,
    rm.message_date,
    COALESCE(rm.views, 0) AS views,
    COALESCE(rm.forwards, 0) AS forwards,
    pm.normalized_text_hash,
    pm.primary_url_fingerprint,
    pm.simhash64,
    {SIGNED_SENTIMENT_SQL} AS signed_sentiment
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
LEFT JOIN preprocessed_messages pm ON pm.event_id = ca.event_id
LEFT JOIN sentiment_results sr ON sr.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND ca.cluster_id >= 0
  AND rm.message_date >= $2
  AND rm.message_date <= $3
ORDER BY (COALESCE(rm.views, 0) + COALESCE(rm.forwards, 0) * 25) DESC,
         rm.message_date DESC,
         rm.event_id DESC
LIMIT $4;
"""

SELECT_RELATED_CLUSTERS_SQL = """
WITH current_entities AS (
    SELECT DISTINCT lower(COALESCE(nr.normalized_text, nr.entity_text)) AS entity_key
    FROM cluster_assignments ca
    JOIN ner_results nr ON nr.event_id = ca.event_id
    WHERE ca.public_cluster_id = $1
),
cluster_run AS (
    SELECT run_id
    FROM cluster_assignments
    WHERE public_cluster_id = $1
    LIMIT 1
)
SELECT ca.public_cluster_id, count(*) AS overlap
FROM cluster_assignments ca
JOIN cluster_run cr ON cr.run_id = ca.run_id
JOIN ner_results nr ON nr.event_id = ca.event_id
JOIN current_entities ce
  ON ce.entity_key = lower(COALESCE(nr.normalized_text, nr.entity_text))
WHERE ca.public_cluster_id <> $1
GROUP BY ca.public_cluster_id
ORDER BY overlap DESC, ca.public_cluster_id ASC
LIMIT $2;
"""

SELECT_MESSAGE_ENTITIES_SQL = """
SELECT
    event_id,
    lower(COALESCE(normalized_text, entity_text)) AS entity_key,
    COALESCE(max(normalized_text), min(entity_text)) AS entity_text,
    entity_type,
    count(*) AS mention_count
FROM ner_results
WHERE event_id = ANY($1::varchar[])
GROUP BY event_id, lower(COALESCE(normalized_text, entity_text)), entity_type
ORDER BY event_id ASC, mention_count DESC, entity_text ASC;
"""

SELECT_MESSAGE_SOURCE_RESOLUTIONS_SQL = """
SELECT
    message_event_id,
    resolution_kind,
    source_type,
    source_confidence,
    source_event_id,
    source_channel,
    source_message_id,
    source_message_date,
    source_snippet,
    explanation_json,
    evidence_json
FROM message_source_resolutions
WHERE message_event_id = ANY($1::varchar[]);
"""

SELECT_OVERVIEW_TOTAL_MESSAGES_SQL = """
SELECT count(*) AS total_messages, count(DISTINCT channel) AS active_channels
FROM raw_messages
WHERE message_date >= $1
  AND message_date <= $2;
"""

SELECT_TOP_ENTITIES_SQL = """
SELECT
    lower(COALESCE(nr.normalized_text, nr.entity_text)) AS entity_key,
    COALESCE(max(nr.normalized_text), min(nr.entity_text)) AS entity_text,
    nr.entity_type,
    count(*) AS mention_count,
    count(DISTINCT COALESCE(ca.public_cluster_id, 'unclustered')) AS topic_count,
    count(DISTINCT rm.channel) AS channel_count
FROM raw_messages rm
JOIN ner_results nr ON nr.event_id = rm.event_id
LEFT JOIN cluster_assignments ca
  ON ca.event_id = rm.event_id
 AND ca.run_id = $1
 AND ca.cluster_id >= 0
WHERE rm.message_date >= $2
  AND rm.message_date <= $3
  AND ($4::varchar IS NULL OR nr.entity_type = $4::varchar)
  AND ($5::varchar IS NULL OR ca.public_cluster_id = $5::varchar)
GROUP BY lower(COALESCE(nr.normalized_text, nr.entity_text)), nr.entity_type
ORDER BY mention_count DESC, entity_text ASC
LIMIT $6;
"""

SELECT_SENTIMENT_DYNAMICS_SQL = """
SELECT
    date_trunc($4::text, rm.message_date) AS bucket,
    lower(COALESCE(sr.sentiment_label, 'neutral')) AS sentiment_label,
    count(*) AS message_count
FROM raw_messages rm
LEFT JOIN sentiment_results sr ON sr.event_id = rm.event_id
LEFT JOIN cluster_assignments ca
  ON ca.event_id = rm.event_id
 AND ca.run_id = $5
 AND ca.cluster_id >= 0
WHERE rm.message_date >= $1
  AND rm.message_date <= $2
  AND ($3::varchar IS NULL OR rm.channel = $3::varchar)
  AND ($6::varchar IS NULL OR ca.public_cluster_id = $6::varchar)
GROUP BY bucket, lower(COALESCE(sr.sentiment_label, 'neutral'))
ORDER BY bucket ASC, sentiment_label ASC;
"""

SELECT_MESSAGES_SQL = f"""
SELECT
    rm.event_id,
    rm.channel,
    rm.message_id,
    rm.permalink,
    rm.text,
    rm.message_date,
    COALESCE(rm.views, 0) AS views,
    COALESCE(rm.forwards, 0) AS forwards,
    ca.public_cluster_id,
    lower(COALESCE(sr.sentiment_label, 'neutral')) AS sentiment_label,
    COALESCE(sr.sentiment_score, 0) AS sentiment_confidence,
    COALESCE(sr.positive_prob, 0) AS positive_prob,
    COALESCE(sr.negative_prob, 0) AS negative_prob,
    COALESCE(sr.neutral_prob, 0) AS neutral_prob,
    {SIGNED_SENTIMENT_SQL} AS ui_sentiment_score
FROM raw_messages rm
LEFT JOIN cluster_assignments ca
  ON ca.event_id = rm.event_id
 AND ca.run_id = $1
 AND ca.cluster_id >= 0
LEFT JOIN sentiment_results sr ON sr.event_id = rm.event_id
WHERE rm.message_date >= $2
  AND rm.message_date <= $3
  AND ($4::varchar IS NULL OR rm.channel = $4::varchar)
  AND ($5::varchar IS NULL OR ca.public_cluster_id = $5::varchar)
  AND ($6::varchar IS NULL OR lower(COALESCE(rm.text, '')) LIKE '%' || lower($6) || '%')
  AND ($7::varchar IS NULL OR lower(COALESCE(sr.sentiment_label, 'neutral')) = $7::varchar)
ORDER BY rm.message_date DESC, rm.event_id DESC
LIMIT $8 OFFSET $9;
"""

SELECT_MESSAGE_BY_EVENT_ID_SQL = f"""
SELECT
    rm.event_id,
    rm.channel,
    rm.message_id,
    rm.permalink,
    rm.text,
    rm.message_date,
    COALESCE(rm.views, 0) AS views,
    COALESCE(rm.forwards, 0) AS forwards,
    ca.public_cluster_id,
    lower(COALESCE(sr.sentiment_label, 'neutral')) AS sentiment_label,
    COALESCE(sr.sentiment_score, 0) AS sentiment_confidence,
    COALESCE(sr.positive_prob, 0) AS positive_prob,
    COALESCE(sr.negative_prob, 0) AS negative_prob,
    COALESCE(sr.neutral_prob, 0) AS neutral_prob,
    {SIGNED_SENTIMENT_SQL} AS ui_sentiment_score
FROM raw_messages rm
LEFT JOIN cluster_assignments ca
  ON ca.event_id = rm.event_id
 AND ca.run_id = $1
 AND ca.cluster_id >= 0
LEFT JOIN sentiment_results sr ON sr.event_id = rm.event_id
WHERE rm.event_id = $2
  AND ($3::varchar IS NULL OR ca.public_cluster_id = $3::varchar)
LIMIT 1;
"""

SELECT_CLUSTER_SOURCE_BY_CLUSTER_SQL = """
SELECT
    public_cluster_id,
    resolution_kind,
    source_type,
    source_confidence,
    source_event_id,
    source_channel,
    source_message_id,
    source_message_date,
    source_snippet,
    explanation_json,
    evidence_json
FROM cluster_source_resolutions
WHERE public_cluster_id = $1;
"""

SELECT_TOPIC_GRAPH_ENTITY_MENTIONS_SQL = """
SELECT
    rm.event_id,
    rm.channel,
    lower(COALESCE(nr.normalized_text, nr.entity_text)) AS entity_key,
    COALESCE(max(nr.normalized_text), min(nr.entity_text)) AS entity_text,
    nr.entity_type,
    count(*) AS mention_count
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
JOIN ner_results nr ON nr.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY
    rm.event_id,
    rm.channel,
    lower(COALESCE(nr.normalized_text, nr.entity_text)),
    nr.entity_type
ORDER BY rm.event_id ASC, mention_count DESC, entity_text ASC;
"""

SELECT_GRAPH_SUBGRAPH_CACHE_SQL = """
SELECT metrics_json
FROM graph_subgraph_metrics
WHERE cache_key = $1
  AND expires_at > NOW();
"""

UPSERT_GRAPH_SUBGRAPH_METRICS_SQL = """
INSERT INTO graph_subgraph_metrics (
    cache_key,
    public_cluster_id,
    window_start,
    window_end,
    algorithm_version,
    node_count,
    edge_count,
    metrics_json,
    computed_at,
    expires_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW(), NOW() + ($9::text)::interval
)
ON CONFLICT (cache_key) DO UPDATE SET
    public_cluster_id = EXCLUDED.public_cluster_id,
    window_start = EXCLUDED.window_start,
    window_end = EXCLUDED.window_end,
    algorithm_version = EXCLUDED.algorithm_version,
    node_count = EXCLUDED.node_count,
    edge_count = EXCLUDED.edge_count,
    metrics_json = EXCLUDED.metrics_json,
    computed_at = EXCLUDED.computed_at,
    expires_at = EXCLUDED.expires_at;
"""

DELETE_GRAPH_TOP_NODES_SQL = "DELETE FROM graph_top_nodes WHERE cache_key = $1;"

INSERT_GRAPH_TOP_NODE_SQL = """
INSERT INTO graph_top_nodes (
    cache_key,
    node_id,
    node_label,
    node_type,
    community_id,
    degree_centrality,
    betweenness_centrality,
    pagerank,
    bridge_score,
    is_bridge,
    rank
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11);
"""

DELETE_GRAPH_COMMUNITIES_SQL = "DELETE FROM graph_topic_communities WHERE cache_key = $1;"

INSERT_GRAPH_COMMUNITY_SQL = """
INSERT INTO graph_topic_communities (
    cache_key,
    community_id,
    node_count,
    edge_count,
    entity_count,
    channel_count,
    summary_json
) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb);
"""


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    if len(normalized) >= 6 and normalized[-6] == " " and normalized[-5] in {"+", "-"}:
        normalized = f"{normalized[:-6]}{normalized[-5:]}"
    elif (
        len(normalized) >= 6
        and normalized[-6] == " "
        and normalized[-5:-3].isdigit()
        and normalized[-2:].isdigit()
    ):
        normalized = f"{normalized[:-6]}+{normalized[-5:]}"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _decode_cluster_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    decoded = value
    for _ in range(2):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def _utc_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ui_entity_type(value: Optional[str]) -> str:
    normalized = (value or "").upper()
    if normalized in {"PERSON", "PER"}:
        return "PER"
    if normalized == "ORG":
        return "ORG"
    if normalized == "LOC":
        return "LOC"
    return "MISC"


def _backend_entity_type(value: Optional[str]) -> Optional[str]:
    normalized = (value or "").upper()
    if not normalized or normalized == "ALL":
        return None
    if normalized == "PER":
        return "PERSON"
    if normalized in {"ORG", "LOC"}:
        return normalized
    return None


def _source_status(
    exact: Optional[dict[str, Any]],
    inferred: Optional[dict[str, Any]],
) -> str:
    if exact and exact.get("source_type") != "unknown" and exact.get("source_event_id"):
        return "exact"
    if inferred and inferred.get("source_type") != "unknown" and inferred.get("source_event_id"):
        return "probable"
    return "unknown"


def _build_resolution_payload(
    row: Optional[asyncpg.Record],
    resolution_kind: str,
) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {
        "resolution_kind": resolution_kind,
        "source_type": row["source_type"],
        "source_confidence": float(row["source_confidence"] or 0),
        "source_event_id": row["source_event_id"],
        "source_channel": row["source_channel"],
        "source_message_id": row["source_message_id"],
        "source_message_date": _utc_iso(row["source_message_date"]),
        "source_snippet": row["source_snippet"],
        "explanation": row["explanation_json"] or {},
        "evidence": row["evidence_json"] or {},
    }


def _sparkline(
    dates: list[datetime],
    start_dt: datetime,
    end_dt: datetime,
    buckets: int = 12,
) -> list[int]:
    if buckets <= 0:
        return []
    if end_dt <= start_dt:
        return [0] * buckets
    total_seconds = max((end_dt - start_dt).total_seconds(), 1.0)
    step = total_seconds / buckets
    counts = [0] * buckets
    for value in dates:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        seconds = (value - start_dt).total_seconds()
        index = min(buckets - 1, max(0, int(seconds / step)))
        counts[index] += 1
    return counts


def _limit(value: Optional[str], default: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(1, min(parsed, maximum))


def _offset(value: Optional[str]) -> int:
    if value is None:
        return 0
    try:
        parsed = int(value)
    except ValueError:
        return 0
    return max(0, parsed)


class AnalyticsApiService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._pool: Optional[asyncpg.Pool] = None
        self._web_runner: Optional[web.AppRunner] = None
        self._health_site: Optional[web.TCPSite] = None
        self._metrics_site: Optional[web.TCPSite] = None
        self._stop_event = asyncio.Event()
        self._llm_client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._config.postgres.dsn(),
            min_size=self._config.postgres.min_size,
            max_size=self._config.postgres.max_size,
            command_timeout=self._config.postgres.command_timeout,
        )
        if self._config.llm_enricher.enabled:
            self._llm_client = httpx.AsyncClient(
                base_url=self._config.llm_enricher.url,
                timeout=httpx.Timeout(self._config.llm_enricher.refresh_timeout_seconds),
            )

        @web.middleware
        async def cors_middleware(request: web.Request, handler):
            origin = request.headers.get("Origin")
            allowed_origins = {
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            }

            if request.method == "OPTIONS":
                response = web.Response(status=204)
            else:
                response = await handler(request)

            if origin in allowed_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
                response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = (
                    "Content-Type, Authorization"
                )
                response.headers["Access-Control-Max-Age"] = "86400"

            return response

        @web.middleware
        async def metrics_middleware(request: web.Request, handler):
            started = time.monotonic()
            route = self._route_label(request)
            status = "500"
            try:
                response = await handler(request)
                status = str(response.status)
                return response
            except web.HTTPException as exc:
                status = str(exc.status)
                raise
            finally:
                API_REQUESTS_TOTAL.labels(
                    method=request.method,
                    route=route,
                    status=status,
                ).inc()
                API_REQUEST_LATENCY.labels(
                    method=request.method,
                    route=route,
                ).observe(time.monotonic() - started)

        app = web.Application(middlewares=[cors_middleware, metrics_middleware])
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/metrics", self._handle_metrics)
        app.router.add_get("/analytics/overview", self._handle_overview)
        app.router.add_get("/analytics/overview/clusters", self._handle_clusters)
        app.router.add_get("/analytics/clusters/{clusterId}", self._handle_cluster_detail)
        app.router.add_get(
            "/analytics/clusters/{clusterId}/documents",
            self._handle_cluster_documents,
        )
        app.router.add_get(
            "/analytics/clusters/{clusterId}/first-source",
            self._handle_cluster_first_source,
        )
        app.router.add_get(
            "/analytics/clusters/{clusterId}/related",
            self._handle_cluster_related,
        )
        app.router.add_get(
            "/analytics/clusters/{clusterId}/compare/{otherClusterId}",
            self._handle_cluster_compare,
        )
        app.router.add_get(
            "/analytics/clusters/{clusterId}/graph-metrics",
            self._handle_cluster_graph_metrics,
        )
        app.router.add_get(
            "/analytics/clusters/{clusterId}/timeline",
            self._handle_cluster_timeline,
        )
        app.router.add_get(
            "/analytics/clusters/{clusterId}/evolution-events",
            self._handle_cluster_evolution_events,
        )
        app.router.add_get("/analytics/entities/top", self._handle_top_entities)
        app.router.add_get(
            "/analytics/sentiment/dynamics",
            self._handle_sentiment_dynamics,
        )
        app.router.add_get("/analytics/messages", self._handle_messages)
        app.router.add_get("/analytics/graph", self._handle_graph)
        app.router.add_get(
            "/analytics/clusters/{clusterId}/llm/{enrichmentType}",
            self._handle_cluster_llm_enrichment,
        )
        app.router.add_post(
            "/analytics/clusters/{clusterId}/llm/{enrichmentType}/refresh",
            self._handle_cluster_llm_refresh,
        )

        self._web_runner = web.AppRunner(app)
        await self._web_runner.setup()
        self._health_site = web.TCPSite(
            self._web_runner,
            self._config.api.host,
            self._config.api.port,
        )
        await self._health_site.start()
        if (
            self._config.metrics.host,
            self._config.metrics.port,
        ) != (
            self._config.api.host,
            self._config.api.port,
        ):
            self._metrics_site = web.TCPSite(
                self._web_runner,
                self._config.metrics.host,
                self._config.metrics.port,
            )
            await self._metrics_site.start()
        logger.info(
            "analytics api started host=%s port=%s",
            self._config.api.host,
            self._config.api.port,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._pool is not None:
            await self._pool.close()
        if self._web_runner is not None:
            await self._web_runner.cleanup()
        if self._llm_client is not None:
            await self._llm_client.aclose()
        logger.info("analytics api stopped")

    async def run(self) -> None:
        await self.start()
        try:
            await self._stop_event.wait()
        finally:
            await self.stop()

    async def _handle_health(self, request: web.Request) -> web.Response:
        ready = self._pool is not None
        return web.json_response(
            {
                "status": "ok" if ready else "starting",
                "ready": ready,
                "service": self._config.service_name,
            }
        )

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        return web.Response(body=generate_latest(), content_type=CONTENT_TYPE_LATEST)

    async def _handle_overview(self, request: web.Request) -> web.Response:
        from_dt, to_dt = self._parse_time_range(request)
        async with self._conn() as conn:
            topics = await self._build_cluster_overview_list(conn, from_dt, to_dt)
            current = await conn.fetchrow(SELECT_OVERVIEW_TOTAL_MESSAGES_SQL, from_dt, to_dt)
            window = to_dt - from_dt
            prev_from = from_dt - window
            prev_to = from_dt
            previous_topics_list = await self._build_cluster_overview_list(conn, prev_from, prev_to)
            previous = await conn.fetchrow(
                SELECT_OVERVIEW_TOTAL_MESSAGES_SQL,
                prev_from,
                prev_to,
            )

        total_messages = int(current["total_messages"]) if current else 0
        active_channels = int(current["active_channels"]) if current else 0
        previous_messages = int(previous["total_messages"]) if previous else 0
        previous_topics = len(
            [
                topic
                for topic in previous_topics_list
                if _parse_iso_datetime(topic["first_seen"]) >= prev_to - timedelta(hours=24)
            ]
        )
        new_topics = len(
            [
                topic
                for topic in topics
                if _parse_iso_datetime(topic["first_seen"]) >= to_dt - timedelta(hours=24)
            ]
        )

        payload = {
            "total_messages": total_messages,
            "messages_change_pct": self._change_pct(total_messages, previous_messages),
            "new_topics": new_topics,
            "topics_change": new_topics - previous_topics,
            "active_channels": active_channels,
            "avg_sentiment": round(
                sum(topic["avg_sentiment"] for topic in topics) / len(topics),
                4,
            )
            if topics
            else 0.0,
        }
        return web.json_response(payload)

    async def _handle_clusters(self, request: web.Request) -> web.Response:
        from_dt, to_dt = self._parse_time_range(request)
        channel = request.query.get("channel")
        sort_by = request.query.get("sort_by", "messages")
        if sort_by not in {"messages", "importance", "recency"}:
            sort_by = "messages"
        min_importance = request.query.get("min_importance")
        importance_levels_param = request.query.get("importance_level")
        async with self._conn() as conn:
            topics = await self._build_cluster_overview_list(conn, from_dt, to_dt)

        if channel:
            topics = [
                topic
                for topic in topics
                if any(item["channel"] == channel for item in topic["channels"])
            ]

        if min_importance is not None:
            try:
                threshold = float(min_importance)
                topics = [t for t in topics if (t.get("importance_score") or 0.0) >= threshold]
            except ValueError:
                pass

        if importance_levels_param:
            allowed = {lvl.strip().lower() for lvl in importance_levels_param.split(",")}
            topics = [t for t in topics if t.get("importance_level") in allowed]

        if sort_by == "importance":
            topics.sort(key=lambda t: t.get("importance_score") or 0.0, reverse=True)
        elif sort_by == "recency":
            topics.sort(
                key=lambda t: t.get("last_seen") or "",
                reverse=True,
            )
        # default "messages" order comes from SQL ORDER BY message_count DESC

        return web.json_response(topics)

    async def _handle_cluster_detail(self, request: web.Request) -> web.Response:
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        from_dt, to_dt = self._parse_time_range(request)
        async with self._conn() as conn:
            payload = await self._build_topic_detail(conn, cluster_id, from_dt, to_dt)
        if payload is None:
            raise web.HTTPNotFound(text=f"cluster not found: {cluster_id}")
        return web.json_response(payload)

    async def _handle_cluster_documents(self, request: web.Request) -> web.Response:
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        from_dt, to_dt = self._parse_time_range(request)
        limit = _limit(
            request.query.get("limit"),
            self._config.api.default_documents_limit,
            self._config.api.max_documents_limit,
        )
        offset = _offset(request.query.get("offset"))
        async with self._conn() as conn:
            rows = await conn.fetch(
                SELECT_CLUSTER_DOCUMENTS_SQL,
                cluster_id,
                from_dt,
                to_dt,
                limit,
                offset,
            )
            payload = await self._build_messages_payload_from_rows(conn, rows)
        return web.json_response(payload)

    async def _handle_cluster_first_source(self, request: web.Request) -> web.Response:
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        async with self._conn() as conn:
            payload = await self._build_first_source_payload(conn, cluster_id)
        if payload is None:
            raise web.HTTPNotFound(text=f"cluster not found: {cluster_id}")
        return web.json_response(payload)

    async def _handle_cluster_related(self, request: web.Request) -> web.Response:
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        from_dt, to_dt = self._parse_time_range(request)
        async with self._conn() as conn:
            related = await self._build_related_topics(conn, cluster_id, from_dt, to_dt)
        return web.json_response(related)

    async def _handle_cluster_compare(self, request: web.Request) -> web.Response:
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        other_cluster_id = _decode_cluster_id(request.match_info["otherClusterId"])
        if not cluster_id or not other_cluster_id:
            raise web.HTTPBadRequest(text="both cluster ids are required")
        from_dt, to_dt = self._parse_time_range(request)
        refresh = request.query.get("refresh") in {"1", "true", "yes"}
        async with self._conn() as conn:
            payload = await self._build_topic_comparison(
                conn,
                cluster_id,
                other_cluster_id,
                from_dt,
                to_dt,
                refresh=refresh,
            )
        if payload is None:
            raise web.HTTPNotFound(text=f"cluster not found: {cluster_id} or {other_cluster_id}")
        return web.json_response(payload)

    async def _handle_cluster_graph_metrics(self, request: web.Request) -> web.Response:
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        from_dt, to_dt = self._parse_time_range(request)
        force = request.query.get("refresh") in {"1", "true", "yes"}
        async with self._conn() as conn:
            payload = await self._build_topic_graph_metrics(conn, cluster_id, from_dt, to_dt, force)
        if payload is None:
            raise web.HTTPNotFound(text=f"cluster not found: {cluster_id}")
        return web.json_response(payload)

    async def _handle_cluster_timeline(self, request: web.Request) -> web.Response:
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        from_dt, to_dt = self._parse_time_range(request)
        try:
            bucket_size = normalize_bucket_size(request.query.get("bucket"))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        refresh = request.query.get("refresh") in {"1", "true", "yes"}
        async with self._conn() as conn:
            payload = await self._build_topic_timeline_payload(
                conn,
                cluster_id,
                from_dt,
                to_dt,
                bucket_size,
                refresh=refresh,
            )
        if payload is None:
            raise web.HTTPNotFound(text=f"cluster not found: {cluster_id}")
        return web.json_response(payload)

    async def _handle_cluster_evolution_events(self, request: web.Request) -> web.Response:
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        from_dt, to_dt = self._parse_time_range(request)
        try:
            bucket_size = normalize_bucket_size(request.query.get("bucket"))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        refresh = request.query.get("refresh") in {"1", "true", "yes"}
        async with self._conn() as conn:
            payload = await self._build_topic_timeline_payload(
                conn,
                cluster_id,
                from_dt,
                to_dt,
                bucket_size,
                refresh=refresh,
            )
        if payload is None:
            raise web.HTTPNotFound(text=f"cluster not found: {cluster_id}")
        return web.json_response(payload["events"])

    async def _handle_top_entities(self, request: web.Request) -> web.Response:
        from_dt, to_dt = self._parse_time_range(request)
        entity_type = _backend_entity_type(request.query.get("entity_type"))
        cluster_id = _decode_cluster_id(request.query.get("cluster_id"))
        async with self._conn() as conn:
            run_id = await self._latest_run_id(conn)
            rows = await conn.fetch(
                SELECT_TOP_ENTITIES_SQL,
                run_id,
                from_dt,
                to_dt,
                entity_type,
                cluster_id,
                50,
            )
        payload = [
            {
                "id": f"{_ui_entity_type(row['entity_type'])}:{row['entity_key']}",
                "text": row["entity_text"],
                "type": _ui_entity_type(row["entity_type"]),
                "normalized": row["entity_text"],
                "confidence": None,
                "mention_count": int(row["mention_count"] or 0),
                "topic_count": int(row["topic_count"] or 0),
                "channel_count": int(row["channel_count"] or 0),
                "trend_pct": 0,
            }
            for row in rows
        ]
        return web.json_response(payload)

    async def _handle_sentiment_dynamics(self, request: web.Request) -> web.Response:
        from_dt, to_dt = self._parse_time_range(request)
        channel = request.query.get("channel")
        cluster_id = _decode_cluster_id(request.query.get("cluster_id"))
        bucket = request.query.get("bucket", "hour")
        if bucket not in {"hour", "day"}:
            bucket = "hour"
        async with self._conn() as conn:
            run_id = await self._latest_run_id(conn)
            rows = await conn.fetch(
                SELECT_SENTIMENT_DYNAMICS_SQL,
                from_dt,
                to_dt,
                channel,
                bucket,
                run_id,
                cluster_id,
            )

        by_bucket: dict[str, dict[str, int]] = {}
        for row in rows:
            bucket_iso = _utc_iso(row["bucket"])
            by_bucket.setdefault(
                bucket_iso,
                {"positive": 0, "neutral": 0, "negative": 0},
            )[row["sentiment_label"]] = int(row["message_count"] or 0)

        payload = [
            {
                "time": bucket_iso,
                "positive": values["positive"],
                "neutral": values["neutral"],
                "negative": values["negative"],
            }
            for bucket_iso, values in sorted(by_bucket.items())
        ]
        return web.json_response(payload)

    async def _handle_messages(self, request: web.Request) -> web.Response:
        from_dt, to_dt = self._parse_time_range(request)
        channel = request.query.get("channel")
        cluster_id = _decode_cluster_id(request.query.get("topic"))
        search = request.query.get("search")
        sentiment = request.query.get("sentiment")
        if sentiment:
            sentiment = sentiment.lower()
            if sentiment not in {"positive", "neutral", "negative"}:
                sentiment = None
        limit = _limit(
            request.query.get("limit"),
            self._config.api.default_documents_limit,
            self._config.api.max_documents_limit,
        )
        offset = _offset(request.query.get("offset"))
        async with self._conn() as conn:
            run_id = await self._latest_run_id(conn)
            rows = await conn.fetch(
                SELECT_MESSAGES_SQL,
                run_id,
                from_dt,
                to_dt,
                channel,
                cluster_id,
                search,
                sentiment,
                limit,
                offset,
            )
            payload = await self._build_messages_payload_from_rows(conn, rows)
        return web.json_response(payload)

    async def _handle_graph(self, request: web.Request) -> web.Response:
        from_dt, to_dt = self._parse_time_range(request)
        focus = request.query.get("focus")
        depth = _limit(request.query.get("depth"), 2, 4)
        mode = request.query.get("mode", "overview")
        cluster_id = _decode_cluster_id(
            request.query.get("cluster_id") or request.query.get("clusterId")
        )

        async with self._conn() as conn:
            if mode == "propagation" and cluster_id:
                payload = await self._build_propagation_graph(
                    conn,
                    cluster_id,
                    from_dt,
                    to_dt,
                    focus,
                    depth,
                )
            else:
                payload = await self._build_overview_graph(
                    conn,
                    from_dt,
                    to_dt,
                    focus,
                    depth,
                )
        return web.json_response(payload)

    # ── LLM Enrichment proxy ─────────────────────────────────────────

    async def _handle_cluster_llm_enrichment(self, request: web.Request) -> web.Response:
        """GET /analytics/clusters/{clusterId}/llm/{enrichmentType}
        Proxies to llm_enricher with refresh=false and a short timeout.
        Returns 202 if enricher is computing (timeout exceeded).
        """
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        enrichment_type = request.match_info["enrichmentType"]
        return await self._proxy_llm_enrichment(cluster_id, enrichment_type, refresh=False)

    async def _handle_cluster_llm_refresh(self, request: web.Request) -> web.Response:
        """POST /analytics/clusters/{clusterId}/llm/{enrichmentType}/refresh
        Forces recomputation with a longer timeout.
        """
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        enrichment_type = request.match_info["enrichmentType"]
        return await self._proxy_llm_enrichment(cluster_id, enrichment_type, refresh=True)

    async def _proxy_llm_enrichment(
        self, cluster_id: str, enrichment_type: str, *, refresh: bool
    ) -> web.Response:
        if not self._config.llm_enricher.enabled or self._llm_client is None:
            return web.json_response(
                {"error": "LLM enrichment is not enabled on this instance"}, status=503
            )
        timeout = (
            self._config.llm_enricher.refresh_timeout_seconds
            if refresh
            else self._config.llm_enricher.timeout_seconds
        )
        try:
            resp = await self._llm_client.post(
                f"/enrich/{enrichment_type}",
                json={"public_cluster_id": cluster_id, "refresh": refresh},
                timeout=timeout,
            )
            if resp.status_code == 404:
                return web.json_response({"error": "Enrichment type not found"}, status=404)
            data = resp.json()
            return web.json_response(data, status=resp.status_code)
        except httpx.TimeoutException:
            if not refresh:
                return web.json_response(
                    {
                        "status": "pending",
                        "message": "LLM enrichment is being computed. Poll this endpoint again shortly.",
                        "is_llm_generated": True,
                    },
                    status=202,
                )
            return web.json_response({"error": "LLM enricher timed out"}, status=504)
        except Exception as exc:
            logger.error("LLM enricher proxy error cluster=%s type=%s: %s", cluster_id, enrichment_type, exc)
            return web.json_response({"error": "LLM enricher unavailable"}, status=503)

    async def _build_cluster_overview_list(
        self,
        conn: asyncpg.Connection,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[dict[str, Any]]:
        run_id = await self._latest_run_id(conn)
        if run_id is None:
            return []

        base_rows = await conn.fetch(SELECT_CLUSTER_OVERVIEW_BASE_SQL, run_id, from_dt, to_dt)
        if not base_rows:
            return []

        date_rows = await conn.fetch(SELECT_CLUSTER_OVERVIEW_DATES_SQL, run_id, from_dt, to_dt)
        entity_rows = await conn.fetch(
            SELECT_CLUSTER_OVERVIEW_ENTITIES_SQL,
            run_id,
            from_dt,
            to_dt,
        )
        channel_rows = await conn.fetch(
            SELECT_CLUSTER_OVERVIEW_CHANNELS_SQL,
            run_id,
            from_dt,
            to_dt,
        )
        resolution_rows = await conn.fetch(SELECT_CLUSTER_SOURCE_RESOLUTIONS_SQL, run_id)
        try:
            score_rows = await conn.fetch(SELECT_TOPIC_SCORES_FOR_RUN_SQL, run_id)
        except asyncpg.UndefinedTableError:
            score_rows = []

        dates_by_cluster: dict[str, list[datetime]] = defaultdict(list)
        for row in date_rows:
            dates_by_cluster[row["public_cluster_id"]].append(row["message_date"])

        entities_by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
        seen_entities: dict[str, set[str]] = defaultdict(set)
        for row in entity_rows:
            public_cluster_id = row["public_cluster_id"]
            entity_key = row["entity_key"]
            if entity_key in seen_entities[public_cluster_id]:
                continue
            seen_entities[public_cluster_id].add(entity_key)
            entities_by_cluster[public_cluster_id].append(
                {
                    "id": f"{_ui_entity_type(row['entity_type'])}:{entity_key}",
                    "text": row["entity_text"],
                    "type": _ui_entity_type(row["entity_type"]),
                    "mention_count": int(row["mention_count"] or 0),
                }
            )

        channels_by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in channel_rows:
            channels_by_cluster[row["public_cluster_id"]].append(
                {
                    "channel": row["channel"],
                    "count": int(row["message_count"] or 0),
                }
            )

        resolutions_by_cluster: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in resolution_rows:
            resolutions_by_cluster[row["public_cluster_id"]][row["resolution_kind"]] = (
                _build_resolution_payload(row, row["resolution_kind"]) or {}
            )

        scores_by_cluster: dict[str, dict[str, Any]] = {}
        for row in score_rows:
            scores_by_cluster[row["public_cluster_id"]] = {
                "importance_score": round(float(row["importance_score"]), 4),
                "importance_level": row["importance_level"],
                "score_calculated_at": _utc_iso(row["calculated_at"]),
            }

        topics: list[dict[str, Any]] = []
        for row in base_rows:
            public_cluster_id = row["public_cluster_id"]
            cluster_entities = entities_by_cluster.get(public_cluster_id, [])[:5]
            cluster_channels = channels_by_cluster.get(public_cluster_id, [])[:10]
            exact = resolutions_by_cluster.get(public_cluster_id, {}).get("exact")
            inferred = resolutions_by_cluster.get(public_cluster_id, {}).get("inferred")
            label = self._topic_label(public_cluster_id, cluster_entities, exact, inferred)
            score_data = scores_by_cluster.get(public_cluster_id, {})
            topics.append(
                {
                    "cluster_id": public_cluster_id,
                    "label": label,
                    "message_count": int(row["message_count"] or 0),
                    "channel_count": int(row["channel_count"] or 0),
                    "avg_sentiment": round(float(row["avg_sentiment"] or 0), 4),
                    "top_entities": cluster_entities[:3],
                    "top_keywords": [],
                    "is_new": bool(
                        row["first_seen"]
                        and row["first_seen"] >= to_dt - timedelta(hours=24)
                    ),
                    "first_seen": _utc_iso(row["first_seen"]),
                    "last_seen": _utc_iso(row["last_seen"]),
                    "sparkline": _sparkline(
                        dates_by_cluster.get(public_cluster_id, []),
                        from_dt,
                        to_dt,
                    ),
                    "channels": cluster_channels,
                    "source_status": _source_status(exact, inferred),
                    "importance_score": score_data.get("importance_score"),
                    "importance_level": score_data.get("importance_level"),
                    "score_calculated_at": score_data.get("score_calculated_at"),
                }
            )
        return topics

    async def _build_topic_detail(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> Optional[dict[str, Any]]:
        stats = await conn.fetchrow(SELECT_CLUSTER_STATS_SQL, cluster_id, from_dt, to_dt)
        if stats is None or int(stats["message_count"] or 0) == 0:
            return None

        top_entities_rows = await conn.fetch(
            SELECT_CLUSTER_TOP_ENTITIES_SQL,
            cluster_id,
            from_dt,
            to_dt,
            10,
        )
        channels_rows = await conn.fetch(SELECT_CLUSTER_CHANNELS_SQL, cluster_id, from_dt, to_dt)
        sentiment_rows = await conn.fetch(
            SELECT_CLUSTER_SENTIMENT_BREAKDOWN_SQL,
            cluster_id,
            from_dt,
            to_dt,
        )
        volume_rows = await conn.fetch(
            SELECT_CLUSTER_VOLUME_TIMELINE_SQL,
            cluster_id,
            from_dt,
            to_dt,
            "hour",
        )
        docs_rows = await conn.fetch(
            SELECT_CLUSTER_DOCUMENTS_SQL,
            cluster_id,
            from_dt,
            to_dt,
            5,
            0,
        )
        representative_messages = await self._build_messages_payload_from_rows(conn, docs_rows)
        first_source = await self._build_first_source_payload(conn, cluster_id)
        related_topics = await self._build_related_topics(conn, cluster_id, from_dt, to_dt)
        try:
            score_row = await conn.fetchrow(SELECT_TOPIC_SCORE_FOR_CLUSTER_SQL, cluster_id)
        except asyncpg.UndefinedTableError:
            score_row = None

        top_entities = [
            {
                "id": f"{_ui_entity_type(row['entity_type'])}:{row['entity_key']}",
                "text": row["entity_text"],
                "type": _ui_entity_type(row["entity_type"]),
                "mention_count": int(row["mention_count"] or 0),
            }
            for row in top_entities_rows
        ]
        exact = first_source["exact_source"] if first_source else None
        inferred = first_source["inferred_source"] if first_source else None
        label = self._topic_label(cluster_id, top_entities, exact, inferred)

        breakdown = {"positive": 0, "neutral": 0, "negative": 0}
        for row in sentiment_rows:
            breakdown[row["sentiment_label"]] = int(row["message_count"] or 0)

        return {
            "cluster_id": cluster_id,
            "label": label,
            "message_count": int(stats["message_count"] or 0),
            "channel_count": int(stats["channel_count"] or 0),
            "avg_sentiment": round(float(stats["avg_sentiment"] or 0), 4),
            "top_entities": top_entities,
            "top_keywords": [],
            "is_new": bool(
                stats["first_seen"] and stats["first_seen"] >= to_dt - timedelta(hours=24)
            ),
            "first_seen": _utc_iso(stats["first_seen"]),
            "last_seen": _utc_iso(stats["last_seen"]),
            "sparkline": [],
            "channels": [
                {"channel": row["channel"], "count": int(row["message_count"] or 0)}
                for row in channels_rows
            ],
            "representative_messages": representative_messages,
            "related_topics": related_topics,
            "sentiment_breakdown": breakdown,
            "volume_timeline": [
                {
                    "time": _utc_iso(row["bucket"]),
                    "count": int(row["message_count"] or 0),
                }
                for row in volume_rows
            ],
            "first_source": first_source,
            "source_status": first_source["source_status"] if first_source else "unknown",
            "importance_score": round(float(score_row["importance_score"]), 4) if score_row else None,
            "importance_level": score_row["importance_level"] if score_row else None,
            "score_breakdown": json.loads(score_row["score_breakdown_json"]) if score_row else None,
            "score_calculated_at": _utc_iso(score_row["calculated_at"]) if score_row else None,
        }

    async def _build_first_source_payload(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
    ) -> Optional[dict[str, Any]]:
        resolution_rows = await conn.fetch(SELECT_CLUSTER_SOURCE_BY_CLUSTER_SQL, cluster_id)
        if not resolution_rows:
            exists = await conn.fetchval(
                "SELECT 1 FROM cluster_assignments WHERE public_cluster_id = $1 LIMIT 1;",
                cluster_id,
            )
            if exists is None:
                return None

        exact_row = next(
            (row for row in resolution_rows if row["resolution_kind"] == "exact"),
            None,
        )
        inferred_row = next(
            (row for row in resolution_rows if row["resolution_kind"] == "inferred"),
            None,
        )
        exact = _build_resolution_payload(exact_row, "exact")
        inferred = _build_resolution_payload(inferred_row, "inferred")
        status = _source_status(exact, inferred)
        display_source = exact if status == "exact" else inferred
        propagation_rows = await conn.fetch(SELECT_PROPAGATION_LINKS_SQL, cluster_id)
        propagation_chain = [
            {
                "child_event_id": row["child_event_id"],
                "child_channel": row["child_channel"],
                "child_message_id": row["child_message_id"],
                "child_message_date": _utc_iso(row["child_message_date"]),
                "parent_event_id": row["parent_event_id"],
                "parent_channel": row["parent_channel"],
                "parent_message_id": row["parent_message_id"],
                "parent_message_date": _utc_iso(row["parent_message_date"]),
                "link_type": row["link_type"],
                "link_confidence": float(row["link_confidence"] or 0),
                "resolution_kind": row["resolution_kind"],
                "explanation": row["explanation_json"] or {},
                "evidence": row["evidence_json"] or {},
            }
            for row in propagation_rows[:12]
        ]
        return {
            "cluster_id": cluster_id,
            "source_status": status,
            "exact_source": exact,
            "inferred_source": inferred,
            "display_source": display_source,
            "propagation_chain": propagation_chain,
        }

    async def _build_topic_timeline_payload(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
        from_dt: datetime,
        to_dt: datetime,
        bucket_size: str,
        refresh: bool = False,
    ) -> Optional[dict[str, Any]]:
        bucket_size = normalize_bucket_size(bucket_size)
        if refresh:
            rebuild = await self._rebuild_topic_timeline(
                conn,
                cluster_id,
                from_dt,
                to_dt,
                bucket_size,
            )
            if rebuild is None:
                return None
        else:
            exists = await conn.fetchval(
                "SELECT 1 FROM cluster_assignments WHERE public_cluster_id = $1 LIMIT 1;",
                cluster_id,
            )
            if exists is None:
                return None

        try:
            storage_from = floor_bucket(from_dt, bucket_size)
            point_rows = await conn.fetch(
                SELECT_TOPIC_TIMELINE_POINTS_SQL,
                cluster_id,
                bucket_size,
                storage_from,
                to_dt,
            )
            if not point_rows and not refresh:
                rebuild = await self._rebuild_topic_timeline(
                    conn,
                    cluster_id,
                    from_dt,
                    to_dt,
                    bucket_size,
                )
                if rebuild is None:
                    return None
                point_rows = await conn.fetch(
                    SELECT_TOPIC_TIMELINE_POINTS_SQL,
                    cluster_id,
                    bucket_size,
                    storage_from,
                    to_dt,
                )
            event_rows = await conn.fetch(
                SELECT_TOPIC_EVOLUTION_EVENTS_SQL,
                cluster_id,
                bucket_size,
                storage_from,
                to_dt,
            )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("topic timeline tables are not migrated yet")
            return {
                "cluster_id": cluster_id,
                "bucket_size": bucket_size,
                "points": [],
                "events": [],
                "generated_at": _utc_iso(datetime.now(timezone.utc)),
                "storage_status": "migration_required",
            }

        return {
            "cluster_id": cluster_id,
            "bucket_size": bucket_size,
            "points": [self._timeline_point_payload(row) for row in point_rows],
            "events": [self._evolution_event_payload(row) for row in event_rows],
            "generated_at": _utc_iso(datetime.now(timezone.utc)),
            "storage_status": "ready",
        }

    async def _rebuild_topic_timeline(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
        from_dt: datetime,
        to_dt: datetime,
        bucket_size: str,
    ) -> Optional[dict[str, int]]:
        started = time.monotonic()
        run_id: Optional[str] = None
        try:
            message_rows = await conn.fetch(
                SELECT_TOPIC_TIMELINE_MESSAGES_SQL,
                cluster_id,
                from_dt,
                to_dt,
            )
            if not message_rows:
                exists = await conn.fetchval(
                    "SELECT 1 FROM cluster_assignments WHERE public_cluster_id = $1 LIMIT 1;",
                    cluster_id,
                )
                if exists is None:
                    return None

            run_id = message_rows[0]["run_id"] if message_rows else None
            messages = [
                TopicMessage(
                    event_id=row["event_id"],
                    channel=row["channel"],
                    message_date=row["message_date"],
                    sentiment_label=row["sentiment_label"],
                    signed_sentiment=float(row["signed_sentiment"] or 0),
                )
                for row in message_rows
            ]
            event_ids = [message.event_id for message in messages]
            entity_rows = (
                await conn.fetch(SELECT_TOPIC_TIMELINE_ENTITIES_SQL, event_ids)
                if event_ids
                else []
            )
            entities_by_event: dict[str, list[TopicEntity]] = defaultdict(list)
            for row in entity_rows:
                entities_by_event[row["event_id"]].append(
                    TopicEntity(
                        event_id=row["event_id"],
                        entity_key=row["entity_key"],
                        entity_text=row["entity_text"],
                        entity_type=row["entity_type"],
                        mention_count=int(row["mention_count"] or 1),
                    )
                )

            points = build_timeline_points(messages, entities_by_event, bucket_size)
            events = detect_evolution_events(points)

            async with conn.transaction():
                storage_from = floor_bucket(from_dt, bucket_size)
                await conn.execute(
                    DELETE_TOPIC_TIMELINE_POINTS_SQL,
                    cluster_id,
                    bucket_size,
                    storage_from,
                    to_dt,
                )
                await conn.execute(
                    DELETE_TOPIC_EVOLUTION_EVENTS_SQL,
                    cluster_id,
                    bucket_size,
                    storage_from,
                    to_dt,
                )
                for point in points:
                    await self._store_timeline_point(conn, cluster_id, run_id, bucket_size, point)
                for event in events:
                    await self._store_evolution_event(conn, cluster_id, run_id, bucket_size, event)
                await conn.execute(
                    INSERT_TOPIC_TIMELINE_REBUILD_RUN_SQL,
                    cluster_id,
                    run_id,
                    bucket_size,
                    from_dt,
                    to_dt,
                    len(points),
                    len(events),
                    "completed",
                    None,
                )
            TOPIC_TIMELINE_REBUILDS_TOTAL.labels(
                status="success",
                bucket_size=bucket_size,
            ).inc()
            logger.info(
                "topic timeline rebuilt cluster_id=%s bucket=%s points=%s events=%s",
                cluster_id,
                bucket_size,
                len(points),
                len(events),
            )
            return {"points": len(points), "events": len(events)}
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("skipping topic timeline rebuild because tables are not migrated")
            return {"points": 0, "events": 0}
        except Exception as exc:
            TOPIC_TIMELINE_REBUILDS_TOTAL.labels(
                status="error",
                bucket_size=bucket_size,
            ).inc()
            logger.exception("topic timeline rebuild failed cluster_id=%s", cluster_id)
            try:
                await conn.execute(
                    INSERT_TOPIC_TIMELINE_REBUILD_RUN_SQL,
                    cluster_id,
                    run_id,
                    bucket_size,
                    from_dt,
                    to_dt,
                    0,
                    0,
                    "failed",
                    str(exc)[:1000],
                )
            except Exception:
                logger.debug("failed to persist topic timeline rebuild error", exc_info=True)
            raise
        finally:
            TOPIC_TIMELINE_REBUILD_DURATION.labels(bucket_size=bucket_size).observe(
                time.monotonic() - started
            )

    async def _store_timeline_point(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
        run_id: Optional[str],
        bucket_size: str,
        point: TimelinePoint,
    ) -> None:
        await conn.execute(
            INSERT_TOPIC_TIMELINE_POINT_SQL,
            cluster_id,
            run_id,
            bucket_size,
            point.bucket_start,
            point.bucket_end,
            point.message_count,
            point.unique_channel_count,
            json.dumps(point.top_entities),
            json.dumps(point.sentiment),
            json.dumps(point.new_channels),
            json.dumps(point.event_ids),
        )

    async def _store_evolution_event(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
        run_id: Optional[str],
        bucket_size: str,
        event: EvolutionEvent,
    ) -> None:
        await conn.execute(
            INSERT_TOPIC_EVOLUTION_EVENT_SQL,
            cluster_id,
            run_id,
            bucket_size,
            event.event_type,
            event.event_time,
            event.bucket_start,
            float(event.severity),
            event.summary,
            json.dumps(event.details),
        )

    async def _build_topic_comparison(
        self,
        conn: asyncpg.Connection,
        cluster_a_id: str,
        cluster_b_id: str,
        from_dt: datetime,
        to_dt: datetime,
        refresh: bool = False,
    ) -> Optional[dict[str, Any]]:
        cache_key = self._topic_comparison_cache_key(cluster_a_id, cluster_b_id, from_dt, to_dt)
        if not refresh:
            cached = await self._load_topic_comparison_cache(conn, cache_key)
            if cached is not None:
                TOPIC_COMPARISON_CACHE_TOTAL.labels(result="hit").inc()
                return cached
            TOPIC_COMPARISON_CACHE_TOTAL.labels(result="miss").inc()

        started = time.monotonic()
        try:
            left = await self._build_topic_compare_profile(conn, cluster_a_id, from_dt, to_dt)
            right = await self._build_topic_compare_profile(conn, cluster_b_id, from_dt, to_dt)
            if left is None or right is None:
                return None

            payload = compare_topics(left, right)
            payload["window"] = {"from": _utc_iso(from_dt), "to": _utc_iso(to_dt)}
            payload["cached"] = False
            await self._store_topic_comparison_cache(
                conn,
                cache_key,
                cluster_a_id,
                cluster_b_id,
                from_dt,
                to_dt,
                payload,
            )
            TOPIC_COMPARISON_RUNS_TOTAL.labels(status="success").inc()
            return payload
        except Exception:
            TOPIC_COMPARISON_RUNS_TOTAL.labels(status="error").inc()
            logger.exception(
                "topic comparison failed cluster_a=%s cluster_b=%s",
                cluster_a_id,
                cluster_b_id,
            )
            raise
        finally:
            TOPIC_COMPARISON_DURATION.observe(time.monotonic() - started)

    async def _build_topic_compare_profile(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> Optional[TopicComparisonProfile]:
        stats = await conn.fetchrow(SELECT_TOPIC_COMPARE_PROFILE_SQL, cluster_id, from_dt, to_dt)
        if stats is None or int(stats["message_count"] or 0) == 0:
            return None

        entity_rows = await conn.fetch(SELECT_TOPIC_COMPARE_ENTITIES_SQL, cluster_id, from_dt, to_dt)
        channel_rows = await conn.fetch(SELECT_TOPIC_COMPARE_CHANNELS_SQL, cluster_id, from_dt, to_dt)
        message_rows = await conn.fetch(
            SELECT_TOPIC_COMPARE_MESSAGES_SQL,
            cluster_id,
            from_dt,
            to_dt,
            25,
        )

        entities: dict[str, int] = {}
        entity_labels: dict[str, dict[str, Any]] = {}
        top_entities: list[dict[str, Any]] = []
        for row in entity_rows:
            key = row["entity_key"]
            mention_count = int(row["mention_count"] or 0)
            entities[key] = mention_count
            label = {
                "text": row["entity_text"],
                "type": _ui_entity_type(row["entity_type"]),
            }
            entity_labels[key] = label
            if len(top_entities) < 5:
                top_entities.append(
                    {
                        "id": f"{label['type']}:{key}",
                        "text": label["text"],
                        "type": label["type"],
                        "mention_count": mention_count,
                    }
                )

        channels = {
            row["channel"]: int(row["message_count"] or 0)
            for row in channel_rows
        }
        messages = [
            {
                "event_id": row["event_id"],
                "channel": row["channel"],
                "message_id": row["message_id"],
                "permalink": row["permalink"],
                "text": row["text"],
                "message_date": _utc_iso(row["message_date"]),
                "views": int(row["views"] or 0),
                "forwards": int(row["forwards"] or 0),
                "normalized_text_hash": row["normalized_text_hash"],
                "primary_url_fingerprint": row["primary_url_fingerprint"],
                "simhash64": row["simhash64"],
                "signed_sentiment": round(float(row["signed_sentiment"] or 0), 4),
            }
            for row in message_rows
        ]
        label = self._topic_label(cluster_id, top_entities, None, None)
        return TopicComparisonProfile(
            cluster_id=cluster_id,
            label=label,
            message_count=int(stats["message_count"] or 0),
            first_seen=stats["first_seen"],
            last_seen=stats["last_seen"],
            avg_sentiment=float(stats["avg_sentiment"] or 0),
            entities=entities,
            entity_labels=entity_labels,
            channels=channels,
            messages=messages,
        )

    async def _load_topic_comparison_cache(
        self,
        conn: asyncpg.Connection,
        cache_key: str,
    ) -> Optional[dict[str, Any]]:
        try:
            cached = await conn.fetchval(SELECT_TOPIC_COMPARISON_CACHE_SQL, cache_key)
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("topic comparison cache table is not migrated yet")
            return None
        if cached is None:
            return None
        if isinstance(cached, str):
            payload = json.loads(cached)
        else:
            payload = dict(cached)
        payload["cached"] = True
        return payload

    async def _store_topic_comparison_cache(
        self,
        conn: asyncpg.Connection,
        cache_key: str,
        cluster_a_id: str,
        cluster_b_id: str,
        from_dt: datetime,
        to_dt: datetime,
        payload: dict[str, Any],
    ) -> None:
        ttl_seconds = max(60, self._config.api.topic_comparison_cache_ttl_seconds)
        interval = f"{ttl_seconds} seconds"
        try:
            await conn.execute(
                UPSERT_TOPIC_COMPARISON_CACHE_SQL,
                cache_key,
                cluster_a_id,
                cluster_b_id,
                from_dt,
                to_dt,
                TOPIC_COMPARISON_ALGO_VERSION,
                json.dumps(payload),
                interval,
            )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("skipping topic comparison cache write because table is not migrated")

    def _timeline_point_payload(self, row: asyncpg.Record) -> dict[str, Any]:
        return {
            "bucket_start": _utc_iso(row["bucket_start"]),
            "bucket_end": _utc_iso(row["bucket_end"]),
            "message_count": int(row["message_count"] or 0),
            "unique_channel_count": int(row["unique_channel_count"] or 0),
            "top_entities": self._json_value(row["top_entities_json"], []),
            "sentiment": self._json_value(row["sentiment_json"], {}),
            "new_channels": self._json_value(row["new_channels_json"], []),
            "event_ids": self._json_value(row["event_ids_json"], []),
            "calculated_at": _utc_iso(row["calculated_at"]),
        }

    def _evolution_event_payload(self, row: asyncpg.Record) -> dict[str, Any]:
        return {
            "event_type": row["event_type"],
            "event_time": _utc_iso(row["event_time"]),
            "bucket_start": _utc_iso(row["bucket_start"]),
            "severity": round(float(row["severity"] or 0), 4),
            "summary": row["summary"],
            "details": self._json_value(row["details_json"], {}),
            "created_at": _utc_iso(row["created_at"]),
        }

    def _json_value(self, value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return default
        return value

    async def _build_related_topics(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[dict[str, Any]]:
        related_rows = await conn.fetch(SELECT_RELATED_CLUSTERS_SQL, cluster_id, 3)
        if not related_rows:
            return []
        topic_map = {
            topic["cluster_id"]: topic
            for topic in await self._build_cluster_overview_list(conn, from_dt, to_dt)
        }
        payload = []
        for row in related_rows:
            topic = topic_map.get(row["public_cluster_id"])
            if topic is None:
                continue
            payload.append(
                {
                    "cluster_id": topic["cluster_id"],
                    "label": topic["label"],
                    "similarity": round(min(0.99, 0.35 + int(row["overlap"]) * 0.08), 2),
                }
            )
        return payload

    async def _build_messages_payload_from_rows(
        self,
        conn: asyncpg.Connection,
        rows: list[asyncpg.Record],
    ) -> list[dict[str, Any]]:
        if not rows:
            return []
        event_ids = [row["event_id"] for row in rows]
        entities_map = await self._message_entities_map(conn, event_ids)
        resolutions_map = await self._message_resolution_map(conn, event_ids)
        cluster_ids = [
            row["public_cluster_id"] for row in rows if row["public_cluster_id"]
        ]
        topic_labels = await self._cluster_label_map(conn, cluster_ids)

        payload = []
        for row in rows:
            event_id = row["event_id"]
            exact = resolutions_map.get(event_id, {}).get("exact")
            inferred = resolutions_map.get(event_id, {}).get("inferred")
            source_status = _source_status(exact, inferred)
            display_source = exact if source_status == "exact" else inferred
            payload.append(
                {
                    "event_id": event_id,
                    "channel": row["channel"],
                    "message_id": row["message_id"],
                    "permalink": row["permalink"],
                    "text": row["text"] or "",
                    "date": _utc_iso(row["message_date"]),
                    "views": int(row["views"] or 0),
                    "forwards": int(row["forwards"] or 0),
                    "topic_label": topic_labels.get(row["public_cluster_id"]),
                    "cluster_id": row["public_cluster_id"],
                    "sentiment_score": round(float(row["ui_sentiment_score"] or 0), 4),
                    "sentiment_label": (row["sentiment_label"] or "neutral").title(),
                    "sentiment_confidence": round(float(row["sentiment_confidence"] or 0), 4),
                    "entities": entities_map.get(event_id, [])[:3],
                    "source_status": source_status,
                    "source_type": display_source["source_type"] if display_source else "unknown",
                    "source_confidence": (
                        display_source["source_confidence"] if display_source else 0.0
                    ),
                    "source_event_id": (
                        display_source["source_event_id"] if display_source else None
                    ),
                    "source_channel": (
                        display_source["source_channel"] if display_source else None
                    ),
                }
            )
        return payload

    async def _cluster_label_map(
        self,
        conn: asyncpg.Connection,
        cluster_ids: list[str],
    ) -> dict[str, str]:
        if not cluster_ids:
            return {}
        rows = await conn.fetch(
            """
            SELECT public_cluster_id, source_snippet, explanation_json
            FROM cluster_source_resolutions
            WHERE public_cluster_id = ANY($1::varchar[])
              AND resolution_kind = 'inferred';
            """,
            cluster_ids,
        )
        labels: dict[str, str] = {}
        for row in rows:
            explanation = row["explanation_json"] or {}
            if isinstance(explanation, str):
                try:
                    explanation = json.loads(explanation)
                except json.JSONDecodeError:
                    explanation = {}
            label = explanation.get("topic_label") or row["source_snippet"]
            if label:
                labels[row["public_cluster_id"]] = str(label)
        return labels

    async def _message_entities_map(
        self,
        conn: asyncpg.Connection,
        event_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        rows = await conn.fetch(SELECT_MESSAGE_ENTITIES_SQL, event_ids)
        entities: dict[str, list[dict[str, Any]]] = defaultdict(list)
        seen: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            event_id = row["event_id"]
            entity_key = row["entity_key"]
            if entity_key in seen[event_id]:
                continue
            seen[event_id].add(entity_key)
            entities[event_id].append(
                {
                    "id": f"{_ui_entity_type(row['entity_type'])}:{entity_key}",
                    "text": row["entity_text"],
                    "type": _ui_entity_type(row["entity_type"]),
                    "normalized": row["entity_text"],
                    "mention_count": int(row["mention_count"] or 0),
                }
            )
        return entities

    async def _message_resolution_map(
        self,
        conn: asyncpg.Connection,
        event_ids: list[str],
    ) -> dict[str, dict[str, dict[str, Any]]]:
        rows = await conn.fetch(SELECT_MESSAGE_SOURCE_RESOLUTIONS_SQL, event_ids)
        resolutions: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in rows:
            resolution = _build_resolution_payload(row, row["resolution_kind"])
            if resolution is not None:
                resolutions[row["message_event_id"]][row["resolution_kind"]] = resolution
        return resolutions

    async def _build_overview_graph(
        self,
        conn: asyncpg.Connection,
        from_dt: datetime,
        to_dt: datetime,
        focus: Optional[str],
        depth: int,
    ) -> dict[str, Any]:
        topics = await self._build_cluster_overview_list(conn, from_dt, to_dt)
        topics = topics[: self._config.api.default_graph_nodes]

        if focus and focus.startswith("topic-"):
            focus_cluster_id = focus.removeprefix("topic-")
            topics = [topic for topic in topics if topic["cluster_id"] == focus_cluster_id] or topics[:1]

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        seen_nodes: set[str] = set()
        messages_by_cluster = await self._overview_messages_by_cluster(
            conn,
            [topic["cluster_id"] for topic in topics],
            from_dt,
            to_dt,
            max(1, min(depth, 3)),
        )

        for topic in topics:
            topic_node_id = f"topic-{topic['cluster_id']}"
            if topic_node_id not in seen_nodes:
                nodes.append(
                    {
                        "id": topic_node_id,
                        "label": topic["label"],
                        "type": "topic",
                        "weight": topic["message_count"],
                        "community": None,
                        "source_status": topic.get("source_status"),
                    }
                )
                seen_nodes.add(topic_node_id)

            for channel in topic["channels"][: max(2, depth + 1)]:
                channel_id = f"ch-{channel['channel']}"
                if channel_id not in seen_nodes:
                    nodes.append(
                        {
                            "id": channel_id,
                            "label": channel["channel"],
                            "type": "channel",
                            "weight": channel["count"],
                            "community": None,
                        }
                    )
                    seen_nodes.add(channel_id)
                edges.append(
                    {
                        "source": topic_node_id,
                        "target": channel_id,
                        "weight": channel["count"],
                        "type": "publishes",
                    }
                )

            for entity in topic["top_entities"][: max(2, depth + 1)]:
                entity_id = f"ent-{entity['id']}"
                if entity_id not in seen_nodes:
                    nodes.append(
                        {
                            "id": entity_id,
                            "label": entity["text"],
                            "type": f"entity_{entity['type'].lower()}",
                            "weight": entity.get("mention_count", 1),
                            "community": None,
                        }
                    )
                    seen_nodes.add(entity_id)
                edges.append(
                    {
                        "source": topic_node_id,
                        "target": entity_id,
                        "weight": entity.get("mention_count", 1),
                        "type": "mentions",
                    }
                )

            for message in messages_by_cluster.get(topic["cluster_id"], []):
                message_node_id = f"msg-{message['event_id']}"
                if message_node_id not in seen_nodes:
                    nodes.append(self._message_graph_node(message))
                    seen_nodes.add(message_node_id)
                edges.append(
                    {
                        "source": topic_node_id,
                        "target": message_node_id,
                        "weight": 1,
                        "type": "contains",
                    }
                )
                channel_id = f"ch-{message['channel']}"
                if channel_id in seen_nodes:
                    edges.append(
                        {
                            "source": message_node_id,
                            "target": channel_id,
                            "weight": max(1, int(message.get("forwards", 0)) + 1),
                            "type": "published_by",
                        }
                    )

        return {"nodes": nodes, "edges": edges}

    async def _build_propagation_graph(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
        from_dt: datetime,
        to_dt: datetime,
        focus: Optional[str] = None,
        depth: int = 2,
    ) -> dict[str, Any]:
        detail = await self._build_topic_detail(conn, cluster_id, from_dt, to_dt)
        if detail is None:
            return {"nodes": [], "edges": []}

        doc_rows = await conn.fetch(
            SELECT_CLUSTER_DOCUMENTS_SQL,
            cluster_id,
            from_dt,
            to_dt,
            min(max(10, depth * 10), self._config.api.max_graph_nodes),
            0,
        )
        documents = await self._build_messages_payload_from_rows(conn, doc_rows)
        focus_event_id = focus.removeprefix("msg-") if focus and focus.startswith("msg-") else None
        if focus_event_id and all(message["event_id"] != focus_event_id for message in documents):
            run_id = await self._latest_run_id(conn)
            focus_row = await conn.fetchrow(
                SELECT_MESSAGE_BY_EVENT_ID_SQL,
                run_id,
                focus_event_id,
                cluster_id,
            )
            if focus_row:
                documents.extend(await self._build_messages_payload_from_rows(conn, [focus_row]))
        first_source = detail.get("first_source") or {}
        chain = first_source.get("propagation_chain") or []

        nodes = [
            {
                "id": f"topic-{cluster_id}",
                "label": detail["label"],
                "type": "topic",
                "weight": detail["message_count"],
                "community": None,
                "source_status": detail.get("source_status"),
            }
        ]
        seen_nodes = {f"topic-{cluster_id}"}
        edges: list[dict[str, Any]] = []

        for message in documents:
            node_id = f"msg-{message['event_id']}"
            if node_id not in seen_nodes:
                nodes.append(self._message_graph_node(message))
                seen_nodes.add(node_id)
            edges.append(
                {
                    "source": f"topic-{cluster_id}",
                    "target": node_id,
                    "weight": 1,
                    "type": "contains",
                }
            )

        for link in chain:
            parent_node = f"msg-{link['parent_event_id']}"
            child_node = f"msg-{link['child_event_id']}"
            if parent_node not in seen_nodes:
                nodes.append(
                    {
                        "id": parent_node,
                        "label": f"{link['parent_channel']} #{link['parent_message_id']}",
                        "type": "message",
                        "weight": 2,
                        "community": None,
                        "channel": link["parent_channel"],
                        "message_id": link["parent_message_id"],
                        "message_date": link["parent_message_date"],
                        "cluster_id": cluster_id,
                        "source_status": "exact" if link["resolution_kind"] == "exact" else "probable",
                        "source_event_id": None,
                        "source_channel": None,
                    }
                )
                seen_nodes.add(parent_node)
            if child_node not in seen_nodes:
                nodes.append(
                    {
                        "id": child_node,
                        "label": f"{link['child_channel']} #{link['child_message_id']}",
                        "type": "message",
                        "weight": 1,
                        "community": None,
                        "channel": link["child_channel"],
                        "message_id": link["child_message_id"],
                        "message_date": link["child_message_date"],
                        "cluster_id": cluster_id,
                        "source_status": "exact" if link["resolution_kind"] == "exact" else "probable",
                        "source_event_id": link["parent_event_id"],
                        "source_channel": link["parent_channel"],
                    }
                )
                seen_nodes.add(child_node)
            edges.append(
                {
                    "source": parent_node,
                    "target": child_node,
                    "weight": max(1, int(round(link["link_confidence"] * 100))),
                    "type": f"propagates_{link['resolution_kind']}",
                    "confidence": link["link_confidence"],
                }
            )

        return {"nodes": nodes, "edges": edges}

    async def _overview_messages_by_cluster(
        self,
        conn: asyncpg.Connection,
        cluster_ids: list[str],
        from_dt: datetime,
        to_dt: datetime,
        limit_per_cluster: int,
    ) -> dict[str, list[dict[str, Any]]]:
        if not cluster_ids:
            return {}
        rows: list[asyncpg.Record] = []
        for cluster_id in cluster_ids:
            rows.extend(
                await conn.fetch(
                    SELECT_CLUSTER_DOCUMENTS_SQL,
                    cluster_id,
                    from_dt,
                    to_dt,
                    limit_per_cluster,
                    0,
                )
            )
        messages = await self._build_messages_payload_from_rows(conn, rows)
        by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for message in messages:
            message_cluster_id = message.get("cluster_id")
            if message_cluster_id:
                by_cluster[message_cluster_id].append(message)
        return by_cluster

    async def _latest_run_id(self, conn: asyncpg.Connection) -> Optional[str]:
        return await conn.fetchval(SELECT_LATEST_RUN_SQL)

    def _topic_label(
        self,
        cluster_id: str,
        entities: list[dict[str, Any]],
        exact: Optional[dict[str, Any]],
        inferred: Optional[dict[str, Any]],
    ) -> str:
        for source in (inferred, exact):
            explanation = (source or {}).get("explanation") or {}
            if isinstance(explanation, str):
                try:
                    explanation = json.loads(explanation)
                except json.JSONDecodeError:
                    explanation = {}
            topic_label = explanation.get("topic_label")
            if topic_label:
                return str(topic_label)
        if entities:
            top = [entity["text"] for entity in entities[:2] if entity.get("text")]
            if top:
                return " / ".join(top)
        display = exact if _source_status(exact, inferred) == "exact" else inferred
        snippet = (display or {}).get("source_snippet")
        if snippet:
            return snippet[:80]
        return cluster_id

    def _message_graph_node(self, message: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"msg-{message['event_id']}",
            "label": self._message_graph_label(message),
            "type": "message",
            "weight": self._message_graph_weight(message),
            "community": None,
            "channel": message["channel"],
            "message_id": message["message_id"],
            "message_date": message["date"],
            "cluster_id": message.get("cluster_id"),
            "permalink": message.get("permalink"),
            "source_status": message.get("source_status"),
            "source_event_id": message.get("source_event_id"),
            "source_channel": message.get("source_channel"),
        }

    def _message_graph_weight(self, message: dict[str, Any]) -> int:
        views = max(0, int(message.get("views", 0) or 0))
        forwards = max(0, int(message.get("forwards", 0) or 0))
        if views == 0 and forwards == 0:
            return 1
        engagement = views + forwards * 25
        return max(1, min(6, 1 + int(engagement ** 0.25)))

    def _message_graph_label(self, message: dict[str, Any]) -> str:
        text = " ".join((message.get("text") or "").split())
        if not text:
            return f"{message['channel']} #{message['message_id']}"
        compact = text[:48].rstrip()
        if len(text) > 48:
            compact += "..."
        return compact

    async def _build_topic_graph_metrics(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
        from_dt: datetime,
        to_dt: datetime,
        force: bool = False,
    ) -> Optional[dict[str, Any]]:
        cache_key = self._graph_cache_key(cluster_id, from_dt, to_dt)
        if not force:
            cached = await self._load_topic_graph_metrics_cache(conn, cache_key)
            if cached is not None:
                GRAPH_ANALYTICS_CACHE_TOTAL.labels(result="hit").inc()
                return cached
            GRAPH_ANALYTICS_CACHE_TOTAL.labels(result="miss").inc()

        exists = await conn.fetchval(
            "SELECT 1 FROM cluster_assignments WHERE public_cluster_id = $1 LIMIT 1;",
            cluster_id,
        )
        if exists is None:
            return None

        started = time.monotonic()
        try:
            rows = await conn.fetch(
                SELECT_TOPIC_GRAPH_ENTITY_MENTIONS_SQL,
                cluster_id,
                from_dt,
                to_dt,
            )
            graph = build_topic_graph([dict(row) for row in rows])
            analysis = analyze_topic_graph(graph["nodes"], graph["edges"])
            payload = {
                "cluster_id": cluster_id,
                "window": {"from": _utc_iso(from_dt), "to": _utc_iso(to_dt)},
                "algorithm_version": ALGO_VERSION,
                "graph": graph,
                **analysis,
            }
            await self._store_topic_graph_metrics_cache(conn, cache_key, cluster_id, from_dt, to_dt, payload)
            GRAPH_ANALYTICS_RUNS_TOTAL.labels(status="success").inc()
            return payload
        except Exception:
            GRAPH_ANALYTICS_RUNS_TOTAL.labels(status="error").inc()
            logger.exception("topic graph analytics failed cluster_id=%s", cluster_id)
            raise
        finally:
            GRAPH_ANALYTICS_DURATION.observe(time.monotonic() - started)

    async def _load_topic_graph_metrics_cache(
        self,
        conn: asyncpg.Connection,
        cache_key: str,
    ) -> Optional[dict[str, Any]]:
        try:
            cached = await conn.fetchval(SELECT_GRAPH_SUBGRAPH_CACHE_SQL, cache_key)
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("graph analytics cache tables are not migrated yet")
            return None
        if cached is None:
            return None
        if isinstance(cached, str):
            return json.loads(cached)
        return dict(cached)

    async def _store_topic_graph_metrics_cache(
        self,
        conn: asyncpg.Connection,
        cache_key: str,
        cluster_id: str,
        from_dt: datetime,
        to_dt: datetime,
        payload: dict[str, Any],
    ) -> None:
        ttl_seconds = max(60, self._config.api.graph_metrics_cache_ttl_seconds)
        interval = f"{ttl_seconds} seconds"
        summary = payload["summary"]
        try:
            async with conn.transaction():
                await conn.execute(
                    UPSERT_GRAPH_SUBGRAPH_METRICS_SQL,
                    cache_key,
                    cluster_id,
                    from_dt,
                    to_dt,
                    ALGO_VERSION,
                    int(summary["node_count"]),
                    int(summary["edge_count"]),
                    json.dumps(payload),
                    interval,
                )
                await conn.execute(DELETE_GRAPH_TOP_NODES_SQL, cache_key)
                ranked_nodes = sorted(
                    payload["nodes"],
                    key=lambda item: (-item["pagerank"], -item["degree_centrality"], item["label"]),
                )
                for rank, node in enumerate(ranked_nodes, start=1):
                    await conn.execute(
                        INSERT_GRAPH_TOP_NODE_SQL,
                        cache_key,
                        node["id"],
                        node["label"],
                        node["type"],
                        node["community_id"],
                        float(node["degree_centrality"]),
                        float(node["betweenness_centrality"]),
                        float(node["pagerank"]),
                        float(node["bridge_score"]),
                        bool(node["is_bridge"]),
                        rank,
                    )
                await conn.execute(DELETE_GRAPH_COMMUNITIES_SQL, cache_key)
                for community in payload["communities"]:
                    await conn.execute(
                        INSERT_GRAPH_COMMUNITY_SQL,
                        cache_key,
                        int(community["community_id"]),
                        int(community["node_count"]),
                        int(community["edge_count"]),
                        int(community["entity_count"]),
                        int(community["channel_count"]),
                        json.dumps(community),
                    )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("skipping graph analytics cache write because tables are not migrated")

    def _graph_cache_key(self, cluster_id: str, from_dt: datetime, to_dt: datetime) -> str:
        raw = "|".join(
            [
                ALGO_VERSION,
                cluster_id,
                _utc_iso(from_dt) or "",
                _utc_iso(to_dt) or "",
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _topic_comparison_cache_key(
        self,
        cluster_a_id: str,
        cluster_b_id: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> str:
        raw = "|".join(
            [
                TOPIC_COMPARISON_ALGO_VERSION,
                cluster_a_id,
                cluster_b_id,
                _utc_iso(from_dt) or "",
                _utc_iso(to_dt) or "",
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _parse_time_range(self, request: web.Request) -> tuple[datetime, datetime]:
        from_raw = request.query.get("from")
        to_raw = request.query.get("to")
        if from_raw and to_raw:
            return _parse_iso_datetime(from_raw), _parse_iso_datetime(to_raw)
        to_dt = datetime.now(timezone.utc)
        from_dt = to_dt - timedelta(hours=self._config.api.default_window_hours)
        return from_dt, to_dt

    def _route_label(self, request: web.Request) -> str:
        resource = getattr(getattr(request.match_info.route, "resource", None), "canonical", None)
        return resource or request.path

    def _change_pct(self, current: int, previous: int) -> float:
        if previous <= 0:
            return 0.0 if current == 0 else 100.0
        return round(((current - previous) / previous) * 100.0, 2)

    def _conn(self):
        if self._pool is None:
            raise RuntimeError("analytics api not started")
        return self._pool.acquire()

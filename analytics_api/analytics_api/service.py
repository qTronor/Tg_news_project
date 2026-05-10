from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
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
    MODEL_DEPLOYMENTS_TOTAL,
    MODEL_VERSIONS_TOTAL,
    TOPIC_COMPARISON_CACHE_TOTAL,
    TOPIC_COMPARISON_DURATION,
    TOPIC_COMPARISON_RUNS_TOTAL,
    TOPIC_TIMELINE_REBUILD_DURATION,
    TOPIC_TIMELINE_REBUILDS_TOTAL,
    TRAINING_DURATION_SECONDS,
    TRAINING_JOBS_FAILED_TOTAL,
    TRAINING_JOBS_TOTAL,
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
from analytics_api import annotation as ann_mod
from analytics_api import mlops as mlops_mod
from analytics_api import topic_review as review_mod


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

SELECT_TOPIC_EXPERIMENTS_SQL = """
SELECT
    te.id,
    te.name,
    te.description,
    te.dataset_version,
    te.dataset_version_id,
    te.window_start,
    te.window_end,
    te.channels,
    te.seed,
    te.status,
    te.created_at,
    count(ter.id) AS run_count,
    count(*) FILTER (WHERE ter.status = 'completed') AS completed_run_count
FROM topic_experiments te
LEFT JOIN topic_experiment_runs ter ON ter.experiment_id = te.id
GROUP BY te.id
ORDER BY te.created_at DESC
LIMIT $1 OFFSET $2;
"""

SELECT_TOPIC_EXPERIMENT_SQL = """
SELECT
    id,
    name,
    description,
    dataset_version,
    dataset_version_id,
    window_start,
    window_end,
    channels,
    seed,
    status,
    created_at,
    updated_at
FROM topic_experiments
WHERE id = $1;
"""

SELECT_TOPIC_EXPERIMENT_RUNS_SQL = """
SELECT
    ter.id,
    ter.cluster_run_id,
    ter.status,
    ter.started_at,
    ter.finished_at,
    ter.duration_seconds,
    ter.error_message,
    ter.random_seed,
    ter.runtime_json,
    tmc.model_key,
    tmc.model_name,
    tmc.embedding_model,
    tmc.params_json,
    tmc.is_baseline
FROM topic_experiment_runs ter
JOIN topic_model_configs tmc ON tmc.id = ter.model_config_id
WHERE ter.experiment_id = $1
ORDER BY tmc.is_baseline DESC, tmc.model_key ASC;
"""

SELECT_TOPIC_EXPERIMENT_METRICS_SQL = """
SELECT
    ter.id AS run_id,
    ter.cluster_run_id,
    ter.status,
    ter.error_message,
    tmc.model_key,
    tmc.model_name,
    tmc.is_baseline,
    tm.metric_name,
    tm.metric_value,
    tm.metric_json,
    tm.calculated_at
FROM topic_experiment_runs ter
JOIN topic_model_configs tmc ON tmc.id = ter.model_config_id
LEFT JOIN topic_metrics tm ON tm.experiment_run_id = ter.id
WHERE ter.experiment_id = $1
ORDER BY tmc.is_baseline DESC, tmc.model_key ASC, tm.metric_name ASC;
"""

INSERT_TOPIC_EXPERIMENT_SQL = """
INSERT INTO topic_experiments (
    name, description, dataset_version, dataset_version_id, window_start, window_end, channels, seed, status
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'created')
RETURNING id;
"""

INSERT_TOPIC_MODEL_CONFIG_SQL = """
INSERT INTO topic_model_configs (
    experiment_id, model_key, model_name, embedding_model, params_json, is_baseline
) VALUES ($1, $2, $3, $4, $5::jsonb, $6)
RETURNING id;
"""

INSERT_TOPIC_EXPERIMENT_RUN_SQL = """
INSERT INTO topic_experiment_runs (
    experiment_id, model_config_id, status, random_seed
) VALUES ($1, $2, 'queued', $3)
RETURNING id;
"""

SELECT_CLUSTER_OVERVIEW_BASE_SQL = f"""
WITH latest_assignments AS (
    SELECT DISTINCT ON (ca.event_id)
        ca.event_id,
        ca.public_cluster_id
    FROM cluster_assignments ca
    JOIN cluster_runs_pg cr ON cr.run_id = ca.run_id
    WHERE ca.cluster_id >= 0
      AND ca.message_date >= $2
      AND ca.message_date <= $3
    ORDER BY ca.event_id, (ca.run_id = $1) DESC, cr.run_timestamp DESC
)
SELECT
    la.public_cluster_id,
    count(*) AS message_count,
    count(DISTINCT rm.channel) AS channel_count,
    COALESCE(avg({SIGNED_SENTIMENT_SQL}), 0) AS avg_sentiment,
    min(rm.message_date) AS first_seen,
    max(rm.message_date) AS last_seen,
    (array_agg(
        NULLIF(trim(regexp_replace(COALESCE(rm.text, ''), '\\s+', ' ', 'g')), '')
        ORDER BY rm.message_date DESC, rm.event_id DESC
    ))[1] AS representative_text
FROM latest_assignments la
JOIN raw_messages rm ON rm.event_id = la.event_id
LEFT JOIN sentiment_results sr ON sr.event_id = la.event_id
WHERE rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY la.public_cluster_id
ORDER BY message_count DESC, last_seen DESC;
"""

SELECT_CLUSTER_OVERVIEW_DATES_SQL = """
WITH latest_assignments AS (
    SELECT DISTINCT ON (ca.event_id)
        ca.event_id,
        ca.public_cluster_id
    FROM cluster_assignments ca
    JOIN cluster_runs_pg cr ON cr.run_id = ca.run_id
    WHERE ca.cluster_id >= 0
      AND ca.message_date >= $2
      AND ca.message_date <= $3
    ORDER BY ca.event_id, (ca.run_id = $1) DESC, cr.run_timestamp DESC
)
SELECT la.public_cluster_id, rm.message_date
FROM latest_assignments la
JOIN raw_messages rm ON rm.event_id = la.event_id
WHERE rm.message_date >= $2
  AND rm.message_date <= $3
ORDER BY rm.message_date ASC;
"""

SELECT_CLUSTER_OVERVIEW_ENTITIES_SQL = """
WITH latest_assignments AS (
    SELECT DISTINCT ON (ca.event_id)
        ca.event_id,
        ca.public_cluster_id
    FROM cluster_assignments ca
    JOIN cluster_runs_pg cr ON cr.run_id = ca.run_id
    WHERE ca.cluster_id >= 0
      AND ca.message_date >= $2
      AND ca.message_date <= $3
    ORDER BY ca.event_id, (ca.run_id = $1) DESC, cr.run_timestamp DESC
)
SELECT
    la.public_cluster_id,
    lower(COALESCE(nr.normalized_text, nr.entity_text)) AS entity_key,
    COALESCE(max(nr.normalized_text), min(nr.entity_text)) AS entity_text,
    nr.entity_type,
    count(*) AS mention_count
FROM latest_assignments la
JOIN raw_messages rm ON rm.event_id = la.event_id
JOIN ner_results nr ON nr.event_id = la.event_id
WHERE rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY
    la.public_cluster_id,
    lower(COALESCE(nr.normalized_text, nr.entity_text)),
    nr.entity_type
ORDER BY la.public_cluster_id, mention_count DESC, entity_text ASC;
"""

SELECT_CLUSTER_OVERVIEW_CHANNELS_SQL = """
WITH latest_assignments AS (
    SELECT DISTINCT ON (ca.event_id)
        ca.event_id,
        ca.public_cluster_id
    FROM cluster_assignments ca
    JOIN cluster_runs_pg cr ON cr.run_id = ca.run_id
    WHERE ca.cluster_id >= 0
      AND ca.message_date >= $2
      AND ca.message_date <= $3
    ORDER BY ca.event_id, (ca.run_id = $1) DESC, cr.run_timestamp DESC
)
SELECT
    la.public_cluster_id,
    rm.channel,
    count(*) AS message_count
FROM latest_assignments la
JOIN raw_messages rm ON rm.event_id = la.event_id
WHERE rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY la.public_cluster_id, rm.channel
ORDER BY la.public_cluster_id, message_count DESC, rm.channel ASC;
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

SELECT_CLUSTER_SOURCE_RESOLUTIONS_FOR_CLUSTERS_SQL = """
SELECT DISTINCT ON (public_cluster_id, resolution_kind)
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
WHERE public_cluster_id = ANY($1::varchar[])
ORDER BY public_cluster_id, resolution_kind, created_at DESC;
"""

SELECT_TOPIC_METADATA_FOR_RUN_SQL = """
SELECT
    public_cluster_id,
    centroid_json,
    keywords_json,
    representative_messages_json,
    top_entities_json,
    top_channels_json,
    time_distribution_json,
    confidence_score,
    stability_score,
    metadata_json
FROM topic_cluster_metadata
WHERE run_id = $1;
"""

SELECT_TOPIC_METADATA_FOR_CLUSTERS_SQL = """
SELECT DISTINCT ON (public_cluster_id)
    public_cluster_id,
    centroid_json,
    keywords_json,
    representative_messages_json,
    top_entities_json,
    top_channels_json,
    time_distribution_json,
    confidence_score,
    stability_score,
    metadata_json
FROM topic_cluster_metadata
WHERE public_cluster_id = ANY($1::varchar[])
ORDER BY public_cluster_id, run_id DESC;
"""

SELECT_TOPIC_METADATA_SQL = """
SELECT
    public_cluster_id,
    centroid_json,
    keywords_json,
    representative_messages_json,
    top_entities_json,
    top_channels_json,
    time_distribution_json,
    confidence_score,
    stability_score,
    metadata_json
FROM topic_cluster_metadata
WHERE public_cluster_id = $1;
"""

SELECT_ACTIVE_TOPIC_LABELS_FOR_RUN_SQL = """
SELECT public_cluster_id, label, source, status, confidence, created_at
FROM topic_labels
WHERE run_id = $1
  AND status IN ('active', 'noise', 'uncertain', 'rejected');
"""

SELECT_ACTIVE_TOPIC_LABEL_SQL = """
SELECT public_cluster_id, label, source, status, confidence, created_at
FROM topic_labels
WHERE public_cluster_id = $1
  AND status IN ('active', 'noise', 'uncertain', 'rejected')
ORDER BY created_at DESC
LIMIT 1;
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

SELECT_TOPIC_SCORES_FOR_CLUSTERS_SQL = """
SELECT
    public_cluster_id,
    importance_score,
    importance_level,
    score_breakdown_json,
    calculated_at
FROM topic_scores_latest
WHERE public_cluster_id = ANY($1::varchar[]);
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

SELECT_TOPIC_NOVELTY_FOR_RUN_SQL = """
SELECT
    public_cluster_id,
    run_id,
    novelty_score,
    novelty_status,
    nearest_topic_id,
    features_json,
    explanation_json,
    algorithm_version,
    calculated_at
FROM topic_novelty_scores_latest
WHERE run_id = $1;
"""

SELECT_TOPIC_NOVELTY_FOR_CLUSTERS_SQL = """
SELECT
    public_cluster_id,
    run_id,
    novelty_score,
    novelty_status,
    nearest_topic_id,
    features_json,
    explanation_json,
    algorithm_version,
    calculated_at
FROM topic_novelty_scores_latest
WHERE public_cluster_id = ANY($1::varchar[]);
"""

SELECT_TOPIC_NOVELTY_FOR_CLUSTER_SQL = """
SELECT
    public_cluster_id,
    run_id,
    novelty_score,
    novelty_status,
    nearest_topic_id,
    features_json,
    explanation_json,
    calculated_at,
    algorithm_version
FROM topic_novelty_scores_latest
WHERE public_cluster_id = $1
LIMIT 1;
"""

SELECT_TOPIC_SIMILAR_HISTORY_SQL = """
SELECT
    tsl.target_cluster_id,
    tsl.semantic_similarity,
    tsl.entity_overlap,
    tsl.channel_overlap,
    tsl.keyword_overlap,
    tsl.overall_similarity,
    tsl.evidence_json,
    th.first_seen,
    th.last_seen,
    th.message_count,
    th.keywords_json,
    th.entities_json,
    tsl.calculated_at
FROM topic_similarity_links tsl
LEFT JOIN topic_history th ON th.public_cluster_id = tsl.target_cluster_id
WHERE tsl.source_cluster_id = $1
ORDER BY tsl.overall_similarity DESC
LIMIT $2;
"""

SELECT_NOVEL_TOPICS_SQL = """
SELECT
    ns.public_cluster_id,
    ns.run_id,
    ns.novelty_score,
    ns.novelty_status,
    ns.nearest_topic_id,
    ns.features_json,
    ns.explanation_json,
    ns.calculated_at,
    th.first_seen,
    th.last_seen,
    th.message_count,
    th.channel_count,
    th.avg_sentiment,
    th.keywords_json,
    th.entities_json,
    th.channels_json,
    tcm.confidence_score,
    tcm.stability_score,
    tcm.metadata_json
FROM topic_novelty_scores_latest ns
JOIN topic_history th ON th.public_cluster_id = ns.public_cluster_id
LEFT JOIN topic_cluster_metadata tcm ON tcm.public_cluster_id = ns.public_cluster_id
WHERE ns.novelty_status IN ('new', 'uncertain')
  AND ns.novelty_score >= $1
  AND th.first_seen <= $3
  AND COALESCE(th.last_seen, th.first_seen) >= $2
ORDER BY
    CASE ns.novelty_status WHEN 'new' THEN 0 ELSE 1 END,
    ns.novelty_score DESC,
    th.first_seen DESC
LIMIT $4;
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

SELECT_DISTINCT_CHANNELS_SQL = """
SELECT DISTINCT channel FROM raw_messages ORDER BY channel ASC;
"""

SELECT_TOP_ENTITIES_SQL = """
SELECT
    ec.id,
    ec.canonical_name,
    ec.canonical_name_normalized,
    ec.entity_type,
    ec.language,
    ec.wikidata_id,
    ec.description,
    ec.confidence,
    ec.source_model,
    count(nr.id) AS mention_count,
    count(DISTINCT COALESCE(ca.public_cluster_id, 'unclustered')) AS topic_count,
    count(DISTINCT rm.channel) AS channel_count,
    min(rm.message_date) AS first_seen_at,
    max(rm.message_date) AS last_seen_at
FROM raw_messages rm
JOIN ner_results nr ON nr.event_id = rm.event_id
JOIN entity_canonical ec ON ec.id = nr.entity_canonical_id
LEFT JOIN cluster_assignments ca
  ON ca.event_id = rm.event_id
 AND ca.run_id = $1
 AND ca.cluster_id >= 0
WHERE rm.message_date >= $2
  AND rm.message_date <= $3
  AND ec.merged_into_id IS NULL
  AND ($4::varchar IS NULL OR ec.entity_type = $4::varchar)
  AND ($5::varchar IS NULL OR ca.public_cluster_id = $5::varchar)
GROUP BY ec.id
ORDER BY mention_count DESC, ec.canonical_name ASC
LIMIT $6;
"""

# ─── canonical entity SQL ──────────────────────────────────────────────────

SELECT_ENTITY_BY_ID_SQL = """
SELECT
    ec.id,
    ec.canonical_name,
    ec.canonical_name_normalized,
    ec.entity_type,
    ec.language,
    ec.wikidata_id,
    ec.description,
    ec.confidence,
    ec.source_model,
    ec.merged_into_id,
    count(DISTINCT nr.id) FILTER (WHERE rm.event_id IS NOT NULL) AS mention_count,
    min(rm.message_date) AS first_seen_at,
    max(rm.message_date) AS last_seen_at,
    count(DISTINCT rm.channel) AS channel_count,
    count(DISTINCT COALESCE(ca.public_cluster_id, 'unclustered')) FILTER (WHERE rm.event_id IS NOT NULL) AS topic_count
FROM entity_canonical ec
LEFT JOIN ner_results nr
  ON nr.entity_canonical_id = ec.id
LEFT JOIN raw_messages rm
  ON rm.event_id = nr.event_id
 AND rm.message_date >= $2
 AND rm.message_date <= $3
LEFT JOIN cluster_assignments ca
  ON rm.event_id IS NOT NULL
 AND ca.event_id = nr.event_id
 AND ca.run_id = $4
 AND ca.cluster_id >= 0
WHERE ec.id = $1
GROUP BY ec.id;
"""

SELECT_ENTITY_ALIASES_SQL = """
SELECT alias, alias_normalized, source, confidence, is_primary, language, created_at
FROM entity_aliases
WHERE entity_canonical_id = $1
ORDER BY is_primary DESC, confidence DESC, created_at ASC;
"""

SELECT_ENTITY_TIMELINE_SQL = """
SELECT
    date_trunc($4::text, rm.message_date) AS bucket,
    count(*) AS mention_count
FROM ner_results nr
JOIN raw_messages rm ON rm.event_id = nr.event_id
WHERE nr.entity_canonical_id = $1
  AND rm.message_date >= $2
  AND rm.message_date <= $3
GROUP BY bucket
ORDER BY bucket ASC;
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
LEFT JOIN LATERAL (
    SELECT ca.public_cluster_id
    FROM cluster_assignments ca
    JOIN cluster_runs_pg cr ON cr.run_id = ca.run_id
    WHERE ca.event_id = rm.event_id
      AND ca.cluster_id >= 0
    ORDER BY (ca.run_id = $1) DESC, cr.run_timestamp DESC
    LIMIT 1
) ca ON TRUE
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
LEFT JOIN LATERAL (
    SELECT ca.public_cluster_id
    FROM cluster_assignments ca
    JOIN cluster_runs_pg cr ON cr.run_id = ca.run_id
    WHERE ca.event_id = rm.event_id
      AND ca.cluster_id >= 0
    ORDER BY (ca.run_id = $1) DESC, cr.run_timestamp DESC
    LIMIT 1
) ca ON TRUE
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


def _experiment_summary(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "dataset_version": row["dataset_version"],
        "dataset_version_id": str(row["dataset_version_id"]) if row["dataset_version_id"] else None,
        "window_start": _utc_iso(row["window_start"]),
        "window_end": _utc_iso(row["window_end"]),
        "channels": list(row["channels"] or []),
        "seed": row["seed"],
        "status": row["status"],
        "created_at": _utc_iso(row["created_at"]),
        "run_count": int(row["run_count"] or 0),
        "completed_run_count": int(row["completed_run_count"] or 0),
    }


def _experiment_detail(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "dataset_version": row["dataset_version"],
        "dataset_version_id": str(row["dataset_version_id"]) if row["dataset_version_id"] else None,
        "window_start": _utc_iso(row["window_start"]),
        "window_end": _utc_iso(row["window_end"]),
        "channels": list(row["channels"] or []),
        "seed": row["seed"],
        "status": row["status"],
        "created_at": _utc_iso(row["created_at"]),
        "updated_at": _utc_iso(row["updated_at"]),
    }


def _experiment_run_payload(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "cluster_run_id": row["cluster_run_id"],
        "status": row["status"],
        "started_at": _utc_iso(row["started_at"]),
        "finished_at": _utc_iso(row["finished_at"]),
        "duration_seconds": row["duration_seconds"],
        "error_message": row["error_message"],
        "random_seed": row["random_seed"],
        "runtime": row["runtime_json"] or {},
        "model_key": row["model_key"],
        "model_name": row["model_name"],
        "embedding_model": row["embedding_model"],
        "params": row["params_json"] or {},
        "is_baseline": bool(row["is_baseline"]),
    }


def _benchmark_model_name(model_key: str) -> str:
    return {
        "sbert_umap_hdbscan": "SBERT + UMAP + HDBSCAN baseline",
        "bertopic_like": "BERTopic-like embeddings + c-TF-IDF",
        "lda": "Latent Dirichlet Allocation",
        "nmf": "Non-negative Matrix Factorization",
        "top2vec": "Top2Vec optional",
        "ctm": "Contextualized Topic Model optional",
    }.get(model_key, model_key)


class AnalyticsApiService:
    _REVIEW_ENSURE_INTERVAL = 300.0  # seconds between automatic task generation passes

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._pool: Optional[asyncpg.Pool] = None
        self._web_runner: Optional[web.AppRunner] = None
        self._health_site: Optional[web.TCPSite] = None
        self._metrics_site: Optional[web.TCPSite] = None
        self._stop_event = asyncio.Event()
        self._llm_client: Optional[httpx.AsyncClient] = None
        self._review_ensure_last_run: float = 0.0
        self._dataset_validator: Optional[mlops_mod.DatasetValidator] = None
        self._training_orchestrator: Optional[mlops_mod.TrainingOrchestrator] = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._config.postgres.dsn(),
            min_size=self._config.postgres.min_size,
            max_size=self._config.postgres.max_size,
            command_timeout=self._config.postgres.command_timeout,
        )
        self._dataset_validator = mlops_mod.DatasetValidator(self._pool)
        self._training_orchestrator = mlops_mod.TrainingOrchestrator(self._pool)
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
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
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
        app.router.add_get("/analytics/topics", self._handle_clusters)
        app.router.add_get("/analytics/topics/novel", self._handle_novel_topics)
        app.router.add_get("/analytics/review/topics", self._handle_topic_review_tasks)
        app.router.add_post("/analytics/review/topics", self._handle_topic_review_manual_request)
        app.router.add_get("/analytics/review/topics/{id}", self._handle_topic_review_task_detail)
        app.router.add_post(
            "/analytics/review/topics/{id}/confirm",
            self._handle_topic_review_confirm,
        )
        app.router.add_post(
            "/analytics/review/topics/{id}/rename",
            self._handle_topic_review_rename,
        )
        app.router.add_post(
            "/analytics/review/topics/{id}/merge",
            self._handle_topic_review_merge,
        )
        app.router.add_post(
            "/analytics/review/topics/{id}/split",
            self._handle_topic_review_split,
        )
        app.router.add_post(
            "/analytics/review/topics/{id}/reject",
            self._handle_topic_review_reject,
        )
        app.router.add_get("/analytics/experiments/topics", self._handle_topic_experiments)
        app.router.add_post("/analytics/experiments/topics/run", self._handle_topic_experiment_run)
        app.router.add_get(
            "/analytics/experiments/topics/{experimentId}",
            self._handle_topic_experiment_detail,
        )
        app.router.add_get(
            "/analytics/experiments/topics/{experimentId}/metrics",
            self._handle_topic_experiment_metrics,
        )
        app.router.add_get("/analytics/clusters/{clusterId}", self._handle_cluster_detail)
        app.router.add_get("/analytics/topics/{clusterId}", self._handle_cluster_detail)
        app.router.add_get(
            "/analytics/topics/{clusterId}/explanation",
            self._handle_topic_explanation,
        )
        app.router.add_get(
            "/analytics/topics/{clusterId}/similar",
            self._handle_cluster_related,
        )
        app.router.add_get(
            "/analytics/topics/{clusterId}/novelty",
            self._handle_topic_novelty,
        )
        app.router.add_get(
            "/analytics/topics/{clusterId}/similar-history",
            self._handle_topic_similar_history,
        )
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
        app.router.add_get("/analytics/channels", self._handle_channels)
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
        app.router.add_get(
            "/analytics/topics/{clusterId}/summary",
            self._handle_topic_summary,
        )
        app.router.add_post(
            "/analytics/topics/{clusterId}/summary/regenerate",
            self._handle_topic_summary_regenerate,
        )
        # ── Scientific paper endpoints ──────────────────────────────────────
        app.router.add_get("/analytics/papers", self._handle_papers_list)
        app.router.add_get("/analytics/papers/{paper_id}", self._handle_paper_detail)
        app.router.add_get("/analytics/papers/{paper_id}/summary", self._handle_paper_summary)
        app.router.add_post("/analytics/papers/{paper_id}/summarize", self._handle_paper_resummary)
        # ── Annotation / Dataset endpoints ──────────────────────────────────
        app.router.add_get("/analytics/datasets", self._handle_datasets_list)
        app.router.add_post("/analytics/datasets/build", self._handle_datasets_build)
        app.router.add_get("/analytics/datasets/{datasetId}", self._handle_dataset_detail)
        app.router.add_get(
            "/analytics/datasets/{datasetId}/validation",
            self._handle_dataset_validation_get,
        )
        app.router.add_post(
            "/analytics/datasets/{datasetId}/validate",
            self._handle_dataset_validation_post,
        )
        app.router.add_get(
            "/analytics/datasets/{datasetId}/export",
            self._handle_datasets_export,
        )
        app.router.add_get("/analytics/training/jobs", self._handle_training_jobs)
        app.router.add_get("/analytics/training/jobs/{jobId}", self._handle_training_job_detail)
        app.router.add_post("/analytics/training/jobs/preview", self._handle_training_preview)
        app.router.add_post("/analytics/training/jobs", self._handle_training_job_create)
        app.router.add_post(
            "/analytics/training/jobs/{jobId}/cancel",
            self._handle_training_job_cancel,
        )
        app.router.add_get(
            "/analytics/training/jobs/{jobId}/logs",
            self._handle_training_job_logs,
        )
        app.router.add_get("/analytics/models", self._handle_models)
        app.router.add_get("/analytics/models/current", self._handle_current_model)
        app.router.add_get("/analytics/models/{modelId}", self._handle_model_detail)
        app.router.add_post("/analytics/models/{modelId}/accept", self._handle_model_accept)
        app.router.add_post("/analytics/models/{modelId}/reject", self._handle_model_reject)
        app.router.add_post("/analytics/models/{modelId}/deploy", self._handle_model_deploy)
        app.router.add_post("/analytics/models/{modelId}/rollback", self._handle_model_rollback)
        app.router.add_get("/analytics/annotation/tasks", self._handle_annotation_tasks)
        app.router.add_get(
            "/analytics/annotation/tasks/{taskId}",
            self._handle_annotation_task_detail,
        )
        app.router.add_post(
            "/analytics/annotation/tasks/{taskId}/label",
            self._handle_annotation_label,
        )
        app.router.add_post(
            "/analytics/annotation/tasks/{taskId}/skip",
            self._handle_annotation_skip,
        )
        app.router.add_get("/analytics/annotation/stats", self._handle_annotation_stats)
        app.router.add_get("/analytics/annotation/topics", self._handle_annotation_topics)
        app.router.add_get(
            "/analytics/annotation/guidelines",
            self._handle_annotation_guidelines,
        )
        # ── Canonical entity endpoints ───────────────────────────────────────
        app.router.add_get(
            "/analytics/entities/{entityId}",
            self._handle_entity_by_id,
        )
        app.router.add_get(
            "/analytics/entities/{entityId}/aliases",
            self._handle_entity_aliases,
        )
        app.router.add_get(
            "/analytics/entities/{entityId}/timeline",
            self._handle_entity_timeline,
        )
        app.router.add_post(
            "/analytics/entities/{entityId}/merge",
            self._handle_entity_merge,
        )
        app.router.add_post(
            "/analytics/entities/normalization-rules",
            self._handle_create_normalization_rule,
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

    async def _handle_novel_topics(self, request: web.Request) -> web.Response:
        from_dt, to_dt = self._parse_time_range(request)
        min_score = request.query.get("min_score")
        limit = _limit(request.query.get("limit"), 50, 200)
        try:
            threshold = float(min_score) if min_score is not None else 0.55
        except ValueError:
            threshold = 0.55
        async with self._conn() as conn:
            topics = await self._build_novel_topics_list(conn, from_dt, to_dt, threshold, limit)
        return web.json_response(topics)

    async def _handle_topic_experiments(self, request: web.Request) -> web.Response:
        limit = _limit(request.query.get("limit"), 50, 200)
        offset = _offset(request.query.get("offset"))
        async with self._conn() as conn:
            try:
                rows = await conn.fetch(SELECT_TOPIC_EXPERIMENTS_SQL, limit, offset)
            except (
                asyncpg.exceptions.UndefinedTableError,
                asyncpg.exceptions.UndefinedColumnError,
            ):
                return web.json_response([])
        return web.json_response([_experiment_summary(row) for row in rows])

    async def _handle_topic_experiment_detail(self, request: web.Request) -> web.Response:
        experiment_id = request.match_info["experimentId"]
        async with self._conn() as conn:
            try:
                row = await conn.fetchrow(SELECT_TOPIC_EXPERIMENT_SQL, experiment_id)
            except (
                asyncpg.exceptions.UndefinedTableError,
                asyncpg.exceptions.UndefinedColumnError,
            ):
                raise web.HTTPNotFound(text="topic benchmark tables are not migrated")
            if row is None:
                raise web.HTTPNotFound(text=f"experiment not found: {experiment_id}")
            run_rows = await conn.fetch(SELECT_TOPIC_EXPERIMENT_RUNS_SQL, experiment_id)
        payload = _experiment_detail(row)
        payload["runs"] = [_experiment_run_payload(run) for run in run_rows]
        return web.json_response(payload)

    async def _handle_topic_experiment_metrics(self, request: web.Request) -> web.Response:
        experiment_id = request.match_info["experimentId"]
        async with self._conn() as conn:
            try:
                rows = await conn.fetch(SELECT_TOPIC_EXPERIMENT_METRICS_SQL, experiment_id)
            except (
                asyncpg.exceptions.UndefinedTableError,
                asyncpg.exceptions.UndefinedColumnError,
            ):
                raise web.HTTPNotFound(text="topic benchmark tables are not migrated")
        runs: dict[str, dict[str, Any]] = {}
        for row in rows:
            run_id = str(row["run_id"])
            runs.setdefault(
                run_id,
                {
                    "run_id": run_id,
                    "cluster_run_id": row["cluster_run_id"],
                    "model_key": row["model_key"],
                    "model_name": row["model_name"],
                    "is_baseline": bool(row["is_baseline"]),
                    "status": row["status"],
                    "error_message": row["error_message"],
                    "metrics": {},
                    "clusters_url": f"/topics?run_id={row['cluster_run_id']}" if row["cluster_run_id"] else None,
                },
            )
            if row["metric_name"] is not None:
                runs[run_id]["metrics"][row["metric_name"]] = (
                    row["metric_json"] if row["metric_json"] is not None else row["metric_value"]
                )
        return web.json_response({"experiment_id": experiment_id, "runs": list(runs.values())})

    async def _handle_topic_experiment_run(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise web.HTTPBadRequest(text=f"invalid json: {exc}") from exc

        now = datetime.now(timezone.utc)
        models = body.get("models") or ["sbert_umap_hdbscan", "lda", "nmf"]
        if not isinstance(models, list) or len(models) < 1:
            raise web.HTTPBadRequest(text="models must be a non-empty list")
        seed = int(body.get("seed") or 42)
        dataset_version_id = body.get("dataset_version_id")
        from_dt = _parse_iso_datetime(body.get("from") or body.get("window_start") or (now - timedelta(hours=24)).isoformat())
        to_dt = _parse_iso_datetime(body.get("to") or body.get("window_end") or now.isoformat())
        channels = body.get("channels") or []
        dataset_version = body.get("dataset_version") or f"{from_dt.date()}_{to_dt.date()}"
        if dataset_version_id is None:
            if to_dt <= from_dt:
                raise web.HTTPBadRequest(text="window_end must be greater than window_start")
            if not isinstance(channels, list):
                raise web.HTTPBadRequest(text="channels must be a list")
        params = {
            "umap": body.get("umap") or {"n_neighbors": 15, "n_components": 10, "min_dist": 0.1},
            "hdbscan": body.get("hdbscan") or {"min_cluster_size": 5, "min_samples": 3},
            "n_topics": int(body.get("n_topics") or 12),
            "max_messages": int(body.get("max_messages") or 2500),
            "resource_profile": "laptop_3050_i5_cpu_friendly",
        }
        async with self._conn() as conn:
            try:
                async with conn.transaction():
                    if dataset_version_id is not None:
                        dataset_row = await conn.fetchrow(
                            """
                            SELECT id, name, window_start, window_end, channels, status
                            FROM dataset_versions
                            WHERE id = $1::uuid
                            """,
                            dataset_version_id,
                        )
                        if dataset_row is None:
                            raise web.HTTPBadRequest(text=f"dataset not found: {dataset_version_id}")
                        if dataset_row["status"] != "ready":
                            raise web.HTTPBadRequest(text="dataset must be in ready status")
                        from_dt = dataset_row["window_start"]
                        to_dt = dataset_row["window_end"]
                        channels = list(dataset_row["channels"] or [])
                        dataset_version = dataset_row["name"]
                    experiment_id = await conn.fetchval(
                        INSERT_TOPIC_EXPERIMENT_SQL,
                        body.get("name") or f"topic-benchmark-{now:%Y%m%d-%H%M%S}",
                        body.get("description"),
                        dataset_version,
                        dataset_version_id,
                        from_dt,
                        to_dt,
                        channels,
                        seed,
                    )
                    run_ids = []
                    for model_key in models:
                        model_key = str(model_key)
                        config_id = await conn.fetchval(
                            INSERT_TOPIC_MODEL_CONFIG_SQL,
                            experiment_id,
                            model_key,
                            _benchmark_model_name(model_key),
                            body.get("embedding_model") if model_key in {"sbert_umap_hdbscan", "bertopic_like"} else None,
                            json.dumps(params),
                            model_key == "sbert_umap_hdbscan",
                        )
                        run_ids.append(
                            str(await conn.fetchval(INSERT_TOPIC_EXPERIMENT_RUN_SQL, experiment_id, config_id, seed))
                        )
            except (
                asyncpg.exceptions.UndefinedTableError,
                asyncpg.exceptions.UndefinedColumnError,
            ):
                raise web.HTTPServiceUnavailable(
                    text="apply migrations 013_topic_benchmark.sql and 015_topic_benchmark_dataset_link.sql first"
                )
        return web.json_response(
            {
                "experiment_id": str(experiment_id),
                "status": "created",
                "run_ids": run_ids,
                "runner_command": (
                    "python topic_benchmark_runner/main.py "
                    "--config topic_benchmark_runner/config.example.yaml "
                    f"run-existing --experiment-id {experiment_id}"
                ),
                "execution_mode": "automatic_worker",
            },
            status=202,
        )

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

    async def _handle_topic_novelty(self, request: web.Request) -> web.Response:
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        async with self._conn() as conn:
            payload = await self._fetch_topic_novelty(conn, cluster_id)
        if payload is None:
            raise web.HTTPNotFound(text=f"topic novelty not found: {cluster_id}")
        return web.json_response(payload)

    async def _handle_topic_similar_history(self, request: web.Request) -> web.Response:
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        limit = _limit(request.query.get("limit"), 10, 50)
        async with self._conn() as conn:
            payload = await self._fetch_topic_similar_history(conn, cluster_id, limit)
        return web.json_response(payload)

    async def _handle_topic_explanation(self, request: web.Request) -> web.Response:
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        async with self._conn() as conn:
            metadata = await self._fetch_topic_metadata(conn, cluster_id)
            if metadata is None:
                exists = await conn.fetchval(
                    "SELECT 1 FROM cluster_assignments WHERE public_cluster_id = $1 LIMIT 1;",
                    cluster_id,
                )
                if exists is None:
                    raise web.HTTPNotFound(text=f"cluster not found: {cluster_id}")
                metadata = {}
        return web.json_response(
            {
                "cluster_id": cluster_id,
                "keywords": metadata.get("keywords", []),
                "representative_messages": metadata.get("representative_messages", []),
                "top_entities": metadata.get("top_entities", []),
                "top_channels": metadata.get("top_channels", []),
                "time_distribution": metadata.get("time_distribution", []),
                "confidence_score": metadata.get("confidence_score"),
                "stability_score": metadata.get("stability_score"),
                "model": metadata.get("model", {}),
            }
        )

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

    async def _handle_channels(self, request: web.Request) -> web.Response:
        async with self._conn() as conn:
            rows = await conn.fetch(SELECT_DISTINCT_CHANNELS_SQL)
        return web.json_response({"channels": [row["channel"] for row in rows]})

    async def _handle_annotation_topics(self, request: web.Request) -> web.Response:
        async with self._conn() as conn:
            try:
                rows = await conn.fetch(ann_mod.SELECT_ANNOTATION_TOPICS_SQL)
            except Exception:
                return web.json_response({"topics": []})
        return web.json_response({"topics": [row["topic"] for row in rows if row["topic"]]})

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
                "id": str(row["id"]),
                "text": row["canonical_name"],
                "type": _ui_entity_type(row["entity_type"]),
                "entity_type": row["entity_type"],
                "normalized": row["canonical_name_normalized"],
                "canonical_name": row["canonical_name"],
                "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
                "source_model": row["source_model"],
                "language": row["language"],
                "wikidata_id": row["wikidata_id"],
                "description": row["description"],
                "mention_count": int(row["mention_count"] or 0),
                "topic_count": int(row["topic_count"] or 0),
                "channel_count": int(row["channel_count"] or 0),
                "trend_pct": 0,
                "first_seen_at": _utc_iso(row["first_seen_at"]) if row["first_seen_at"] else None,
                "last_seen_at": _utc_iso(row["last_seen_at"]) if row["last_seen_at"] else None,
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

    async def _handle_topic_summary(self, request: web.Request) -> web.Response:
        """GET /analytics/topics/{clusterId}/summary?language=ru
        Proxies to llm_enricher POST /summary/{id} with refresh=False.
        Returns 202 if enricher is computing (timeout exceeded).
        """
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        language = request.rel_url.query.get("language", "ru")
        return await self._proxy_topic_summary(cluster_id, language, refresh=False)

    async def _handle_topic_summary_regenerate(self, request: web.Request) -> web.Response:
        """POST /analytics/topics/{clusterId}/summary/regenerate
        Forces full recomputation of topic summary.
        """
        cluster_id = _decode_cluster_id(request.match_info["clusterId"])
        try:
            body = await request.json()
            language = body.get("language", "ru")
        except Exception:
            language = "ru"
        return await self._proxy_topic_summary(cluster_id, language, refresh=True)

    async def _proxy_topic_summary(
        self, cluster_id: str, language: str, *, refresh: bool
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
        triggered_by = "regenerate" if refresh else "cache_miss"
        try:
            resp = await self._llm_client.post(
                f"/summary/{cluster_id}",
                json={"language": language, "refresh": refresh, "triggered_by": triggered_by},
                timeout=timeout,
            )
            data = resp.json()
            return web.json_response(data, status=resp.status_code)
        except Exception as exc:
            import httpx
            if isinstance(exc, httpx.TimeoutException) and not refresh:
                return web.json_response(
                    {
                        "status": "pending",
                        "message": "Topic summary is being computed. Poll again shortly.",
                    },
                    status=202,
                )
            logger.error("Topic summary proxy error cluster=%s: %s", cluster_id, exc)
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
        cluster_ids = [row["public_cluster_id"] for row in base_rows if row["public_cluster_id"]]

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
        resolution_rows = await conn.fetch(
            SELECT_CLUSTER_SOURCE_RESOLUTIONS_FOR_CLUSTERS_SQL,
            cluster_ids,
        )
        try:
            score_rows = await conn.fetch(SELECT_TOPIC_SCORES_FOR_CLUSTERS_SQL, cluster_ids)
        except asyncpg.UndefinedTableError:
            score_rows = []
        try:
            novelty_rows = await conn.fetch(SELECT_TOPIC_NOVELTY_FOR_CLUSTERS_SQL, cluster_ids)
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            novelty_rows = []
        try:
            metadata_rows = await conn.fetch(SELECT_TOPIC_METADATA_FOR_CLUSTERS_SQL, cluster_ids)
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            metadata_rows = []
        try:
            label_rows = await conn.fetch(
                """
                SELECT DISTINCT ON (public_cluster_id)
                    public_cluster_id, label, source, status, confidence, created_at
                FROM topic_labels
                WHERE public_cluster_id = ANY($1::varchar[])
                  AND status IN ('active', 'noise', 'uncertain', 'rejected')
                ORDER BY public_cluster_id, created_at DESC;
                """,
                cluster_ids,
            )
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            label_rows = []

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
        novelty_by_cluster = {
            row["public_cluster_id"]: self._topic_novelty_payload(row)
            for row in novelty_rows
        }
        metadata_by_cluster = {
            row["public_cluster_id"]: self._topic_metadata_payload(row)
            for row in metadata_rows
        }
        labels_by_cluster = {
            row["public_cluster_id"]: {
                "label": row["label"],
                "source": row["source"],
                "status": row["status"],
                "confidence": round(float(row["confidence"]), 4) if row["confidence"] is not None else None,
                "created_at": _utc_iso(row["created_at"]),
            }
            for row in label_rows
        }

        topics: list[dict[str, Any]] = []
        for row in base_rows:
            public_cluster_id = row["public_cluster_id"]
            cluster_entities = entities_by_cluster.get(public_cluster_id, [])[:5]
            cluster_channels = channels_by_cluster.get(public_cluster_id, [])[:10]
            exact = resolutions_by_cluster.get(public_cluster_id, {}).get("exact")
            inferred = resolutions_by_cluster.get(public_cluster_id, {}).get("inferred")
            reviewed_label = labels_by_cluster.get(public_cluster_id)
            score_data = scores_by_cluster.get(public_cluster_id, {})
            novelty_data = novelty_by_cluster.get(public_cluster_id, {})
            topic_meta = metadata_by_cluster.get(public_cluster_id, {})
            metadata_label = self._topic_label_from_metadata(
                topic_meta.get("top_entities", []),
                topic_meta.get("keywords", []),
            )
            label = (
                reviewed_label["label"]
                if reviewed_label
                else metadata_label
                or self._topic_label(public_cluster_id, cluster_entities, exact, inferred)
            )
            if label == public_cluster_id:
                label = self._topic_label_from_text(row["representative_text"])
            topics.append(
                {
                    "cluster_id": public_cluster_id,
                    "label": label,
                    "message_count": int(row["message_count"] or 0),
                    "channel_count": int(row["channel_count"] or 0),
                    "avg_sentiment": round(float(row["avg_sentiment"] or 0), 4),
                    "top_entities": cluster_entities[:3],
                    "top_keywords": topic_meta.get("keywords", []),
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
                    "novelty_score": novelty_data.get("novelty_score"),
                    "novelty_status": novelty_data.get("novelty_status"),
                    "novelty_explanation": novelty_data.get("explanation"),
                    "confidence_score": topic_meta.get("confidence_score"),
                    "stability_score": topic_meta.get("stability_score"),
                    "review": reviewed_label,
                    "model": topic_meta.get("model"),
                }
            )
        return topics

    def _topic_label_from_text(self, value: Any) -> str:
        text = " ".join(str(value or "").split())
        alnum_count = sum(1 for char in text if char.isalnum())
        if alnum_count < 3:
            return "Untitled topic"
        compact = text[:64].rstrip()
        if len(text) > 64:
            compact += "..."
        return compact

    async def _build_novel_topics_list(
        self,
        conn: asyncpg.Connection,
        from_dt: datetime,
        to_dt: datetime,
        threshold: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            rows = await conn.fetch(SELECT_NOVEL_TOPICS_SQL, threshold, from_dt, to_dt, limit)
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            return []

        topics: list[dict[str, Any]] = []
        for row in rows:
            entities = self._entities_from_history_json(row["entities_json"])[:5]
            channels = self._channels_from_history_json(row["channels_json"])[:10]
            keywords = self._json_value(row["keywords_json"], [])
            metadata = self._json_value(row["metadata_json"], {})
            explanation = self._json_value(row["explanation_json"], {})
            label = (
                self._topic_label_from_metadata(entities, keywords)
                or self._topic_label(row["public_cluster_id"], entities, None, None)
            )
            topics.append(
                {
                    "cluster_id": row["public_cluster_id"],
                    "label": label,
                    "message_count": int(row["message_count"] or 0),
                    "channel_count": int(row["channel_count"] or 0),
                    "avg_sentiment": round(float(row["avg_sentiment"] or 0), 4),
                    "top_entities": entities[:3],
                    "top_keywords": keywords,
                    "is_new": row["novelty_status"] == "new",
                    "first_seen": _utc_iso(row["first_seen"]),
                    "last_seen": _utc_iso(row["last_seen"]),
                    "sparkline": [],
                    "channels": channels,
                    "source_status": "unknown",
                    "importance_score": None,
                    "importance_level": None,
                    "score_calculated_at": None,
                    "novelty_score": round(float(row["novelty_score"] or 0), 4),
                    "novelty_status": row["novelty_status"],
                    "novelty_explanation": explanation,
                    "confidence_score": round(float(row["confidence_score"]), 4)
                    if row["confidence_score"] is not None
                    else None,
                    "stability_score": round(float(row["stability_score"]), 4)
                    if row["stability_score"] is not None
                    else None,
                    "review": None,
                    "model": {
                        "run_id": row["run_id"],
                        "model_version": metadata.get("model_version"),
                        "config_hash": metadata.get("config_hash"),
                        "dataset_version": metadata.get("dataset_version"),
                        "embedding_model": metadata.get("embedding_model"),
                        "created_at": metadata.get("created_at"),
                        "metrics": metadata.get("metrics", {}),
                        "config": metadata.get("config", {}),
                    },
                }
            )
        return topics

    async def _fetch_topic_metadata(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
    ) -> Optional[dict[str, Any]]:
        try:
            row = await conn.fetchrow(SELECT_TOPIC_METADATA_SQL, cluster_id)
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            return None
        return self._topic_metadata_payload(row) if row else None

    def _topic_metadata_payload(self, row: asyncpg.Record) -> dict[str, Any]:
        metadata = self._json_value(row["metadata_json"], {})
        return {
            "centroid": self._json_value(row["centroid_json"], []),
            "keywords": self._json_value(row["keywords_json"], []),
            "representative_messages": self._json_value(
                row["representative_messages_json"], []
            ),
            "top_entities": self._json_value(row["top_entities_json"], []),
            "top_channels": self._json_value(row["top_channels_json"], []),
            "time_distribution": self._json_value(row["time_distribution_json"], []),
            "confidence_score": round(float(row["confidence_score"]), 4)
            if row["confidence_score"] is not None
            else None,
            "stability_score": round(float(row["stability_score"]), 4)
            if row["stability_score"] is not None
            else None,
            "model": {
                "run_id": metadata.get("run_id"),
                "model_version": metadata.get("model_version"),
                "config_hash": metadata.get("config_hash"),
                "dataset_version": metadata.get("dataset_version"),
                "embedding_model": metadata.get("embedding_model"),
                "created_at": metadata.get("created_at"),
                "metrics": metadata.get("metrics", {}),
                "config": metadata.get("config", {}),
            },
        }

    async def _fetch_topic_novelty(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
    ) -> Optional[dict[str, Any]]:
        try:
            row = await conn.fetchrow(SELECT_TOPIC_NOVELTY_FOR_CLUSTER_SQL, cluster_id)
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            return None
        return self._topic_novelty_payload(row) if row else None

    async def _fetch_topic_similar_history(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            rows = await conn.fetch(SELECT_TOPIC_SIMILAR_HISTORY_SQL, cluster_id, limit)
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            return []
        return [self._topic_similarity_history_payload(row) for row in rows]

    def _topic_novelty_payload(self, row: asyncpg.Record) -> dict[str, Any]:
        explanation = self._json_value(row["explanation_json"], {})
        return {
            "cluster_id": row["public_cluster_id"],
            "run_id": row["run_id"],
            "novelty_score": round(float(row["novelty_score"] or 0), 4),
            "novelty_status": row["novelty_status"],
            "nearest_topic_id": row["nearest_topic_id"],
            "features": self._json_value(row["features_json"], {}),
            "explanation": explanation,
            "calculated_at": _utc_iso(row["calculated_at"]),
            "algorithm_version": row["algorithm_version"] if "algorithm_version" in row.keys() else None,
        }

    def _topic_similarity_history_payload(self, row: asyncpg.Record) -> dict[str, Any]:
        entities = self._json_value(row["entities_json"], {})
        if isinstance(entities, dict):
            top_entities = [
                {"id": key, "text": key.split(":", 1)[-1], "mention_count": value}
                for key, value in sorted(entities.items(), key=lambda item: item[1], reverse=True)[:8]
            ]
        else:
            top_entities = []
        return {
            "cluster_id": row["target_cluster_id"],
            "semantic_similarity": round(float(row["semantic_similarity"] or 0), 4),
            "entity_overlap": round(float(row["entity_overlap"] or 0), 4),
            "channel_overlap": round(float(row["channel_overlap"] or 0), 4),
            "keyword_overlap": round(float(row["keyword_overlap"] or 0), 4),
            "overall_similarity": round(float(row["overall_similarity"] or 0), 4),
            "first_seen": _utc_iso(row["first_seen"]),
            "last_seen": _utc_iso(row["last_seen"]),
            "message_count": int(row["message_count"] or 0),
            "keywords": self._json_value(row["keywords_json"], []),
            "top_entities": top_entities,
            "evidence": self._json_value(row["evidence_json"], {}),
            "calculated_at": _utc_iso(row["calculated_at"]),
        }

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
        topic_meta = await self._fetch_topic_metadata(conn, cluster_id) or {}
        novelty = await self._fetch_topic_novelty(conn, cluster_id)
        similar_history = await self._fetch_topic_similar_history(conn, cluster_id, 5)
        try:
            label_row = await conn.fetchrow(SELECT_ACTIVE_TOPIC_LABEL_SQL, cluster_id)
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            label_row = None
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
        review_label = {
            "label": label_row["label"],
            "source": label_row["source"],
            "status": label_row["status"],
            "confidence": round(float(label_row["confidence"]), 4) if label_row["confidence"] is not None else None,
            "created_at": _utc_iso(label_row["created_at"]),
        } if label_row else None
        label = review_label["label"] if review_label else self._topic_label(cluster_id, top_entities, exact, inferred)

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
            "top_keywords": topic_meta.get("keywords", []),
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
            "score_breakdown": self._json_value(score_row["score_breakdown_json"], {}) if score_row else None,
            "score_calculated_at": _utc_iso(score_row["calculated_at"]) if score_row else None,
            "novelty_score": novelty.get("novelty_score") if novelty else None,
            "novelty_status": novelty.get("novelty_status") if novelty else None,
            "novelty": novelty,
            "similar_history": similar_history,
            "centroid": topic_meta.get("centroid"),
            "top_channels": topic_meta.get("top_channels", []),
            "time_distribution": topic_meta.get("time_distribution", []),
            "confidence_score": topic_meta.get("confidence_score"),
            "stability_score": topic_meta.get("stability_score"),
            "review": review_label,
            "model": topic_meta.get("model"),
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

    def _entities_from_history_json(self, value: Any) -> list[dict[str, Any]]:
        raw = self._json_value(value, {})
        if not isinstance(raw, dict):
            return []
        entities: list[dict[str, Any]] = []
        for key, count in sorted(raw.items(), key=lambda item: self._numeric_json_value(item[1]), reverse=True):
            entity_type, _, entity_text = str(key).partition(":")
            try:
                mention_count = int(float(count or 0))
            except (TypeError, ValueError):
                mention_count = 0
            ui_type = _ui_entity_type(entity_type)
            entities.append(
                {
                    "id": f"{ui_type}:{entity_text or key}",
                    "text": entity_text or str(key),
                    "type": ui_type,
                    "mention_count": mention_count,
                }
            )
        return entities

    def _channels_from_history_json(self, value: Any) -> list[dict[str, Any]]:
        raw = self._json_value(value, {})
        if not isinstance(raw, dict):
            return []
        channels: list[dict[str, Any]] = []
        for channel, count in sorted(raw.items(), key=lambda item: self._numeric_json_value(item[1]), reverse=True):
            try:
                message_count = int(float(count or 0))
            except (TypeError, ValueError):
                message_count = 0
            channels.append({"channel": str(channel), "count": message_count})
        return channels

    @staticmethod
    def _numeric_json_value(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

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
        try:
            label_rows = await conn.fetch(
                """
                SELECT DISTINCT ON (public_cluster_id) public_cluster_id, label
                FROM topic_labels
                WHERE public_cluster_id = ANY($1::varchar[])
                  AND status IN ('active', 'noise', 'uncertain', 'rejected')
                ORDER BY public_cluster_id, created_at DESC;
                """,
                cluster_ids,
            )
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            label_rows = []
        try:
            metadata_rows = await conn.fetch(
                """
                SELECT public_cluster_id, top_entities_json, keywords_json
                FROM topic_cluster_metadata
                WHERE public_cluster_id = ANY($1::varchar[]);
                """,
                cluster_ids,
            )
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            metadata_rows = []
        rows = await conn.fetch(
            """
            SELECT public_cluster_id, source_snippet, explanation_json
            FROM cluster_source_resolutions
            WHERE public_cluster_id = ANY($1::varchar[])
              AND resolution_kind = 'inferred';
            """,
            cluster_ids,
        )
        labels: dict[str, str] = {
            row["public_cluster_id"]: str(row["label"])
            for row in label_rows
            if row["label"]
        }
        for row in metadata_rows:
            cluster_id = row["public_cluster_id"]
            if cluster_id in labels:
                continue
            label = self._topic_label_from_metadata(
                row["top_entities_json"],
                row["keywords_json"],
            )
            if label:
                labels[cluster_id] = label
        for row in rows:
            if row["public_cluster_id"] in labels:
                continue
            explanation = row["explanation_json"] or {}
            if isinstance(explanation, str):
                try:
                    explanation = json.loads(explanation)
                except json.JSONDecodeError:
                    explanation = {}
            label = explanation.get("topic_label")
            if label:
                labels[row["public_cluster_id"]] = str(label)
        return labels

    def _topic_label_from_metadata(self, entities_value: Any, keywords_value: Any) -> Optional[str]:
        entities = self._json_value(entities_value, [])
        if isinstance(entities, list):
            names = [
                str(entity.get("text")).strip()
                for entity in entities
                if isinstance(entity, dict) and entity.get("text")
            ]
            if names:
                return " / ".join(names[:2])

        keywords = self._json_value(keywords_value, [])
        if isinstance(keywords, list):
            terms = [
                str(keyword).strip()
                for keyword in keywords
                if str(keyword).strip()
            ]
            if terms:
                return " / ".join(terms[:3])
        return None

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
                        "novelty_status": topic.get("novelty_status"),
                        "novelty_score": topic.get("novelty_score"),
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
        first_source_event_id = (
            (first_source.get("display_source") or {}).get("source_event_id")
        )
        chain = first_source.get("propagation_chain") or []

        nodes = [
            {
                "id": f"topic-{cluster_id}",
                "label": detail["label"],
                "type": "topic",
                "weight": detail["message_count"],
                "community": None,
                "source_status": detail.get("source_status"),
                "novelty_status": detail.get("novelty_status"),
                "novelty_score": detail.get("novelty_score"),
            }
        ]
        seen_nodes = {f"topic-{cluster_id}"}
        edges: list[dict[str, Any]] = []

        for message in documents:
            message["is_first_source"] = (
                bool(first_source_event_id)
                and message["event_id"] == first_source_event_id
            )
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
                        "is_first_source": bool(first_source_event_id)
                        and link["parent_event_id"] == first_source_event_id,
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
                        "is_first_source": bool(first_source_event_id)
                        and link["child_event_id"] == first_source_event_id,
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
            "is_first_source": bool(message.get("is_first_source")),
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

    # ── Annotation / Dataset handlers ─────────────────────────────────────────

    async def _ensure_topic_review_tasks(self, conn: asyncpg.Connection) -> int:
        try:
            rows = await conn.fetch(review_mod.SELECT_REVIEW_CANDIDATES_SQL)
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            return 0

        created = 0
        for row in rows:
            for reason, priority, signals in review_mod.review_reasons_for_candidate(row):
                existing = await conn.fetchval(
                    """
                    SELECT 1
                    FROM topic_review_tasks
                    WHERE public_cluster_id = $1
                      AND reason = $2
                      AND status IN ('pending', 'in_progress', 'deferred', 'completed', 'rejected')
                    LIMIT 1;
                    """,
                    row["public_cluster_id"],
                    reason,
                )
                if existing:
                    continue
                enriched_signals = {
                    **signals,
                    "message_count": int(row["message_count"] or 0),
                    "first_seen": review_mod.iso(row["first_seen"]),
                    "last_seen": review_mod.iso(row["last_seen"]),
                }
                task_id = await conn.fetchval(
                    review_mod.INSERT_REVIEW_TASK_SQL,
                    row["public_cluster_id"],
                    row["run_id"],
                    reason,
                    priority,
                    json.dumps(enriched_signals, default=review_mod.json_default, ensure_ascii=False),
                    None,
                )
                if task_id:
                    created += 1
        return created

    async def _build_topic_review_summary(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
    ) -> Optional[dict[str, Any]]:
        """Lightweight topic summary for the review task list (6 queries vs 14+)."""
        from_dt = datetime(1970, 1, 1, tzinfo=timezone.utc)
        to_dt = datetime.now(timezone.utc) + timedelta(days=1)

        stats = await conn.fetchrow(SELECT_CLUSTER_STATS_SQL, cluster_id, from_dt, to_dt)
        if stats is None or int(stats["message_count"] or 0) == 0:
            return None

        top_entities_rows = await conn.fetch(
            SELECT_CLUSTER_TOP_ENTITIES_SQL, cluster_id, from_dt, to_dt, 10
        )
        docs_rows = await conn.fetch(
            SELECT_CLUSTER_DOCUMENTS_SQL, cluster_id, from_dt, to_dt, 5, 0
        )
        representative_messages = await self._build_messages_payload_from_rows(conn, docs_rows)
        topic_meta = await self._fetch_topic_metadata(conn, cluster_id) or {}
        try:
            label_row = await conn.fetchrow(SELECT_ACTIVE_TOPIC_LABEL_SQL, cluster_id)
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            label_row = None

        top_entities = [
            {
                "id": f"{_ui_entity_type(row['entity_type'])}:{row['entity_key']}",
                "text": row["entity_text"],
                "type": _ui_entity_type(row["entity_type"]),
                "mention_count": int(row["mention_count"] or 0),
            }
            for row in top_entities_rows
        ]
        review_label = {
            "label": label_row["label"],
            "source": label_row["source"],
            "status": label_row["status"],
            "confidence": round(float(label_row["confidence"]), 4) if label_row["confidence"] is not None else None,
            "created_at": _utc_iso(label_row["created_at"]),
        } if label_row else None
        label = review_label["label"] if review_label else self._topic_label(cluster_id, top_entities, None, None)

        return {
            "cluster_id": cluster_id,
            "label": label,
            "message_count": int(stats["message_count"] or 0),
            "channel_count": int(stats["channel_count"] or 0),
            "avg_sentiment": round(float(stats["avg_sentiment"] or 0), 4),
            "top_entities": top_entities,
            "top_keywords": topic_meta.get("keywords", []),
            "is_new": bool(
                stats["first_seen"] and stats["first_seen"] >= to_dt - timedelta(hours=24)
            ),
            "first_seen": _utc_iso(stats["first_seen"]),
            "last_seen": _utc_iso(stats["last_seen"]),
            "sparkline": [],
            "channels": [],
            "representative_messages": representative_messages,
            "related_topics": [],
            "sentiment_breakdown": {"positive": 0, "neutral": 0, "negative": 0},
            "volume_timeline": [],
            "first_source": None,
            "source_status": "unknown",
            "importance_score": None,
            "importance_level": None,
            "score_breakdown": None,
            "score_calculated_at": None,
            "novelty_score": None,
            "novelty_status": None,
            "novelty": None,
            "similar_history": [],
            "centroid": topic_meta.get("centroid"),
            "top_channels": topic_meta.get("top_channels", []),
            "time_distribution": topic_meta.get("time_distribution", []),
            "confidence_score": topic_meta.get("confidence_score"),
            "stability_score": topic_meta.get("stability_score"),
            "review": review_label,
            "model": topic_meta.get("model"),
        }

    async def _handle_topic_review_tasks(self, request: web.Request) -> web.Response:
        status = request.rel_url.query.get("status") or "pending"
        if status == "all":
            status = None
        cluster_id = _decode_cluster_id(request.rel_url.query.get("cluster_id"))
        limit = _limit(request.rel_url.query.get("limit"), 30, 100)
        offset = _offset(request.rel_url.query.get("offset"))
        async with self._conn() as conn:
            now = time.monotonic()
            if now - self._review_ensure_last_run >= self._REVIEW_ENSURE_INTERVAL:
                await self._ensure_topic_review_tasks(conn)
                self._review_ensure_last_run = time.monotonic()
            try:
                rows = await conn.fetch(
                    review_mod.SELECT_REVIEW_TASKS_SQL,
                    status,
                    cluster_id,
                    limit,
                    offset,
                )
            except (
                asyncpg.exceptions.UndefinedTableError,
                asyncpg.exceptions.UndefinedColumnError,
            ):
                return web.json_response([])

            payload = [review_mod.task_payload(row, None) for row in rows]
        return web.json_response(payload)

    async def _handle_topic_review_task_detail(self, request: web.Request) -> web.Response:
        task_id = request.match_info["id"]
        async with self._conn() as conn:
            try:
                row = await conn.fetchrow(review_mod.SELECT_REVIEW_TASK_SQL, task_id)
            except (
                asyncpg.exceptions.UndefinedTableError,
                asyncpg.exceptions.UndefinedColumnError,
            ):
                raise web.HTTPNotFound(reason="review task not found")
            if not row:
                raise web.HTTPNotFound(reason="review task not found")
            topic = await self._build_topic_review_summary(conn, row["public_cluster_id"])
        return web.json_response(review_mod.task_payload(row, topic))

    async def _handle_topic_review_manual_request(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        cluster_id = _decode_cluster_id(body.get("cluster_id"))
        if not cluster_id:
            raise web.HTTPBadRequest(reason="cluster_id is required")
        actor_user_id, actor_username = self._review_actor(body)
        async with self._conn() as conn:
            run_id = await conn.fetchval(
                "SELECT run_id FROM cluster_assignments WHERE public_cluster_id = $1 LIMIT 1;",
                cluster_id,
            )
            if not run_id:
                raise web.HTTPNotFound(reason="cluster not found")
            task_id = await conn.fetchval(
                review_mod.INSERT_REVIEW_TASK_SQL,
                cluster_id,
                run_id,
                "manual_request",
                int(body.get("priority") or 90),
                json.dumps({"comment": body.get("comment")}, ensure_ascii=False),
                actor_user_id,
            )
            await conn.execute(
                review_mod.INSERT_REVIEW_ACTION_SQL,
                task_id,
                cluster_id,
                "manual_request",
                actor_user_id,
                actor_username,
                json.dumps({}, ensure_ascii=False),
                json.dumps({"reason": "manual_request", "comment": body.get("comment")}, ensure_ascii=False),
                body.get("comment"),
            )
        return web.json_response({"ok": True, "task_id": str(task_id)}, status=201)

    async def _handle_topic_review_confirm(self, request: web.Request) -> web.Response:
        return await self._apply_topic_review_action(request, "confirm")

    async def _handle_topic_review_rename(self, request: web.Request) -> web.Response:
        return await self._apply_topic_review_action(request, "rename")

    async def _handle_topic_review_merge(self, request: web.Request) -> web.Response:
        return await self._apply_topic_review_action(request, "merge")

    async def _handle_topic_review_split(self, request: web.Request) -> web.Response:
        return await self._apply_topic_review_action(request, "split")

    async def _handle_topic_review_reject(self, request: web.Request) -> web.Response:
        return await self._apply_topic_review_action(request, "reject")

    async def _apply_topic_review_action(
        self,
        request: web.Request,
        action: str,
    ) -> web.Response:
        if action not in review_mod.REVIEW_ACTIONS:
            raise web.HTTPBadRequest(reason="unsupported review action")
        task_id = request.match_info["id"]
        try:
            task_uuid = uuid.UUID(task_id)
        except ValueError:
            raise web.HTTPBadRequest(reason="review task id must be a UUID")
        body = await self._json_body(request)
        actor_user_id, actor_username = self._review_actor(body)
        comment = body.get("comment")

        async with self._conn() as conn:
            async with conn.transaction():
                task = await conn.fetchrow(review_mod.SELECT_REVIEW_TASK_SQL, task_id)
                if not task:
                    raise web.HTTPNotFound(reason="review task not found")
                cluster_id = task["public_cluster_id"]
                old_label = await conn.fetchrow(review_mod.SELECT_ACTIVE_LABEL_SQL, cluster_id)
                old_value = dict(old_label) if old_label else {
                    "cluster_id": cluster_id,
                    "label": task.get("active_label"),
                    "source": task.get("label_source"),
                }
                run_id = task["run_id"]
                new_value: dict[str, Any] = {"action": action}
                label_id = None

                if action == "confirm":
                    label = (body.get("label") or task.get("active_label") or "").strip()
                    if not label:
                        topic = await self._build_topic_detail(
                            conn,
                            cluster_id,
                            datetime(1970, 1, 1, tzinfo=timezone.utc),
                            datetime.now(timezone.utc) + timedelta(days=1),
                        )
                        label = topic["label"] if topic else cluster_id
                    label_id = await self._replace_topic_label(
                        conn, cluster_id, run_id, label, body.get("description"),
                        "active", "human", body.get("confidence", 1.0), actor_user_id,
                        {"review_task_id": task_id, "review_action": action},
                    )
                    new_value = {"label": label, "source": "human", "label_id": str(label_id)}

                elif action == "rename":
                    label = (body.get("label") or body.get("new_label") or "").strip()
                    if not label:
                        raise web.HTTPBadRequest(reason="label is required")
                    label_id = await self._replace_topic_label(
                        conn, cluster_id, run_id, label, body.get("description"),
                        "active", "human", body.get("confidence", 1.0), actor_user_id,
                        {"review_task_id": task_id, "review_action": action},
                    )
                    new_value = {"label": label, "source": "human", "label_id": str(label_id)}

                elif action == "merge":
                    target_cluster_id = _decode_cluster_id(body.get("target_cluster_id"))
                    if not target_cluster_id:
                        raise web.HTTPBadRequest(reason="target_cluster_id is required")
                    target_exists = await conn.fetchval(
                        "SELECT 1 FROM cluster_assignments WHERE public_cluster_id = $1 LIMIT 1;",
                        target_cluster_id,
                    )
                    if not target_exists:
                        raise web.HTTPNotFound(reason="target cluster not found")
                    label = (body.get("label") or task.get("active_label") or target_cluster_id).strip()
                    label_id = await self._replace_topic_label(
                        conn, target_cluster_id, run_id, label, body.get("description"),
                        "active", "merged", body.get("confidence", 1.0), actor_user_id,
                        {"merged_from": cluster_id, "review_task_id": task_id},
                    )
                    new_value = {
                        "source_cluster_id": cluster_id,
                        "target_cluster_id": target_cluster_id,
                        "label": label,
                        "source": "merged",
                    }

                elif action == "split":
                    child_labels = body.get("child_labels") or []
                    if not isinstance(child_labels, list) or len(child_labels) < 2:
                        raise web.HTTPBadRequest(reason="child_labels must contain at least two labels")
                    event_ids = body.get("event_ids") or []
                    label_id = await self._replace_topic_label(
                        conn, cluster_id, run_id, f"{task.get('active_label') or cluster_id} / split",
                        body.get("description"), "uncertain", "split", body.get("confidence"),
                        actor_user_id,
                        {"child_labels": child_labels, "event_ids": event_ids, "review_task_id": task_id},
                    )
                    new_value = {
                        "source_cluster_id": cluster_id,
                        "child_labels": child_labels,
                        "event_ids": event_ids,
                        "source": "split",
                    }

                elif action == "reject":
                    reason = body.get("reason") or body.get("quality") or "noise"
                    label_text = body.get("label") or task.get("active_label") or cluster_id
                    label_id = await self._replace_topic_label(
                        conn, cluster_id, run_id, label_text, body.get("description"),
                        "noise" if reason == "noise" else "rejected", "human",
                        body.get("confidence", 1.0), actor_user_id,
                        {"review_task_id": task_id, "review_action": action, "reason": reason},
                    )
                    new_value = {"status": "noise" if reason == "noise" else "rejected", "reason": reason}

                action_id = await conn.fetchval(
                    review_mod.INSERT_REVIEW_ACTION_SQL,
                    task_uuid,
                    cluster_id,
                    action,
                    actor_user_id,
                    actor_username,
                    json.dumps(old_value, default=review_mod.json_default, ensure_ascii=False),
                    json.dumps(new_value, default=review_mod.json_default, ensure_ascii=False),
                    comment,
                )

                if action == "merge":
                    await conn.execute(
                        review_mod.INSERT_MERGE_HISTORY_SQL,
                        cluster_id, new_value["target_cluster_id"], label_id, action_id,
                        comment, actor_user_id, json.dumps({"task_id": task_id}, ensure_ascii=False),
                    )
                elif action == "split":
                    await conn.execute(
                        review_mod.INSERT_SPLIT_HISTORY_SQL,
                        cluster_id, json.dumps(new_value["child_labels"], ensure_ascii=False),
                        json.dumps(new_value["event_ids"], ensure_ascii=False), action_id,
                        comment, actor_user_id, json.dumps({"task_id": task_id}, ensure_ascii=False),
                    )

                task_status = "rejected" if action == "reject" else "completed"
                await conn.execute(review_mod.UPDATE_TASK_DONE_SQL, task_id, task_status)

        return web.json_response(
            {
                "ok": True,
                "task_id": task_id,
                "cluster_id": cluster_id,
                "action": action,
                "label_id": str(label_id) if label_id else None,
            }
        )

    async def _replace_topic_label(
        self,
        conn: asyncpg.Connection,
        cluster_id: str,
        run_id: str | None,
        label: str,
        description: str | None,
        status: str,
        source: str,
        confidence: Any,
        actor_user_id: uuid.UUID | None,
        metadata: dict[str, Any],
    ) -> uuid.UUID:
        await conn.execute(review_mod.SUPERSEDE_ACTIVE_LABEL_SQL, cluster_id)
        return await conn.fetchval(
            review_mod.INSERT_TOPIC_LABEL_SQL,
            cluster_id,
            run_id,
            label,
            description,
            status,
            source,
            review_mod.clamp_confidence(confidence),
            actor_user_id,
            json.dumps(metadata, ensure_ascii=False),
        )

    async def _json_body(self, request: web.Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="invalid JSON body")
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(reason="JSON body must be an object")
        return body

    def _review_actor(self, body: dict[str, Any]) -> tuple[uuid.UUID | None, str | None]:
        raw_user_id = body.get("actor_user_id") or body.get("user_id")
        actor_user_id = uuid.UUID(raw_user_id) if raw_user_id else None
        actor_username = body.get("actor_username") or body.get("username") or "analyst"
        return actor_user_id, actor_username

    async def _handle_dataset_detail(self, request: web.Request) -> web.Response:
        dataset_id = request.match_info["datasetId"]
        task_type = request.rel_url.query.get("task_type") or "topic_classification"
        async with self._conn() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    dv.id,
                    dv.name,
                    dv.description,
                    dv.language,
                    dv.window_start,
                    dv.window_end,
                    dv.channels,
                    dv.min_word_count,
                    dv.dedup_strategy,
                    dv.total_items,
                    dv.status,
                    dv.config_json,
                    dv.created_at,
                    dv.updated_at,
                    count(DISTINCT di.id) AS item_count,
                    count(DISTINCT CASE WHEN at2.status = 'completed' THEN di.id END) AS annotated_count
                FROM dataset_versions dv
                LEFT JOIN dataset_items di ON di.dataset_version_id = dv.id
                LEFT JOIN annotation_tasks at2 ON at2.dataset_item_id = di.id
                WHERE dv.id = $1::uuid
                GROUP BY dv.id
                """,
                dataset_id,
            )
            if not row:
                raise web.HTTPNotFound(reason="dataset not found")
            validation_row = await conn.fetchrow(
                """
                SELECT id, dataset_id, task_type, status, report_json, created_at
                FROM dataset_validation_reports
                WHERE dataset_id=$1::uuid AND task_type=$2
                ORDER BY created_at DESC
                LIMIT 1
                """,
                dataset_id,
                task_type,
            )
        payload = ann_mod.dataset_payload(row)
        if validation_row:
            payload["validation"] = mlops_mod.validation_report_payload(validation_row)
        return web.json_response(payload)

    async def _handle_dataset_validation_get(self, request: web.Request) -> web.Response:
        if self._dataset_validator is None:
            raise web.HTTPServiceUnavailable(reason="service not ready")
        dataset_id = request.match_info["datasetId"]
        task_type = request.rel_url.query.get("task_type") or "topic_classification"
        report = await self._dataset_validator.latest(dataset_id, task_type)
        if report is None:
            raise web.HTTPNotFound(reason="validation report not found")
        return web.json_response(report)

    async def _handle_dataset_validation_post(self, request: web.Request) -> web.Response:
        if self._dataset_validator is None:
            raise web.HTTPServiceUnavailable(reason="service not ready")
        dataset_id = request.match_info["datasetId"]
        body = await self._json_body(request)
        task_type = body.get("task_type") or request.rel_url.query.get("task_type") or "topic_classification"
        try:
            report = await self._dataset_validator.validate(dataset_id, task_type)
        except ValueError as exc:
            raise web.HTTPBadRequest(reason=str(exc))
        return web.json_response(report)

    async def _handle_training_preview(self, request: web.Request) -> web.Response:
        if self._training_orchestrator is None:
            raise web.HTTPServiceUnavailable(reason="service not ready")
        body = await self._json_body(request)
        dataset_id = body.get("dataset_id")
        task_type = body.get("task_type")
        if not dataset_id or not task_type:
            raise web.HTTPBadRequest(reason="dataset_id and task_type are required")
        try:
            plan = await self._training_orchestrator.preview(
                dataset_id,
                task_type,
                body.get("base_model"),
                body.get("training_config") or {},
            )
        except ValueError as exc:
            raise web.HTTPBadRequest(reason=str(exc))
        return web.json_response(plan)

    async def _handle_training_job_create(self, request: web.Request) -> web.Response:
        if self._training_orchestrator is None:
            raise web.HTTPServiceUnavailable(reason="service not ready")
        body = await self._json_body(request)
        if body.get("consent_to_train") is not True:
            raise web.HTTPBadRequest(reason="consent_to_train=true is required; no training job was created")
        dataset_id = body.get("dataset_id")
        task_type = body.get("task_type")
        if not dataset_id or not task_type:
            raise web.HTTPBadRequest(reason="dataset_id and task_type are required")
        try:
            job = await self._training_orchestrator.create_job(
                dataset_id=dataset_id,
                task_type=task_type,
                base_model=body.get("base_model") or mlops_mod.DEFAULT_BASE_MODELS.get(task_type, "mock-base-model"),
                training_config=body.get("training_config") or {},
                consent_to_train=True,
                actor_user_id=body.get("actor_user_id") or body.get("user_id"),
            )
        except ValueError as exc:
            raise web.HTTPBadRequest(reason=str(exc))
        TRAINING_JOBS_TOTAL.labels(status="queued", task_type=task_type).inc()
        asyncio.create_task(self._run_training_job_background(job["id"], task_type))
        return web.json_response(job, status=201)

    async def _run_training_job_background(self, job_id: str, task_type: str) -> None:
        if self._training_orchestrator is None:
            return
        started = time.monotonic()
        result = await self._training_orchestrator.run_job(job_id)
        TRAINING_JOBS_TOTAL.labels(status=result["status"], task_type=task_type).inc()
        TRAINING_DURATION_SECONDS.labels(task_type=task_type).observe(time.monotonic() - started)
        if result["status"] == "failed":
            TRAINING_JOBS_FAILED_TOTAL.labels(task_type=task_type).inc()
        candidate = result.get("candidate_model")
        if candidate:
            model_type = mlops_mod.TASK_TO_MODEL_TYPE.get(task_type, "unknown")
            MODEL_VERSIONS_TOTAL.labels(model_type=model_type, status=candidate["status"]).inc()

    async def _handle_training_jobs(self, request: web.Request) -> web.Response:
        q = request.rel_url.query
        status = q.get("status") or None
        limit = _limit(q.get("limit"), 50, 200)
        offset = _offset(q.get("offset"))
        async with self._conn() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    tj.*,
                    dv.name AS dataset_name,
                    mv.id AS model_version_id,
                    mv.version AS model_version,
                    mv.status AS model_status,
                    mv.metrics_json AS model_metrics
                FROM training_jobs tj
                JOIN dataset_versions dv ON dv.id = tj.dataset_id
                LEFT JOIN model_versions mv ON mv.training_job_id = tj.id
                WHERE ($1::text IS NULL OR tj.status = $1)
                ORDER BY tj.created_at DESC
                LIMIT $2 OFFSET $3
                """,
                status,
                limit,
                offset,
            )
        return web.json_response([mlops_mod.training_job_payload(row) for row in rows])

    async def _handle_training_job_detail(self, request: web.Request) -> web.Response:
        job_id = request.match_info["jobId"]
        async with self._conn() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    tj.*,
                    dv.name AS dataset_name,
                    mv.id AS model_version_id,
                    mv.version AS model_version,
                    mv.status AS model_status,
                    mv.metrics_json AS model_metrics
                FROM training_jobs tj
                JOIN dataset_versions dv ON dv.id = tj.dataset_id
                LEFT JOIN model_versions mv ON mv.training_job_id = tj.id
                WHERE tj.id = $1::uuid
                """,
                job_id,
            )
            if not row:
                raise web.HTTPNotFound(reason="training job not found")
            evaluations = await conn.fetch(
                """
                SELECT split, metrics_json, confusion_matrix_json, created_at
                FROM model_evaluation_results
                WHERE model_version_id = $1::uuid
                ORDER BY created_at DESC
                """,
                row["model_version_id"],
            ) if row["model_version_id"] else []
        payload = mlops_mod.training_job_payload(row)
        payload["evaluations"] = [
            {
                "split": r["split"],
                "metrics": mlops_mod._json(r["metrics_json"]),
                "confusion_matrix": mlops_mod._json(r["confusion_matrix_json"]),
                "created_at": mlops_mod.utc_iso(r["created_at"]),
            }
            for r in evaluations
        ]
        return web.json_response(payload)

    async def _handle_training_job_cancel(self, request: web.Request) -> web.Response:
        if self._training_orchestrator is None:
            raise web.HTTPServiceUnavailable(reason="service not ready")
        job_id = request.match_info["jobId"]
        try:
            job = await self._training_orchestrator.cancel_job(job_id)
        except ValueError as exc:
            raise web.HTTPBadRequest(reason=str(exc))
        return web.json_response(job)

    async def _handle_training_job_logs(self, request: web.Request) -> web.Response:
        job_id = request.match_info["jobId"]
        async with self._conn() as conn:
            rows = await conn.fetch(
                """
                SELECT id, level, message, metadata_json, created_at
                FROM training_job_logs
                WHERE training_job_id=$1::uuid
                ORDER BY created_at ASC
                """,
                job_id,
            )
        return web.json_response([
            {
                "id": str(row["id"]),
                "level": row["level"],
                "message": row["message"],
                "metadata": mlops_mod._json(row["metadata_json"]),
                "created_at": mlops_mod.utc_iso(row["created_at"]),
            }
            for row in rows
        ])

    async def _handle_models(self, request: web.Request) -> web.Response:
        q = request.rel_url.query
        model_type = q.get("model_type") or None
        status = q.get("status") or None
        async with self._conn() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM model_versions
                WHERE ($1::text IS NULL OR model_type=$1)
                  AND ($2::text IS NULL OR status=$2)
                ORDER BY created_at DESC
                LIMIT 200
                """,
                model_type,
                status,
            )
        return web.json_response([mlops_mod.model_payload(row) for row in rows])

    async def _handle_model_detail(self, request: web.Request) -> web.Response:
        model_id = request.match_info["modelId"]
        async with self._conn() as conn:
            row = await conn.fetchrow("SELECT * FROM model_versions WHERE id=$1::uuid", model_id)
            if not row:
                raise web.HTTPNotFound(reason="model not found")
            evaluations = await conn.fetch(
                """
                SELECT dataset_id, split, metrics_json, confusion_matrix_json, created_at
                FROM model_evaluation_results
                WHERE model_version_id=$1::uuid
                ORDER BY created_at DESC
                """,
                model_id,
            )
            history = await conn.fetch(
                """
                SELECT previous_model_version_id, deployed_by, deployed_at, rollback_available, metadata_json
                FROM model_deployment_history
                WHERE model_version_id=$1::uuid
                ORDER BY deployed_at DESC
                """,
                model_id,
            )
        payload = mlops_mod.model_payload(row)
        payload["evaluations"] = [
            {
                "dataset_id": str(r["dataset_id"]),
                "split": r["split"],
                "metrics": mlops_mod._json(r["metrics_json"]),
                "confusion_matrix": mlops_mod._json(r["confusion_matrix_json"]),
                "created_at": mlops_mod.utc_iso(r["created_at"]),
            }
            for r in evaluations
        ]
        payload["deployment_history"] = [
            {
                "previous_model_version_id": str(r["previous_model_version_id"]) if r["previous_model_version_id"] else None,
                "deployed_by": str(r["deployed_by"]) if r["deployed_by"] else None,
                "deployed_at": mlops_mod.utc_iso(r["deployed_at"]),
                "rollback_available": bool(r["rollback_available"]),
                "metadata": mlops_mod._json(r["metadata_json"]),
            }
            for r in history
        ]
        return web.json_response(payload)

    async def _handle_current_model(self, request: web.Request) -> web.Response:
        model_type = request.rel_url.query.get("model_type")
        if not model_type:
            raise web.HTTPBadRequest(reason="model_type is required")
        async with self._conn() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM model_versions
                WHERE model_type=$1 AND status='deployed'
                ORDER BY deployed_at DESC
                LIMIT 1
                """,
                model_type,
            )
        if not row:
            raise web.HTTPNotFound(reason="current production model not found")
        return web.json_response(mlops_mod.model_payload(row))

    async def _handle_model_accept(self, request: web.Request) -> web.Response:
        model_id = request.match_info["modelId"]
        async with self._conn() as conn:
            row = await conn.fetchrow(
                """
                UPDATE model_versions
                SET status='accepted'
                WHERE id=$1::uuid AND status IN ('candidate', 'accepted')
                RETURNING *
                """,
                model_id,
            )
            if not row:
                raise web.HTTPBadRequest(reason="model not found or cannot be accepted")
        return web.json_response(mlops_mod.model_payload(row))

    async def _handle_model_reject(self, request: web.Request) -> web.Response:
        model_id = request.match_info["modelId"]
        async with self._conn() as conn:
            row = await conn.fetchrow(
                """
                UPDATE model_versions
                SET status='rejected'
                WHERE id=$1::uuid AND status IN ('candidate', 'accepted')
                RETURNING *
                """,
                model_id,
            )
            if not row:
                raise web.HTTPBadRequest(reason="model not found or cannot be rejected")
        return web.json_response(mlops_mod.model_payload(row))

    async def _handle_model_deploy(self, request: web.Request) -> web.Response:
        model_id = request.match_info["modelId"]
        body = await self._json_body(request)
        if body.get("consent_to_deploy") is not True:
            raise web.HTTPBadRequest(reason="consent_to_deploy=true is required; no deployment was performed")
        async with self._conn() as conn:
            try:
                payload = await mlops_mod.deploy_model(
                    conn,
                    model_id=model_id,
                    consent_to_deploy=True,
                    actor_user_id=body.get("actor_user_id") or body.get("user_id"),
                    actor_role=body.get("actor_role") or request.headers.get("X-User-Role"),
                )
            except PermissionError as exc:
                raise web.HTTPForbidden(reason=str(exc))
            except ValueError as exc:
                raise web.HTTPBadRequest(reason=str(exc))
        MODEL_DEPLOYMENTS_TOTAL.labels(model_type=payload["model_type"], status="deployed").inc()
        return web.json_response(payload)

    async def _handle_model_rollback(self, request: web.Request) -> web.Response:
        model_id = request.match_info["modelId"]
        body = await self._json_body(request)
        async with self._conn() as conn:
            previous_id = await conn.fetchval(
                """
                SELECT previous_model_version_id
                FROM model_deployment_history
                WHERE model_version_id=$1::uuid AND rollback_available=TRUE
                ORDER BY deployed_at DESC
                LIMIT 1
                """,
                model_id,
            )
            if not previous_id:
                raise web.HTTPBadRequest(reason="rollback target not found")
            try:
                payload = await mlops_mod.deploy_model(
                    conn,
                    model_id=str(previous_id),
                    consent_to_deploy=True,
                    actor_user_id=body.get("actor_user_id") or body.get("user_id"),
                    actor_role=body.get("actor_role") or request.headers.get("X-User-Role"),
                )
            except PermissionError as exc:
                raise web.HTTPForbidden(reason=str(exc))
            except ValueError as exc:
                raise web.HTTPBadRequest(reason=str(exc))
        MODEL_DEPLOYMENTS_TOTAL.labels(model_type=payload["model_type"], status="rollback").inc()
        return web.json_response(payload)

    async def _handle_datasets_list(self, request: web.Request) -> web.Response:
        limit = _limit(request.rel_url.query.get("limit"), 50, 200)
        offset = _offset(request.rel_url.query.get("offset"))
        async with self._conn() as conn:
            rows = await conn.fetch(ann_mod.SELECT_DATASETS_SQL, limit, offset)
        return web.json_response([ann_mod.dataset_payload(r) for r in rows])

    async def _handle_datasets_build(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="invalid JSON body")

        name = (body.get("name") or "").strip()
        if not name:
            raise web.HTTPBadRequest(reason="name is required")
        window_start_s = body.get("window_start")
        window_end_s = body.get("window_end")
        if not window_start_s or not window_end_s:
            raise web.HTTPBadRequest(reason="window_start and window_end are required")
        try:
            window_start = _parse_iso_datetime(window_start_s)
            window_end = _parse_iso_datetime(window_end_s)
        except Exception:
            raise web.HTTPBadRequest(reason="invalid datetime format")

        if self._pool is None:
            raise web.HTTPServiceUnavailable(reason="service not ready")

        try:
            version_id = await ann_mod.build_dataset(
                pool=self._pool,
                name=name,
                description=body.get("description") or "",
                window_start=window_start,
                window_end=window_end,
                channels=body.get("channels") or [],
                min_word_count=int(body.get("min_word_count") or 5),
                dedup_strategy=body.get("dedup_strategy") or "event_id",
                languages=body.get("languages") or ["ru", "en"],
                created_by=body.get("created_by"),
            )
        except Exception as exc:
            import asyncpg as _asyncpg
            if isinstance(exc, _asyncpg.UniqueViolationError):
                return web.json_response(
                    {"error": f"Датасет с именем «{name}» уже существует"},
                    status=409,
                )
            raise
        return web.json_response({"id": version_id, "status": "ready"}, status=201)

    async def _handle_datasets_export(self, request: web.Request) -> web.Response:
        dataset_id = request.match_info["datasetId"]
        fmt = request.rel_url.query.get("format", "jsonl")
        if fmt not in ("csv", "jsonl", "octis", "huggingface"):
            raise web.HTTPBadRequest(reason=f"unsupported format: {fmt}")
        async with self._conn() as conn:
            try:
                content_type, filename, data = await ann_mod.export_dataset(conn, dataset_id, fmt)
            except ValueError as exc:
                raise web.HTTPBadRequest(reason=str(exc))
        return web.Response(
            body=data,
            content_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def _handle_annotation_tasks(self, request: web.Request) -> web.Response:
        q = request.rel_url.query
        status = q.get("status") or None
        dataset_id = q.get("dataset_id") or None
        annotator_id = q.get("annotator_id") or None
        limit = _limit(q.get("limit"), 20, 100)
        offset = _offset(q.get("offset"))
        async with self._conn() as conn:
            rows = await conn.fetch(
                ann_mod.SELECT_ANNOTATION_TASKS_SQL,
                status,
                dataset_id,
                annotator_id,
                limit,
                offset,
            )
        return web.json_response([ann_mod.task_payload(r) for r in rows])

    async def _handle_annotation_task_detail(self, request: web.Request) -> web.Response:
        task_id = request.match_info["taskId"]
        async with self._conn() as conn:
            row = await conn.fetchrow(ann_mod.SELECT_TASK_DETAIL_SQL, task_id)
        if not row:
            raise web.HTTPNotFound(reason="task not found")
        return web.json_response(ann_mod.task_payload(row))

    async def _handle_annotation_label(self, request: web.Request) -> web.Response:
        task_id = request.match_info["taskId"]
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(reason="invalid JSON body")

        user_id = (body.get("user_id") or "").strip()
        username = (body.get("username") or "annotator").strip()
        if not user_id:
            raise web.HTTPBadRequest(reason="user_id is required")

        quality = body.get("quality") or "useful"
        if quality not in ("useful", "noise", "duplicate"):
            raise web.HTTPBadRequest(reason="quality must be useful|noise|duplicate")

        broad_topic = body.get("broad_topic") or None
        storyline = body.get("storyline") or None
        is_new_storyline = body.get("is_new_storyline")
        entities = body.get("entities") or []
        sentiment = body.get("sentiment") or None
        if sentiment and sentiment not in ("positive", "neutral", "negative"):
            sentiment = None
        comment = body.get("comment") or None
        confidence = body.get("annotator_confidence")
        if confidence is not None:
            confidence = max(0.0, min(1.0, float(confidence)))

        _ENTITY_TYPE_MAP = {
            "PER": "PERSON", "PERSON": "PERSON",
            "ORG": "ORG",
            "LOC": "LOC",
            "GPE": "GPE",
        }

        async with self._conn() as conn:
            # Upsert annotator
            annotator_id = await conn.fetchval(
                ann_mod.UPSERT_ANNOTATOR_SQL, user_id, username
            )
            # Upsert label
            await conn.execute(
                ann_mod.UPSERT_LABEL_SQL,
                task_id, annotator_id,
                broad_topic, None,
                storyline, is_new_storyline,
                quality, json.dumps(entities, ensure_ascii=False),
                sentiment, comment, confidence,
            )
            # Mark task completed
            await conn.execute(ann_mod.UPDATE_TASK_COMPLETE_SQL, task_id, annotator_id)
            await conn.execute(ann_mod.INCREMENT_ANNOTATOR_COUNT_SQL, annotator_id)

            # ── Fetch task context for backfill (once, only when needed) ─────
            task_ctx = None
            if entities or storyline:
                task_ctx = await conn.fetchrow(
                    """
                    SELECT di.event_id, di.cluster_id,
                           pm.id AS pm_id,
                           rm.message_id, rm.channel, rm.message_date
                    FROM annotation_tasks at2
                    JOIN dataset_items di ON di.id = at2.dataset_item_id
                    LEFT JOIN preprocessed_messages pm ON pm.event_id = di.event_id
                    LEFT JOIN raw_messages rm ON rm.id = pm.raw_message_id
                    WHERE at2.id = $1
                    LIMIT 1
                    """,
                    task_id,
                )

            # ── Backfill entities → ner_results ──────────────────────────────
            if entities and task_ctx and task_ctx["pm_id"]:
                for ent in entities:
                    db_type = _ENTITY_TYPE_MAP.get((ent.get("type") or "").upper())
                    text = (ent.get("text") or "").strip()
                    if not db_type or not text:
                        continue
                    await conn.execute(
                        """
                        INSERT INTO ner_results (
                            preprocessed_message_id, message_id, channel, event_id,
                            entity_text, entity_type, start_pos, end_pos, confidence,
                            normalized_text, model_name, event_timestamp, extracted_at
                        )
                        SELECT $1, $2, $3, $4, $5, $6, 0, 1, 1.0, $5, 'annotation', $7, NOW()
                        WHERE NOT EXISTS (
                            SELECT 1 FROM ner_results
                            WHERE event_id = $4
                              AND lower(entity_text) = lower($5)
                              AND entity_type = $6
                              AND model_name = 'annotation'
                        )
                        """,
                        task_ctx["pm_id"], task_ctx["message_id"],
                        task_ctx["channel"], task_ctx["event_id"],
                        text, db_type, task_ctx["message_date"],
                    )

            # ── Backfill storyline → topic_labels ────────────────────────────
            if storyline and task_ctx and task_ctx.get("cluster_id"):
                cluster_id = task_ctx["cluster_id"]
                await conn.execute(
                    "UPDATE topic_labels SET status = 'superseded' "
                    "WHERE public_cluster_id = $1 AND status = 'active'",
                    cluster_id,
                )
                await conn.execute(
                    "INSERT INTO topic_labels (public_cluster_id, label, source, confidence) "
                    "VALUES ($1, $2, 'human', $3)",
                    cluster_id, storyline, confidence or 1.0,
                )

        return web.json_response({"ok": True, "task_id": task_id})

    async def _handle_annotation_skip(self, request: web.Request) -> web.Response:
        task_id = request.match_info["taskId"]
        async with self._conn() as conn:
            await conn.execute(ann_mod.UPDATE_TASK_SKIP_SQL, task_id)
        return web.json_response({"ok": True, "task_id": task_id})

    async def _handle_annotation_stats(self, request: web.Request) -> web.Response:
        dataset_id = request.rel_url.query.get("dataset_id") or None
        async with self._conn() as conn:
            rows = await conn.fetch(ann_mod.SELECT_ANNOTATION_STATS_SQL, dataset_id)
        result = []
        for row in rows:
            total = int(row["total_items"] or 0)
            annotated = int(row["annotated_items"] or 0)
            result.append({
                "dataset_version_id": str(row["dataset_version_id"]),
                "dataset_version_name": row["dataset_version_name"],
                "total_items": total,
                "annotated_items": annotated,
                "pending_items": int(row["pending_items"] or 0),
                "skipped_items": int(row["skipped_items"] or 0),
                "annotation_progress": round(annotated / total, 3) if total > 0 else 0.0,
                "quality_distribution": {
                    "useful": int(row["useful_count"] or 0),
                    "noise": int(row["noise_count"] or 0),
                    "duplicate": int(row["duplicate_count"] or 0),
                },
                "distinct_topics": int(row["distinct_topics"] or 0),
            })
        return web.json_response(result)

    async def _handle_annotation_guidelines(self, request: web.Request) -> web.Response:
        async with self._conn() as conn:
            row = await conn.fetchrow(ann_mod.SELECT_ACTIVE_GUIDELINES_SQL)
        if not row:
            return web.json_response({"version": None, "content": None})
        return web.json_response({
            "id": str(row["id"]),
            "version": row["version"],
            "title": row["title"],
            "content": row["content"],
            "created_at": ann_mod._iso(row["created_at"]),
        })

    # ── canonical entity handlers ────────────────────────────────────────────

    async def _handle_entity_by_id(self, request: web.Request) -> web.Response:
        import uuid as _uuid
        entity_id_str = request.match_info["entityId"]
        try:
            entity_uuid = _uuid.UUID(entity_id_str)
        except ValueError:
            raise web.HTTPBadRequest(text="entityId must be a valid UUID")

        from_dt, to_dt = self._parse_time_range(request)
        async with self._conn() as conn:
            run_id = await self._latest_run_id(conn)
            row = await conn.fetchrow(SELECT_ENTITY_BY_ID_SQL, entity_uuid, from_dt, to_dt, run_id)
        if not row:
            raise web.HTTPNotFound(text=f"entity not found: {entity_id_str}")

        if row["merged_into_id"] is not None:
            raise web.HTTPFound(
                location=f"/analytics/entities/{row['merged_into_id']}"
            )

        return web.json_response({
            "id": str(row["id"]),
            "text": row["canonical_name"],
            "type": _ui_entity_type(row["entity_type"]),
            "canonical_name": row["canonical_name"],
            "normalized": row["canonical_name_normalized"],
            "entity_type": row["entity_type"],
            "language": row["language"],
            "wikidata_id": row["wikidata_id"],
            "description": row["description"],
            "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
            "source_model": row["source_model"],
            "mention_count": int(row["mention_count"] or 0),
            "channel_count": int(row["channel_count"] or 0),
            "topic_count": int(row["topic_count"] or 0),
            "first_seen_at": _utc_iso(row["first_seen_at"]) if row["first_seen_at"] else None,
            "last_seen_at": _utc_iso(row["last_seen_at"]) if row["last_seen_at"] else None,
            "merged_into_id": str(row["merged_into_id"]) if row["merged_into_id"] else None,
        })

    async def _handle_entity_aliases(self, request: web.Request) -> web.Response:
        import uuid as _uuid
        entity_id_str = request.match_info["entityId"]
        try:
            entity_uuid = _uuid.UUID(entity_id_str)
        except ValueError:
            raise web.HTTPBadRequest(text="entityId must be a valid UUID")

        async with self._conn() as conn:
            rows = await conn.fetch(SELECT_ENTITY_ALIASES_SQL, entity_uuid)

        return web.json_response([
            {
                "alias": r["alias"],
                "source": r["source"],
                "confidence": float(r["confidence"]),
                "is_primary": bool(r["is_primary"]),
                "language": r["language"],
                "created_at": _utc_iso(r["created_at"]) if r["created_at"] else None,
            }
            for r in rows
        ])

    async def _handle_entity_timeline(self, request: web.Request) -> web.Response:
        import uuid as _uuid
        entity_id_str = request.match_info["entityId"]
        try:
            entity_uuid = _uuid.UUID(entity_id_str)
        except ValueError:
            raise web.HTTPBadRequest(text="entityId must be a valid UUID")

        from_dt, to_dt = self._parse_time_range(request)
        bucket = request.query.get("bucket", "day")
        if bucket not in ("hour", "day"):
            bucket = "day"

        async with self._conn() as conn:
            rows = await conn.fetch(SELECT_ENTITY_TIMELINE_SQL, entity_uuid, from_dt, to_dt, bucket)

        return web.json_response([
            {
                "time": _utc_iso(r["bucket"]),
                "mention_count": int(r["mention_count"] or 0),
            }
            for r in rows
        ])

    async def _handle_entity_merge(self, request: web.Request) -> web.Response:
        import uuid as _uuid
        entity_id_str = request.match_info["entityId"]
        try:
            source_uuid = _uuid.UUID(entity_id_str)
        except ValueError:
            raise web.HTTPBadRequest(text="entityId must be a valid UUID")

        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="invalid JSON body")

        target_id_str = (body.get("target_id") or "").strip()
        reason = (body.get("reason") or "").strip() or None
        actor = (body.get("actor") or "api").strip()

        try:
            target_uuid = _uuid.UUID(target_id_str)
        except ValueError:
            raise web.HTTPBadRequest(text="target_id must be a valid UUID")

        if source_uuid == target_uuid:
            raise web.HTTPBadRequest(text="source and target must be different entities")

        async with self._conn() as conn:
            async with conn.transaction():
                # Verify both exist and are not already merged
                src_row = await conn.fetchrow(
                    "SELECT id, canonical_name FROM entity_canonical WHERE id = $1 AND merged_into_id IS NULL",
                    source_uuid,
                )
                if not src_row:
                    raise web.HTTPNotFound(text=f"source entity not found or already merged: {entity_id_str}")

                tgt_row = await conn.fetchrow(
                    "SELECT id FROM entity_canonical WHERE id = $1 AND merged_into_id IS NULL",
                    target_uuid,
                )
                if not tgt_row:
                    raise web.HTTPNotFound(text=f"target entity not found or already merged: {target_id_str}")

                # 1. Transfer aliases
                alias_count = await conn.fetchval(
                    "SELECT count(*) FROM entity_aliases WHERE entity_canonical_id = $1",
                    source_uuid,
                )
                await conn.execute(
                    """
                    INSERT INTO entity_aliases (entity_canonical_id, alias, alias_normalized, language, source, confidence)
                    SELECT $2, alias, alias_normalized, language, source, confidence
                    FROM entity_aliases WHERE entity_canonical_id = $1
                    ON CONFLICT (entity_canonical_id, alias_normalized) DO NOTHING
                    """,
                    source_uuid, target_uuid,
                )
                await conn.execute(
                    "DELETE FROM entity_aliases WHERE entity_canonical_id = $1",
                    source_uuid,
                )
                # Add source canonical_name as alias on target
                src_norm = src_row["canonical_name"].casefold()
                await conn.execute(
                    """
                    INSERT INTO entity_aliases (entity_canonical_id, alias, alias_normalized, source, confidence)
                    VALUES ($1, $2, $3, 'manual', 1.0)
                    ON CONFLICT (entity_canonical_id, alias_normalized) DO NOTHING
                    """,
                    target_uuid, src_row["canonical_name"], src_norm,
                )

                # 2. Repoint linking candidates
                lc_count = await conn.fetchval(
                    "SELECT count(*) FROM entity_linking_candidates WHERE entity_canonical_id = $1",
                    source_uuid,
                )
                await conn.execute(
                    "UPDATE entity_linking_candidates SET entity_canonical_id = $2 WHERE entity_canonical_id = $1",
                    source_uuid, target_uuid,
                )

                # 3. Repoint ner_results
                nr_count = await conn.fetchval(
                    "SELECT count(*) FROM ner_results WHERE entity_canonical_id = $1",
                    source_uuid,
                )
                await conn.execute(
                    "UPDATE ner_results SET entity_canonical_id = $2 WHERE entity_canonical_id = $1",
                    source_uuid, target_uuid,
                )

                # 4. Tombstone the source
                await conn.execute(
                    "UPDATE entity_canonical SET merged_into_id = $2, updated_at = NOW() WHERE id = $1",
                    source_uuid, target_uuid,
                )

                # 5. Record history
                await conn.execute(
                    """
                    INSERT INTO entity_merge_history
                        (source_canonical_id, target_canonical_id, reason, actor, metadata)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    source_uuid, target_uuid, reason, actor,
                    json.dumps({
                        "transferred_aliases": int(alias_count or 0),
                        "repointed_ner_results": int(nr_count or 0),
                        "repointed_linking_candidates": int(lc_count or 0),
                    }),
                )

                # 6. NOTIFY resolver to invalidate
                await conn.execute("SELECT pg_notify('entity_resolver_invalidate', $1)", str(source_uuid))

        return web.json_response({
            "source_id": str(source_uuid),
            "target_id": str(target_uuid),
            "transferred_aliases": int(alias_count or 0),
            "repointed_ner_results": int(nr_count or 0),
        }, status=200)

    async def _handle_create_normalization_rule(self, request: web.Request) -> web.Response:
        import re as _re
        import uuid as _uuid
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="invalid JSON body")

        rule_type = (body.get("rule_type") or "").strip()
        if rule_type not in ("alias", "abbreviation", "regex", "merge"):
            raise web.HTTPBadRequest(text="rule_type must be alias|abbreviation|regex|merge")

        pattern = (body.get("pattern") or "").strip()
        if not pattern:
            raise web.HTTPBadRequest(text="pattern is required")

        if rule_type == "regex":
            try:
                _re.compile(pattern)
            except _re.error as exc:
                raise web.HTTPBadRequest(text=f"invalid regex pattern: {exc}")

        replacement = body.get("replacement") or None
        entity_type = body.get("entity_type") or None
        language = body.get("language") or None
        target_canonical_id_str = body.get("target_canonical_id") or None
        priority = int(body.get("priority") or 100)
        created_by = (body.get("created_by") or "api").strip()

        target_uuid = None
        if target_canonical_id_str:
            try:
                target_uuid = _uuid.UUID(target_canonical_id_str)
            except ValueError:
                raise web.HTTPBadRequest(text="target_canonical_id must be a valid UUID")

        async with self._conn() as conn:
            if target_uuid:
                exists = await conn.fetchval(
                    "SELECT id FROM entity_canonical WHERE id = $1 AND merged_into_id IS NULL",
                    target_uuid,
                )
                if not exists:
                    raise web.HTTPNotFound(text=f"target_canonical_id not found: {target_canonical_id_str}")

            row = await conn.fetchrow(
                """
                INSERT INTO entity_normalization_rules
                    (rule_type, pattern, replacement, entity_type, language,
                     target_canonical_id, priority, enabled, created_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7, true, $8)
                RETURNING id, created_at
                """,
                rule_type, pattern, replacement, entity_type, language,
                target_uuid, priority, created_by,
            )
            await conn.execute("SELECT pg_notify('entity_resolver_invalidate', 'rules')")

        return web.json_response({
            "id": str(row["id"]),
            "rule_type": rule_type,
            "pattern": pattern,
            "priority": priority,
            "created_at": _utc_iso(row["created_at"]),
        }, status=201)

    # ── Scientific paper endpoints ──────────────────────────────────────
    async def _handle_papers_list(self, request: web.Request) -> web.Response:
        params = request.rel_url.query
        source_type = params.get("source_type")
        source_channel = params.get("source_channel")
        from_dt = params.get("from")
        to_dt = params.get("to")
        parsing_status = params.get("parsing_status")
        search = params.get("search")
        try:
            limit = min(int(params.get("limit", 50)), 200)
            offset = int(params.get("offset", 0))
        except ValueError:
            return web.json_response({"error": "invalid limit/offset"}, status=400)

        conditions = []
        args: list = []
        i = 1

        if source_type:
            conditions.append(f"p.source_type = ${i}")
            args.append(source_type); i += 1
        if source_channel:
            conditions.append(f"p.source_channel = ${i}")
            args.append(source_channel); i += 1
        if from_dt:
            conditions.append(f"p.detected_at >= ${i}::timestamptz")
            args.append(from_dt); i += 1
        if to_dt:
            conditions.append(f"p.detected_at <= ${i}::timestamptz")
            args.append(to_dt); i += 1
        if parsing_status:
            conditions.append(f"p.parsing_status = ${i}")
            args.append(parsing_status); i += 1
        if search:
            conditions.append(f"(p.title ILIKE ${i} OR p.abstract ILIKE ${i})")
            args.append(f"%{search}%"); i += 1

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        args += [limit, offset]

        sql = f"""
            SELECT
                p.id::text, p.source_message_id, p.source_channel, p.source_url,
                p.source_type, p.title, p.authors, p.abstract, p.detected_at,
                p.parsing_status, p.created_at,
                (SELECT sps.short_summary FROM scientific_paper_summaries sps
                 WHERE sps.paper_id = p.id ORDER BY sps.created_at DESC LIMIT 1) AS short_summary,
                EXISTS(SELECT 1 FROM scientific_paper_summaries sps2 WHERE sps2.paper_id = p.id) AS has_summary
            FROM scientific_papers p
            {where}
            ORDER BY p.detected_at DESC
            LIMIT ${i} OFFSET ${i+1}
        """

        rows = await self._pool.fetch(sql, *args)
        result = []
        for r in rows:
            authors = r["authors"]
            if isinstance(authors, str):
                try:
                    import json as _json
                    authors = _json.loads(authors)
                except Exception:
                    authors = []
            result.append({
                "id": r["id"],
                "source_message_id": r["source_message_id"],
                "source_channel": r["source_channel"],
                "source_url": r["source_url"],
                "source_type": r["source_type"],
                "title": r["title"],
                "authors": authors if isinstance(authors, list) else [],
                "abstract": r["abstract"],
                "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
                "parsing_status": r["parsing_status"],
                "has_summary": r["has_summary"],
                "short_summary": r["short_summary"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })
        return web.json_response(result)

    async def _handle_paper_detail(self, request: web.Request) -> web.Response:
        paper_id = request.match_info["paper_id"]
        try:
            row = await self._pool.fetchrow(
                """
                SELECT p.*, p.id::text as id_str,
                    EXISTS(SELECT 1 FROM scientific_paper_texts t WHERE t.paper_id = p.id) AS has_text
                FROM scientific_papers p
                WHERE p.id = $1::uuid
                """,
                paper_id,
            )
        except Exception:
            return web.json_response({"error": "invalid paper_id"}, status=400)
        if not row:
            return web.json_response({"error": "not found"}, status=404)

        summary_row = await self._pool.fetchrow(
            """
            SELECT id::text, paper_id::text, model_name, prompt_version,
                   summary_json, short_summary, created_at
            FROM scientific_paper_summaries
            WHERE paper_id = $1::uuid
            ORDER BY created_at DESC LIMIT 1
            """,
            paper_id,
        )

        import json as _json
        authors = row["authors"]
        if isinstance(authors, str):
            try:
                authors = _json.loads(authors)
            except Exception:
                authors = []

        paper = {
            "id": str(row["id"]),
            "source_message_id": row["source_message_id"],
            "source_channel": row["source_channel"],
            "source_url": row["source_url"],
            "source_type": row["source_type"],
            "telegram_file_id": row["telegram_file_id"],
            "title": row["title"],
            "authors": authors if isinstance(authors, list) else [],
            "abstract": row["abstract"],
            "published_at": row["published_at"].isoformat() if row["published_at"] else None,
            "detected_at": row["detected_at"].isoformat() if row["detected_at"] else None,
            "parsing_status": row["parsing_status"],
            "has_text": row["has_text"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

        if summary_row:
            sj = summary_row["summary_json"]
            if isinstance(sj, str):
                try:
                    sj = _json.loads(sj)
                except Exception:
                    sj = {}
            paper["summary"] = {
                "id": summary_row["id"],
                "paper_id": summary_row["paper_id"],
                "model_name": summary_row["model_name"],
                "prompt_version": summary_row["prompt_version"],
                "summary_json": dict(sj) if sj else {},
                "short_summary": summary_row["short_summary"],
                "created_at": summary_row["created_at"].isoformat() if summary_row["created_at"] else None,
            }

        return web.json_response(paper)

    async def _handle_paper_summary(self, request: web.Request) -> web.Response:
        paper_id = request.match_info["paper_id"]
        try:
            row = await self._pool.fetchrow(
                """
                SELECT id::text, paper_id::text, model_name, prompt_version,
                       summary_json, short_summary, created_at
                FROM scientific_paper_summaries
                WHERE paper_id = $1::uuid
                ORDER BY created_at DESC LIMIT 1
                """,
                paper_id,
            )
        except Exception:
            return web.json_response({"error": "invalid paper_id"}, status=400)
        if not row:
            return web.json_response({"error": "no summary found"}, status=404)
        import json as _json
        sj = row["summary_json"]
        if isinstance(sj, str):
            try:
                sj = _json.loads(sj)
            except Exception:
                sj = {}
        return web.json_response({
            "id": row["id"],
            "paper_id": row["paper_id"],
            "model_name": row["model_name"],
            "prompt_version": row["prompt_version"],
            "summary_json": dict(sj) if sj else {},
            "short_summary": row["short_summary"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        })

    async def _handle_paper_resummary(self, request: web.Request) -> web.Response:
        paper_id = request.match_info["paper_id"]
        try:
            exists = await self._pool.fetchval(
                "SELECT id FROM scientific_papers WHERE id = $1::uuid", paper_id
            )
        except Exception:
            return web.json_response({"error": "invalid paper_id"}, status=400)
        if not exists:
            return web.json_response({"error": "not found"}, status=404)
        await self._pool.execute(
            "UPDATE scientific_papers SET parsing_status='parsed', updated_at=NOW() WHERE id=$1::uuid",
            paper_id,
        )
        return web.json_response({"status": "queued", "paper_id": paper_id})

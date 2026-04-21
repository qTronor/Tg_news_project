\set ON_ERROR_STOP on

CREATE TEMP TABLE gpt_topic_cluster_raw (
    line text NOT NULL
);
\copy gpt_topic_cluster_raw (line) FROM '/tmp/gpt_topics_clustered_2026_04_21_v1.jsonl';

CREATE TEMP TABLE gpt_topic_cluster_stage AS
SELECT
    line::jsonb AS payload,
    line::jsonb ->> 'request_id' AS request_id,
    line::jsonb ->> 'event_id' AS event_id,
    line::jsonb ->> 'channel' AS channel,
    (line::jsonb ->> 'message_id')::bigint AS message_id,
    (line::jsonb ->> 'raw_message_id')::uuid AS raw_message_id,
    (line::jsonb ->> 'preprocessed_message_id')::uuid AS preprocessed_message_id,
    line::jsonb ->> 'run_id' AS run_id,
    (line::jsonb ->> 'cluster_id')::integer AS cluster_id,
    line::jsonb ->> 'public_cluster_id' AS public_cluster_id,
    (line::jsonb ->> 'cluster_probability')::real AS cluster_probability,
    line::jsonb ->> 'bucket_id' AS bucket_id,
    line::jsonb ->> 'topic_label' AS topic_label,
    line::jsonb ->> 'topic_summary' AS topic_summary,
    COALESCE(line::jsonb -> 'topic_keywords', '[]'::jsonb) AS topic_keywords,
    COALESCE(line::jsonb -> 'primary_entities', '[]'::jsonb) AS primary_entities,
    line::jsonb ->> 'event_type' AS event_type
FROM gpt_topic_cluster_raw;

DO $$
DECLARE
    bad_count integer;
    run_count integer;
BEGIN
    SELECT count(DISTINCT run_id) INTO run_count FROM gpt_topic_cluster_stage;
    IF run_count <> 1 THEN
        RAISE EXCEPTION 'expected exactly one run_id, got %', run_count;
    END IF;

    SELECT count(*) INTO bad_count
    FROM gpt_topic_cluster_stage
    WHERE public_cluster_id <> run_id || ':' || cluster_id::text
       OR cluster_id < -1
       OR cluster_probability < 0
       OR cluster_probability > 1;
    IF bad_count > 0 THEN
        RAISE EXCEPTION 'invalid cluster rows: %', bad_count;
    END IF;

    SELECT count(*) INTO bad_count
    FROM gpt_topic_cluster_stage s
    LEFT JOIN raw_messages rm
      ON rm.event_id = s.event_id
     AND rm.channel = s.channel
     AND rm.message_id = s.message_id
    LEFT JOIN preprocessed_messages pm
      ON pm.id = s.preprocessed_message_id
     AND pm.event_id = s.event_id
    WHERE rm.id IS NULL OR pm.id IS NULL;
    IF bad_count > 0 THEN
        RAISE EXCEPTION 'stage rows without matching raw/preprocessed messages: %', bad_count;
    END IF;

    SELECT count(*) INTO bad_count
    FROM (
        SELECT event_id
        FROM gpt_topic_cluster_stage
        GROUP BY event_id
        HAVING count(*) > 1
    ) d;
    IF bad_count > 0 THEN
        RAISE EXCEPTION 'duplicate event_id rows: %', bad_count;
    END IF;
END
$$;

INSERT INTO cluster_runs_pg (
    run_id,
    run_timestamp,
    algo_version,
    window_start,
    window_end,
    total_messages,
    total_clustered,
    total_noise,
    n_clusters,
    config_json,
    duration_seconds
)
SELECT
    s.run_id,
    NOW(),
    'gpt-manual-topic-clustering',
    min(rm.message_date),
    max(rm.message_date),
    count(*),
    count(*) FILTER (WHERE s.cluster_id >= 0),
    count(*) FILTER (WHERE s.cluster_id < 0),
    count(DISTINCT s.cluster_id) FILTER (WHERE s.cluster_id >= 0),
    jsonb_build_object(
        'source', 'manual-gpt-jsonl',
        'input_file', 'docs/gpt_topics_clustered_2026_04_21_v1.jsonl',
        'rows', count(*),
        'labels_from_gpt', true
    ),
    NULL
FROM gpt_topic_cluster_stage s
JOIN raw_messages rm ON rm.event_id = s.event_id
GROUP BY s.run_id
ON CONFLICT (run_id) DO UPDATE
SET run_timestamp = EXCLUDED.run_timestamp,
    algo_version = EXCLUDED.algo_version,
    window_start = EXCLUDED.window_start,
    window_end = EXCLUDED.window_end,
    total_messages = EXCLUDED.total_messages,
    total_clustered = EXCLUDED.total_clustered,
    total_noise = EXCLUDED.total_noise,
    n_clusters = EXCLUDED.n_clusters,
    config_json = EXCLUDED.config_json,
    duration_seconds = EXCLUDED.duration_seconds;

INSERT INTO cluster_assignments (
    run_id,
    cluster_id,
    event_id,
    channel,
    message_id,
    raw_message_id,
    preprocessed_message_id,
    cluster_probability,
    bucket_id,
    window_start,
    window_end,
    message_date
)
SELECT
    s.run_id,
    s.cluster_id,
    s.event_id,
    s.channel,
    s.message_id,
    rm.id,
    pm.id,
    s.cluster_probability,
    s.bucket_id,
    run.window_start,
    run.window_end,
    rm.message_date
FROM gpt_topic_cluster_stage s
JOIN raw_messages rm ON rm.event_id = s.event_id
JOIN preprocessed_messages pm ON pm.event_id = s.event_id
JOIN cluster_runs_pg run ON run.run_id = s.run_id
ON CONFLICT (run_id, event_id) DO UPDATE
SET cluster_id = EXCLUDED.cluster_id,
    channel = EXCLUDED.channel,
    message_id = EXCLUDED.message_id,
    raw_message_id = EXCLUDED.raw_message_id,
    preprocessed_message_id = EXCLUDED.preprocessed_message_id,
    cluster_probability = EXCLUDED.cluster_probability,
    bucket_id = EXCLUDED.bucket_id,
    window_start = EXCLUDED.window_start,
    window_end = EXCLUDED.window_end,
    message_date = EXCLUDED.message_date;

WITH ranked AS (
    SELECT
        s.*,
        row_number() OVER (
            PARTITION BY s.run_id, s.cluster_id
            ORDER BY s.cluster_probability DESC, s.event_id
        ) AS rn,
        avg(s.cluster_probability) OVER (
            PARTITION BY s.run_id, s.cluster_id
        ) AS avg_probability
    FROM gpt_topic_cluster_stage s
    WHERE s.cluster_id >= 0
)
INSERT INTO cluster_source_resolutions (
    public_cluster_id,
    run_id,
    cluster_id,
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
)
SELECT
    r.public_cluster_id,
    r.run_id,
    r.cluster_id,
    'inferred',
    'unknown',
    round(r.avg_probability::numeric, 4)::real,
    NULL,
    NULL,
    NULL,
    NULL,
    r.topic_label,
    jsonb_build_object(
        'topic_label', r.topic_label,
        'topic_summary', r.topic_summary,
        'topic_keywords', r.topic_keywords,
        'primary_entities', r.primary_entities,
        'event_type', r.event_type,
        'source', 'gpt-manual-topic-clustering'
    ),
    jsonb_build_object(
        'representative_event_id', r.event_id,
        'representative_request_id', r.request_id
    )
FROM ranked r
WHERE r.rn = 1
ON CONFLICT (public_cluster_id, resolution_kind) DO UPDATE
SET run_id = EXCLUDED.run_id,
    cluster_id = EXCLUDED.cluster_id,
    source_type = EXCLUDED.source_type,
    source_confidence = EXCLUDED.source_confidence,
    source_event_id = EXCLUDED.source_event_id,
    source_channel = EXCLUDED.source_channel,
    source_message_id = EXCLUDED.source_message_id,
    source_message_date = EXCLUDED.source_message_date,
    source_snippet = EXCLUDED.source_snippet,
    explanation_json = EXCLUDED.explanation_json,
    evidence_json = EXCLUDED.evidence_json,
    resolved_at = NOW(),
    updated_at = NOW();

SELECT
    run_id,
    total_messages,
    total_clustered,
    total_noise,
    n_clusters,
    window_start,
    window_end
FROM cluster_runs_pg
WHERE run_id = (SELECT min(run_id) FROM gpt_topic_cluster_stage);

SELECT cluster_id, count(*) AS messages
FROM cluster_assignments
WHERE run_id = (SELECT min(run_id) FROM gpt_topic_cluster_stage)
GROUP BY cluster_id
ORDER BY cluster_id
LIMIT 20;

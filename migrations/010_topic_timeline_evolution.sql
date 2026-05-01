-- Migration: 010_topic_timeline_evolution
-- Description: Materialized timeline points and evolution events for topic clusters
-- Date: 2026-04-22

CREATE TABLE IF NOT EXISTS topic_timeline_points (
    public_cluster_id VARCHAR(320) NOT NULL,
    run_id VARCHAR(255) REFERENCES cluster_runs_pg(run_id) ON DELETE CASCADE,
    bucket_size VARCHAR(16) NOT NULL,
    bucket_start TIMESTAMPTZ NOT NULL,
    bucket_end TIMESTAMPTZ NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    unique_channel_count INTEGER NOT NULL DEFAULT 0,
    top_entities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    sentiment_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    new_channels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    event_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (public_cluster_id, bucket_size, bucket_start),
    CONSTRAINT topic_timeline_points_bucket_size_check CHECK (bucket_size IN ('15m', '1h', '1d')),
    CONSTRAINT topic_timeline_points_count_check CHECK (message_count >= 0),
    CONSTRAINT topic_timeline_points_channel_count_check CHECK (unique_channel_count >= 0),
    CONSTRAINT topic_timeline_points_bucket_order_check CHECK (bucket_end > bucket_start)
);

CREATE INDEX IF NOT EXISTS idx_topic_timeline_points_cluster_bucket
    ON topic_timeline_points(public_cluster_id, bucket_size, bucket_start);
CREATE INDEX IF NOT EXISTS idx_topic_timeline_points_run
    ON topic_timeline_points(run_id, bucket_size, bucket_start)
    WHERE run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_topic_timeline_points_calculated
    ON topic_timeline_points(calculated_at DESC);

CREATE TABLE IF NOT EXISTS topic_evolution_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_cluster_id VARCHAR(320) NOT NULL,
    run_id VARCHAR(255) REFERENCES cluster_runs_pg(run_id) ON DELETE CASCADE,
    bucket_size VARCHAR(16) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    bucket_start TIMESTAMPTZ NOT NULL,
    severity REAL NOT NULL DEFAULT 0,
    summary TEXT NOT NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT topic_evolution_events_bucket_size_check CHECK (bucket_size IN ('15m', '1h', '1d')),
    CONSTRAINT topic_evolution_events_type_check CHECK (event_type IN (
        'topic_created',
        'growth_spike',
        'new_channel_joined',
        'new_actor_detected',
        'sentiment_shift',
        'decline_started'
    )),
    CONSTRAINT topic_evolution_events_severity_check CHECK (severity >= 0 AND severity <= 1),
    CONSTRAINT topic_evolution_events_unique UNIQUE (
        public_cluster_id,
        bucket_size,
        event_type,
        bucket_start,
        summary
    )
);

CREATE INDEX IF NOT EXISTS idx_topic_evolution_events_cluster_time
    ON topic_evolution_events(public_cluster_id, bucket_size, event_time);
CREATE INDEX IF NOT EXISTS idx_topic_evolution_events_type
    ON topic_evolution_events(event_type, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_topic_evolution_events_run
    ON topic_evolution_events(run_id, bucket_size, event_time)
    WHERE run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS topic_timeline_rebuild_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_cluster_id VARCHAR(320),
    run_id VARCHAR(255),
    bucket_size VARCHAR(16) NOT NULL,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    points_written INTEGER NOT NULL DEFAULT 0,
    events_written INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'completed',
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    CONSTRAINT topic_timeline_rebuild_runs_bucket_size_check CHECK (bucket_size IN ('15m', '1h', '1d')),
    CONSTRAINT topic_timeline_rebuild_runs_status_check CHECK (status IN ('completed', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_topic_timeline_rebuild_runs_cluster
    ON topic_timeline_rebuild_runs(public_cluster_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_topic_timeline_rebuild_runs_started
    ON topic_timeline_rebuild_runs(started_at DESC);

COMMENT ON TABLE topic_timeline_points IS 'Materialized per-topic time buckets for UI timeline visualizations.';
COMMENT ON TABLE topic_evolution_events IS 'Explainable events detected from materialized topic timeline points.';
COMMENT ON COLUMN topic_timeline_points.sentiment_json IS 'Counts and signed sentiment summary: positive/neutral/negative/avg_signed.';
COMMENT ON COLUMN topic_timeline_points.new_channels_json IS 'Channels that first appeared in this topic in the bucket.';
COMMENT ON COLUMN topic_evolution_events.details_json IS 'Event-specific evidence for UI tooltips and auditability.';

DO $$
BEGIN
    RAISE NOTICE 'Migration 010_topic_timeline_evolution completed successfully';
END $$;

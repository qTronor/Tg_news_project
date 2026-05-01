-- Migration: 011_topic_comparison_cache
-- Description: Cache deterministic on-demand topic comparison results
-- Date: 2026-04-22

CREATE TABLE IF NOT EXISTS topic_comparison_cache (
    cache_key VARCHAR(64) PRIMARY KEY,
    cluster_a_id VARCHAR(320) NOT NULL,
    cluster_b_id VARCHAR(320) NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    algorithm_version VARCHAR(100) NOT NULL,
    result_json JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT topic_comparison_cache_window_check CHECK (window_end > window_start)
);

CREATE INDEX IF NOT EXISTS idx_topic_comparison_cache_clusters
    ON topic_comparison_cache(cluster_a_id, cluster_b_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_topic_comparison_cache_expires
    ON topic_comparison_cache(expires_at);

COMMENT ON TABLE topic_comparison_cache IS 'TTL cache for deterministic topic-to-topic comparison API results.';
COMMENT ON COLUMN topic_comparison_cache.result_json IS 'Full API comparison payload including scores, classification, evidence, and explanation.';

DO $$
BEGIN
    RAISE NOTICE 'Migration 011_topic_comparison_cache completed successfully';
END $$;

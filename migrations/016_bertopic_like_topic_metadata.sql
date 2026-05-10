-- Migration: 016_bertopic_like_topic_metadata
-- Description: Persist BERTopic-like run metadata and explainable per-topic artifacts.
-- Date: 2026-05-02

ALTER TABLE cluster_runs_pg
    ADD COLUMN IF NOT EXISTS model_version VARCHAR(100),
    ADD COLUMN IF NOT EXISTS config_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS dataset_version VARCHAR(255),
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS metrics_json JSONB;

CREATE INDEX IF NOT EXISTS idx_cluster_runs_pg_config_hash
    ON cluster_runs_pg(config_hash)
    WHERE config_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cluster_runs_pg_dataset_version
    ON cluster_runs_pg(dataset_version)
    WHERE dataset_version IS NOT NULL;

CREATE TABLE IF NOT EXISTS topic_cluster_metadata (
    public_cluster_id VARCHAR(320) PRIMARY KEY,
    run_id VARCHAR(255) NOT NULL REFERENCES cluster_runs_pg(run_id) ON DELETE CASCADE,
    cluster_id INTEGER NOT NULL,
    centroid_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    representative_messages_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    top_entities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    top_channels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    time_distribution_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence_score REAL,
    stability_score REAL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT topic_cluster_metadata_confidence_check CHECK (
        confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)
    ),
    CONSTRAINT topic_cluster_metadata_stability_check CHECK (
        stability_score IS NULL OR (stability_score >= 0 AND stability_score <= 1)
    )
);

CREATE INDEX IF NOT EXISTS idx_topic_cluster_metadata_run
    ON topic_cluster_metadata(run_id, cluster_id);

DO $$
BEGIN
    RAISE NOTICE 'Migration 016_bertopic_like_topic_metadata completed successfully';
END $$;

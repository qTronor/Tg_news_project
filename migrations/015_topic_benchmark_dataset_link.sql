-- Migration: 015_topic_benchmark_dataset_link
-- Description: Link topic benchmark experiments to annotation datasets
-- Date: 2026-05-02

ALTER TABLE topic_experiments
    ADD COLUMN IF NOT EXISTS dataset_version_id UUID REFERENCES dataset_versions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_topic_experiments_dataset_version
    ON topic_experiments(dataset_version_id, created_at DESC);

DO $$
BEGIN
    RAISE NOTICE 'Migration 015_topic_benchmark_dataset_link completed successfully';
END $$;

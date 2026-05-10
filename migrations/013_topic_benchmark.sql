-- Migration: 013_topic_benchmark
-- Description: Reproducible topic modeling benchmark experiments
-- Date: 2026-05-02

CREATE TABLE IF NOT EXISTS topic_experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    dataset_version VARCHAR(120) NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    channels TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    seed INTEGER NOT NULL DEFAULT 42,
    status VARCHAR(40) NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT topic_experiments_window_check CHECK (window_end > window_start),
    CONSTRAINT topic_experiments_status_check CHECK (status IN ('created', 'running', 'completed', 'failed'))
);

CREATE TABLE IF NOT EXISTS topic_model_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES topic_experiments(id) ON DELETE CASCADE,
    model_key VARCHAR(80) NOT NULL,
    model_name VARCHAR(255) NOT NULL,
    embedding_model VARCHAR(255),
    params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_baseline BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT topic_model_configs_unique UNIQUE (experiment_id, model_key)
);

CREATE TABLE IF NOT EXISTS topic_experiment_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES topic_experiments(id) ON DELETE CASCADE,
    model_config_id UUID NOT NULL REFERENCES topic_model_configs(id) ON DELETE CASCADE,
    cluster_run_id VARCHAR(255) REFERENCES cluster_runs_pg(run_id) ON DELETE SET NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'queued',
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    duration_seconds REAL,
    error_message TEXT,
    random_seed INTEGER NOT NULL DEFAULT 42,
    runtime_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT topic_experiment_runs_status_check CHECK (status IN ('queued', 'running', 'completed', 'failed', 'skipped'))
);

CREATE TABLE IF NOT EXISTS topic_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_run_id UUID NOT NULL REFERENCES topic_experiment_runs(id) ON DELETE CASCADE,
    metric_name VARCHAR(120) NOT NULL,
    metric_value DOUBLE PRECISION,
    metric_json JSONB,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT topic_metrics_unique UNIQUE (experiment_run_id, metric_name)
);

CREATE TABLE IF NOT EXISTS topic_experiment_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_run_id UUID NOT NULL REFERENCES topic_experiment_runs(id) ON DELETE CASCADE,
    artifact_type VARCHAR(80) NOT NULL,
    uri TEXT,
    payload_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_topic_experiments_created
    ON topic_experiments(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_topic_experiment_runs_experiment
    ON topic_experiment_runs(experiment_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_topic_metrics_run
    ON topic_metrics(experiment_run_id, metric_name);
CREATE INDEX IF NOT EXISTS idx_topic_artifacts_run
    ON topic_experiment_artifacts(experiment_run_id, artifact_type);

DO $$
BEGIN
    RAISE NOTICE 'Migration 013_topic_benchmark completed successfully';
END $$;

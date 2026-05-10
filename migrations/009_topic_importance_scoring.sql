-- Migration: 009_topic_importance_scoring
-- Description: Storage layer for topic importance scoring
-- Date: 2026-04-22

-- =====================================================
-- TABLE: topic_scores
-- Description: Importance scores computed per cluster per scoring run
-- Each run inserts a new row; history is preserved.
-- =====================================================
CREATE TABLE IF NOT EXISTS topic_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Cluster identity
    public_cluster_id VARCHAR(320) NOT NULL,
    run_id VARCHAR(255) NOT NULL REFERENCES cluster_runs_pg(run_id) ON DELETE CASCADE,

    -- Score
    importance_score REAL NOT NULL,
    importance_level VARCHAR(16) NOT NULL,

    -- Explainability
    score_breakdown_json JSONB NOT NULL,
    features_json JSONB NOT NULL,

    -- Versioning / audit
    scoring_version VARCHAR(64) NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Time window the score was computed over
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,

    CONSTRAINT topic_scores_score_range CHECK (importance_score >= 0 AND importance_score <= 1),
    CONSTRAINT topic_scores_level_check CHECK (
        importance_level IN ('low', 'medium', 'high', 'critical')
    )
);

CREATE INDEX IF NOT EXISTS idx_topic_scores_cluster_time
    ON topic_scores(public_cluster_id, calculated_at DESC);

CREATE INDEX IF NOT EXISTS idx_topic_scores_run_score
    ON topic_scores(run_id, importance_score DESC);

CREATE INDEX IF NOT EXISTS idx_topic_scores_level
    ON topic_scores(importance_level, calculated_at DESC);

CREATE INDEX IF NOT EXISTS idx_topic_scores_calculated_at
    ON topic_scores(calculated_at DESC);

-- =====================================================
-- VIEW: topic_scores_latest
-- Description: Latest score per cluster (DISTINCT ON pattern)
-- Use this in API queries instead of the raw table.
-- =====================================================
CREATE OR REPLACE VIEW topic_scores_latest AS
SELECT DISTINCT ON (public_cluster_id)
    id,
    public_cluster_id,
    run_id,
    importance_score,
    importance_level,
    score_breakdown_json,
    features_json,
    scoring_version,
    calculated_at,
    window_start,
    window_end
FROM topic_scores
ORDER BY public_cluster_id, calculated_at DESC;

-- =====================================================
-- TABLE: topic_scoring_runs
-- Description: Audit log of scoring batch runs
-- =====================================================
CREATE TABLE IF NOT EXISTS topic_scoring_runs (
    run_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger VARCHAR(32) NOT NULL,          -- 'batch' | 'oneshot' | 'scheduled'
    cluster_run_id VARCHAR(255),           -- which cluster run was scored
    topics_scored INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL,
    scoring_version VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    CONSTRAINT topic_scoring_runs_trigger_check CHECK (
        trigger IN ('batch', 'oneshot', 'scheduled')
    )
);

CREATE INDEX IF NOT EXISTS idx_topic_scoring_runs_started
    ON topic_scoring_runs(started_at DESC);

COMMENT ON TABLE topic_scores IS 'Importance scores for topic clusters. One row per (cluster, scoring run). Query via topic_scores_latest view.';
COMMENT ON COLUMN topic_scores.importance_score IS 'Normalized importance score in [0,1].';
COMMENT ON COLUMN topic_scores.importance_level IS 'Human-readable bucket: low | medium | high | critical.';
COMMENT ON COLUMN topic_scores.score_breakdown_json IS 'Per-component breakdown: {components: {name: {raw, normalized, weight, contribution}}, penalties: [...], final_score, level}.';
COMMENT ON COLUMN topic_scores.features_json IS 'Raw computed features used as input to scoring formula.';
COMMENT ON COLUMN topic_scores.scoring_version IS 'Scoring formula version (e.g. v1). Change on any formula/weight update.';

DO $$
BEGIN
    RAISE NOTICE 'Migration 009_topic_importance_scoring completed successfully';
END $$;

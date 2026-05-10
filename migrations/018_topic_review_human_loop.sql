-- Migration: 018_topic_review_human_loop
-- Description: Human-in-the-loop review loop for topic clusters.
-- Date: 2026-05-03

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS topic_review_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_cluster_id VARCHAR(320) NOT NULL,
    run_id VARCHAR(255) REFERENCES cluster_runs_pg(run_id) ON DELETE SET NULL,
    reason VARCHAR(60) NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 0,
    signals_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    requested_by UUID,
    assigned_to UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT topic_review_tasks_reason_check CHECK (
        reason IN (
            'new_topic',
            'low_confidence',
            'high_outlier_ratio',
            'history_conflict',
            'rapid_growth',
            'manual_request'
        )
    ),
    CONSTRAINT topic_review_tasks_status_check CHECK (
        status IN ('pending', 'in_progress', 'completed', 'rejected', 'deferred')
    )
);

CREATE TABLE IF NOT EXISTS topic_labels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_cluster_id VARCHAR(320) NOT NULL,
    run_id VARCHAR(255) REFERENCES cluster_runs_pg(run_id) ON DELETE SET NULL,
    label TEXT NOT NULL,
    description TEXT,
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    source VARCHAR(40) NOT NULL DEFAULT 'auto',
    confidence REAL,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    superseded_by UUID REFERENCES topic_labels(id) ON DELETE SET NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT topic_labels_status_check CHECK (
        status IN ('active', 'superseded', 'rejected', 'noise', 'uncertain')
    ),
    CONSTRAINT topic_labels_source_check CHECK (
        source IN ('auto', 'human', 'merged', 'split')
    ),
    CONSTRAINT topic_labels_confidence_check CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_labels_active
    ON topic_labels(public_cluster_id)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS topic_review_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES topic_review_tasks(id) ON DELETE SET NULL,
    public_cluster_id VARCHAR(320) NOT NULL,
    action VARCHAR(40) NOT NULL,
    actor_user_id UUID,
    actor_username VARCHAR(255),
    old_value JSONB,
    new_value JSONB,
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT topic_review_actions_action_check CHECK (
        action IN ('confirm', 'rename', 'merge', 'split', 'reject', 'manual_request')
    )
);

CREATE TABLE IF NOT EXISTS topic_merge_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_cluster_id VARCHAR(320) NOT NULL,
    target_cluster_id VARCHAR(320) NOT NULL,
    resulting_label_id UUID REFERENCES topic_labels(id) ON DELETE SET NULL,
    action_id UUID REFERENCES topic_review_actions(id) ON DELETE SET NULL,
    reason TEXT,
    actor_user_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS topic_split_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_cluster_id VARCHAR(320) NOT NULL,
    child_labels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    event_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    action_id UUID REFERENCES topic_review_actions(id) ON DELETE SET NULL,
    reason TEXT,
    actor_user_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_topic_review_tasks_status
    ON topic_review_tasks(status, priority DESC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_topic_review_tasks_cluster
    ON topic_review_tasks(public_cluster_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_review_tasks_unique_open
    ON topic_review_tasks(public_cluster_id, reason)
    WHERE status IN ('pending', 'in_progress', 'deferred');
CREATE INDEX IF NOT EXISTS idx_topic_review_actions_cluster
    ON topic_review_actions(public_cluster_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_topic_labels_cluster_source
    ON topic_labels(public_cluster_id, source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_topic_merge_history_source
    ON topic_merge_history(source_cluster_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_topic_split_history_source
    ON topic_split_history(source_cluster_id, created_at DESC);

ALTER TABLE dataset_items
    ADD COLUMN IF NOT EXISTS topic_label_source VARCHAR(40) NOT NULL DEFAULT 'auto',
    ADD COLUMN IF NOT EXISTS topic_review_status VARCHAR(40),
    ADD COLUMN IF NOT EXISTS reviewed_topic_label TEXT;

CREATE OR REPLACE FUNCTION update_topic_review_task_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_topic_review_tasks_updated_at ON topic_review_tasks;
CREATE TRIGGER trg_topic_review_tasks_updated_at
    BEFORE UPDATE ON topic_review_tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_topic_review_task_updated_at();

DO $$
BEGIN
    RAISE NOTICE 'Migration 018_topic_review_human_loop completed successfully';
END $$;

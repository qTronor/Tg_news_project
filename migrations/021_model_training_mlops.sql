-- Migration: 021_model_training_mlops
-- Description: User-consented model training, evaluation and deployment registry
-- Date: 2026-05-09

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

ALTER TABLE dataset_versions
    ADD COLUMN IF NOT EXISTS task_type VARCHAR(80),
    ADD COLUMN IF NOT EXISTS owner_user_id UUID;

ALTER TABLE dataset_items
    ADD COLUMN IF NOT EXISTS source_message_id UUID,
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE dataset_versions
SET task_type = COALESCE(task_type, 'topic_classification')
WHERE task_type IS NULL;

ALTER TABLE dataset_versions
    ADD CONSTRAINT dataset_versions_task_type_check
    CHECK (
        task_type IS NULL OR task_type IN (
            'topic_classification',
            'sentiment_classification',
            'embedding_finetuning',
            'ner_finetuning'
        )
    ) NOT VALID;

-- Generic label table used by the MLOps contour. Existing UI annotation remains
-- in annotation_labels; validators read both sources.
CREATE TABLE IF NOT EXISTS dataset_labels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_item_id UUID NOT NULL REFERENCES dataset_items(id) ON DELETE CASCADE,
    label_type VARCHAR(80) NOT NULL,
    label_value TEXT NOT NULL,
    span_start INTEGER,
    span_end INTEGER,
    annotated_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT dataset_labels_span_check CHECK (
        (span_start IS NULL AND span_end IS NULL)
        OR (span_start IS NOT NULL AND span_end IS NOT NULL AND span_start >= 0 AND span_end > span_start)
    )
);

CREATE INDEX IF NOT EXISTS idx_dataset_labels_item
    ON dataset_labels(dataset_item_id, label_type);
CREATE INDEX IF NOT EXISTS idx_dataset_labels_value
    ON dataset_labels(label_type, label_value);

CREATE TABLE IF NOT EXISTS dataset_validation_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES dataset_versions(id) ON DELETE CASCADE,
    task_type VARCHAR(80) NOT NULL,
    status VARCHAR(20) NOT NULL,
    report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT dataset_validation_reports_task_check CHECK (
        task_type IN ('topic_classification', 'sentiment_classification', 'embedding_finetuning', 'ner_finetuning')
    ),
    CONSTRAINT dataset_validation_reports_status_check CHECK (status IN ('valid', 'warning', 'invalid'))
);

CREATE INDEX IF NOT EXISTS idx_dataset_validation_reports_dataset
    ON dataset_validation_reports(dataset_id, task_type, created_at DESC);

CREATE TABLE IF NOT EXISTS training_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES dataset_versions(id) ON DELETE RESTRICT,
    task_type VARCHAR(80) NOT NULL,
    base_model TEXT NOT NULL,
    training_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(40) NOT NULL DEFAULT 'draft',
    consent_to_train_by UUID,
    consent_to_train_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT training_jobs_task_check CHECK (
        task_type IN ('topic_classification', 'sentiment_classification', 'embedding_finetuning', 'ner_finetuning')
    ),
    CONSTRAINT training_jobs_status_check CHECK (
        status IN ('draft', 'waiting_for_consent', 'queued', 'running', 'evaluating', 'completed', 'failed', 'cancelled')
    ),
    CONSTRAINT training_jobs_consent_check CHECK (
        status IN ('draft', 'waiting_for_consent')
        OR (consent_to_train_by IS NOT NULL AND consent_to_train_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_training_jobs_status
    ON training_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_training_jobs_dataset
    ON training_jobs(dataset_id, created_at DESC);

CREATE TABLE IF NOT EXISTS training_job_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    training_job_id UUID NOT NULL REFERENCES training_jobs(id) ON DELETE CASCADE,
    level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT training_job_logs_level_check CHECK (level IN ('debug', 'info', 'warning', 'error'))
);

CREATE INDEX IF NOT EXISTS idx_training_job_logs_job
    ON training_job_logs(training_job_id, created_at ASC);

CREATE TABLE IF NOT EXISTS model_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    training_job_id UUID REFERENCES training_jobs(id) ON DELETE SET NULL,
    model_name TEXT NOT NULL,
    model_type VARCHAR(80) NOT NULL,
    base_model TEXT NOT NULL,
    version TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(40) NOT NULL DEFAULT 'candidate',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deployed_at TIMESTAMPTZ,
    deployed_by UUID,
    CONSTRAINT model_versions_type_check CHECK (
        model_type IN ('topic_classifier', 'sentiment_classifier', 'embedding_model', 'ner_model')
    ),
    CONSTRAINT model_versions_status_check CHECK (
        status IN ('candidate', 'accepted', 'rejected', 'deployed', 'archived', 'failed')
    ),
    CONSTRAINT model_versions_unique_version UNIQUE (model_type, version)
);

CREATE INDEX IF NOT EXISTS idx_model_versions_type_status
    ON model_versions(model_type, status, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_model_versions_one_deployed
    ON model_versions(model_type)
    WHERE status = 'deployed';

CREATE TABLE IF NOT EXISTS model_evaluation_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_version_id UUID NOT NULL REFERENCES model_versions(id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL REFERENCES dataset_versions(id) ON DELETE RESTRICT,
    split VARCHAR(40) NOT NULL,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confusion_matrix_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT model_evaluation_results_split_check CHECK (split IN ('validation', 'test', 'temporal_test', 'all'))
);

CREATE INDEX IF NOT EXISTS idx_model_evaluation_results_model
    ON model_evaluation_results(model_version_id, split);

CREATE TABLE IF NOT EXISTS model_deployment_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_version_id UUID NOT NULL REFERENCES model_versions(id) ON DELETE CASCADE,
    requested_by UUID,
    status VARCHAR(40) NOT NULL DEFAULT 'pending',
    current_production_model_id UUID REFERENCES model_versions(id) ON DELETE SET NULL,
    decision_by UUID,
    decision_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT model_deployment_requests_status_check CHECK (
        status IN ('pending', 'approved', 'rejected', 'deployed', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_model_deployment_requests_model
    ON model_deployment_requests(model_version_id, created_at DESC);

CREATE TABLE IF NOT EXISTS model_deployment_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_version_id UUID NOT NULL REFERENCES model_versions(id) ON DELETE RESTRICT,
    previous_model_version_id UUID REFERENCES model_versions(id) ON DELETE SET NULL,
    deployed_by UUID,
    deployed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rollback_available BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_model_deployment_history_model
    ON model_deployment_history(model_version_id, deployed_at DESC);

CREATE OR REPLACE VIEW datasets AS
SELECT
    id,
    name,
    task_type,
    COALESCE(owner_user_id, created_by) AS created_by,
    status,
    created_at,
    updated_at
FROM dataset_versions;

-- Migration 019: topic summaries, summary runs, prompt version registry
-- Idempotent: all statements use IF NOT EXISTS / ON CONFLICT DO NOTHING

CREATE TABLE IF NOT EXISTS llm_prompt_versions (
    id              SERIAL PRIMARY KEY,
    enrichment_type VARCHAR(64)  NOT NULL,
    language        VARCHAR(8)   NOT NULL,
    prompt_version  VARCHAR(32)  NOT NULL,
    prompt_sha256   CHAR(64)     NOT NULL,
    prompt_body     TEXT         NOT NULL,
    registered_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (enrichment_type, language, prompt_version)
);

CREATE TABLE IF NOT EXISTS topic_summaries (
    public_cluster_id   VARCHAR(320) NOT NULL,
    summary_kind        VARCHAR(32)  NOT NULL,
    language            VARCHAR(8)   NOT NULL,
    prompt_version      VARCHAR(32)  NOT NULL DEFAULT '',
    model_provider      VARCHAR(32)  NOT NULL,
    model_name          VARCHAR(64)  NOT NULL,
    input_fingerprint   CHAR(64)     NOT NULL,
    payload_json        JSONB        NOT NULL,
    status              VARCHAR(24)  NOT NULL,
    generated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (public_cluster_id, summary_kind, language)
);

CREATE INDEX IF NOT EXISTS idx_topic_summaries_expires
    ON topic_summaries (expires_at);

CREATE INDEX IF NOT EXISTS idx_topic_summaries_cluster
    ON topic_summaries (public_cluster_id);

CREATE TABLE IF NOT EXISTS topic_summary_runs (
    id                  BIGSERIAL    PRIMARY KEY,
    public_cluster_id   VARCHAR(320) NOT NULL,
    triggered_by        VARCHAR(32)  NOT NULL,
    language            VARCHAR(8)   NOT NULL,
    kinds_requested     TEXT[]       NOT NULL,
    kinds_succeeded     TEXT[]       NOT NULL DEFAULT '{}',
    kinds_failed        TEXT[]       NOT NULL DEFAULT '{}',
    total_cost_usd      NUMERIC(10,6) NOT NULL DEFAULT 0,
    total_latency_ms    INTEGER      NOT NULL DEFAULT 0,
    started_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_topic_summary_runs_cluster
    ON topic_summary_runs (public_cluster_id, started_at DESC);

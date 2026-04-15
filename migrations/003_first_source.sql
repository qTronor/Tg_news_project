-- Migration: 003_first_source
-- Description: Add provenance, clustering, and first-source resolution storage
-- Date: 2026-04-09

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =====================================================
-- raw_messages provenance expansion
-- =====================================================
ALTER TABLE raw_messages
    ADD COLUMN IF NOT EXISTS channel_id BIGINT,
    ADD COLUMN IF NOT EXISTS permalink TEXT,
    ADD COLUMN IF NOT EXISTS grouped_id BIGINT,
    ADD COLUMN IF NOT EXISTS reply_to_top_message_id BIGINT,
    ADD COLUMN IF NOT EXISTS post_author VARCHAR(255),
    ADD COLUMN IF NOT EXISTS forward_from_channel_id BIGINT,
    ADD COLUMN IF NOT EXISTS forward_from_message_id BIGINT,
    ADD COLUMN IF NOT EXISTS forward_date TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS forward_origin_type VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS ux_raw_messages_event_id ON raw_messages(event_id);
CREATE INDEX IF NOT EXISTS idx_raw_messages_channel_id ON raw_messages(channel_id) WHERE channel_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_raw_messages_channel_id_message_id ON raw_messages(channel_id, message_id)
    WHERE channel_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_raw_messages_reply_lookup ON raw_messages(channel, reply_to_message_id)
    WHERE reply_to_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_raw_messages_forward_lookup ON raw_messages(forward_from_channel_id, forward_from_message_id)
    WHERE forward_from_channel_id IS NOT NULL AND forward_from_message_id IS NOT NULL;

-- =====================================================
-- preprocessed_messages fingerprints
-- =====================================================
ALTER TABLE preprocessed_messages
    ADD COLUMN IF NOT EXISTS normalized_text_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS simhash64 BIGINT,
    ADD COLUMN IF NOT EXISTS url_fingerprints TEXT[],
    ADD COLUMN IF NOT EXISTS primary_url_fingerprint VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_preprocessed_messages_normalized_text_hash
    ON preprocessed_messages(normalized_text_hash)
    WHERE normalized_text_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_preprocessed_messages_simhash64
    ON preprocessed_messages(simhash64)
    WHERE simhash64 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_preprocessed_messages_primary_url_fingerprint
    ON preprocessed_messages(primary_url_fingerprint)
    WHERE primary_url_fingerprint IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_preprocessed_messages_url_fingerprints
    ON preprocessed_messages USING gin(url_fingerprints);

-- =====================================================
-- PostgreSQL clustering source of truth
-- =====================================================
CREATE TABLE IF NOT EXISTS cluster_runs_pg (
    run_id VARCHAR(255) PRIMARY KEY,
    run_timestamp TIMESTAMPTZ NOT NULL,
    algo_version VARCHAR(100) NOT NULL,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    total_messages INTEGER NOT NULL DEFAULT 0,
    total_clustered INTEGER NOT NULL DEFAULT 0,
    total_noise INTEGER NOT NULL DEFAULT 0,
    n_clusters INTEGER NOT NULL DEFAULT 0,
    config_json JSONB,
    duration_seconds REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cluster_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id VARCHAR(255) NOT NULL REFERENCES cluster_runs_pg(run_id) ON DELETE CASCADE,
    cluster_id INTEGER NOT NULL,
    public_cluster_id VARCHAR(320) GENERATED ALWAYS AS (run_id || ':' || cluster_id::text) STORED,
    event_id VARCHAR(512) NOT NULL,
    channel VARCHAR(255) NOT NULL,
    message_id BIGINT NOT NULL,
    raw_message_id UUID REFERENCES raw_messages(id) ON DELETE SET NULL,
    preprocessed_message_id UUID REFERENCES preprocessed_messages(id) ON DELETE SET NULL,
    cluster_probability REAL NOT NULL DEFAULT 0,
    bucket_id TEXT,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    message_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT cluster_assignments_unique_run_event UNIQUE (run_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_cluster_assignments_public_cluster_id ON cluster_assignments(public_cluster_id);
CREATE INDEX IF NOT EXISTS idx_cluster_assignments_cluster_id ON cluster_assignments(cluster_id);
CREATE INDEX IF NOT EXISTS idx_cluster_assignments_run_id ON cluster_assignments(run_id);
CREATE INDEX IF NOT EXISTS idx_cluster_assignments_message_date ON cluster_assignments(message_date DESC);
CREATE INDEX IF NOT EXISTS idx_cluster_assignments_event_id ON cluster_assignments(event_id);

-- =====================================================
-- First-source materializations
-- =====================================================
CREATE TABLE IF NOT EXISTS message_source_resolutions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_event_id VARCHAR(512) NOT NULL,
    message_channel VARCHAR(255) NOT NULL,
    message_id BIGINT NOT NULL,
    public_cluster_id VARCHAR(320),
    resolution_kind VARCHAR(20) NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    source_confidence REAL NOT NULL,
    source_event_id VARCHAR(512),
    source_channel VARCHAR(255),
    source_message_id BIGINT,
    source_message_date TIMESTAMPTZ,
    source_snippet TEXT,
    explanation_json JSONB,
    evidence_json JSONB,
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT message_source_resolutions_unique UNIQUE (message_event_id, resolution_kind),
    CONSTRAINT message_source_resolutions_kind_check CHECK (resolution_kind IN ('exact', 'inferred')),
    CONSTRAINT message_source_resolutions_type_check CHECK (source_type IN (
        'exact_forward',
        'exact_reply',
        'exact_url',
        'quoted',
        'inferred_semantic',
        'earliest_in_cluster',
        'unknown'
    )),
    CONSTRAINT message_source_resolutions_confidence_check CHECK (
        source_confidence >= 0 AND source_confidence <= 1
    )
);

CREATE TABLE IF NOT EXISTS cluster_source_resolutions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_cluster_id VARCHAR(320) NOT NULL,
    run_id VARCHAR(255) NOT NULL REFERENCES cluster_runs_pg(run_id) ON DELETE CASCADE,
    cluster_id INTEGER NOT NULL,
    resolution_kind VARCHAR(20) NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    source_confidence REAL NOT NULL,
    source_event_id VARCHAR(512),
    source_channel VARCHAR(255),
    source_message_id BIGINT,
    source_message_date TIMESTAMPTZ,
    source_snippet TEXT,
    explanation_json JSONB,
    evidence_json JSONB,
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT cluster_source_resolutions_unique UNIQUE (public_cluster_id, resolution_kind),
    CONSTRAINT cluster_source_resolutions_kind_check CHECK (resolution_kind IN ('exact', 'inferred')),
    CONSTRAINT cluster_source_resolutions_type_check CHECK (source_type IN (
        'exact_forward',
        'exact_reply',
        'exact_url',
        'quoted',
        'inferred_semantic',
        'earliest_in_cluster',
        'unknown'
    )),
    CONSTRAINT cluster_source_resolutions_confidence_check CHECK (
        source_confidence >= 0 AND source_confidence <= 1
    )
);

CREATE TABLE IF NOT EXISTS message_propagation_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_cluster_id VARCHAR(320),
    resolution_kind VARCHAR(20) NOT NULL,
    child_event_id VARCHAR(512) NOT NULL,
    child_channel VARCHAR(255) NOT NULL,
    child_message_id BIGINT NOT NULL,
    parent_event_id VARCHAR(512) NOT NULL,
    parent_channel VARCHAR(255),
    parent_message_id BIGINT,
    link_type VARCHAR(50) NOT NULL,
    link_confidence REAL NOT NULL,
    explanation_json JSONB,
    evidence_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT message_propagation_links_child_unique UNIQUE (child_event_id),
    CONSTRAINT message_propagation_links_kind_check CHECK (resolution_kind IN ('exact', 'inferred')),
    CONSTRAINT message_propagation_links_type_check CHECK (link_type IN (
        'exact_forward',
        'exact_reply',
        'exact_url',
        'quoted',
        'inferred_semantic',
        'earliest_in_cluster'
    )),
    CONSTRAINT message_propagation_links_confidence_check CHECK (
        link_confidence >= 0 AND link_confidence <= 1
    )
);

CREATE INDEX IF NOT EXISTS idx_message_source_resolutions_cluster_id
    ON message_source_resolutions(public_cluster_id);
CREATE INDEX IF NOT EXISTS idx_message_source_resolutions_source_event_id
    ON message_source_resolutions(source_event_id)
    WHERE source_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_message_source_resolutions_message_event_id
    ON message_source_resolutions(message_event_id);

CREATE INDEX IF NOT EXISTS idx_cluster_source_resolutions_source_event_id
    ON cluster_source_resolutions(source_event_id)
    WHERE source_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_message_propagation_links_cluster_id
    ON message_propagation_links(public_cluster_id);
CREATE INDEX IF NOT EXISTS idx_message_propagation_links_parent_event_id
    ON message_propagation_links(parent_event_id);

DROP TRIGGER IF EXISTS update_message_source_resolutions_updated_at ON message_source_resolutions;
CREATE TRIGGER update_message_source_resolutions_updated_at
    BEFORE UPDATE ON message_source_resolutions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_cluster_source_resolutions_updated_at ON cluster_source_resolutions;
CREATE TRIGGER update_cluster_source_resolutions_updated_at
    BEFORE UPDATE ON cluster_source_resolutions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_message_propagation_links_updated_at ON message_propagation_links;
CREATE TRIGGER update_message_propagation_links_updated_at
    BEFORE UPDATE ON message_propagation_links
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DO $$
BEGIN
    RAISE NOTICE 'Migration 003_first_source completed successfully';
END $$;

-- Migration: 012_llm_enrichments
-- Description: Storage for LLM-generated explainability artifacts over pre-computed ML results
-- Date: 2026-04-22

CREATE TABLE IF NOT EXISTS llm_enrichments (
    id BIGSERIAL PRIMARY KEY,
    cache_key VARCHAR(64) NOT NULL,
    public_cluster_id VARCHAR(320) NOT NULL,
    enrichment_type VARCHAR(64) NOT NULL,
    language VARCHAR(8) NOT NULL,
    analysis_mode VARCHAR(16) NOT NULL,
    prompt_version VARCHAR(32) NOT NULL,
    model_provider VARCHAR(32) NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    input_fingerprint CHAR(64) NOT NULL,
    result_json JSONB,
    tokens_input INTEGER,
    tokens_output INTEGER,
    cost_usd NUMERIC(10, 6),
    latency_ms INTEGER,
    status VARCHAR(24) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT llm_enrichments_cache_key_unique UNIQUE (cache_key),
    CONSTRAINT llm_enrichments_status_check CHECK (
        status IN ('ok', 'unsupported', 'budget_exhausted', 'error')
    ),
    CONSTRAINT llm_enrichments_analysis_mode_check CHECK (
        analysis_mode IN ('full', 'partial', 'unknown')
    )
);

CREATE INDEX IF NOT EXISTS idx_llm_enrichments_cluster_type
    ON llm_enrichments(public_cluster_id, enrichment_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_enrichments_expires
    ON llm_enrichments(expires_at);

CREATE INDEX IF NOT EXISTS idx_llm_enrichments_status
    ON llm_enrichments(status) WHERE status != 'ok';

COMMENT ON TABLE llm_enrichments IS 'TTL cache for LLM-generated explainability artifacts. Never replaces base ML analytics.';
COMMENT ON COLUMN llm_enrichments.cache_key IS 'sha256(cluster_id|enrichment_type|language|prompt_version|model_name|input_fingerprint)';
COMMENT ON COLUMN llm_enrichments.input_fingerprint IS 'sha256 of canonical JSON of ClusterEnrichmentInput; changes when cluster data changes';
COMMENT ON COLUMN llm_enrichments.analysis_mode IS 'full=RU/EN, partial=OTHER language via Mistral, unknown=insufficient data';
COMMENT ON COLUMN llm_enrichments.result_json IS 'Validated structured LLM output. Shape depends on enrichment_type.';

DO $$
BEGIN
    RAISE NOTICE 'Migration 012_llm_enrichments completed successfully';
END $$;

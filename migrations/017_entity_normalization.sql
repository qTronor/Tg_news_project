-- Migration: 017_entity_normalization
-- Description: Canonical entity layer for NER deduplication (aliases, fuzzy linking, merge)
-- Date: 2026-05-02

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─── entity_canonical ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entity_canonical (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name           TEXT NOT NULL,
    canonical_name_normalized TEXT NOT NULL,
    entity_type              VARCHAR(16) NOT NULL
        CHECK (entity_type IN ('PERSON','ORG','LOC','MISC','GPE','PRODUCT','EVENT')),
    language                 VARCHAR(8),
    wikidata_id              VARCHAR(32),
    description              TEXT,
    confidence               REAL NOT NULL DEFAULT 0,
    source_model             VARCHAR(64),
    mention_count            BIGINT NOT NULL DEFAULT 0,
    first_seen_at            TIMESTAMPTZ,
    last_seen_at             TIMESTAMPTZ,
    merged_into_id           UUID REFERENCES entity_canonical(id) ON DELETE SET NULL,
    metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique active canonical per (normalized_name, type) — tombstones excluded
CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_canonical_name_type
    ON entity_canonical(canonical_name_normalized, entity_type)
    WHERE merged_into_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_entity_canonical_type
    ON entity_canonical(entity_type);

CREATE INDEX IF NOT EXISTS idx_entity_canonical_wikidata
    ON entity_canonical(wikidata_id)
    WHERE wikidata_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_entity_canonical_metadata
    ON entity_canonical USING GIN (metadata);

CREATE INDEX IF NOT EXISTS idx_entity_canonical_name_trgm
    ON entity_canonical USING GIN (canonical_name_normalized gin_trgm_ops);

-- ─── entity_aliases ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entity_aliases (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_canonical_id  UUID NOT NULL REFERENCES entity_canonical(id) ON DELETE CASCADE,
    alias                TEXT NOT NULL,
    alias_normalized     TEXT NOT NULL,
    language             VARCHAR(8),
    source               VARCHAR(32) NOT NULL
        CHECK (source IN ('rule','dictionary','fuzzy','embedding','manual','model')),
    confidence           REAL NOT NULL DEFAULT 1.0,
    is_primary           BOOLEAN NOT NULL DEFAULT false,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (entity_canonical_id, alias_normalized)
);

CREATE INDEX IF NOT EXISTS idx_entity_aliases_lookup
    ON entity_aliases(alias_normalized, language);

CREATE INDEX IF NOT EXISTS idx_entity_aliases_trgm
    ON entity_aliases USING GIN (alias_normalized gin_trgm_ops);

-- ─── entity_linking_candidates ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entity_linking_candidates (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ner_result_id        UUID NOT NULL REFERENCES ner_results(id) ON DELETE CASCADE,
    entity_canonical_id  UUID REFERENCES entity_canonical(id) ON DELETE SET NULL,
    score                REAL NOT NULL,
    method               VARCHAR(32) NOT NULL
        CHECK (method IN ('exact','rule','alias_dict','fuzzy','embedding','llm')),
    selected             BOOLEAN NOT NULL DEFAULT false,
    metadata             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_linking_candidates_ner_result
    ON entity_linking_candidates(ner_result_id);

CREATE INDEX IF NOT EXISTS idx_linking_candidates_canonical
    ON entity_linking_candidates(entity_canonical_id);

CREATE INDEX IF NOT EXISTS idx_linking_candidates_selected
    ON entity_linking_candidates(ner_result_id)
    WHERE selected = true;

-- ─── entity_normalization_rules ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entity_normalization_rules (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_type            VARCHAR(32) NOT NULL
        CHECK (rule_type IN ('alias','abbreviation','regex','merge')),
    pattern              TEXT NOT NULL,
    replacement          TEXT,
    entity_type          VARCHAR(16)
        CHECK (entity_type IS NULL OR entity_type IN ('PERSON','ORG','LOC','MISC','GPE','PRODUCT','EVENT')),
    language             VARCHAR(8),
    target_canonical_id  UUID REFERENCES entity_canonical(id) ON DELETE SET NULL,
    priority             INT NOT NULL DEFAULT 100,
    enabled              BOOLEAN NOT NULL DEFAULT true,
    created_by           VARCHAR(64),
    metadata             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_normalization_rules_enabled_priority
    ON entity_normalization_rules(enabled, priority DESC)
    WHERE enabled = true;

CREATE INDEX IF NOT EXISTS idx_normalization_rules_lang_type
    ON entity_normalization_rules(language, rule_type);

-- ─── ner_model_runs ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ner_model_runs (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    preprocessed_message_id    UUID NOT NULL REFERENCES preprocessed_messages(id) ON DELETE CASCADE,
    provider_name              VARCHAR(64),
    provider_version           VARCHAR(64),
    language                   VARCHAR(8),
    entity_count               INT,
    latency_ms                 REAL,
    success                    BOOLEAN NOT NULL DEFAULT true,
    error                      TEXT,
    metadata                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ner_model_runs_message_provider
    ON ner_model_runs(preprocessed_message_id, provider_name);

-- ─── entity_merge_history ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entity_merge_history (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_canonical_id  UUID NOT NULL,
    target_canonical_id  UUID NOT NULL REFERENCES entity_canonical(id) ON DELETE CASCADE,
    reason               TEXT,
    actor                VARCHAR(64),
    metadata             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_merge_history_source
    ON entity_merge_history(source_canonical_id);

CREATE INDEX IF NOT EXISTS idx_merge_history_target
    ON entity_merge_history(target_canonical_id);

-- ─── extend ner_results ──────────────────────────────────────────────────────
ALTER TABLE ner_results
    ADD COLUMN IF NOT EXISTS entity_canonical_id UUID REFERENCES entity_canonical(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_ner_results_canonical
    ON ner_results(entity_canonical_id)
    WHERE entity_canonical_id IS NOT NULL;

DO $$
BEGIN
    RAISE NOTICE 'Migration 017_entity_normalization completed successfully';
END $$;

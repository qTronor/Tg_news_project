-- Migration 022: Scientific paper analysis tables
-- Tracks scientific papers detected in Telegram messages

CREATE TABLE IF NOT EXISTS scientific_papers (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_message_id TEXT NOT NULL,
    source_channel    TEXT NOT NULL,
    source_url        TEXT,
    source_type       TEXT NOT NULL CHECK (source_type IN ('arxiv','openreview','doi','pdf_url','telegram_file','webpage')),
    telegram_file_id  TEXT,
    local_file_path   TEXT,
    title             TEXT,
    authors           JSONB DEFAULT '[]'::jsonb,
    abstract          TEXT,
    published_at      TIMESTAMPTZ,
    detected_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    parsing_status    TEXT NOT NULL DEFAULT 'detected'
                        CHECK (parsing_status IN ('detected','parsing','parsed','partial','failed')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_scientific_papers_source_url
    ON scientific_papers (source_url)
    WHERE source_url IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scientific_papers_source_message_id ON scientific_papers (source_message_id);
CREATE INDEX IF NOT EXISTS idx_scientific_papers_source_type       ON scientific_papers (source_type);
CREATE INDEX IF NOT EXISTS idx_scientific_papers_created_at        ON scientific_papers (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scientific_papers_parsing_status    ON scientific_papers (parsing_status);

CREATE TABLE IF NOT EXISTS scientific_paper_texts (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id           UUID NOT NULL REFERENCES scientific_papers(id) ON DELETE CASCADE,
    full_text          TEXT,
    sections_json      JSONB DEFAULT '{}'::jsonb,
    extraction_method  TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scientific_paper_texts_paper_id ON scientific_paper_texts (paper_id);

CREATE TABLE IF NOT EXISTS scientific_paper_summaries (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id       UUID NOT NULL REFERENCES scientific_papers(id) ON DELETE CASCADE,
    model_name     TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    summary_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    short_summary  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scientific_paper_summaries_paper_id ON scientific_paper_summaries (paper_id);

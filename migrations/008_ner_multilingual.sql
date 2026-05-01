-- Migration: 008_ner_multilingual
-- Description: Add backend routing metadata to ner_results for multilingual NER
-- Date: 2026-04-22

ALTER TABLE ner_results
    ADD COLUMN IF NOT EXISTS model_backend VARCHAR(32),
    ADD COLUMN IF NOT EXISTS model_language VARCHAR(8);

-- Backfill existing rows: all pre-migration rows used Natasha (RU)
UPDATE ner_results
SET model_backend = 'natasha',
    model_language = 'ru'
WHERE model_backend IS NULL;

CREATE INDEX IF NOT EXISTS idx_ner_results_model_backend
    ON ner_results(model_backend);
CREATE INDEX IF NOT EXISTS idx_ner_results_model_language
    ON ner_results(model_language);

COMMENT ON COLUMN ner_results.model_backend IS 'NER backend name: natasha (RU) or dslim/bert-base-NER (EN).';
COMMENT ON COLUMN ner_results.model_language IS 'Language the backend was invoked for (ISO 639-1).';

DO $$
BEGIN
    RAISE NOTICE 'Migration 008_ner_multilingual completed successfully';
END $$;

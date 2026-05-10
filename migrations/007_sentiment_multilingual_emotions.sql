-- Migration: 007_sentiment_multilingual_emotions
-- Description: Add multilingual routing metadata and emotion model tracking to sentiment_results
-- Date: 2026-04-22

ALTER TABLE sentiment_results
    ADD COLUMN IF NOT EXISTS model_language VARCHAR(16),
    ADD COLUMN IF NOT EXISTS emotion_model_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS emotion_model_version VARCHAR(32),
    ADD COLUMN IF NOT EXISTS aspects_status VARCHAR(32) DEFAULT 'not_supported_v1';

-- Backfill model_language for existing RU rows (the only language that was
-- processed before this migration).
UPDATE sentiment_results
SET model_language = 'ru'
WHERE model_language IS NULL
  AND model_name LIKE '%rubert%';

-- All historical rows pre-date real emotion inference; leave emotion_model_*
-- as NULL (consistent with "no emotion backend ran").

-- aspects_status: all historical rows are also pre-v1-aspects, so the default
-- 'not_supported_v1' is correct without explicit backfill.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'sentiment_results_aspects_status_check'
    ) THEN
        ALTER TABLE sentiment_results
            ADD CONSTRAINT sentiment_results_aspects_status_check
            CHECK (aspects_status IN ('supported', 'not_supported_v1'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_sentiment_results_model_language
    ON sentiment_results(model_language);

COMMENT ON COLUMN sentiment_results.model_language IS 'Backend language routing key: ru = rubert, multilingual = XLM-R, null = legacy row.';
COMMENT ON COLUMN sentiment_results.emotion_model_name IS 'HuggingFace model ID of the emotion classifier that ran, or NULL if skipped.';
COMMENT ON COLUMN sentiment_results.emotion_model_version IS 'Version tag of the emotion model.';
COMMENT ON COLUMN sentiment_results.aspects_status IS 'Aspect-based sentiment support status: not_supported_v1 until an ABSA model is integrated.';

DO $$
BEGIN
    RAISE NOTICE 'Migration 007_sentiment_multilingual_emotions completed successfully';
END $$;

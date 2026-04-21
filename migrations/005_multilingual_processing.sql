-- Migration: 005_multilingual_processing
-- Description: Add language detection and multilingual routing metadata
-- Date: 2026-04-20

ALTER TABLE preprocessed_messages
    ADD COLUMN IF NOT EXISTS original_language VARCHAR(16),
    ADD COLUMN IF NOT EXISTS language_confidence REAL,
    ADD COLUMN IF NOT EXISTS is_supported_for_full_analysis BOOLEAN,
    ADD COLUMN IF NOT EXISTS analysis_mode VARCHAR(16),
    ADD COLUMN IF NOT EXISTS translation_status VARCHAR(32);

UPDATE preprocessed_messages
SET original_language = COALESCE(original_language, language),
    is_supported_for_full_analysis = COALESCE(is_supported_for_full_analysis, language IN ('ru', 'en')),
    analysis_mode = COALESCE(
        analysis_mode,
        CASE
            WHEN language IN ('ru', 'en') THEN 'full'
            WHEN language IS NULL THEN 'unknown'
            ELSE 'partial'
        END
    ),
    translation_status = COALESCE(translation_status, 'not_requested')
WHERE original_language IS NULL
   OR is_supported_for_full_analysis IS NULL
   OR analysis_mode IS NULL
   OR translation_status IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'preprocessed_messages_language_confidence_check'
    ) THEN
        ALTER TABLE preprocessed_messages
            ADD CONSTRAINT preprocessed_messages_language_confidence_check
            CHECK (language_confidence IS NULL OR (language_confidence >= 0 AND language_confidence <= 1));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'preprocessed_messages_analysis_mode_check'
    ) THEN
        ALTER TABLE preprocessed_messages
            ADD CONSTRAINT preprocessed_messages_analysis_mode_check
            CHECK (analysis_mode IN ('full', 'partial', 'unknown'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'preprocessed_messages_translation_status_check'
    ) THEN
        ALTER TABLE preprocessed_messages
    ADD CONSTRAINT preprocessed_messages_translation_status_check
            CHECK (translation_status IN ('not_requested', 'pending', 'translated', 'failed'));
    END IF;
END $$;

ALTER TABLE preprocessed_messages
    ALTER COLUMN is_supported_for_full_analysis SET DEFAULT TRUE,
    ALTER COLUMN analysis_mode SET DEFAULT 'full',
    ALTER COLUMN translation_status SET DEFAULT 'not_requested';

CREATE INDEX IF NOT EXISTS idx_preprocessed_messages_original_language
    ON preprocessed_messages(original_language);
CREATE INDEX IF NOT EXISTS idx_preprocessed_messages_analysis_mode
    ON preprocessed_messages(analysis_mode);
CREATE INDEX IF NOT EXISTS idx_preprocessed_messages_full_analysis
    ON preprocessed_messages(is_supported_for_full_analysis);

COMMENT ON COLUMN preprocessed_messages.original_language IS 'Detected original message language; ISO 639-1 where known, other/und for fallback modes.';
COMMENT ON COLUMN preprocessed_messages.language_confidence IS 'Language detection confidence from 0 to 1.';
COMMENT ON COLUMN preprocessed_messages.is_supported_for_full_analysis IS 'True for languages routed through the full analytics contour.';
COMMENT ON COLUMN preprocessed_messages.analysis_mode IS 'Language routing mode: full, partial, or unknown.';
COMMENT ON COLUMN preprocessed_messages.translation_status IS 'Placeholder for future asynchronous translation or summary enrichment.';

DO $$
BEGIN
    RAISE NOTICE 'Migration 005_multilingual_processing completed successfully';
END $$;

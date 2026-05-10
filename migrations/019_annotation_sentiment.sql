-- Migration: 019_annotation_sentiment
-- Description: Add sentiment field to annotation_labels for manual sentiment annotation
-- Date: 2026-05-04

ALTER TABLE annotation_labels
    ADD COLUMN IF NOT EXISTS sentiment VARCHAR(20)
        CHECK (sentiment IS NULL OR sentiment IN ('positive', 'neutral', 'negative'));

CREATE INDEX IF NOT EXISTS idx_annotation_labels_sentiment
    ON annotation_labels(sentiment)
    WHERE sentiment IS NOT NULL;

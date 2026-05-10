-- Migration: 020_topic_novelty_detection
-- Description: Multi-signal novelty detection storage for topic clusters
-- Date: 2026-05-03

CREATE TABLE IF NOT EXISTS topic_history (
    public_cluster_id VARCHAR(320) PRIMARY KEY,
    run_id VARCHAR(255) NOT NULL REFERENCES cluster_runs_pg(run_id) ON DELETE CASCADE,
    cluster_id INTEGER NOT NULL,
    first_seen TIMESTAMPTZ,
    last_seen TIMESTAMPTZ,
    message_count INTEGER NOT NULL DEFAULT 0,
    channel_count INTEGER NOT NULL DEFAULT 0,
    avg_sentiment REAL NOT NULL DEFAULT 0,
    centroid_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    entities_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    channels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT topic_history_message_count_check CHECK (message_count >= 0),
    CONSTRAINT topic_history_channel_count_check CHECK (channel_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_topic_history_run
    ON topic_history(run_id, cluster_id);
CREATE INDEX IF NOT EXISTS idx_topic_history_seen
    ON topic_history(first_seen, last_seen);
CREATE INDEX IF NOT EXISTS idx_topic_history_entities_gin
    ON topic_history USING gin(entities_json);
CREATE INDEX IF NOT EXISTS idx_topic_history_keywords_gin
    ON topic_history USING gin(keywords_json);

CREATE TABLE IF NOT EXISTS topic_novelty_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_cluster_id VARCHAR(320) NOT NULL REFERENCES topic_history(public_cluster_id) ON DELETE CASCADE,
    run_id VARCHAR(255) NOT NULL REFERENCES cluster_runs_pg(run_id) ON DELETE CASCADE,
    novelty_score REAL NOT NULL,
    novelty_status VARCHAR(32) NOT NULL,
    nearest_topic_id VARCHAR(320),
    features_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    explanation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    algorithm_version VARCHAR(64) NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT topic_novelty_scores_score_check CHECK (novelty_score >= 0 AND novelty_score <= 1),
    CONSTRAINT topic_novelty_scores_status_check CHECK (
        novelty_status IN ('new', 'continuation', 'merged', 'split', 'uncertain', 'noise')
    )
);

CREATE INDEX IF NOT EXISTS idx_topic_novelty_scores_cluster_time
    ON topic_novelty_scores(public_cluster_id, calculated_at DESC);
CREATE INDEX IF NOT EXISTS idx_topic_novelty_scores_run_status
    ON topic_novelty_scores(run_id, novelty_status, novelty_score DESC);
CREATE INDEX IF NOT EXISTS idx_topic_novelty_scores_new
    ON topic_novelty_scores(novelty_score DESC, calculated_at DESC)
    WHERE novelty_status = 'new';

CREATE OR REPLACE VIEW topic_novelty_scores_latest AS
SELECT DISTINCT ON (public_cluster_id)
    id,
    public_cluster_id,
    run_id,
    novelty_score,
    novelty_status,
    nearest_topic_id,
    features_json,
    explanation_json,
    algorithm_version,
    calculated_at
FROM topic_novelty_scores
ORDER BY public_cluster_id, calculated_at DESC;

CREATE TABLE IF NOT EXISTS topic_lifecycle_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_cluster_id VARCHAR(320) NOT NULL REFERENCES topic_history(public_cluster_id) ON DELETE CASCADE,
    run_id VARCHAR(255) REFERENCES cluster_runs_pg(run_id) ON DELETE SET NULL,
    event_type VARCHAR(32) NOT NULL,
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    related_topic_id VARCHAR(320),
    confidence REAL NOT NULL DEFAULT 0,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT topic_lifecycle_events_type_check CHECK (
        event_type IN ('new', 'continuation', 'merged', 'split', 'uncertain', 'noise')
    ),
    CONSTRAINT topic_lifecycle_events_confidence_check CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE INDEX IF NOT EXISTS idx_topic_lifecycle_events_cluster
    ON topic_lifecycle_events(public_cluster_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_topic_lifecycle_events_type
    ON topic_lifecycle_events(event_type, event_time DESC);

CREATE TABLE IF NOT EXISTS topic_similarity_links (
    source_cluster_id VARCHAR(320) NOT NULL REFERENCES topic_history(public_cluster_id) ON DELETE CASCADE,
    target_cluster_id VARCHAR(320) NOT NULL,
    run_id VARCHAR(255) REFERENCES cluster_runs_pg(run_id) ON DELETE SET NULL,
    semantic_similarity REAL NOT NULL DEFAULT 0,
    entity_overlap REAL NOT NULL DEFAULT 0,
    channel_overlap REAL NOT NULL DEFAULT 0,
    keyword_overlap REAL NOT NULL DEFAULT 0,
    overall_similarity REAL NOT NULL DEFAULT 0,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_cluster_id, target_cluster_id),
    CONSTRAINT topic_similarity_links_scores_check CHECK (
        semantic_similarity >= 0 AND semantic_similarity <= 1
        AND entity_overlap >= 0 AND entity_overlap <= 1
        AND channel_overlap >= 0 AND channel_overlap <= 1
        AND keyword_overlap >= 0 AND keyword_overlap <= 1
        AND overall_similarity >= 0 AND overall_similarity <= 1
    )
);

CREATE INDEX IF NOT EXISTS idx_topic_similarity_links_source_score
    ON topic_similarity_links(source_cluster_id, overall_similarity DESC);
CREATE INDEX IF NOT EXISTS idx_topic_similarity_links_target
    ON topic_similarity_links(target_cluster_id, overall_similarity DESC);

COMMENT ON TABLE topic_history IS 'Historical feature snapshots for every persisted topic cluster.';
COMMENT ON TABLE topic_novelty_scores IS 'Explainable multi-signal novelty scores for topic clusters.';
COMMENT ON COLUMN topic_novelty_scores.features_json IS 'semantic/entity/channel/keyword dissimilarity, temporal burst, sentiment shift, and new entity ratio.';
COMMENT ON COLUMN topic_novelty_scores.explanation_json IS 'Human-readable reasons and formula metadata for the UI.';
COMMENT ON TABLE topic_lifecycle_events IS 'Lifecycle labels emitted by the novelty detector: new, continuation, merged, split, uncertain, noise.';
COMMENT ON TABLE topic_similarity_links IS 'Similarity evidence between a current topic and historical topics.';

DO $$
BEGIN
    RAISE NOTICE 'Migration 020_topic_novelty_detection completed successfully';
END $$;

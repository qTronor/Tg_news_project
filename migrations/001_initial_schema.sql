-- Migration: 001_initial_schema
-- Description: Create initial database schema for Telegram News Pipeline
-- Version: 1.0.0
-- Date: 2026-01-31

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For fuzzy text search

-- =====================================================
-- TABLE: raw_messages
-- Description: Raw messages collected from Telegram
-- =====================================================
CREATE TABLE raw_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Telegram identifiers
    message_id BIGINT NOT NULL,
    channel VARCHAR(255) NOT NULL,
    
    -- Content
    text TEXT,
    message_date TIMESTAMPTZ NOT NULL,
    
    -- Engagement metrics
    views INTEGER DEFAULT 0,
    forwards INTEGER DEFAULT 0,
    reactions JSONB,
    
    -- Media
    media JSONB,
    
    -- Threading
    edit_date TIMESTAMPTZ,
    reply_to_message_id BIGINT,
    author VARCHAR(255),
    is_forwarded BOOLEAN DEFAULT FALSE,
    forward_from_channel VARCHAR(255),
    
    -- Event metadata
    event_id VARCHAR(512) GENERATED ALWAYS AS (channel || ':' || message_id) STORED,
    event_timestamp TIMESTAMPTZ NOT NULL,
    trace_id UUID,
    
    -- Technical fields
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT raw_messages_channel_message_id_unique UNIQUE (channel, message_id),
    CONSTRAINT raw_messages_views_check CHECK (views >= 0),
    CONSTRAINT raw_messages_forwards_check CHECK (forwards >= 0)
);

-- Indexes for raw_messages
CREATE INDEX idx_raw_messages_channel ON raw_messages(channel);
CREATE INDEX idx_raw_messages_message_date ON raw_messages(message_date DESC);
CREATE INDEX idx_raw_messages_event_timestamp ON raw_messages(event_timestamp DESC);
CREATE INDEX idx_raw_messages_trace_id ON raw_messages(trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX idx_raw_messages_event_id ON raw_messages(event_id);
CREATE INDEX idx_raw_messages_text_fts ON raw_messages USING gin(to_tsvector('russian', COALESCE(text, '')));
CREATE INDEX idx_raw_messages_text_trgm ON raw_messages USING gin(text gin_trgm_ops);

COMMENT ON TABLE raw_messages IS 'Raw messages collected from Telegram channels';
COMMENT ON COLUMN raw_messages.event_id IS 'Unique event identifier: {channel}:{message_id}';
COMMENT ON COLUMN raw_messages.reactions IS 'JSON object with emoji reactions: {"👍": 45, "🔥": 12}';
COMMENT ON COLUMN raw_messages.media IS 'JSON object with media information: {type, url, file_size, mime_type}';

-- =====================================================
-- TABLE: preprocessed_messages
-- Description: Preprocessed and cleaned text
-- =====================================================
CREATE TABLE preprocessed_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_message_id UUID NOT NULL REFERENCES raw_messages(id) ON DELETE CASCADE,
    
    -- Identifiers
    message_id BIGINT NOT NULL,
    channel VARCHAR(255) NOT NULL,
    event_id VARCHAR(512) NOT NULL,
    
    -- Processed text
    original_text TEXT NOT NULL,
    cleaned_text TEXT NOT NULL,
    normalized_text TEXT,
    language VARCHAR(10),
    tokens TEXT[],
    sentences_count INTEGER,
    word_count INTEGER,
    
    -- Flags
    has_urls BOOLEAN DEFAULT FALSE,
    has_mentions BOOLEAN DEFAULT FALSE,
    has_hashtags BOOLEAN DEFAULT FALSE,
    
    -- Extracted elements
    urls TEXT[],
    mentions TEXT[],
    hashtags TEXT[],
    
    -- Metadata
    preprocessing_version VARCHAR(50),
    event_timestamp TIMESTAMPTZ NOT NULL,
    trace_id UUID,
    processing_time_ms REAL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT preprocessed_messages_channel_message_id_unique UNIQUE (channel, message_id),
    CONSTRAINT preprocessed_messages_word_count_check CHECK (word_count >= 0),
    CONSTRAINT preprocessed_messages_sentences_count_check CHECK (sentences_count >= 0)
);

-- Indexes for preprocessed_messages
CREATE INDEX idx_preprocessed_messages_raw_id ON preprocessed_messages(raw_message_id);
CREATE INDEX idx_preprocessed_messages_event_id ON preprocessed_messages(event_id);
CREATE INDEX idx_preprocessed_messages_language ON preprocessed_messages(language);
CREATE INDEX idx_preprocessed_messages_channel ON preprocessed_messages(channel);
CREATE INDEX idx_preprocessed_messages_normalized_fts ON preprocessed_messages 
    USING gin(to_tsvector('russian', COALESCE(normalized_text, '')));

COMMENT ON TABLE preprocessed_messages IS 'Messages after text preprocessing (cleaning, normalization, tokenization)';

-- =====================================================
-- TABLE: sentiment_results
-- Description: Sentiment analysis results
-- =====================================================
CREATE TABLE sentiment_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    preprocessed_message_id UUID NOT NULL REFERENCES preprocessed_messages(id) ON DELETE CASCADE,
    
    -- Identifiers
    message_id BIGINT NOT NULL,
    channel VARCHAR(255) NOT NULL,
    event_id VARCHAR(512) NOT NULL,
    
    -- Sentiment
    sentiment_label VARCHAR(50) NOT NULL,
    sentiment_score REAL NOT NULL,
    positive_prob REAL,
    negative_prob REAL,
    neutral_prob REAL,
    
    -- Emotions
    emotion_anger REAL,
    emotion_fear REAL,
    emotion_joy REAL,
    emotion_sadness REAL,
    emotion_surprise REAL,
    emotion_disgust REAL,
    
    -- Aspect-based sentiment (JSONB for flexibility)
    aspects JSONB,
    
    -- Model
    model_name VARCHAR(100),
    model_version VARCHAR(50),
    model_framework VARCHAR(50),
    
    -- Metadata
    event_timestamp TIMESTAMPTZ NOT NULL,
    trace_id UUID,
    processing_time_ms REAL,
    analyzed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT sentiment_results_channel_message_id_unique UNIQUE (channel, message_id),
    CONSTRAINT sentiment_results_score_check CHECK (sentiment_score >= 0 AND sentiment_score <= 1),
    CONSTRAINT sentiment_results_label_check CHECK (sentiment_label IN ('positive', 'negative', 'neutral'))
);

-- Indexes for sentiment_results
CREATE INDEX idx_sentiment_results_preprocessed_id ON sentiment_results(preprocessed_message_id);
CREATE INDEX idx_sentiment_results_event_id ON sentiment_results(event_id);
CREATE INDEX idx_sentiment_results_label ON sentiment_results(sentiment_label);
CREATE INDEX idx_sentiment_results_score ON sentiment_results(sentiment_score DESC);
CREATE INDEX idx_sentiment_results_channel ON sentiment_results(channel);
CREATE INDEX idx_sentiment_results_analyzed_at ON sentiment_results(analyzed_at DESC);

COMMENT ON TABLE sentiment_results IS 'Sentiment analysis results for messages';
COMMENT ON COLUMN sentiment_results.aspects IS 'JSON array of aspect-based sentiment: [{aspect, sentiment, score}]';

-- =====================================================
-- TABLE: ner_results
-- Description: Named Entity Recognition results
-- =====================================================
CREATE TABLE ner_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    preprocessed_message_id UUID NOT NULL REFERENCES preprocessed_messages(id) ON DELETE CASCADE,
    
    -- Identifiers
    message_id BIGINT NOT NULL,
    channel VARCHAR(255) NOT NULL,
    event_id VARCHAR(512) NOT NULL,
    
    -- Entity
    entity_text VARCHAR(500) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    start_pos INTEGER NOT NULL,
    end_pos INTEGER NOT NULL,
    confidence REAL NOT NULL,
    normalized_text VARCHAR(500),
    wikidata_id VARCHAR(50),
    aliases TEXT[],
    
    -- Entity metadata
    entity_metadata JSONB,
    
    -- Model
    model_name VARCHAR(100),
    model_version VARCHAR(50),
    
    -- Metadata
    event_timestamp TIMESTAMPTZ NOT NULL,
    trace_id UUID,
    extracted_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT ner_results_confidence_check CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT ner_results_position_check CHECK (start_pos >= 0 AND end_pos > start_pos),
    CONSTRAINT ner_results_entity_type_check CHECK (entity_type IN (
        'PERSON', 'ORG', 'GPE', 'LOC', 'PRODUCT', 'EVENT', 
        'DATE', 'TIME', 'MONEY', 'PERCENT', 'QUANTITY', 'ORDINAL', 'CARDINAL'
    ))
);

-- Indexes for ner_results
CREATE INDEX idx_ner_results_preprocessed_id ON ner_results(preprocessed_message_id);
CREATE INDEX idx_ner_results_event_id ON ner_results(event_id);
CREATE INDEX idx_ner_results_entity_type ON ner_results(entity_type);
CREATE INDEX idx_ner_results_entity_text ON ner_results(entity_text);
CREATE INDEX idx_ner_results_normalized_text ON ner_results(normalized_text);
CREATE INDEX idx_ner_results_wikidata ON ner_results(wikidata_id) WHERE wikidata_id IS NOT NULL;
CREATE INDEX idx_ner_results_channel ON ner_results(channel);
CREATE INDEX idx_ner_results_confidence ON ner_results(confidence DESC);

COMMENT ON TABLE ner_results IS 'Named entities extracted from messages';
COMMENT ON COLUMN ner_results.entity_type IS 'NER class: PERSON, ORG, GPE, LOC, etc.';
COMMENT ON COLUMN ner_results.wikidata_id IS 'Wikidata Q-identifier for entity linking';

-- =====================================================
-- TABLE: entity_relations
-- Description: Semantic relations between entities
-- =====================================================
CREATE TABLE entity_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    preprocessed_message_id UUID NOT NULL REFERENCES preprocessed_messages(id) ON DELETE CASCADE,
    
    -- Identifiers
    message_id BIGINT NOT NULL,
    channel VARCHAR(255) NOT NULL,
    
    -- Relation (SPO triple)
    subject VARCHAR(500) NOT NULL,
    predicate VARCHAR(200) NOT NULL,
    object VARCHAR(500) NOT NULL,
    confidence REAL NOT NULL,
    
    -- Types
    subject_type VARCHAR(50),
    object_type VARCHAR(50),
    
    -- Metadata
    event_timestamp TIMESTAMPTZ NOT NULL,
    trace_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT entity_relations_confidence_check CHECK (confidence >= 0 AND confidence <= 1)
);

-- Indexes for entity_relations
CREATE INDEX idx_entity_relations_preprocessed_id ON entity_relations(preprocessed_message_id);
CREATE INDEX idx_entity_relations_subject ON entity_relations(subject);
CREATE INDEX idx_entity_relations_predicate ON entity_relations(predicate);
CREATE INDEX idx_entity_relations_object ON entity_relations(object);
CREATE INDEX idx_entity_relations_channel ON entity_relations(channel);
CREATE INDEX idx_entity_relations_spo ON entity_relations(subject, predicate, object);

COMMENT ON TABLE entity_relations IS 'Subject-Predicate-Object triples extracted from messages';

-- =====================================================
-- TABLE: processed_events
-- Description: Event deduplication and idempotency tracking
-- =====================================================
CREATE TABLE processed_events (
    event_id VARCHAR(512) PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL,
    consumer_id VARCHAR(100) NOT NULL,
    
    -- Processing tracking
    processing_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_completed_at TIMESTAMPTZ,
    status VARCHAR(50) DEFAULT 'processing',
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT processed_events_status_check CHECK (status IN ('processing', 'completed', 'failed', 'retrying')),
    CONSTRAINT processed_events_retry_count_check CHECK (retry_count >= 0)
);

-- Indexes for processed_events
CREATE INDEX idx_processed_events_consumer ON processed_events(consumer_id);
CREATE INDEX idx_processed_events_type ON processed_events(event_type);
CREATE INDEX idx_processed_events_timestamp ON processed_events(event_timestamp DESC);
CREATE INDEX idx_processed_events_status ON processed_events(status) WHERE status != 'completed';
CREATE INDEX idx_processed_events_created ON processed_events(created_at);

COMMENT ON TABLE processed_events IS 'Tracks processed events for idempotency (at-least-once delivery)';
COMMENT ON COLUMN processed_events.event_id IS 'Unique event identifier from Kafka message key';

-- =====================================================
-- TABLE: outbox
-- Description: Transactional Outbox pattern for Kafka publishing
-- =====================================================
CREATE TABLE outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Aggregate information
    aggregate_type VARCHAR(100) NOT NULL,
    aggregate_id VARCHAR(512) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    
    -- Kafka metadata
    topic VARCHAR(255) NOT NULL,
    message_key VARCHAR(512) NOT NULL,
    partition_key VARCHAR(512),
    headers JSONB,
    
    -- Status tracking
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    
    -- Ordering
    sequence_number BIGSERIAL NOT NULL,
    
    CONSTRAINT outbox_status_check CHECK (status IN ('pending', 'published', 'failed')),
    CONSTRAINT outbox_retry_count_check CHECK (retry_count >= 0)
);

-- Indexes for outbox
CREATE INDEX idx_outbox_status ON outbox(status, created_at) WHERE status = 'pending';
CREATE INDEX idx_outbox_aggregate ON outbox(aggregate_type, aggregate_id);
CREATE INDEX idx_outbox_sequence ON outbox(sequence_number);
CREATE INDEX idx_outbox_topic ON outbox(topic);
CREATE INDEX idx_outbox_created_at ON outbox(created_at);

COMMENT ON TABLE outbox IS 'Transactional Outbox pattern for guaranteed Kafka message delivery';
COMMENT ON COLUMN outbox.sequence_number IS 'Global sequence for ordering across all aggregates';

-- =====================================================
-- TABLE: channels
-- Description: Telegram channel metadata
-- =====================================================
CREATE TABLE channels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    title VARCHAR(500),
    description TEXT,
    
    -- Statistics
    subscriber_count INTEGER,
    message_count INTEGER DEFAULT 0,
    
    -- Timestamps
    first_message_date TIMESTAMPTZ,
    last_message_date TIMESTAMPTZ,
    last_collected_at TIMESTAMPTZ,
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT channels_message_count_check CHECK (message_count >= 0)
);

CREATE INDEX idx_channels_name ON channels(name);
CREATE INDEX idx_channels_last_collected ON channels(last_collected_at DESC);

COMMENT ON TABLE channels IS 'Metadata about Telegram channels being monitored';

-- =====================================================
-- TRIGGERS
-- =====================================================

-- Auto-update updated_at column
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_raw_messages_updated_at 
    BEFORE UPDATE ON raw_messages 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_channels_updated_at 
    BEFORE UPDATE ON channels 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- MAINTENANCE FUNCTIONS
-- =====================================================

-- Cleanup old processed_events (retention: 7 days for completed)
CREATE OR REPLACE FUNCTION cleanup_processed_events()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM processed_events 
    WHERE created_at < NOW() - INTERVAL '7 days' 
    AND status = 'completed';
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_processed_events() IS 'Delete processed events older than 7 days (completed only)';

-- Cleanup old outbox entries (retention: 1 day for published)
CREATE OR REPLACE FUNCTION cleanup_outbox()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM outbox 
    WHERE status = 'published' 
    AND published_at < NOW() - INTERVAL '1 day';
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_outbox() IS 'Delete published outbox entries older than 1 day';

-- =====================================================
-- VIEWS
-- =====================================================

-- Aggregated channel statistics
CREATE OR REPLACE VIEW channel_stats AS
SELECT 
    c.name,
    c.title,
    COUNT(DISTINCT rm.id) AS total_messages,
    MAX(rm.message_date) AS latest_message_date,
    AVG(rm.views) AS avg_views,
    AVG(rm.forwards) AS avg_forwards,
    AVG(sr.sentiment_score) AS avg_sentiment,
    COUNT(DISTINCT CASE WHEN sr.sentiment_label = 'positive' THEN rm.id END) AS positive_count,
    COUNT(DISTINCT CASE WHEN sr.sentiment_label = 'negative' THEN rm.id END) AS negative_count,
    COUNT(DISTINCT CASE WHEN sr.sentiment_label = 'neutral' THEN rm.id END) AS neutral_count
FROM channels c
LEFT JOIN raw_messages rm ON rm.channel = c.name
LEFT JOIN preprocessed_messages pm ON pm.raw_message_id = rm.id
LEFT JOIN sentiment_results sr ON sr.preprocessed_message_id = pm.id
GROUP BY c.name, c.title;

COMMENT ON VIEW channel_stats IS 'Aggregated statistics per channel';

-- Top entities by mention count
CREATE OR REPLACE VIEW top_entities AS
SELECT 
    entity_type,
    normalized_text,
    wikidata_id,
    COUNT(*) AS mention_count,
    AVG(confidence) AS avg_confidence,
    COUNT(DISTINCT channel) AS channel_count,
    MIN(extracted_at) AS first_seen,
    MAX(extracted_at) AS last_seen
FROM ner_results
WHERE confidence >= 0.7  -- Only high-confidence entities
GROUP BY entity_type, normalized_text, wikidata_id
HAVING COUNT(*) >= 3  -- At least 3 mentions
ORDER BY mention_count DESC;

COMMENT ON VIEW top_entities IS 'Most frequently mentioned entities across all channels';

-- =====================================================
-- GRANTS (adjust according to your user roles)
-- =====================================================

-- Example: Grant permissions to application user
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO app_user;

-- =====================================================
-- COMPLETION
-- =====================================================

-- Verify installation
DO $$
BEGIN
    RAISE NOTICE 'Migration 001_initial_schema completed successfully';
    RAISE NOTICE 'Tables created: %', (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public');
    RAISE NOTICE 'Indexes created: %', (SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'public');
END $$;

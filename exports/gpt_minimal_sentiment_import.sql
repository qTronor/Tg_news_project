\set ON_ERROR_STOP on
CREATE TEMP TABLE gpt_minimal_sentiment_stage (
    request_id text,
    event_id varchar(512),
    preprocessed_message_id uuid,
    channel varchar(255),
    message_id bigint,
    sentiment_label varchar(50),
    sentiment_score real,
    positive_prob real,
    negative_prob real,
    neutral_prob real,
    emotion_anger real,
    emotion_fear real,
    emotion_joy real,
    emotion_sadness real,
    emotion_surprise real,
    emotion_disgust real,
    aspects jsonb
);
\copy gpt_minimal_sentiment_stage (request_id, event_id, preprocessed_message_id, channel, message_id, sentiment_label, sentiment_score, positive_prob, negative_prob, neutral_prob, emotion_anger, emotion_fear, emotion_joy, emotion_sadness, emotion_surprise, emotion_disgust, aspects) FROM '/tmp/gpt_minimal_sentiment_stage.csv' WITH (FORMAT csv, HEADER true);

DO $$
DECLARE
    missing_count integer;
BEGIN
    SELECT count(*)
    INTO missing_count
    FROM gpt_minimal_sentiment_stage s
    LEFT JOIN preprocessed_messages pm
      ON pm.id = s.preprocessed_message_id
     AND pm.channel = s.channel
     AND pm.message_id = s.message_id
     AND pm.event_id = s.event_id
    WHERE pm.id IS NULL;

    IF missing_count > 0 THEN
        RAISE EXCEPTION 'stage rows without matching preprocessed_messages: %', missing_count;
    END IF;
END
$$;

INSERT INTO sentiment_results (
    preprocessed_message_id,
    message_id,
    channel,
    event_id,
    sentiment_label,
    sentiment_score,
    positive_prob,
    negative_prob,
    neutral_prob,
    emotion_anger,
    emotion_fear,
    emotion_joy,
    emotion_sadness,
    emotion_surprise,
    emotion_disgust,
    aspects,
    model_name,
    model_version,
    model_framework,
    event_timestamp,
    trace_id,
    processing_time_ms,
    analyzed_at
)
SELECT
    s.preprocessed_message_id,
    s.message_id,
    s.channel,
    s.event_id,
    s.sentiment_label,
    s.sentiment_score,
    s.positive_prob,
    s.negative_prob,
    s.neutral_prob,
    s.emotion_anger,
    s.emotion_fear,
    s.emotion_joy,
    s.emotion_sadness,
    s.emotion_surprise,
    s.emotion_disgust,
    s.aspects,
    'gpt-manual-minimal-analysis',
    'manual-gpt-output-2026-04-21',
    'openai',
    COALESCE(pm.event_timestamp, NOW()),
    pm.trace_id,
    NULL,
    NOW()
FROM gpt_minimal_sentiment_stage s
JOIN preprocessed_messages pm
  ON pm.id = s.preprocessed_message_id
 AND pm.channel = s.channel
 AND pm.message_id = s.message_id
 AND pm.event_id = s.event_id
ON CONFLICT (channel, message_id) DO UPDATE
SET preprocessed_message_id = EXCLUDED.preprocessed_message_id,
    event_id = EXCLUDED.event_id,
    sentiment_label = EXCLUDED.sentiment_label,
    sentiment_score = EXCLUDED.sentiment_score,
    positive_prob = EXCLUDED.positive_prob,
    negative_prob = EXCLUDED.negative_prob,
    neutral_prob = EXCLUDED.neutral_prob,
    emotion_anger = EXCLUDED.emotion_anger,
    emotion_fear = EXCLUDED.emotion_fear,
    emotion_joy = EXCLUDED.emotion_joy,
    emotion_sadness = EXCLUDED.emotion_sadness,
    emotion_surprise = EXCLUDED.emotion_surprise,
    emotion_disgust = EXCLUDED.emotion_disgust,
    aspects = EXCLUDED.aspects,
    model_name = EXCLUDED.model_name,
    model_version = EXCLUDED.model_version,
    model_framework = EXCLUDED.model_framework,
    event_timestamp = EXCLUDED.event_timestamp,
    trace_id = EXCLUDED.trace_id,
    processing_time_ms = EXCLUDED.processing_time_ms,
    analyzed_at = EXCLUDED.analyzed_at;

SELECT
    count(*) AS imported_rows,
    count(*) FILTER (WHERE sentiment_label = 'positive') AS positive,
    count(*) FILTER (WHERE sentiment_label = 'negative') AS negative,
    count(*) FILTER (WHERE sentiment_label = 'neutral') AS neutral
FROM sentiment_results
WHERE model_name = 'gpt-manual-minimal-analysis'
  AND model_version = 'manual-gpt-output-2026-04-21';

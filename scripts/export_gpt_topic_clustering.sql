WITH source_rows AS (
    SELECT
        sr.id AS sentiment_result_id,
        sr.preprocessed_message_id,
        pm.raw_message_id,
        sr.event_id,
        sr.channel,
        sr.message_id,
        rm.message_date,
        COALESCE(NULLIF(rm.text, ''), pm.original_text, pm.cleaned_text) AS text,
        pm.cleaned_text,
        pm.language,
        pm.word_count,
        rm.views,
        rm.forwards,
        sr.sentiment_label,
        sr.sentiment_score,
        sr.positive_prob,
        sr.negative_prob,
        sr.neutral_prob,
        sr.aspects
    FROM sentiment_results sr
    JOIN preprocessed_messages pm ON pm.id = sr.preprocessed_message_id
    JOIN raw_messages rm ON rm.event_id = sr.event_id
    WHERE sr.model_name = 'gpt-manual-minimal-analysis'
      AND COALESCE(pm.word_count, 0) >= 12
),
ordered AS (
    SELECT
        *,
        row_number() OVER (ORDER BY message_date DESC, channel, message_id) AS rn
    FROM source_rows
)
SELECT jsonb_build_object(
    'request_id', 'topic_src_' || lpad(rn::text, 4, '0'),
    'run_hint', 'gpt_topics_2026_04_21_v1',
    'event_id', event_id,
    'channel', channel,
    'message_id', message_id,
    'raw_message_id', raw_message_id,
    'preprocessed_message_id', preprocessed_message_id,
    'message_date', to_char(message_date AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'language', language,
    'word_count', word_count,
    'engagement', jsonb_build_object(
        'views', views,
        'forwards', forwards
    ),
    'sentiment', jsonb_build_object(
        'label', sentiment_label,
        'score', sentiment_score,
        'positive_prob', positive_prob,
        'negative_prob', negative_prob,
        'neutral_prob', neutral_prob
    ),
    'aspects', COALESCE(aspects, '[]'::jsonb),
    'entities', COALESCE(entities.entities, '[]'::jsonb),
    'text', text
)::text AS payload
FROM ordered o
LEFT JOIN LATERAL (
    SELECT jsonb_agg(entity_obj ORDER BY mention_count DESC, confidence DESC, entity_text) AS entities
    FROM (
        SELECT
            jsonb_build_object(
                'text', COALESCE(max(nr.normalized_text), min(nr.entity_text)),
                'type', nr.entity_type,
                'mentions', count(*),
                'confidence', round(avg(nr.confidence)::numeric, 4)
            ) AS entity_obj,
            count(*) AS mention_count,
            avg(nr.confidence) AS confidence,
            COALESCE(max(nr.normalized_text), min(nr.entity_text)) AS entity_text
        FROM ner_results nr
        WHERE nr.event_id = o.event_id
        GROUP BY lower(COALESCE(nr.normalized_text, nr.entity_text)), nr.entity_type
        ORDER BY mention_count DESC, confidence DESC, entity_text
        LIMIT 8
    ) e
) entities ON true
ORDER BY message_date DESC, channel, message_id;

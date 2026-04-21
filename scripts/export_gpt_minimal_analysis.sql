COPY (
WITH ranked AS (
    SELECT
        pm.id AS preprocessed_message_id,
        pm.raw_message_id,
        pm.event_id,
        pm.channel,
        pm.message_id,
        pm.cleaned_text,
        pm.original_text,
        pm.language,
        pm.original_language,
        pm.analysis_mode,
        pm.word_count,
        pm.sentences_count,
        pm.has_urls,
        pm.has_mentions,
        pm.has_hashtags,
        rm.message_date,
        rm.views,
        rm.forwards,
        rm.reactions,
        row_number() OVER (
            PARTITION BY pm.channel, pm.language
            ORDER BY rm.message_date DESC, pm.message_id DESC
        ) AS rank_in_channel_language
    FROM preprocessed_messages pm
    JOIN raw_messages rm ON rm.id = pm.raw_message_id
    LEFT JOIN sentiment_results sr ON sr.preprocessed_message_id = pm.id
    WHERE sr.id IS NULL
      AND pm.language IN ('ru', 'en')
      AND pm.word_count >= 12
      AND length(pm.cleaned_text) >= 80
),
selected AS (
    SELECT *
    FROM ranked
    WHERE rank_in_channel_language <= 50
)
SELECT jsonb_build_object(
    'request_id', 'gpt_min_' || lpad(row_number() OVER (
        ORDER BY message_date DESC, channel, message_id
    )::text, 4, '0'),
    'target_table', 'sentiment_results',
    'preprocessed_message_id', preprocessed_message_id,
    'raw_message_id', raw_message_id,
    'event_id', event_id,
    'channel', channel,
    'message_id', message_id,
    'message_date', to_char(message_date AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'language', language,
    'original_language', original_language,
    'analysis_mode', analysis_mode,
    'word_count', word_count,
    'sentences_count', sentences_count,
    'engagement', jsonb_build_object(
        'views', views,
        'forwards', forwards,
        'reactions', reactions
    ),
    'text_flags', jsonb_build_object(
        'has_urls', has_urls,
        'has_mentions', has_mentions,
        'has_hashtags', has_hashtags
    ),
    'text', cleaned_text,
    'existing_entities', COALESCE(entities.entities, '[]'::jsonb),
    'existing_relations', COALESCE(relations.relations, '[]'::jsonb)
) AS payload
FROM selected s
LEFT JOIN LATERAL (
    SELECT jsonb_agg(entity_obj ORDER BY confidence DESC, entity_text) AS entities
    FROM (
        SELECT jsonb_build_object(
            'text', nr.entity_text,
            'type', nr.entity_type,
            'confidence', nr.confidence,
            'normalized', nr.normalized_text
        ) AS entity_obj,
        nr.confidence,
        nr.entity_text
        FROM ner_results nr
        WHERE nr.preprocessed_message_id = s.preprocessed_message_id
        ORDER BY nr.confidence DESC, nr.entity_text
        LIMIT 12
    ) e
) entities ON true
LEFT JOIN LATERAL (
    SELECT jsonb_agg(relation_obj ORDER BY confidence DESC, subject, predicate, object) AS relations
    FROM (
        SELECT jsonb_build_object(
            'subject', er.subject,
            'predicate', er.predicate,
            'object', er.object,
            'confidence', er.confidence,
            'subject_type', er.subject_type,
            'object_type', er.object_type
        ) AS relation_obj,
        er.confidence,
        er.subject,
        er.predicate,
        er.object
        FROM entity_relations er
        WHERE er.preprocessed_message_id = s.preprocessed_message_id
        ORDER BY er.confidence DESC, er.subject, er.predicate, er.object
        LIMIT 8
    ) r
) relations ON true
ORDER BY message_date DESC, channel, message_id
) TO STDOUT;

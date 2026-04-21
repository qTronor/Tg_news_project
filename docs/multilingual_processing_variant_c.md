# Multilingual Processing Variant C

Date: 2026-04-20

## Scope

Variant C keeps the existing event-driven pipeline and adds language-aware routing at the preprocessor boundary.

- `ru`, `en`: full analytics contour (`analysis_mode=full`).
- Other detected languages: partial contour (`analysis_mode=partial`).
- Unsafe detection: safe fallback (`analysis_mode=unknown`).
- Topic clustering remains active for every non-empty text through multilingual sentence-transformer embeddings.
- No LLM or external translation API is called in the critical path.

## Contract Fields

`preprocessed.messages.payload` now includes:

- `original_language`: detected language. Uses ISO 639-1 when known, `other` for unsupported Latin text, and `und` for unsafe detection.
- `language_confidence`: detector confidence from `0` to `1`.
- `is_supported_for_full_analysis`: true for languages allowed through full NER and sentiment.
- `analysis_mode`: `full`, `partial`, or `unknown`.
- `translation_status`: placeholder for future asynchronous translation or summary enrichment. Initial value is `not_requested`.

The legacy `language` field remains and mirrors `original_language`.

## Storage

Migration `migrations/005_multilingual_processing.sql` adds the same routing fields to `preprocessed_messages` and creates indexes for language/mode filtering.

## Runtime Config

Preprocessor:

```yaml
language_detection:
  enabled: true
  min_confidence: 0.55
  full_analysis_languages:
    - "ru"
    - "en"
```

Topic clusterer:

```yaml
model:
  sbert_model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
  device: "auto"
```

`device=auto` uses CUDA when available and CPU otherwise. The selected default model is compact enough for laptop GPU/CPU fallback and supports multilingual embeddings.

Set `PREPROCESSOR__LANGUAGE_DETECTION__ENABLED=false` only as a rollback switch: detection metadata is still emitted, but every message is routed as `analysis_mode=full` to preserve the legacy contour.

## Routing

Preprocessor emits the routing contract for every message. `sentiment_analyzer` and `ner_extractor` consume the same topic, but skip and mark the event completed when `analysis_mode != full` or `is_supported_for_full_analysis=false`. This keeps at-least-once/idempotent semantics without DLQ noise for unsupported languages.

`topic_clusterer` stores `language` and `analysis_mode` in its local embeddings DB and clusters all languages with the multilingual embedding backend.

## Metrics

New preprocessor metrics:

- `preprocessor_language_detection_latency_seconds`
- `preprocessor_messages_by_language_total{language,analysis_mode,supported_for_full_analysis}`

Existing processed/DLQ/latency metrics remain unchanged.

## Future Work

Translation and LLM summaries should be implemented as an asynchronous downstream service that consumes `preprocessed.messages` and writes a separate enrichment topic/table. It should not block preprocessing, embeddings, sentiment, NER, or graph writes.

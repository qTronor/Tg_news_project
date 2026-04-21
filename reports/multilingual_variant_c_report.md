# Multilingual Variant C Implementation Report

Date: 2026-04-20

## What Was Found

- `preprocessor.text_processing.detect_language` already existed, but it only used Cyrillic/Latin heuristics and defaulted unknown text to `ru`.
- `preprocessor` is the right insertion point because it already owns text normalization, persistence into `preprocessed_messages`, and publication to `preprocessed.messages`.
- `topic_clusterer` already uses `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, so the embedding backend was already compatible with Variant C.
- `sentiment_analyzer` and `ner_extractor` consumed every `preprocessed.messages` event and had no language-aware skip path.

## What Was Implemented

- Added a lightweight local language detection contract in `preprocessor`.
- Added routing fields to `preprocessed.messages` and `preprocessed_messages`.
- Added migration `005_multilingual_processing.sql`.
- Added preprocessor metrics for language detection latency and message counts by language/mode.
- Added safe skip routing for unsupported/unknown languages in sentiment and NER.
- Kept topic clustering active for all detected languages and persisted language/mode in the local embeddings DB.
- Documented the architecture in `docs/multilingual_processing_variant_c.md`.

## Changed Contracts

`preprocessed.messages.payload` now emits:

- `original_language`
- `language_confidence`
- `is_supported_for_full_analysis`
- `analysis_mode`
- `translation_status`

The legacy `language` field remains for compatibility and mirrors `original_language`.

## Next Agent Notes

- Consider replacing the heuristic detector with a compact packaged detector only if dependency size and cold-start are acceptable.
- Add language-aware graph/UI fields if product needs to filter topic clusters by language.
- Implement translation/summary as an asynchronous downstream service, not in the critical path.
- If EN NER quality matters, add a separate configurable English NER backend; current NER model is Natasha-oriented.

# Explainable Topic Comparison Report

## Implemented

- Added deterministic comparison logic in `analytics_api.topic_comparison`.
- Added on-demand endpoint:
  - `GET /analytics/clusters/{clusterId}/compare/{otherClusterId}`
  - query params: `from`, `to`, `refresh=1`
- Added cache storage migration:
  - `migrations/011_topic_comparison_cache.sql`
- Added Prometheus metrics for comparison runs, latency, and cache hits/misses.
- Added unit tests for classifications and edge cases.
- Added skipped-by-default Postgres integration test guarded by `TEST_DATABASE_DSN`.

## Comparison Signals

- Embedding/centroid similarity: contract-ready, currently unavailable in `analytics_api` until embeddings or centroids are materialized in Postgres.
- Entity overlap: weighted Jaccard over normalized entities and mention counts.
- Channel overlap: weighted Jaccard over channel message counts.
- Time overlap: activity-window overlap coefficient plus proximity fallback.
- Representative message overlap: shared `event_id`, `normalized_text_hash`, or URL fingerprint among representative messages.
- Sentiment similarity: signed sentiment distance.

## Interpretation

- `same_topic`: strong overall similarity and evidence that the two clusters describe one event/story.
- `related_topics`: clusters share meaningful context but not enough evidence to call them identical.
- `different_topics`: weak overlap across deterministic signals.
- `possible_subtopic_split`: shared entities with divergence in channels, sentiment, or timing.

This layer is read-only analytics. It does not alter cluster assignments and does not perform merge decisions.

## UI Connection

The UI can call the compare endpoint from a topic detail page and render:

- top-level classification and similarity score;
- weighted feature breakdown;
- shared entities/channels;
- time-overlap summary;
- sentiment delta;
- positive, negative, and subtopic split explanation bullets.

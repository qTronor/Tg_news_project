# Explainable Topic Comparison

## Purpose

Topic comparison is a deterministic analytics layer over existing clusters. It does not use LLMs, does not change `cluster_assignments`, and never merges clusters. It answers whether two `public_cluster_id` values look like the same topic, related topics, unrelated topics, or a possible subtopic split.

## API

```http
GET /analytics/clusters/{clusterId}/compare/{otherClusterId}?from=2026-04-22T00:00:00Z&to=2026-04-22T23:59:59Z
```

Optional:

- `refresh=1`: bypass TTL cache and recompute.

Example:

```http
GET /analytics/clusters/run_abc%3A0/compare/run_abc%3A3?from=2026-04-22T00:00:00Z&to=2026-04-23T00:00:00Z
```

## Response Schema

```json
{
  "cluster_a_id": "run_abc:0",
  "cluster_b_id": "run_abc:3",
  "algorithm_version": "topic-comparison-v1",
  "similarity_score": 0.67,
  "classification": "possible_subtopic_split",
  "is_same_topic": false,
  "breakdown": {
    "entities": {"score": 0.52, "weight": 0.3846, "contribution": 0.2},
    "channels": {"score": 0.18, "weight": 0.1846, "contribution": 0.0332},
    "time": {"score": 1.0, "weight": 0.2, "contribution": 0.2},
    "messages": {"score": 0.0, "weight": 0.1538, "contribution": 0.0},
    "sentiment": {"score": 0.78, "weight": 0.0769, "contribution": 0.06}
  },
  "evidence": {
    "entities": {"score": 0.52, "shared": [], "a_count": 12, "b_count": 9},
    "channels": {"score": 0.18, "shared": [], "a_count": 4, "b_count": 5},
    "time": {"score": 1.0, "overlap_coefficient": 1.0, "overlap_seconds": 7200, "gap_seconds": 0},
    "messages": {"score": 0.0, "shared_event_ids": [], "shared_fingerprints": []},
    "sentiment": {"score": 0.78, "delta": 0.44, "a_avg_signed": 0.2, "b_avg_signed": -0.24},
    "embedding": {"score": null, "available": false}
  },
  "explanation": {
    "summary": "possible_subtopic_split with similarity 0.67.",
    "positive_factors": [],
    "negative_factors": [],
    "subtopic_split_signals": []
  },
  "window": {"from": "2026-04-22T00:00:00Z", "to": "2026-04-23T00:00:00Z"},
  "cached": false
}
```

## Features

- Embedding centroid similarity: supported by the comparison engine, but currently `null` in `analytics_api` because embeddings are stored in the topic clusterer's local SQLite store, not in Postgres. When centroids are materialized in Postgres, this component can be enabled without changing the response contract.
- Entity overlap: weighted Jaccard over normalized NER keys and mention counts.
- Channel overlap: weighted Jaccard over channel message counts.
- Time overlap: overlap coefficient for activity windows, with a small proximity score for close non-overlapping windows.
- Representative message overlap: exact shared `event_id`, `normalized_text_hash`, and `primary_url_fingerprint` intersections among top representative messages.
- Sentiment similarity: `1 - abs(avg_signed_a - avg_signed_b) / 2` for signed sentiment in `[-1, 1]`.

If a component is unavailable, its weight is redistributed across available components. This keeps the score deterministic while making missing evidence explicit in `evidence.embedding.available`.

## Classification

- `same_topic`: high overall score, strong semantic evidence, and overlapping activity windows.
- `related_topics`: moderate score or meaningful entity/time overlap.
- `different_topics`: weak overlap across the explainable signals.
- `possible_subtopic_split`: shared actors/entities with diverging channel coverage, sentiment, or timing.

The output is an analytical recommendation, not cluster merge logic.

## Storage

Migration: `migrations/011_topic_comparison_cache.sql`.

Table:

- `topic_comparison_cache`: TTL cache keyed by ordered cluster pair, window, and algorithm version.

Config:

- `api.topic_comparison_cache_ttl_seconds`, default `900`.

## UI Integration

Suggested UI pattern:

- Add "Compare" action on a topic detail page.
- Let the user pick a second topic from related topics or search.
- Show the classification and `similarity_score` as the header.
- Render the `breakdown` as weighted bars.
- Render `evidence.entities.shared`, `evidence.channels.shared`, time overlap, and sentiment delta in separate tabs.
- Display `explanation.positive_factors`, `negative_factors`, and `subtopic_split_signals` as audit-friendly bullets.

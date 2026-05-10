# Topic novelty detection

## Purpose

Novelty is no longer equal to "HDBSCAN produced a new cluster". The system now scores each persisted topic against historical topic snapshots using semantic, entity, source, keyword, temporal and sentiment signals.

## Storage

Migration `020_topic_novelty_detection.sql` adds:

- `topic_history`: one feature snapshot per `public_cluster_id`;
- `topic_novelty_scores`: versioned novelty score, status, features and explanation;
- `topic_lifecycle_events`: lifecycle labels (`new`, `continuation`, `merged`, `split`, `uncertain`, `noise`);
- `topic_similarity_links`: evidence links from a current topic to similar historical topics.

The latest novelty row is exposed through `topic_novelty_scores_latest`.

## Formula

Implementation: `topic_clusterer/topic_clusterer/novelty.py`.

Final score is a weighted sum in `[0, 1]`:

```text
novelty_score =
  0.28 * semantic_dissimilarity +
  0.18 * entity_dissimilarity +
  0.12 * channel_dissimilarity +
  0.12 * keyword_dissimilarity +
  0.14 * temporal_burst +
  0.08 * sentiment_shift +
  0.08 * new_entity_ratio
```

Feature definitions:

- `semantic_dissimilarity`: `1 - cosine(current_centroid, nearest_historical_centroid)`;
- `entity_dissimilarity`: `1 - weighted_jaccard(current_entities, historical_entities)`;
- `channel_dissimilarity`: `1 - weighted_jaccard(current_channels, historical_channels)`;
- `keyword_dissimilarity`: `1 - jaccard(current_keywords, historical_keywords)`;
- `temporal_burst`: current message/hour rate versus median historical rate;
- `sentiment_shift`: absolute signed sentiment delta normalized to `[0, 1]`;
- `new_entity_ratio`: share of current entities absent from all historical topic snapshots.

## Status Rules

- `new`: high novelty score and low similarity to the closest historical topic;
- `continuation`: high similarity to a previous topic and low novelty score;
- `merged`: current topic is moderately similar to multiple historical topics;
- `split`: semantic/source similarity exists, but entity overlap is low;
- `uncertain`: signals are weak or mixed, or sample size is too small;
- `noise`: reserved for low-confidence cluster outputs.

## Integration

`topic_clusterer` scores novelty after writing `cluster_assignments` and `topic_cluster_metadata`. For each `new` topic it publishes a Kafka event to `topic.novelty.candidates`.

API endpoints:

- `GET /analytics/topics/novel`;
- `GET /analytics/topics/{id}/novelty`;
- `GET /analytics/topics/{id}/similar-history`.

The topic detail payload also includes `novelty`, `novelty_score`, `novelty_status` and `similar_history`.

## Evaluation

The formula is deterministic and can be evaluated against annotation datasets by comparing `topic_novelty_scores_latest.novelty_status` or thresholded `novelty_score` against manual `is_new_storyline` labels. Unit tests cover synthetic new topics, continuations, split-like cases and single-message false positives.

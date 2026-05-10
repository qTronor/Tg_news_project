# Topic Importance Scoring

## Overview

The topic importance scoring layer computes a numeric `importance_score ∈ [0, 1]`
and a human-readable `importance_level` (`low | medium | high | critical`) for every
topic cluster produced by the clustering pipeline.

Scores are:
- **Deterministic** — same inputs always produce the same output.
- **Explainable** — every score includes a full breakdown by component.
- **Non-LLM** — all arithmetic is pure statistics over existing signals.
- **Configurable** — weights and thresholds live in `config.yaml`.

---

## Architecture

```
cluster_assignments  ──┐
raw_messages         ──┤
sentiment_results    ──┤──► feature extraction ──► normalization ──► weighted sum ──► topic_scores
ner_results          ──┤                                                              (PostgreSQL)
graph_subgraph_metrics─┘
```

The `topic_scorer` service is standalone (separate Docker container).
It reads from existing tables and writes to `topic_scores`.
It never modifies clustering logic.

---

## Features

| Feature | Formula | Source |
|---|---|---|
| `growth_rate` | `(recent_count - prev_count) / (prev_count + ε)`, clipped to `[-1, 5]` | cluster_assignments + raw_messages |
| `message_count` | `log1p(count)` | cluster_assignments |
| `unique_channels` | `log1p(count_distinct)` | raw_messages |
| `new_channel_ratio` | `new_channels / total_channels` | raw_messages vs history |
| `unique_entities` | `log1p(count_distinct)` | ner_results |
| `novelty` | `novel_entity_count / total_entity_count` | ner_results vs history |
| `sentiment_intensity` | `max(|avg_sentiment|, negative_share)` | sentiment_results |
| `sentiment_shift` | `|recent_avg_sentiment - prev_avg_sentiment|` | sentiment_results |
| `cluster_density` | `graph_subgraph_metrics.metrics_json->>'density'` (fallback: 0.3) | graph cache |

### Sub-window split

"Recent" = second half of the cluster's time window; "prev" = first half.
`growth_split_fraction: 0.5` in config (adjustable).

### Normalization

Each raw feature is **min-max normalized per run**:

```
norm = (raw - run_min) / (run_max - run_min)
```

If all clusters in a run have identical values for a feature (span ≈ 0),
the normalized value is set to **0.5** (neutral), preventing division by zero.

---

## Scoring Formula

```
weighted_sum = Σ (norm_i × weight_i)
final_score  = weighted_sum × penalty_factor
```

### Default weights (sum = 1.0)

| Component | Weight |
|---|---|
| growth_rate | 0.22 |
| unique_channels | 0.14 |
| message_count | 0.12 |
| novelty | 0.10 |
| unique_entities | 0.10 |
| sentiment_intensity | 0.10 |
| new_channel_ratio | 0.08 |
| cluster_density | 0.08 |
| sentiment_shift | 0.06 |

### Small-cluster penalty

If `message_count < min_messages_for_full_score` (default: 3),
`final_score` is multiplied by `small_cluster_penalty` (default: 0.5).

This prevents noise clusters from scoring high based on growth rate alone.

### Importance levels

| Level | Score range |
|---|---|
| low | [0.00, 0.35) |
| medium | [0.35, 0.65) |
| high | [0.65, 0.85) |
| critical | [0.85, 1.00] |

All thresholds are configurable in `scoring.level_thresholds`.

---

## Score Breakdown JSON

Every scored topic stores a `score_breakdown_json` with full explainability:

```json
{
  "components": {
    "growth_rate": {
      "raw": 2.3,
      "normalized": 0.87,
      "weight": 0.22,
      "contribution": 0.1914
    },
    ...
  },
  "penalties": ["small_cluster: message_count=1 < threshold=3"],
  "penalty_factor": 0.5,
  "raw_weighted_sum": 0.712,
  "final_score": 0.356,
  "level": "medium"
}
```

The `features_json` column stores the raw computed values for debugging.

---

## Storage

```sql
-- Latest score per cluster (use this in queries)
SELECT * FROM topic_scores_latest WHERE run_id = '...';

-- Full history
SELECT * FROM topic_scores WHERE public_cluster_id = '...' ORDER BY calculated_at DESC;
```

Table: `topic_scores` — see migration `009_topic_importance_scoring.sql`.
Audit table: `topic_scoring_runs`.

---

## Service Modes

```bash
# Score all clusters in the latest run, then exit
python main.py batch

# Score a specific run
python main.py batch --run-id <run_id>

# Score a single cluster on demand
python main.py oneshot --run-id <run_id> --cluster-id <public_cluster_id>

# Periodic re-scoring (default Docker mode)
python main.py scheduled
```

---

## Configuration

Copy `config.example.yaml` to `config.yaml` and adjust.

Override via environment: `TOPIC_SCORER__SCORING__WEIGHTS__GROWTH_RATE=0.30`

To change the formula version after a weight update:
```yaml
scoring:
  version: "v2"
```
All new rows will carry `scoring_version=v2`, old rows are preserved.

---

## Observability

Prometheus metrics (port 8005 by default):

| Metric | Type | Description |
|---|---|---|
| `topic_scorer_scoring_duration_seconds` | Histogram | Duration per batch run |
| `topic_scorer_scored_topics_total` | Counter | Topics scored, by level |
| `topic_scorer_errors_total` | Counter | Errors by stage (features/scoring/persist) |
| `topic_scorer_last_run_timestamp_seconds` | Gauge | Unix ts of last successful run |
| `topic_scorer_features_duration_seconds` | Histogram | Per-cluster feature extraction time |

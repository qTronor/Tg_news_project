# Topic Timeline / Evolution Layer

## Purpose

The evolution layer is a deterministic analytics layer over existing topic clusters. It does not recluster messages and does not use LLMs. It materializes how a `public_cluster_id` develops over time so UI/API consumers can render topic growth, spread, actor changes, sentiment changes, and decline.

## Storage

Migration: `migrations/010_topic_timeline_evolution.sql`.

Tables:

- `topic_timeline_points`: one row per `(public_cluster_id, bucket_size, bucket_start)`.
- `topic_evolution_events`: explainable events detected from timeline points.
- `topic_timeline_rebuild_runs`: audit log for batch or on-demand rebuilds.

Supported bucket sizes:

- `15m`
- `1h`
- `1d`

## Timeline Point Contract

Each timeline point contains:

- `bucket_start`, `bucket_end`
- `message_count`
- `unique_channel_count`
- `top_entities`: top 10 entities by mentions inside the bucket
- `sentiment`: `positive`, `neutral`, `negative`, `avg_signed`
- `new_channels`: channels that first appeared in this topic in the bucket
- `event_ids`: message ids backing the bucket
- `calculated_at`

## Evolution Events

Detected event types:

- `topic_created`: first non-empty bucket for the topic.
- `growth_spike`: current bucket volume is at least 2x recent baseline and at least 3 messages.
- `new_channel_joined`: one or more channels first appear after topic creation.
- `new_actor_detected`: new `PERSON`/`ORG` entity appears in top bucket entities.
- `sentiment_shift`: signed sentiment changes by at least `0.35` between adjacent buckets.
- `decline_started`: message volume drops materially after a topic has reached at least 3 messages in a bucket.

Each event includes `event_time`, `bucket_start`, `severity`, `summary`, and `details` with evidence for UI tooltips.

## API

Timeline with points and events:

```http
GET /analytics/clusters/{clusterId}/timeline?bucket=1h&from=2026-04-21T00:00:00Z&to=2026-04-22T00:00:00Z
```

Events only:

```http
GET /analytics/clusters/{clusterId}/evolution-events?bucket=1h&from=2026-04-21T00:00:00Z&to=2026-04-22T00:00:00Z
```

On-demand rebuild for old data:

```http
GET /analytics/clusters/{clusterId}/timeline?bucket=15m&refresh=1
```

Batch rebuild:

```bash
python scripts/rebuild_topic_timeline.py --cluster-id "run_x:0" --bucket 1h --from 2026-04-01T00:00:00Z --to 2026-04-22T00:00:00Z
```

Without `--cluster-id`, the script rebuilds all non-noise clusters from the latest clustering run.

## Observability

Metrics:

- `analytics_api_topic_timeline_rebuilds_total{status,bucket_size}`
- `analytics_api_topic_timeline_rebuild_duration_seconds{bucket_size}`

Logs include `cluster_id`, `bucket`, number of points, and number of events for each rebuild.

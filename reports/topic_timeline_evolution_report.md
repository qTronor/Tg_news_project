# Topic Timeline / Evolution Report

## Implemented Data

For every `public_cluster_id`, the backend can materialize timeline points with configurable `15m`, `1h`, or `1d` buckets. Each point stores message volume, unique channels, top entities, sentiment summary, newly joined channels, and backing `event_ids`.

The layer reads existing `cluster_assignments`, `raw_messages`, `sentiment_results`, and `ner_results`. It does not change topic clustering and does not call LLMs.

## Detected Events

- `topic_created`
- `growth_spike`
- `new_channel_joined`
- `new_actor_detected`
- `sentiment_shift`
- `decline_started`

Events are derived from materialized bucket data and include evidence in `details_json` for UI rendering and auditability.

## API/UI Integration

Use:

- `GET /analytics/clusters/{clusterId}/timeline?bucket=1h`
- `GET /analytics/clusters/{clusterId}/evolution-events?bucket=1h`

For stale or historical data, pass `refresh=1` or run:

```bash
python scripts/rebuild_topic_timeline.py --bucket 1h
```

Recommended UI mapping:

- line/area chart: `points[].message_count`
- channel spread markers: `points[].new_channels`
- entity chips per bucket: `points[].top_entities`
- sentiment band: `points[].sentiment.avg_signed`
- annotated chart markers: `events[]`

## Files

- `migrations/010_topic_timeline_evolution.sql`
- `analytics_api/analytics_api/topic_evolution.py`
- `analytics_api/analytics_api/service.py`
- `scripts/rebuild_topic_timeline.py`
- `tests/unit/test_topic_evolution.py`
- `tests/integration/test_topic_evolution_pg.py`
- `docs/topic_timeline_evolution.md`

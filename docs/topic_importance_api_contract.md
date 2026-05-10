# API Contract: Topic Importance Scoring

## New fields in existing endpoints

### `GET /analytics/overview/clusters`

**New query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `sort_by` | `messages \| importance \| recency` | `messages` | Sort order |
| `min_importance` | float [0, 1] | — | Filter clusters below threshold |
| `importance_level` | comma-separated `low,medium,high,critical` | — | Filter by level |

**New response fields per cluster:**

```json
{
  "cluster_id": "run-abc:0",
  "label": "Банк России повысил ставку",
  "message_count": 42,
  "importance_score": 0.7812,
  "importance_level": "high",
  "score_calculated_at": "2026-04-22T14:00:00Z",
  ...
}
```

`importance_score` and `importance_level` are `null` if the topic scorer
has not run yet for this cluster run.

### `GET /analytics/clusters/{clusterId}`

**New response fields:**

```json
{
  "cluster_id": "run-abc:0",
  "importance_score": 0.7812,
  "importance_level": "high",
  "score_calculated_at": "2026-04-22T14:00:00Z",
  "score_breakdown": {
    "components": {
      "growth_rate": {"raw": 2.1, "normalized": 0.85, "weight": 0.22, "contribution": 0.187},
      "unique_channels": {"raw": 2.77, "normalized": 0.9, "weight": 0.14, "contribution": 0.126},
      ...
    },
    "penalties": [],
    "penalty_factor": 1.0,
    "raw_weighted_sum": 0.7812,
    "final_score": 0.7812,
    "level": "high"
  },
  ...
}
```

`score_breakdown` is included only in the detail endpoint (not in the list).
For the list, use `importance_score` + `importance_level`.

---

## Frontend usage examples

### Sort topics by importance
```
GET /analytics/overview/clusters?sort_by=importance&from=...&to=...
```

### Show only high/critical topics
```
GET /analytics/overview/clusters?importance_level=high,critical
```

### Filter to significance threshold
```
GET /analytics/overview/clusters?min_importance=0.6
```

### "Why is this topic important?" panel
```
GET /analytics/clusters/{clusterId}
→ use response.score_breakdown.components to render a bar chart of contributions
```

---

## Score breakdown UI interpretation

Each `components[name]` entry shows:
- `raw` — the raw computed value (e.g. growth_rate = 2.1 means +110% growth)
- `normalized` — relative rank within this scoring run (0 = lowest, 1 = highest)
- `weight` — formula weight for this factor
- `contribution` — normalized × weight = this component's share of the final score

`penalties` lists any penalties applied (e.g. small cluster).
`penalty_factor < 1.0` means the final score was reduced by a penalty.

---

## Backward compatibility

All new fields (`importance_score`, `importance_level`, `score_breakdown`,
`score_calculated_at`) are nullable/optional in the response.
Existing consumers that don't read these fields are unaffected.

# Topic / Cluster Analytics Page

## What Was Found

- Route: `frontend/src/app/topics/[clusterId]/page.tsx`.
- Data hook: `useTopicDetail(clusterId)` in `frontend/src/lib/use-data.ts`.
- API endpoint: `GET /analytics/clusters/{cluster_id}` in `frontend/src/lib/api.ts`.
- DTOs: `Topic`, `TopicDetail`, `FirstSourcePayload` in `frontend/src/types/index.ts`.
- Demo data: `mockTopicDetail()` in `frontend/src/lib/mock-data.ts`.
- Existing sections: title/status, message count, channel count, average sentiment, volume chart, channel distribution, entities, sentiment, related topics, source panel, representative messages.

## New Page Structure

1. Header / Overview
   - Topic label, derived status, `NEW` badge and source status.
   - Short summary line from `summary`, with a fallback generated from existing counts.
   - First source preview with first seen timestamp and source confidence.

2. KPI Metrics
   - Dedicated top-row metric grid for messages, channels, average sentiment, importance, novelty, growth, communities, density, bridge nodes and source confidence.
   - Existing backend fields render immediately.
   - Missing optional fields render as `Pending` instead of breaking the layout.

3. Dynamics
   - Message volume chart.
   - Timeline annotations area prepared for future key events.

4. Structure
   - High-frequency entities, explicitly labelled as frequency rather than centrality.
   - Channel distribution.
   - Sentiment mix.
   - Related topics with affinity bars instead of raw `sim: n` text.

5. Graph Analytics
   - Dedicated network metrics section for nodes, edges, communities, bridge nodes, density, top central entity, top central channel and graph summary.
   - If graph metrics are not returned, the section shows a reserved empty state.

6. Source / Provenance
   - Source panel is promoted into an analytic section.
   - Labels now emphasize first source, first seen, confidence and propagation.

## Backend / API Fields Needed

Extend `GET /analytics/clusters/{cluster_id}` response with these optional fields:

```ts
summary?: string | null;
status?: "new" | "growing" | "declining" | "stable" | "exact" | "probable" | "unknown" | null;
kpi_metrics?: {
  importance_score?: number | null;
  novelty_score?: number | null;
  growth_rate?: number | null;
} | null;
timeline_annotations?: {
  time: string;
  label: string;
  description?: string | null;
}[];
graph_analytics?: {
  node_count?: number | null;
  edge_count?: number | null;
  communities_count?: number | null;
  bridge_nodes_count?: number | null;
  density?: number | null;
  top_central_entity?: Entity | null;
  top_central_channel?: ChannelStat | null;
  summary?: string | null;
} | null;
source_provenance?: {
  first_seen?: string | null;
  first_source_channel?: string | null;
  source_confidence?: number | null;
  propagation_count?: number | null;
} | null;
```

## Future-Ready Blocks

- KPI layout is ready for importance, novelty, growth and graph-derived metrics.
- Dynamics is ready for timeline annotations and key events.
- Graph Analytics is ready for backend-computed graph summaries without another layout change.
- Source / Provenance can consume either the existing `first_source` payload or the lighter `source_provenance` summary.

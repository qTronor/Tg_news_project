# Topic / Cluster UI Changelog

## 2026-04-21

- Rebuilt `frontend/src/app/topics/[clusterId]/page.tsx` around an analytics-first hierarchy.
- Added a dedicated KPI grid at the top of the topic detail page.
- Added graceful pending states for optional future metrics.
- Added explicit sections for Overview, KPI Metrics, Dynamics, Structure, Graph Analytics, Source / Provenance and Representative Messages.
- Renamed entity section from a centrality-like label to `High-frequency entities` because current data is mention frequency, not graph centrality.
- Improved related topics by replacing raw similarity text with affinity bars.
- Promoted source/provenance from a lower utility card into an analytic section.
- Extended `TopicDetail` with optional future DTO fields for KPI metrics, graph analytics, timeline annotations, summary and source provenance.
- Updated demo topic detail data so demo mode exercises the new layout and partial graph-metrics state.

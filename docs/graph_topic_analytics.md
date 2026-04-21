# Local Topic Graph Analytics

## Scope

The graph analytics layer computes explainable metrics for a local topic subgraph. It does not run LLM-based analysis and does not recompute the global Neo4j graph. The current implementation builds a topic-local graph from PostgreSQL source-of-truth tables used by the Analytics API:

- `cluster_assignments` selects messages in a topic.
- `raw_messages` provides channels and timestamps.
- `ner_results` provides entities.

Neo4j write logic and constraints remain unchanged. The local graph is a derived analytical view.

## Local Graph Model

For one `public_cluster_id`, the API creates:

- channel nodes: `ch-{channel}`
- entity nodes: `ent-{ENTITY_TYPE}:{normalized_entity}`
- `mentions` edges between a channel and an entity when the channel published a topic message mentioning that entity
- `co_occurs` edges between entities mentioned in the same message

Edge weights are mention/co-occurrence counts inside the selected time window.

## Metrics

`GET /analytics/clusters/{clusterId}/graph-metrics`

Query params:

- `from`, `to`: ISO timestamps. Defaults to the Analytics API window.
- `refresh=true`: bypass cache and recompute.

Response fields:

- `summary.node_count`, `summary.edge_count`
- `summary.density`: local undirected graph density
- `summary.average_degree`
- `summary.component_count`, `summary.largest_component_size`
- `summary.community_count`
- `summary.is_small_graph`: true when results should be interpreted cautiously
- `top_entities`: entity nodes ranked by PageRank, with degree and betweenness
- `top_channels`: channel nodes ranked by PageRank
- `bridge_nodes`: nodes with high betweenness, articulation behavior, or connections across communities
- `communities`: deterministic label-propagation communities with top nodes
- `graph.nodes`, `graph.edges`: UI-ready local graph

## Algorithms

- Degree centrality: normalized number of distinct neighbors.
- Betweenness centrality: Brandes shortest-path centrality on the local unweighted graph.
- PageRank: weighted undirected PageRank over local edges.
- Communities: deterministic weighted label propagation.
- Bridge detection: combines betweenness, articulation points, and cross-community adjacency.

These metrics are intentionally explainable and suitable for a diploma description: each score is computed directly from observable channels, entities, and message co-occurrence.

## Cache Tables

Migration `006_graph_topic_analytics.sql` adds:

- `graph_subgraph_metrics`: full JSON payload for a topic/time-window cache key
- `graph_top_nodes`: ranked node metrics for querying/debugging
- `graph_topic_communities`: community summaries

The cache key is based on algorithm version, cluster id, and time window. Default TTL is `api.graph_metrics_cache_ttl_seconds` (900 seconds).

## UI/API Usage

Use the endpoint on topic detail pages to add:

- key entities by graph importance, not only raw mentions
- central channels driving a topic
- bridge nodes that connect subplots
- community panels for subplots inside a topic
- summary badges for density, connectedness, and community count

For tiny graphs, show the metrics but label them as low-evidence using `summary.is_small_graph`.

## Observability

Prometheus metrics:

- `analytics_api_graph_analytics_runs_total{status}`
- `analytics_api_graph_analytics_cache_total{result}`
- `analytics_api_graph_analytics_duration_seconds`

Errors are logged with `cluster_id`.

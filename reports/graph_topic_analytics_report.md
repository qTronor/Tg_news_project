# Graph Topic Analytics Report

## Added Metrics

- Degree centrality: who has the most direct local connections inside a topic.
- Betweenness centrality: which nodes sit on shortest paths between different parts of the story.
- Weighted PageRank: which entities/channels are structurally important, not just frequently mentioned.
- Density and average degree: how tightly connected the topic graph is.
- Component stats: whether the topic is one connected story or several disconnected fragments.
- Communities: deterministic local label-propagation groups.
- Bridge nodes: entities/channels that connect communities or act as articulation points.

## Interpretation

- High PageRank entity: a core actor/object in the topic.
- High PageRank channel: a channel structurally central to the topic coverage.
- High betweenness or `is_bridge=true`: a node linking subplots, useful for explaining narrative transitions.
- High density: entities/channels are tightly co-mentioned; the topic is coherent.
- Many components or low density: the cluster may contain loosely related subplots.
- `is_small_graph=true`: show results as low-evidence analytics because there are too few nodes/edges.

## API/UI Connection

Endpoint:

`GET /analytics/clusters/{clusterId}/graph-metrics?from=...&to=...`

Use:

- `top_entities` for "central entities" panels.
- `top_channels` for "central channels" panels.
- `bridge_nodes` for "bridges between subplots".
- `communities` for community/subplot cards.
- `summary` for density, connectedness, component count, and warnings.
- `graph.nodes` / `graph.edges` for Cytoscape or another UI graph view.

Cache/storage:

- `graph_subgraph_metrics`
- `graph_top_nodes`
- `graph_topic_communities`

The implementation is local to a topic/time window and does not recompute the full global graph.

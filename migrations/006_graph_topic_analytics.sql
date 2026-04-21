-- Migration: 006_graph_topic_analytics
-- Description: Cache local topic subgraph analytics for UI/API
-- Date: 2026-04-21

CREATE TABLE IF NOT EXISTS graph_subgraph_metrics (
    cache_key VARCHAR(128) PRIMARY KEY,
    public_cluster_id VARCHAR(320) NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    algorithm_version VARCHAR(100) NOT NULL,
    node_count INTEGER NOT NULL DEFAULT 0,
    edge_count INTEGER NOT NULL DEFAULT 0,
    metrics_json JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_graph_subgraph_metrics_cluster
    ON graph_subgraph_metrics(public_cluster_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_graph_subgraph_metrics_expires
    ON graph_subgraph_metrics(expires_at);

CREATE TABLE IF NOT EXISTS graph_top_nodes (
    cache_key VARCHAR(128) NOT NULL REFERENCES graph_subgraph_metrics(cache_key) ON DELETE CASCADE,
    node_id VARCHAR(640) NOT NULL,
    node_label TEXT NOT NULL,
    node_type VARCHAR(80) NOT NULL,
    community_id INTEGER,
    degree_centrality REAL NOT NULL DEFAULT 0,
    betweenness_centrality REAL NOT NULL DEFAULT 0,
    pagerank REAL NOT NULL DEFAULT 0,
    bridge_score REAL NOT NULL DEFAULT 0,
    is_bridge BOOLEAN NOT NULL DEFAULT FALSE,
    rank INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (cache_key, node_id)
);

CREATE INDEX IF NOT EXISTS idx_graph_top_nodes_cache_rank
    ON graph_top_nodes(cache_key, rank);
CREATE INDEX IF NOT EXISTS idx_graph_top_nodes_type_rank
    ON graph_top_nodes(cache_key, node_type, rank);

CREATE TABLE IF NOT EXISTS graph_topic_communities (
    cache_key VARCHAR(128) NOT NULL REFERENCES graph_subgraph_metrics(cache_key) ON DELETE CASCADE,
    community_id INTEGER NOT NULL,
    node_count INTEGER NOT NULL DEFAULT 0,
    edge_count INTEGER NOT NULL DEFAULT 0,
    entity_count INTEGER NOT NULL DEFAULT 0,
    channel_count INTEGER NOT NULL DEFAULT 0,
    summary_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (cache_key, community_id)
);

DO $$
BEGIN
    RAISE NOTICE 'Migration 006_graph_topic_analytics completed successfully';
END $$;

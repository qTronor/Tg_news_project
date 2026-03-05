from prometheus_client import Counter, Gauge, Histogram

MESSAGES_CONSUMED = Counter(
    "topic_clusterer_messages_consumed_total",
    "Total messages consumed from Kafka",
)
MESSAGES_PROCESSED = Counter(
    "topic_clusterer_messages_processed_total",
    "Total messages processed (embeddings computed)",
    ["status"],
)
MESSAGES_DLQ = Counter(
    "topic_clusterer_messages_dlq_total",
    "Total messages sent to DLQ",
)
PROCESSING_LATENCY = Histogram(
    "topic_clusterer_processing_latency_seconds",
    "Message processing latency in seconds",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
CLUSTERING_RUNS = Counter(
    "topic_clusterer_clustering_runs_total",
    "Total clustering runs executed",
    ["status"],
)
CLUSTERING_DURATION = Histogram(
    "topic_clusterer_clustering_duration_seconds",
    "Clustering run duration in seconds",
    buckets=(1, 5, 10, 30, 60, 120, 300),
)
BUFFER_SIZE = Gauge(
    "topic_clusterer_buffer_size",
    "Number of messages pending clustering in DuckDB",
)
CLUSTERS_FOUND = Gauge(
    "topic_clusterer_clusters_found",
    "Number of clusters found in last run",
)

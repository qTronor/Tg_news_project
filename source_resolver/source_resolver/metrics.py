from prometheus_client import Counter, Gauge, Histogram

SOURCE_RESOLUTION_TOTAL = Counter(
    "source_resolver_resolutions_total",
    "Total message and cluster source resolutions by kind/type",
    ["target", "resolution_kind", "source_type"],
)
SOURCE_CONFIDENCE = Histogram(
    "source_resolver_confidence",
    "Distribution of source resolution confidence",
    buckets=(0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0),
)
SOURCE_RESOLUTION_LATENCY = Histogram(
    "source_resolver_resolution_latency_seconds",
    "Time spent resolving one cluster",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
PROPAGATION_EDGES_COUNT = Gauge(
    "source_resolver_propagation_edges_count",
    "Total number of materialized propagation edges",
)

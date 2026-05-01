from prometheus_client import Counter, Histogram


API_REQUESTS_TOTAL = Counter(
    "analytics_api_requests_total",
    "Total analytics API requests",
    ["method", "route", "status"],
)
API_REQUEST_LATENCY = Histogram(
    "analytics_api_request_latency_seconds",
    "Analytics API request latency in seconds",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

GRAPH_ANALYTICS_RUNS_TOTAL = Counter(
    "analytics_api_graph_analytics_runs_total",
    "Total local graph analytics computations",
    ["status"],
)
GRAPH_ANALYTICS_CACHE_TOTAL = Counter(
    "analytics_api_graph_analytics_cache_total",
    "Total local graph analytics cache lookups",
    ["result"],
)
GRAPH_ANALYTICS_DURATION = Histogram(
    "analytics_api_graph_analytics_duration_seconds",
    "Local graph analytics computation latency in seconds",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

TOPIC_TIMELINE_REBUILDS_TOTAL = Counter(
    "analytics_api_topic_timeline_rebuilds_total",
    "Total topic timeline rebuilds",
    ["status", "bucket_size"],
)
TOPIC_TIMELINE_REBUILD_DURATION = Histogram(
    "analytics_api_topic_timeline_rebuild_duration_seconds",
    "Topic timeline rebuild latency in seconds",
    ["bucket_size"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

TOPIC_COMPARISON_CACHE_TOTAL = Counter(
    "analytics_api_topic_comparison_cache_total",
    "Total topic comparison cache lookups",
    ["result"],
)
TOPIC_COMPARISON_RUNS_TOTAL = Counter(
    "analytics_api_topic_comparison_runs_total",
    "Total topic comparison computations",
    ["status"],
)
TOPIC_COMPARISON_DURATION = Histogram(
    "analytics_api_topic_comparison_duration_seconds",
    "Topic comparison computation latency in seconds",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

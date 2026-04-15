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

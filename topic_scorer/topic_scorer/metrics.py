from prometheus_client import Counter, Gauge, Histogram

SCORING_DURATION = Histogram(
    "topic_scorer_scoring_duration_seconds",
    "Duration of a scoring batch run",
    ["mode"],
    buckets=(0.1, 0.5, 1, 5, 10, 30, 60, 120, 300),
)

SCORED_TOPICS_TOTAL = Counter(
    "topic_scorer_scored_topics_total",
    "Total topics scored",
    ["level"],
)

ERRORS_TOTAL = Counter(
    "topic_scorer_errors_total",
    "Total scoring errors",
    ["stage"],  # features | scoring | persist
)

LAST_RUN_TIMESTAMP = Gauge(
    "topic_scorer_last_run_timestamp_seconds",
    "Unix timestamp of the last completed scoring run",
)

FEATURES_DURATION = Histogram(
    "topic_scorer_features_duration_seconds",
    "Duration of feature extraction per cluster",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1),
)

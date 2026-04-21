from prometheus_client import Counter, Histogram

MESSAGES_CONSUMED = Counter(
    "preprocessor_messages_consumed_total",
    "Total messages consumed from Kafka",
)
MESSAGES_PROCESSED = Counter(
    "preprocessor_messages_processed_total",
    "Total messages processed",
    ["status"],
)
MESSAGES_DLQ = Counter(
    "preprocessor_messages_dlq_total",
    "Total messages sent to DLQ",
)
PROCESSING_LATENCY = Histogram(
    "preprocessor_processing_latency_seconds",
    "Message processing latency in seconds",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
LANGUAGE_DETECTION_LATENCY = Histogram(
    "preprocessor_language_detection_latency_seconds",
    "Language detection latency in seconds",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
)
MESSAGES_BY_LANGUAGE = Counter(
    "preprocessor_messages_by_language_total",
    "Messages processed by detected language and analysis mode",
    ["language", "analysis_mode", "supported_for_full_analysis"],
)

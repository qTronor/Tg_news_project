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

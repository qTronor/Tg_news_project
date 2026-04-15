from prometheus_client import Counter, Histogram

MESSAGES_CONSUMED = Counter(
    "ner_extractor_messages_consumed_total",
    "Total messages consumed from Kafka",
)
MESSAGES_PROCESSED = Counter(
    "ner_extractor_messages_processed_total",
    "Total messages processed",
    ["status"],
)
MESSAGES_DLQ = Counter(
    "ner_extractor_messages_dlq_total",
    "Total messages sent to DLQ",
)
PROCESSING_LATENCY = Histogram(
    "ner_extractor_processing_latency_seconds",
    "Message processing latency in seconds",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
ENTITIES_EXTRACTED = Counter(
    "ner_extractor_entities_extracted_total",
    "Total entities extracted",
    ["entity_type"],
)

from prometheus_client import Counter, Histogram

ENRICH_REQUESTS = Counter(
    "llm_enricher_requests_total",
    "Total enrichment requests",
    ["enrichment_type", "status"],
)

ENRICH_CACHE_HITS = Counter(
    "llm_enricher_cache_hits_total",
    "Total cache hits",
    ["enrichment_type"],
)

ENRICH_LATENCY = Histogram(
    "llm_enricher_latency_seconds",
    "End-to-end enrichment request latency",
    ["enrichment_type"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30, 60),
)

LLM_CALL_LATENCY = Histogram(
    "llm_enricher_llm_call_latency_seconds",
    "LLM provider call latency",
    ["provider"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
)

TOKENS_USED = Counter(
    "llm_enricher_tokens_total",
    "Total tokens consumed",
    ["provider", "direction"],  # direction: input | output
)

COST_USD = Counter(
    "llm_enricher_cost_usd_total",
    "Total LLM cost in USD",
    ["provider"],
)

BUDGET_EXHAUSTED = Counter(
    "llm_enricher_budget_exhausted_total",
    "Requests rejected due to daily budget exhaustion",
)

CIRCUIT_BREAKER_OPEN = Counter(
    "llm_enricher_circuit_breaker_open_total",
    "Times the circuit breaker tripped open",
    ["provider"],
)

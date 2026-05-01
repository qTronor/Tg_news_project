# LLM Enrichment — Cost Reference

## Mistral Pricing (as of 2026-04-22)

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|---|---|---|
| `mistral-large-latest` | $2.00 | $6.00 |
| `mistral-small-latest` | $0.20 | $0.60 |

Prices are configurable via env vars (defaults in `config.example.yaml`):
```
LLM_ENRICHER__BUDGET__PRICING_INPUT_PER_MTOK=2.0
LLM_ENRICHER__BUDGET__PRICING_OUTPUT_PER_MTOK=6.0
```

## Token Budget Per Enrichment Type

| Type | Input tokens (est.) | Output tokens (est.) | Cost per call (mistral-large) |
|---|---|---|---|
| `cluster_label` | ~1,500 | ~80 | ~$0.003 |
| `cluster_summary` | ~3,500 | ~400 | ~$0.010 |
| `cluster_explanation` | ~2,500 | ~500 | ~$0.008 |
| `novelty_explanation` | ~2,000 | ~250 | ~$0.006 |

*Input includes system prompt with schema + cluster context (representative messages, entities, etc.).*

## Daily Budget Cap

Default: **$5.00/day** (`LLM_ENRICHER__BUDGET__DAILY_USD=5.0`)

At $0.01/call average, that's ~500 calls/day. With caching (7d TTL), real daily spend is much lower unless data changes frequently.

**When the cap is hit:**
- `llm_enricher` returns `status=budget_exhausted` with HTTP 200
- No Mistral API call is made
- Result is **not cached** (to allow retry after midnight UTC)
- `analytics_api` propagates `budget_exhausted` to the UI
- Budget resets at midnight UTC (in-memory counter + DB warm-start)

## Cost Estimation Formula

```python
cost = (tokens_input / 1_000_000 * pricing_input_per_mtok
      + tokens_output / 1_000_000 * pricing_output_per_mtok)
```

Budget is pre-checked with estimated tokens before calling the provider, then adjusted with actual token counts after the call.

## Cost Control Recommendations

| Scenario | Recommendation |
|---|---|
| Development / CI | `LLM_ENRICHER__LLM__PROVIDER=mock` — zero cost |
| Staging | Use `mistral-small-latest`, lower daily cap ($0.50) |
| Production | `mistral-large-latest`, $5–$20/day depending on cluster count |
| High-frequency clusters | Rely on cache (7d TTL); most clusters don't change intra-day |

## Monitoring

Prometheus metrics exposed on `:8001`:
- `llm_enricher_cost_usd_total{provider}` — cumulative spend
- `llm_enricher_tokens_total{provider,direction}` — token consumption
- `llm_enricher_budget_exhausted_total` — cap hits per day
- `llm_enricher_cache_hits_total{enrichment_type}` — cache efficiency
- `llm_enricher_llm_call_latency_seconds{provider}` — p50/p95/p99 latency

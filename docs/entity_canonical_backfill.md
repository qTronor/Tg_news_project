# Entity Canonical Backfill

## Purpose

Populates `ner_results.entity_canonical_id` for rows created before migration 017.
The script reuses the online `CanonicalResolver` to guarantee consistency with new messages.

## Prerequisites

1. Migration 017 applied:
   ```
   docker exec telegram-news-postgres psql -U postgres -d telegram_news \
     -f migrations/017_entity_normalization.sql
   ```
2. Python dependencies installed:
   ```
   pip install -r ner_extractor/requirements.txt
   ```

## Usage

```bash
# Dry-run: print plan for first 100 rows
python scripts/backfill_entity_canonical.py --dry-run --limit 100

# Full backfill
python scripts/backfill_entity_canonical.py

# Limit to a date range
python scripts/backfill_entity_canonical.py --from-date 2025-01-01 --to-date 2025-12-31

# Custom batch size and DSN
python scripts/backfill_entity_canonical.py --batch-size 500 \
  --dsn "postgresql://postgres:postgres@localhost:5432/telegram_news"

# Resume after interruption
python scripts/backfill_entity_canonical.py --resume
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dsn` | env `NER_EXTRACTOR__POSTGRES__DSN` or localhost | PostgreSQL connection string |
| `--batch-size` | 1000 | Rows processed per transaction |
| `--limit` | unlimited | Stop after N rows (useful for staged rollouts) |
| `--from-date` | — | Only rows with `extracted_at >= date` |
| `--to-date` | — | Only rows with `extracted_at <= date` |
| `--dry-run` | off | Print what would happen without writing |
| `--resume` | off | Continue from last processed row id (`/tmp/backfill_resume.txt`) |

## Estimated time

On a typical Postgres instance with 1M `ner_results` rows:
- Pure SQL overhead: ~5–10 ms per batch of 1000
- Resolver latency: 2–10 ms per entity (mostly fuzzy DB round-trips)
- Rough estimate: **~2–5 hours** for 1M rows; use `--batch-size 2000` and parallel runs per entity_type to speed up

## Verification

```sql
-- Check progress
SELECT count(*) FILTER (WHERE entity_canonical_id IS NOT NULL) AS linked,
       count(*) AS total,
       round(100.0 * count(*) FILTER (WHERE entity_canonical_id IS NOT NULL) / count(*), 1) AS pct
FROM ner_results;

-- Spot-check: all Putin variants should share one canonical_id
SELECT entity_canonical_id, entity_text, count(*)
FROM ner_results
WHERE lower(COALESCE(normalized_text, entity_text)) LIKE '%путин%'
GROUP BY entity_canonical_id, entity_text
ORDER BY count(*) DESC;
```

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Event-driven microservices pipeline for collecting, processing, and analyzing news from Telegram channels. Raw messages flow through Kafka topics, getting enriched by ML services (sentiment, NER, topic clustering), stored in PostgreSQL + Neo4j, and surfaced via a Next.js frontend.

## Commands

### Infrastructure

```bash
# Start all infrastructure (Postgres, Neo4j, Kafka, Redis)
docker compose -f docker-compose.infrastructure.yml up -d

# Run migrations in order
docker exec telegram-news-postgres psql -U postgres -d telegram_news -f migrations/001_initial_schema.sql
# ... through migrations/012_*
```

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev          # Dev server on :3000
npm run build        # Production build
npm run lint         # ESLint
npm run test         # Jest unit tests
npm run test:e2e     # Playwright E2E
```

### Python Services

```bash
# Install service dependencies (example: sentiment_analyzer)
pip install -r sentiment_analyzer/requirements.txt

# Run a service directly
cd sentiment_analyzer && python -m sentiment_analyzer.service

# Run tests
pytest tests/unit/ -v                        # Unit tests (no DB required)
pytest tests/integration/ -v --tb=short      # Requires running infrastructure
pytest tests/unit/ -v -k "contract"          # Target specific tests
```

### Kafka Topic Creation

```bash
docker exec telegram-news-kafka kafka-topics --bootstrap-server kafka:9093 \
  --create --topic raw.telegram.messages --partitions 6 --replication-factor 1
```

### Observability UIs

- Kafka UI: http://localhost:8080
- Neo4j Browser: http://localhost:7474 (user: neo4j)
- Prometheus: http://localhost:9090 (profile: monitoring)
- Grafana: http://localhost:3001 (admin/admin, profile: monitoring)

## Architecture

### Data Flow (Kafka Pipeline)

```
Telegram → raw.telegram.messages
              ↓                    ↓
    message-persister        preprocessor
    (→ PostgreSQL)           (→ preprocessed.messages)
                                   ↓              ↓
                        sentiment-analyzer    ner-extractor
                        (→ sentiment.enriched) (→ ner.enriched)
                                   ↓              ↓
                              topic-clusterer  graph-builder
                              (→ PostgreSQL)   (→ Neo4j, graph.updates)
```

All topics have 6 partitions. Failed messages route to `dlq.*` topics after 3 retries with exponential backoff (1s→2s→4s).

### Services & Ports

| Service | Internal Port | Role |
|---|---|---|
| analytics-api | 8020/8021 | Read API for frontend |
| auth-service | 8030 | JWT auth, user management |
| message-persister | 8000/8001 | Kafka → PostgreSQL |
| sentiment-analyzer | 8012/8013 | PyTorch sentiment + emotion |
| ner-extractor | 8014/8015 | Natasha + Transformers NER |
| topic-clusterer | 8032/8033 | Unsupervised clustering + SQLite |
| llm-enricher | 8050/8051 | Mistral API wrapper (budget-limited) |
| source-resolver | 8040/8041 | First-source tracking |
| frontend | 3000 | Next.js UI |

### Databases

- **PostgreSQL** (`telegram_news` + `tg_news_auth`): messages, sentiment, NER, auth, materialized views for analytics
- **Neo4j**: graph of entities (PERSON, ORG, GPE, LOC, PRODUCT), channels, topics with MENTIONED_IN / CO_OCCURS_WITH relationships
- **Redis**: idempotency cache (512MB, allkeys-lru)

### Idempotency & Reliability

- `event_id` = `{channel}:{message_id}` — natural dedup key, stored in `processed_events` table (7-day retention)
- `trace_id` (UUID) threads through all stages for distributed tracing
- Transactional Outbox pattern in `outbox` table for reliable Kafka publishing
- At-least-once delivery; consumers must be idempotent

### Configuration Pattern

Each Python service uses a YAML config file (`config.yaml`) with a Pydantic `AppConfig` class that supports environment variable overrides. The `.env` file in the repo root provides secrets (`DB_PASSWORD`, `NEO4J_PASSWORD`, `AUTH_JWT_SECRET`, `TG_API_ID`, `TG_API_HASH`, `TG_STRING_SESSION`, `MISTRAL_API_KEY`).

### Multilingual Support

Preprocessed messages include `original_language`, `language_confidence`, `is_supported_for_full_analysis`, and `analysis_mode`. Russian/English get full analytics; other languages get partial clustering only.

### Schema Contracts

Kafka event schemas live in `schemas/` as JSON Schema files. Breaking changes require a new topic version (e.g., `raw.telegram.messages.v2`). `tests/unit/test_analysis_contracts.py` validates schemas.

### Migrations

SQL migrations are numbered `migrations/001_` through `migrations/012_` and must be applied in order. Each migration is idempotent (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).

### Metrics

All Python services expose Prometheus metrics on their secondary port (`+1`): `kafka_messages_processed_total`, `kafka_messages_failed_total`, `kafka_message_processing_duration_seconds`, `kafka_consumer_lag`.

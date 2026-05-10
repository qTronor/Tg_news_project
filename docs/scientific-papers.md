# Scientific Paper Analysis Pipeline

## Overview

This module detects and analyzes scientific papers shared in Telegram channels. When a message contains a link to arXiv, OpenReview, a DOI, or a PDF file, it is routed through a dedicated analysis pipeline that extracts metadata and generates a structured LLM summary.

The main Telegram news pipeline is not affected — scientific paper processing runs as a separate branch.

## Supported Source Types

| Type | Example | Detection |
|---|---|---|
| `arxiv` | `arxiv.org/abs/2401.xxxxx` | URL pattern |
| `openreview` | `openreview.net/forum?id=...` | URL pattern |
| `doi` | `doi.org/10....` | URL pattern |
| `pdf_url` | `example.com/paper.pdf` | URL ending |
| `telegram_file` | Telegram PDF attachment | Media metadata |
| `webpage` | Any message with scientific keywords | Keyword match |

## Kafka Topics

| Topic | Partitions | Retention | Description |
|---|---|---|---|
| `paper.detected` | 6 | 30 days | Detection events |
| `paper.parsed` | 6 | 30 days | Parsed metadata |
| `paper.summarized` | 6 | 30 days | LLM summaries |
| `dlq.paper` | 3 | 90 days | Failed events |

## PostgreSQL Tables

- `scientific_papers` — one row per detected paper (dedup by `source_url`)
- `scientific_paper_texts` — full text (stored separately, can be large)
- `scientific_paper_summaries` — structured LLM summaries

## Services

| Service | Port | Input | Output |
|---|---|---|---|
| `paper_detector` | 8060/8061 | `preprocessed.messages` | `paper.detected` |
| `paper_parser` | 8062/8063 | `paper.detected` | `paper.parsed` |
| `paper_summarizer` | 8064/8065 | `paper.parsed` | `paper.summarized` |

## Running the Services

```bash
# Apply migration
docker exec telegram-news-postgres psql -U postgres -d telegram_news -f migrations/022_scientific_papers.sql

# Create Kafka topics
bash scripts/create_kafka_topics.sh

# Start services
docker compose -f docker-compose.infrastructure.yml up paper-detector paper-parser paper-summarizer
```

## Environment Variables

| Variable | Service | Default |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | all | `localhost:9092` |
| `POSTGRES_DSN` | all | see config.yaml |
| `MISTRAL_API_KEY` | paper_summarizer | — (required) |
| `MISTRAL_MODEL` | paper_summarizer | `mistral-small-latest` |

## Verification

```bash
# Publish test message to preprocessed.messages (via Kafka UI or kafkacat)
# Message should contain URL: https://arxiv.org/abs/2401.00001

# Check detection
docker exec telegram-news-postgres psql -U postgres -d telegram_news \
  -c "SELECT id, title, parsing_status FROM scientific_papers ORDER BY created_at DESC LIMIT 5;"

# Check summary
docker exec telegram-news-postgres psql -U postgres -d telegram_news \
  -c "SELECT paper_id, short_summary FROM scientific_paper_summaries ORDER BY created_at DESC LIMIT 5;"

# Frontend
# http://localhost:3000/papers
# http://localhost:3000/papers/{id}
```

## LLM Summary Fields

The Mistral summary returns these fields (all text in Russian, technical terms in original language):

- `title`, `authors`
- `abstract_summary` — summary of the abstract
- `research_problem` — what problem is solved
- `main_contribution` — the key innovation
- `method` — technical approach
- `datasets` — datasets used
- `metrics` — evaluation metrics
- `experiments` — experimental setup
- `results` — key results
- `limitations` — stated limitations
- `keywords` — paper keywords
- `paper_type` — one of: research_paper, survey, benchmark, dataset_paper, method_paper
- `short_summary` — one-paragraph summary

## Future Work

- Neo4j integration: `(:Paper)` nodes linked to `(:Message)` and `(:Entity)`
- OpenReview full API parsing
- Telegram PDF file download via TDLib
- DOI resolution
- Grafana dashboard for paper pipeline

# Project Structure

```
Tg_news_project/
│
├── docs/                                    # Documentation
│   ├── contracts.md                         # 📋 MAIN: Data contracts specification
│   ├── engineering-standards.md             # Engineering standards
│   └── INFRASTRUCTURE.md                    # Infrastructure setup guide
│
├── schemas/                                 # JSON Schema definitions
│   ├── raw_message.schema.json             # Schema: Raw Telegram message
│   ├── persisted_message.schema.json       # Schema: Persistence confirmation
│   ├── preprocessed_message.schema.json    # Schema: Preprocessed text
│   ├── sentiment_enriched.schema.json      # Schema: Sentiment analysis
│   ├── ner_enriched.schema.json           # Schema: Named entities
│   ├── graph_update.schema.json           # Schema: Graph updates
│   └── README.md                           # Schema documentation
│
├── examples/                               # Example events
│   ├── raw_message.example.json
│   ├── persisted_message.example.json
│   ├── preprocessed_message.example.json
│   ├── sentiment_enriched.example.json
│   ├── ner_enriched.example.json
│   └── graph_update.example.json
│
├── migrations/                             # PostgreSQL migrations
│   └── 001_initial_schema.sql            # Initial database schema
│
├── neo4j/                                 # Neo4j initialization
│   └── init.cypher                       # Graph schema and constraints
│
├── kafka/                                 # Kafka configuration
│   └── topics.yml                        # Topic definitions
│
├── scripts/                               # Automation scripts
│   ├── create_kafka_topics.sh           # Create all Kafka topics
│   ├── apply_migrations.sh              # Apply PostgreSQL migrations
│   ├── init_neo4j.sh                    # Initialize Neo4j
│   └── validate_schemas.sh              # Validate JSON schemas
│
├── rbc_telegram_collector/               # Existing ingestion service
│   ├── collector/                        # Service code
│   ├── config.yaml                       # Configuration
│   ├── Dockerfile                        # Docker image
│   └── README.md                         # Service documentation
│
├── docker-compose.infrastructure.yml     # Full infrastructure stack
├── .env.example                          # Environment variables template
├── .gitignore                            # Git ignore rules
└── README.md                             # 📘 Project overview

```

## Key Files

### 🔴 Critical Documents

1. **`docs/contracts.md`** - Complete data contracts specification
   - Kafka topics table
   - JSON schemas overview
   - Postgres DDL
   - Neo4j model
   - DLQ/retry/error handling

2. **`migrations/001_initial_schema.sql`** - PostgreSQL schema
   - All tables with indexes
   - Constraints and foreign keys
   - Views and functions
   - Maintenance procedures

3. **`neo4j/init.cypher`** - Neo4j graph schema
   - Constraints (uniqueness)
   - Indexes (performance)
   - Helper procedures
   - Sample queries

4. **`kafka/topics.yml`** - Kafka topics configuration
   - All topics with partitions/retention
   - Consumer groups
   - Creation commands

### 🟡 JSON Schemas (6 files)

All schemas in `schemas/*.schema.json`:
- `raw_message` - From Telegram
- `persisted_message` - DB confirmation
- `preprocessed_message` - Cleaned text
- `sentiment_enriched` - Sentiment analysis
- `ner_enriched` - Named entities
- `graph_update` - Neo4j commands

### 🟢 Automation Scripts (4 files)

All scripts in `scripts/*.sh`:
- `create_kafka_topics.sh` - Create all Kafka topics
- `apply_migrations.sh` - Apply PostgreSQL migrations
- `init_neo4j.sh` - Initialize Neo4j schema
- `validate_schemas.sh` - Validate JSON schemas

## Quick Reference

### Architecture

```
Telegram → raw.telegram.messages → message-persister → Postgres
                ↓
         preprocessed.messages
                ↓
    ┌───────────┴──────────┐
    ↓                      ↓
sentiment.enriched    ner.enriched
    └───────────┬──────────┘
                ↓
         graph.updates → neo4j-writer → Neo4j
```

### Topics Summary

| Topic | Partitions | Retention | Description |
|-------|-----------|-----------|-------------|
| `raw.telegram.messages` | 6 | 30d | Raw Telegram messages |
| `persisted.messages` | 6 | 7d | Persistence confirmation |
| `preprocessed.messages` | 6 | 30d | Preprocessed text |
| `sentiment.enriched` | 6 | 30d | Sentiment analysis |
| `ner.enriched` | 6 | 30d | Named entities |
| `graph.updates` | 6 | 7d | Neo4j updates |
| `dlq.*` | 3 | 90d | Dead letter queues |

### Message Key Format

All messages use: `{channel}:{message_id}`

Examples:
- `rbc_news:123456`
- `cbpub:789012`

This ensures:
- ✅ Ordering within channel
- ✅ Idempotency (natural key)
- ✅ Partition distribution

### Database Tables

**PostgreSQL** (8 tables):
- `raw_messages` - Raw Telegram data
- `preprocessed_messages` - Cleaned text
- `sentiment_results` - Sentiment scores
- `ner_results` - Extracted entities
- `entity_relations` - SPO triples
- `processed_events` - Deduplication
- `outbox` - Transactional outbox
- `channels` - Channel metadata

**Neo4j** (4 node types):
- `Message` - Telegram message
- `Entity` - Named entity
- `Channel` - Telegram channel
- `Topic` - Thematic cluster

### Common Commands

```bash
# Start infrastructure
docker-compose -f docker-compose.infrastructure.yml up -d

# Initialize databases
./scripts/apply_migrations.sh
./scripts/init_neo4j.sh

# Create Kafka topics
./scripts/create_kafka_topics.sh

# Validate schemas
./scripts/validate_schemas.sh

# Check services
docker-compose -f docker-compose.infrastructure.yml ps

# View logs
docker logs telegram-news-postgres
docker logs telegram-news-neo4j
docker logs telegram-news-kafka
```

## Next Steps

1. ✅ Contracts defined
2. ✅ Schemas created
3. ✅ Database DDL ready
4. ✅ Infrastructure config ready
5. ⏳ Implement services:
   - `message-persister`
   - `preprocessor`
   - `sentiment-analyzer`
   - `ner-extractor`
   - `graph-builder`
   - `neo4j-writer`

## Service Template

Use `docs/engineering-standards.md` section 7 for new service skeleton.

Each service should:
- ✅ Follow plugin architecture (sources/sinks)
- ✅ Use Pydantic for config
- ✅ Implement idempotency
- ✅ Have retry + DLQ logic
- ✅ Export Prometheus metrics
- ✅ Include Dockerfile + docker-compose.yml

# Project Structure

Tg_news_project is a Telegram News Intelligence system. The product core is not
just message collection: it collects Telegram news, groups messages into topics
and storylines, explains dynamics across sources, entities and sentiment, and
feeds human review back into quality improvements.

## Product Areas

### Product Core

User-facing analytics for daily work:

- Dashboard: high-level volume, topic, source and sentiment view.
- Topics: topic list, novelty/importance signals and topic detail.
- Topic detail: volume, spread, freshness, growth, sentiment, key actors,
  first source, provenance, related topics and representative messages.
- Feed: searchable message stream.
- Entities: entity mentions, aliases, normalization and merge operations.
- Graph: entity/topic/source graph exploration.
- Sources: Telegram channel visibility and source management.

### Quality Lab

Human-in-the-loop quality cycle for improving topic intelligence:

- Review topics: analyst decisions for uncertain, novel or low-confidence
  topics.
- Annotation: topic/storyline labels, confidence and quality judgments.
- Datasets: versioned outputs from reviewed and annotated cases.
- Topic benchmark experiments: compare topic-modeling runs on controlled
  datasets.
- Candidate training jobs: consent-gated training candidates, currently MVP/mock
  where the backend says so.
- Models / model registry: candidate history, evaluation metadata and explicit
  deploy/rollback flow.

The intended cycle is:

`topic error or uncertainty -> review -> annotation/dataset -> benchmark or training candidate -> explicit deploy -> better analytics`.

Training does not start without explicit user consent. A trained candidate is
not deployed automatically. Deploying a model requires a separate explicit
deploy action.

### Experimental / Research

Research-oriented modules that are intentionally separate from the product core:

- Scientific papers.
- Paper detection, parsing and summarization.
- Future full MLOps capabilities beyond the current MVP.

## Architecture Layers

### Ingestion Layer

Moves Telegram content into durable event and storage layers.

- `rbc_telegram_collector/`: Telegram collection and backfill code.
- `message_persister/`: idempotent raw-message persistence.
- `preprocessor/`: text cleanup, language and normalized payload preparation.
- `source_resolver/`: source/provenance resolution.
- `kafka/topics.yml`: event topic definitions.
- `migrations/001_initial_schema.sql` and later migrations: PostgreSQL schema
  evolution.

### Understanding Layer

Turns messages into analysis-ready signals.

- `sentiment_analyzer/`: sentiment and emotion enrichment.
- `ner_extractor/`: entity extraction, normalization and canonical resolution.
- `topic_clusterer/`: topic assignment, topic pipeline and novelty logic.
- `topic_scorer/`: topic importance scoring.
- `llm_enricher/`: summaries, labels, key actors, timeline and what-changed
  enrichment.
- `schemas/`: JSON Schema contracts for raw, preprocessed, enriched, topic,
  training and paper events.

### Analyst Layer

Serves product views and user workflows.

- `analytics_api/`: aiohttp API for topics, feed, entities, graph, review,
  annotation, datasets, experiments, models and papers.
- `auth_service/`: authentication, roles, audit, channel visibility and user
  reactions.
- `frontend/`: Next.js application for Core Analytics, Quality Lab,
  Experimental and Admin/Settings routes.
- `neo4j/`: graph schema initialization.

### Quality Layer

Closes the loop between analyst judgment and model quality.

- `analytics_api/analytics_api/topic_review.py`: review-task API capability.
- `analytics_api/analytics_api/annotation.py`: annotation and dataset API
  capability.
- `dataset_builder/`: builds dataset artifacts from reviewed/annotated cases.
- `topic_benchmark_runner/`: benchmark metrics and experiment runner.
- `analytics_api/analytics_api/mlops.py`: dataset validation, training preview,
  candidate model records, evaluation helpers and explicit deploy helpers.
- `training_orchestrator/`: MVP/mock-capable worker for candidate training jobs.
- `migrations/013_topic_benchmark.sql` through
  `migrations/021_model_training_mlops.sql`: benchmark, annotation, review,
  novelty and model lifecycle tables.

Some MLOps pieces are implemented as logical capabilities inside
`analytics_api.mlops` and `training_orchestrator`, not as separate production
services. Full trainer/evaluator/deployer service separation remains future
work unless a concrete service directory exists.

### Experimental Layer

Research modules and non-core analysis capabilities.

- `paper_detector/`: scientific-paper detection.
- `paper_parser/`: arXiv/OpenReview/PDF parsing.
- `paper_summarizer/`: paper summarization.
- `migrations/022_scientific_papers.sql`: paper tables.
- `docs/scientific-papers.md`: module documentation.

## Repository Map

```text
Tg_news_project/
  analytics_api/              Analyst, Quality Lab and Experimental APIs
  auth_service/               Auth, RBAC, audit and source admin APIs
  dataset_builder/            Quality Lab dataset artifact builder
  docs/                       Architecture, contracts, UI and feature docs
  examples/                   Example event payloads
  frontend/                   Next.js Telegram News Intelligence UI
  kafka/                      Kafka topic definitions
  llm_enricher/               LLM/baseline enrichment and summaries
  message_persister/          Raw-message persistence
  migrations/                 PostgreSQL migrations 001..022
  models/                     Local model artifact placeholder
  neo4j/                      Graph initialization
  ner_extractor/              Entity extraction and normalization
  paper_detector/             Experimental paper detection
  paper_parser/               Experimental paper parsing
  paper_summarizer/           Experimental paper summarization
  preprocessor/               Text preprocessing
  rbc_telegram_collector/     Telegram collection and backfill
  schemas/                    JSON event schemas
  scripts/                    Migration, topic, import and backfill scripts
  sentiment_analyzer/         Sentiment and emotion enrichment
  source_resolver/            Source/provenance resolution
  tests/                      Unit and integration tests
  topic_benchmark_runner/     Quality Lab benchmark experiments
  topic_clusterer/            Topic assignment and novelty pipeline
  topic_scorer/               Importance scoring
  training_orchestrator/      Candidate-training MVP worker
```

## Current Event Contracts

`schemas/*.schema.json` currently includes contracts for:

- Raw, persisted and preprocessed Telegram messages.
- Sentiment, NER, graph updates and topic assignments.
- Candidate training job events.
- Model version and deployment-request events.
- Scientific paper detection, parsing and summarization events.

Keep `docs/contracts.md` as the detailed source for event semantics and storage
contracts.

## Data Stores

### PostgreSQL

PostgreSQL stores raw messages, preprocessed messages, sentiment, entities,
topic assignments/runs, topic review/annotation data, benchmark data, model
lifecycle metadata, source/admin data and papers metadata.

### Neo4j

Neo4j stores graph-oriented views around:

- `Message`
- `Entity`
- `Channel`
- `Topic`

Graph writes and graph analytics are represented in the codebase, but some graph
builder/writer capabilities may be logical or planned depending on deployment.
Do not document a standalone production service unless the service exists.

### Object / Artifact Storage

Object storage is the intended place for dataset exports, model artifacts,
benchmark artifacts and release manifests. Current local development may use
paths and MVP/mock artifacts.

## Frontend Navigation Model

The frontend sidebar should be organized by user intent:

- Core Analytics: Dashboard, Topics, Feed, Entities, Graph, Sources.
- Quality Lab: Review topics, Annotation, Datasets, Topic benchmark experiments,
  Candidate training, Models.
- Experimental: Scientific papers.
- Admin/Settings: Settings, channel administration and audit log.

Datasets, training and models are part of the Quality Lab, not independent
business features. Papers are Experimental unless they become a primary product
line later.

## Common Commands

```bash
# Start infrastructure
docker-compose -f docker-compose.infrastructure.yml up -d

# Apply PostgreSQL migrations
./scripts/apply_migrations.sh

# Initialize Neo4j
./scripts/init_neo4j.sh

# Create Kafka topics
./scripts/create_kafka_topics.sh

# Validate schemas
./scripts/validate_schemas.sh

# Frontend tests
cd frontend && npm test
```

## Documentation Pointers

- `docs/IMPLEMENTATION.md`: current implementation status and caveats.
- `docs/contracts.md`: data contracts.
- `docs/model-training.md`: Quality Lab candidate-training flow.
- `docs/topic_modeling_benchmark.md`: topic benchmark experiments.
- `docs/topic_novelty_detection.md`: novelty detection.
- `docs/annotation_guidelines.md`: annotation workflow.
- `docs/scientific-papers.md`: Experimental papers module.

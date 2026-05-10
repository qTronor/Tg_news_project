# Telegram News Intelligence Implementation Status

This document describes the current implementation status of the Telegram News
Intelligence system. It avoids treating planned, MVP or mock capabilities as
fully production-ready services.

Related diagrams:

- [`implementation_sequence.puml`](./implementation_sequence.puml)
- [`implementation_sequence_conceptual.puml`](./implementation_sequence_conceptual.puml)
- [`architecture_overview_updated.puml`](./architecture_overview_updated.puml)

## 1. Status Summary

### Core pipeline implemented

The core news pipeline is implemented as an event-oriented set of Python
services and APIs:

- Telegram collection/backfill.
- Raw-message persistence.
- Preprocessing.
- Sentiment enrichment.
- Entity extraction and normalization.
- Topic clustering, topic pipeline persistence and novelty logic.
- Topic importance scoring.
- LLM/baseline enrichment for summaries, labels and key actor/timeline views.
- Analytics API and Next.js frontend.
- Auth/admin service for users, roles, audit and source/channel operations.

### Quality Lab partially implemented

Quality Lab exists as a product area but not every capability is a mature
production MLOps system:

- Topic review is implemented as API/UI capability.
- Annotation and dataset building are implemented as API/UI plus
  `dataset_builder/`.
- Topic benchmark experiments are implemented as benchmark APIs/UI and
  `topic_benchmark_runner/`.
- Training jobs and model registry are implemented as an MVP/candidate flow.

The intended human-in-the-loop cycle is:

`topic error or uncertainty -> review -> annotation/dataset -> benchmark or training candidate -> explicit deploy -> better analytics`.

Training requires explicit user consent. Candidate models are not deployed
automatically. Deployment requires a separate explicit deploy confirmation.

### MLOps/training currently MVP/mock where applicable

The current training/model lifecycle code supports validation, preview, job
records, candidate model records, evaluation metadata and explicit deploy/rollback
actions. In places where the code or configuration uses `mode: "mock"` or mock
trainer behavior, it should be treated as MVP infrastructure for controlled
candidate training, not as production ML training.

Logical capabilities such as trainer, evaluator, registry and deployer are
implemented primarily inside `analytics_api/analytics_api/mlops.py` and
`training_orchestrator/`. They are not separate production services unless a
concrete service directory exists.

### Scientific papers experimental module

Scientific paper detection, parsing and summarization are present as an
Experimental/Research module:

- `paper_detector/`
- `paper_parser/`
- `paper_summarizer/`
- `analytics_api` paper endpoints
- frontend `/papers`

This module is not part of the primary Product Core unless the product direction
explicitly changes.

## 2. Product Layers

### Ingestion Layer

Purpose: move Telegram content into durable streams and storage.

Implemented pieces:

- `rbc_telegram_collector`: Telegram collection/backfill.
- `message_persister`: idempotent raw-message persistence.
- `preprocessor`: text preprocessing and normalized event production.
- Kafka topic definitions in `kafka/topics.yml`.
- PostgreSQL migrations in `migrations/`.

### Understanding Layer

Purpose: turn messages into analytic signals.

Implemented pieces:

- `sentiment_analyzer`: sentiment/emotion enrichment.
- `ner_extractor`: NER, provider chain and canonical normalization.
- `source_resolver`: source/provenance logic.
- `topic_clusterer`: topic assignment, BERTopic-like pipeline and novelty.
- `topic_scorer`: importance scoring.
- `llm_enricher`: summaries, labels, timelines and key actors.

Some graph update/writer capabilities are represented by contracts, docs and API
logic. Do not describe a standalone `graph-builder` or `neo4j-writer` as a
production service unless it exists in the repository/deployment.

### Analyst Layer

Purpose: expose useful product workflows to analysts.

Implemented pieces:

- `analytics_api`: topics, topic detail, feed, entities, graph analytics,
  review, annotation, datasets, benchmarks, models and papers endpoints.
- `auth_service`: authentication, RBAC, admin audit, channel visibility and user
  reactions.
- `frontend`: Core Analytics, Quality Lab, Experimental and Admin/Settings UI.

The main UI should prioritize product metrics: topic volume, spread, freshness,
growth/trend, sentiment balance, key actors, first source, source confidence,
novelty, importance and review status. Technical operations metrics such as
Kafka offsets, consumer lag and raw service health belong in ops/admin/debug
surfaces, not in primary analyst cards.

### Quality Layer

Purpose: close the quality loop when a topic is wrong, uncertain or novel.

Implemented or partially implemented pieces:

- `analytics_api/analytics_api/topic_review.py`: review tasks and actions.
- `analytics_api/analytics_api/annotation.py`: annotation tasks and dataset
  support.
- `dataset_builder/`: versioned dataset artifact builder.
- `topic_benchmark_runner/`: topic benchmark experiments.
- `analytics_api/analytics_api/mlops.py`: validation, preview, candidate model
  records, model registry helpers and explicit deploy helpers.
- `training_orchestrator/`: polling worker for candidate training jobs; current
  implementation may be MVP/mock depending on configuration.

Planned/future when needed:

- Separate production-grade trainer service.
- Separate evaluator service with quality gates.
- Separate deployment controller with rollout/canary automation.
- Full artifact storage integration and model lineage UI beyond the current MVP.

### Experimental Layer

Purpose: research workflows that may later become product capabilities.

Implemented pieces:

- Scientific paper detection.
- Paper parsing.
- Paper summarization.
- Paper API/UI.

Planned/future:

- Broader research ingestion sources.
- Full paper quality workflow.
- Integration with the main topic intelligence loop if productized.

## 3. Current Service Inventory

| Component | Current status | Role |
|---|---|---|
| `rbc_telegram_collector` | Implemented | Telegram collection/backfill |
| `message_persister` | Implemented | Raw-message persistence |
| `preprocessor` | Implemented | Text preprocessing |
| `sentiment_analyzer` | Implemented | Sentiment/emotion enrichment |
| `ner_extractor` | Implemented | Entity extraction and normalization |
| `source_resolver` | Implemented | Source/provenance resolution |
| `topic_clusterer` | Implemented | Topic assignments, pipeline and novelty |
| `topic_scorer` | Implemented | Topic importance scoring |
| `llm_enricher` | Implemented | Summaries, labels and actor/timeline enrichment |
| `analytics_api` | Implemented | Analyst, Quality Lab and Experimental APIs |
| `auth_service` | Implemented | Auth, RBAC, admin/audit and source admin |
| `frontend` | Implemented | Next.js user interface |
| `dataset_builder` | Implemented/MVP | Dataset artifacts for Quality Lab |
| `topic_benchmark_runner` | Implemented | Topic benchmark experiments |
| `training_orchestrator` | MVP/mock-capable | Candidate training job worker |
| `paper_detector` | Experimental | Scientific-paper detection |
| `paper_parser` | Experimental | Paper parsing |
| `paper_summarizer` | Experimental | Paper summarization |
| `model_trainer` | Planned/future as separate service | Logical capability currently covered by MVP flow |
| `model_evaluator` | Planned/future as separate service | Logical capability currently covered by MVP flow |
| `model_deployer` | Planned/future as separate service | Explicit deploy helper exists in API |
| `graph-builder` | Logical/planned unless deployed separately | Graph update aggregation |
| `neo4j-writer` | Logical/planned unless deployed separately | Graph write application |

## 4. Data Flow

```text
Telegram channels
  -> rbc_telegram_collector
  -> raw.telegram.messages
  -> message_persister
  -> PostgreSQL raw_messages

raw/persisted messages
  -> preprocessor
  -> preprocessed.messages
  -> sentiment_analyzer / ner_extractor / topic_clusterer
  -> sentiment_results / ner_results / cluster assignments

topic assignments
  -> novelty and importance scoring
  -> source/provenance and LLM/baseline enrichment
  -> analytics_api
  -> frontend Core Analytics

uncertain or disputed topics
  -> review
  -> annotation
  -> dataset
  -> benchmark or candidate training
  -> explicit model deploy
```

## 5. Storage

### PostgreSQL

PostgreSQL stores operational and analytic records, including:

- raw and preprocessed messages;
- sentiment and entity results;
- topic runs and assignments;
- source/provenance data;
- topic importance, novelty, summaries and comparison data;
- review, annotation and dataset tables;
- benchmark and candidate model lifecycle tables;
- auth/admin/channel data;
- scientific paper metadata.

### Neo4j

Neo4j is used for graph-oriented exploration around messages, channels, topics
and entities. Graph analytics may be served from Neo4j and/or cached analytic
tables depending on deployment.

### Artifact storage

Dataset exports, benchmark outputs and model artifacts are intended to live in
object/artifact storage. Local MVP flows may use local paths or mock artifacts.

## 6. UI Positioning

The UI should keep the product hierarchy explicit:

- Core Analytics: Dashboard, Topics, Feed, Entities, Graph, Sources.
- Quality Lab: Review, Annotation, Datasets, Topic benchmark experiments,
  Candidate training, Models.
- Experimental: Papers.
- Admin/Settings: Settings, channel admin and audit.

Datasets are Quality Lab artifacts. Training is a controlled candidate-training
flow. Models are candidates/registry entries until explicitly accepted and
deployed. Papers are Experimental.

## 7. Reliability And Ops

Implemented reliability patterns include:

- idempotent persistence and processed-event tracking;
- retry/DLQ conventions in event services;
- health and metrics endpoints in services where implemented;
- Docker/Docker Compose configuration for local infrastructure;
- tests covering core contracts, topic pipeline, scoring, review, annotation,
  benchmark, MLOps MVP and paper modules.

Operational metrics such as service health, consumer lag, Kafka offsets and raw
processor metrics should be exposed through ops/admin/debug tooling. They should
not dominate the main analyst dashboard.

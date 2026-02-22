# E2E Report

Date: 2026-02-04  
Environment: Windows + Docker Desktop  
Run type: Infra restart + Collector (3-day window) + JSONL bridge → Kafka + storage checks  

## Commands Executed
- `powershell -ExecutionPolicy Bypass -File scripts/e2e_run.ps1 -RunCollector -PublishJsonl -StorageChecks`

## Infrastructure Status
- Postgres: healthy
- Neo4j: healthy
- Kafka/Zookeeper: healthy
- Kafka UI: healthy
- Redis: healthy

## Kafka Results
- Topics list:
  - `raw.telegram.messages`, `persisted.messages`, `preprocessed.messages`, `sentiment.enriched`, `ner.enriched`, `graph.updates`
  - `dlq.raw.messages`, `dlq.preprocessing`, `dlq.sentiment`, `dlq.ner`, `dlq.graph`
  - `message-persister-group`, `preprocessor-group`, `sentiment-analyzer-group`, `ner-extractor-group`, `graph-builder-group`, `neo4j-writer-group`, `monitoring-group`, `dlq-manual-review-group`
- `raw.telegram.messages` log-end count (approx): 12
- Consumer group lag snapshot:
  - `message-persister-group`: lag 0 on partitions with offsets
  - `preprocessor-group`: lag 0 on partitions with offsets

## Collector Results
- Collector run: OK
- Channels: `rbc_news`, `Cbpub`
- Window: last 3 days (since 2026-02-01)
- Messages collected: 8 (`rbc_news`=4, `Cbpub`=4)
- JSONL bridge: published 100 messages
- JSONL file used: `rbc_telegram_collector/data/Cbpub.jsonl`

## Postgres Results
- `raw_messages` count: 874
- `preprocessed_messages` count: 874
- `sentiment_results` count: 0
- `ner_results` count: 0
- `processed_events` count: 204

## Neo4j Results
- `Message` nodes: 0
- `Entity` nodes: 0
- `MENTIONS` edges: 0

## Idempotency
- Not executed (single publish run)

## Issues / Gaps
- `scripts/e2e_run.ps1` previously created topics for consumer groups because `topics.yml` includes `consumer_groups`. The parser is now fixed, but any extra topics should be deleted manually if undesired.
- Kafka sink in collector is not implemented; bridge is required.

## Evidence / Logs
- `docker compose -f docker-compose.infrastructure.yml ps` shows all infra containers healthy.
- `kafka-consumer-groups --all-groups --describe` shows zero lag for active partitions.
- `raw.telegram.messages` log-end count (approx): 217
- Cyrillic text displays correctly after UTF-8 JSONL decoding fix.

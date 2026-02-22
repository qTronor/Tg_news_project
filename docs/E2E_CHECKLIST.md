# E2E Checklist (Windows PowerShell)

This checklist is the fastest way to confirm the pipeline is alive. It is written for Windows PowerShell and Docker Desktop.

## 0) Prerequisites
- `.env` exists with `DB_PASSWORD` and `NEO4J_PASSWORD`.
- Docker Desktop is running in Linux containers mode.

## 1) Infrastructure Health
- Start infra:
  - `docker compose -f docker-compose.infrastructure.yml up -d`
- Verify health:
  - `docker compose -f docker-compose.infrastructure.yml ps`
  - Expect healthy: `postgres`, `neo4j`, `zookeeper`, `kafka`, `kafka-ui`, `redis`

## 2) Storage Initialization
- Postgres migrations:
  - `docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -f /docker-entrypoint-initdb.d/001_initial_schema.sql`
- Neo4j constraints:
  - `docker exec -i telegram-news-neo4j cypher-shell -u neo4j -p $env:NEO4J_PASSWORD -f /var/lib/neo4j/import/init.cypher`

## 3) Kafka Topics
- List topics:
  - `docker exec -i telegram-news-kafka kafka-topics --bootstrap-server kafka:9093 --list`
- Create topics (if missing):
  - `powershell -ExecutionPolicy Bypass -File scripts/e2e_run.ps1 -OnlyTopics`

## 4) Collector → raw.telegram.messages
Collector currently writes JSONL locally; Kafka sink is not implemented yet, so use the bridge.

- Run collector (non-interactive requires `TG_STRING_SESSION`):
  - `docker compose -f rbc_telegram_collector/docker-compose.yml run --rm telegram-collector`
- Publish JSONL to Kafka (bridge):
  - `powershell -ExecutionPolicy Bypass -File scripts/e2e_run.ps1 -PublishJsonl`
- Validate raw topic:
  - `docker exec -i telegram-news-kafka kafka-console-consumer --bootstrap-server kafka:9093 --topic raw.telegram.messages --from-beginning --max-messages 1 --property print.key=true --property key.separator="|"`

## 5) Pipeline (once processors exist)
- Start processors:
  - `powershell -ExecutionPolicy Bypass -File scripts/e2e_run.ps1 -StartProcessors`
- Check consumer groups & lag:
  - `docker exec -i telegram-news-kafka kafka-consumer-groups --bootstrap-server kafka:9093 --all-groups --describe`
- Confirm messages in each topic:
  - `raw.telegram.messages`
  - `preprocessed.messages`
  - `sentiment.enriched`
  - `ner.enriched`
  - `graph.updates`

## 6) Postgres Checks
- Counts:
  - `docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -c "SELECT count(*) FROM raw_messages;"`
  - `docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -c "SELECT count(*) FROM preprocessed_messages;"`
  - `docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -c "SELECT count(*) FROM sentiment_results;"`
  - `docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -c "SELECT count(*) FROM ner_results;"`
  - `docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -c "SELECT count(*) FROM processed_events;"`
- Sample last 5:
  - `docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -c "SELECT event_id,message_date FROM raw_messages ORDER BY message_date DESC LIMIT 5;"`

## 7) Neo4j Checks
- Counts:
  - `docker exec -i telegram-news-neo4j cypher-shell -u neo4j -p $env:NEO4J_PASSWORD "MATCH (m:Message) RETURN count(m);"`
  - `docker exec -i telegram-news-neo4j cypher-shell -u neo4j -p $env:NEO4J_PASSWORD "MATCH (e:Entity) RETURN count(e);"`
  - `docker exec -i telegram-news-neo4j cypher-shell -u neo4j -p $env:NEO4J_PASSWORD "MATCH (:Entity)-[r:MENTIONS]->(:Message) RETURN count(r);"`

## 8) Idempotency
- Re-send the same raw events:
  - `powershell -ExecutionPolicy Bypass -File scripts/e2e_run.ps1 -PublishJsonl -MaxPublish 20`
- Verify:
  - Domain tables do not increase due to duplicates.
  - `processed_events` grows as expected.
  - Neo4j constraints prevent duplicate nodes.

## 9) Observability
- Kafka UI: `http://localhost:8080`
- Neo4j Browser: `http://localhost:7474`
- Logs:
  - `docker compose -f docker-compose.infrastructure.yml logs -f kafka`
  - `docker compose -f docker-compose.infrastructure.yml logs -f postgres`
  - `docker compose -f docker-compose.infrastructure.yml logs -f neo4j`
